"""Build from a verified vanilla file, then install a self-contained runtime."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def vanilla_file(game, expected):
    current = game / "data.win"
    backup = game / "data.win.qqmod-backup"
    if digest(current) == expected:
        return current
    # Do not patch an unknown (possibly updated) game with an old backup.
    known = {expected}
    guard_candidates = [ROOT / "mod" / "mod_guard.py", ROOT / "runtime" / "mod_guard.py"]
    for guard in guard_candidates:
        if guard.exists():
            known.update(re.findall(r'PATCHED_SHA256 = "([0-9a-f]{64})"', guard.read_text(encoding="utf-8-sig")))
    if digest(current) not in known:
        raise RuntimeError("游戏版本与当前 Mod 不匹配。请等待适配版本；游戏文件未修改。")
    if not backup.exists() or digest(backup) != expected:
        raise RuntimeError("缺少匹配的原版备份。请在 Steam 验证游戏文件后重新安装 Mod。")
    return backup


def ensure_game_closed(game):
    sys.path.insert(0, str(ROOT / "launcher"))
    import lifecycle
    handle = lifecycle.find_game(str(game / "ChillPulse.exe"))
    if handle:
        lifecycle.close_handle(handle)
        raise RuntimeError("请先关闭 ChillPulse，等待 Steam 恢复“开始游戏”后再安装。")
    lock = lifecycle.acquire_singleton("launcher", str(game))
    if not lock:
        raise RuntimeError("游戏会话尚未退出，请稍后重试。")
    command_lock = lifecycle.acquire_singleton("game-command", str(game))
    if not command_lock:
        lifecycle.close_handle(lock)
        raise RuntimeError("游戏正在启动，请关闭游戏后重试。")
    return lifecycle, (lock, command_lock)


def deploy(files, backup_dir):
    """Roll back earlier writes if any replacement fails; auth is never a target."""
    backup_dir.mkdir(parents=True)
    changed = []
    try:
        for index, (source, target) in enumerate(files):
            target.parent.mkdir(parents=True, exist_ok=True)
            previous = backup_dir / str(index) if target.exists() else None
            if previous:
                shutil.copy2(target, previous)
            temporary = target.with_name(target.name + ".installing")
            try:
                shutil.copy2(source, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            changed.append((target, previous))
    except Exception:
        for target, previous in reversed(changed):
            if previous:
                shutil.copy2(previous, target)
            else:
                target.unlink(missing_ok=True)
        raise


def install(game, ffmpeg, utmt, dotnet=None):
    runtime = ROOT / "runtime"
    guard_text = (ROOT / "mod" / "mod_guard.py").read_text(encoding="utf-8-sig")
    expected = re.search(r'VANILLA_SHA256 = "([0-9a-f]{64})"', guard_text).group(1)
    lifecycle, locks = ensure_game_closed(game)
    try:
        original = vanilla_file(game, expected)
        subprocess.run([sys.executable, str(ROOT / "mod" / "make_methods.py")], check=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=ROOT) as temp:
            stage = Path(temp)
            patched = stage / "data_patched.win"
            log = ROOT / "install.log"
            environment = dict(os.environ, QQM_ROOT=str(ROOT))
            command = [str(dotnet), str(utmt)] if dotnet else [str(utmt)]
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run(command + ["load", str(original), "-s",
                    str(ROOT / "mod" / "apply_mod.csx"), "-o", str(patched)],
                    stdout=stream, stderr=subprocess.STDOUT, env=environment, cwd=ROOT)
            if result.returncode or not patched.exists() or "QQM: patch applied successfully." not in log.read_text(encoding="utf-8", errors="replace"):
                raise RuntimeError("补丁生成失败，游戏文件未修改。详情见安装目录的 install.log。")
            guard_text = re.sub(r'PATCHED_SHA256 = "[0-9a-f]+"',
                'PATCHED_SHA256 = "' + digest(patched) + '"', guard_text)
            (stage / "mod_guard.py").write_text(guard_text, encoding="utf-8")
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            if not pythonw.exists():
                raise RuntimeError("未找到 pythonw.exe，请安装 python.org 提供的完整 Python。")
            options = '"%s" "%s" %%command%%' % (pythonw, runtime / "launcher.py")
            for name, content in {
                "game_dir.txt": str(game), "ffmpeg_path.txt": str(ffmpeg),
                "python_path.txt": str(pythonw), "steam_launch_options.txt": options,
            }.items():
                (stage / name).write_text(content + "\n", encoding="utf-8")
            files = [(stage / "mod_guard.py", runtime / "mod_guard.py"), (patched, runtime / "data_patched.win")]
            for name in ("launcher.py", "lifecycle.py", "accounts.py"):
                files.append((ROOT / "launcher" / name, runtime / name))
            for name in ("qqbridge.py", "qqmusic.py"):
                files.append((ROOT / "bridge" / name, runtime / name))
            for path in (ROOT / "bridge" / "providers").rglob("*.py"):
                files.append((path, runtime / "providers" / path.relative_to(ROOT / "bridge" / "providers")))
            for name in ("game_dir.txt", "ffmpeg_path.txt", "python_path.txt", "steam_launch_options.txt"):
                files.append((stage / name, runtime / name))
            backup = game / "data.win.qqmod-backup"
            if not backup.exists() or digest(backup) != expected:
                files.append((original, backup))
            # Old checkout users keep their accounts, without overwriting new ones.
            for name in ("auth.json", "auth_netease.json"):
                old = ROOT / "bridge" / name
                if old.exists() and not (runtime / name).exists():
                    files.append((old, runtime / name))
            files.append((patched, game / "data.win"))
            deploy(files, ROOT / (".install-backup-" + time.strftime("%Y%m%d-%H%M%S")))
        return options
    finally:
        for lock in locks:
            lifecycle.close_handle(lock)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-dir", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--utmt", required=True, type=Path)
    parser.add_argument("--dotnet", type=Path)
    args = parser.parse_args()
    try:
        options = install(args.game_dir.resolve(), args.ffmpeg.resolve(), args.utmt.resolve(), args.dotnet)
        print("\n安装完成。Steam 启动参数：\n" + options)
        return 0
    except Exception as exc:
        print("\n安装未完成：" + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
