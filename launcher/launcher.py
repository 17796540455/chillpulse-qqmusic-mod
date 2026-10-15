"""Start one bridge per game session and reap it when the game exits."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

import lifecycle
import mod_guard

HERE = Path(__file__).resolve().parent
PORT = 38612
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LOG = logging.getLogger("launcher")


def request(route):
    with OPENER.open("http://127.0.0.1:%d/%s" % (PORT, route), timeout=1) as reply:
        return json.load(reply)


def ready_bridge(proc, game_dir):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("Bridge exited before becoming ready (code %s). "
                               "Check qqbridge.log for a port conflict." % proc.returncode)
        try:
            status = request("status")
            if (status.get("pid") == proc.pid and status.get("ok") and
                    os.path.normcase(status.get("game_dir", "")) ==
                    os.path.normcase(game_dir)):
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError("Bridge did not become ready within 15 seconds.")


def stop_bridge(proc):
    if proc is None:
        return
    if proc.poll() is None:
        try:
            if request("status").get("pid") == proc.pid:
                request("quit")
        except (OSError, ValueError):
            LOG.warning("Bridge did not answer quit; terminating the owned helper.")
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)
    LOG.info("bridge pid=%s stopped, code=%s", proc.pid, proc.returncode)


def run_game_command(command, game_dir):
    lock = lifecycle.acquire_singleton("game-command", game_dir)
    if not lock:
        LOG.info("game command already starting/running; ignored duplicate")
        return 0
    try:
        handle = lifecycle.find_game(os.path.join(game_dir, "ChillPulse.exe"))
        if handle:
            lifecycle.close_handle(handle)
            return 0
        return subprocess.call(command, cwd=game_dir)
    finally:
        lifecycle.close_handle(lock)


def run(command):
    game_dir = os.path.abspath(mod_guard.game_dir())
    executable = os.path.join(game_dir, "ChillPulse.exe")
    lock = lifecycle.acquire_singleton("launcher", game_dir)
    if not lock:
        # A desktop launch may already own the bridge when Steam invokes its
        # configured wrapper. Let that wrapper launch the actual game once.
        if command:
            handle = lifecycle.find_game(executable)
            if handle:
                lifecycle.close_handle(handle)
                LOG.info("game already running; ignored duplicate launch")
                return 0
            LOG.info("existing supervisor owns bridge; passing Steam command through")
            return run_game_command(command, game_dir)
        LOG.info("session already starting/running; ignored duplicate launch")
        return 0

    bridge = None
    game_handle = None
    try:
        result = mod_guard.main()
        if result not in (0, 10):
            raise RuntimeError("Mod data check failed (code %d). See mod_guard.log." % result)
        game_handle = lifecycle.find_game(executable)
        bridge = subprocess.Popen(
            [sys.executable, str(HERE / "qqbridge.py"), "--port", str(PORT),
             "--game-dir", game_dir, "--cache-mb", "1024", "--quality", "128",
             "--watch-pid", str(os.getpid())],
            cwd=str(HERE), env=lifecycle.bridge_environment(), close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        ready_bridge(bridge, game_dir)
        LOG.info("bridge ready pid=%s port=%s", bridge.pid, PORT)

        if game_handle:
            LOG.info("attached to existing game")
            lifecycle.wait_process(game_handle)
            return 0
        if command:
            LOG.info("starting Steam game command")
            return run_game_command(command, game_dir)

        LOG.info("asking Steam to launch ChillPulse")
        os.startfile("steam://rungameid/2826180")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if bridge.poll() is not None:
                raise RuntimeError("Bridge exited while waiting for the game.")
            game_handle = lifecycle.find_game(executable)
            if game_handle:
                LOG.info("game detected; waiting for exit")
                lifecycle.wait_process(game_handle)
                return 0
            time.sleep(0.2)
        raise RuntimeError("Steam did not start the game within 180 seconds; bridge stopped.")
    finally:
        lifecycle.close_handle(game_handle)
        try:
            stop_bridge(bridge)
        finally:
            lifecycle.close_handle(lock)
            LOG.info("session ended")


def main():
    logging.basicConfig(filename=str(HERE / "launcher.log"), encoding="utf-8",
                        level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run(sys.argv[1:])
    except Exception as exc:
        LOG.exception("launch failed")
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, str(exc) + "\n\nLog: " + str(HERE / "launcher.log"),
            "ChillPulse QQ Music", 0x10)
        return 1


if __name__ == "__main__":
    sys.exit(main())
