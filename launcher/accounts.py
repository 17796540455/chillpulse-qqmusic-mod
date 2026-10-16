"""Local account settings. Credentials only go to the selected music service."""
import json
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

HERE = Path(__file__).resolve().parent
SOURCES = {
    "qq": ("QQ 音乐", "https://y.qq.com/", "auth.json"),
    "netease": ("网易云音乐", "https://music.163.com/", "auth_netease.json"),
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


class LoginError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_cookie(text, source):
    text = text.strip()
    if text.startswith("{"):
        try:
            text = str(json.loads(text).get("cookie") or "").strip()
        except (ValueError, AttributeError):
            raise LoginError("内容不是有效的 Cookie。请只复制请求标头中的 Cookie 值。") from None
    text = re.sub(r"^cookie\s*:\s*", "", text, flags=re.I)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise LoginError("请只复制 Cookie 这一项的值，不要复制整组请求标头。")
    parts = {}
    for part in text.split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            parts[key.strip()] = value.strip()
    if source == "qq":
        uin = (parts.get("uin") or parts.get("wxuin") or "").lstrip("o")
        if not uin.isdigit() or int(uin) == 0 or not (parts.get("qm_keyst") or parts.get("qqmusic_key")):
            raise LoginError("未找到 QQ 音乐登录信息。请登录 y.qq.com，再复制包含 uin（或 wxuin）及 qm_keyst（或 qqmusic_key）的 Cookie。")
        return {"uin": uin, "cookie": text}
    if source != "netease":
        raise LoginError("未知音源。")
    if not parts.get("MUSIC_U"):
        raise LoginError("未找到 MUSIC_U。请登录 music.163.com 后刷新页面，再复制 Cookie。")
    return {"cookie": text}


def fetch_json(url, cookie, body=None):
    request = urllib.request.Request(url, data=body, headers={
        "User-Agent": UA, "Cookie": cookie,
        "Referer": SOURCES["netease" if "163.com/" in url else "qq"][1],
        "Content-Type": "application/json",
    })
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        raise LoginError("暂时无法验证，请检查网络后重试；原来的登录信息已保留。") from None


def validate(payload, source):
    if source == "netease":
        result = fetch_json("https://music.163.com/api/nuser/account/get", payload["cookie"])
        profile = result.get("profile") or {}
        if not profile.get("userId"):
            raise LoginError("网易云登录已失效。请重新登录网页并复制新的 Cookie。")
        return "已验证登录：" + str(profile.get("nickname") or "网易云用户")
    # Reading a playlist is a connectivity check, not proof of playback rights.
    body = json.dumps({"req_0": {"module": "music.musicasset.PlaylistBaseRead",
        "method": "GetPlaylistByUin", "param": {"uin": payload["uin"]}},
        "comm": {"ct": 24, "cv": 4747474, "format": "json", "platform": "yqq.json",
                 "uin": payload["uin"], "g_tk": 5381, "g_tk_new_20200303": 5381}}).encode("utf-8")
    result = fetch_json("https://u.y.qq.com/cgi-bin/musicu.fcg", payload["cookie"], body)
    reply = result.get("req_0") or {}
    if result.get("code", 0) != 0 or reply.get("code") != 0 or not isinstance(reply.get("data"), dict):
        raise LoginError("QQ 音乐未能读取歌单。请重新登录网页并复制 Cookie，再重试。")
    data = reply["data"]
    count = len(data.get("v_playlist") or data.get("playlist") or [])
    return "凭证格式正确，已读取 %d 个歌单；请在游戏内播放确认登录权限。" % count


def save_login(text, source, directory=HERE):
    payload = parse_cookie(text, source)
    message = validate(payload, source)
    path = Path(directory) / SOURCES[source][2]
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return message


def main():
    import tkinter as tk
    from tkinter import messagebox, ttk

    window = tk.Tk()
    window.title("ChillPulse · 音乐账号设置")
    window.geometry("760x660")
    window.minsize(720, 660)
    frame = ttk.Frame(window, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="音乐账号设置", font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
    ttk.Label(frame, text="两个平台分别登录，只设置你要使用的平台即可。", padding=(0, 8)).pack(anchor="w")
    notebook = ttk.Notebook(frame)
    notebook.pack(fill="both", expand=True)
    results = queue.Queue()
    states = {}
    guide = (
        "1. 点击“打开官网登录”，在浏览器中扫码或使用官网支持的方式登录。\n"
        "2. 按 F12，打开“网络 / Network”，刷新网页。\n"
        "3. 选一个发往该音乐平台、带 Cookie 的请求。\n"
        "4. 在“标头 / Headers → 请求标头 / Request Headers”中，\n"
        "   复制 Cookie 的整项值，回到这里粘贴并保存。\n\n"
        "浏览器或桌面客户端的登录不会自动同步到 Mod。\n"
        "当前稳定登录方式是导入网页 Cookie，尚未提供 Mod 内直接扫码。"
    )
    for source, (name, url, filename) in SOURCES.items():
        tab = ttk.Frame(notebook, padding=16)
        notebook.add(tab, text=name)
        ttk.Label(tab, text=guide, justify="left", wraplength=610).pack(anchor="w")
        ttk.Button(tab, text="打开官网登录", command=lambda u=url: webbrowser.open(u)).pack(anchor="w", pady=10)
        ttk.Label(tab, text="Cookie（保存在本机，不要分享给他人）").pack(anchor="w")
        value = tk.StringVar()
        entry = ttk.Entry(tab, textvariable=value, show="●")
        entry.pack(fill="x", pady=6)
        status = tk.StringVar(value="已保存登录信息，可点击检查。" if (HERE / filename).exists() else "尚未设置登录。")
        ttk.Label(tab, textvariable=status, wraplength=610).pack(anchor="w", pady=8)
        buttons = ttk.Frame(tab)
        buttons.pack(anchor="w")
        states[source] = {"value": value, "status": status, "buttons": []}

        def run(action, src=source):
            state = states[src]
            text = state["value"].get()
            if action == "save" and not text.strip():
                state["status"].set("请先粘贴 Cookie。")
                return
            for button in state["buttons"]:
                button.configure(state="disabled")
            state["status"].set("正在验证，请稍候……")

            def worker():
                try:
                    if action == "save":
                        message = save_login(text, src)
                    else:
                        path = HERE / SOURCES[src][2]
                        if not path.exists():
                            raise LoginError("尚未设置登录。")
                        payload = json.loads(path.read_text(encoding="utf-8-sig"))
                        payload = parse_cookie(payload.get("cookie") or "", src)
                        message = validate(payload, src)
                    results.put((src, True, message))
                except LoginError as exc:
                    results.put((src, False, str(exc)))
                except Exception:
                    results.put((src, False, "无法读取或保存登录信息，请确认安装目录可写；原文件未被替换。"))
            threading.Thread(target=worker, daemon=True).start()

        def logout(src=source):
            if messagebox.askyesno("退出 Mod 登录", "仅移除这个音源在 Mod 中保存的登录信息。继续？", parent=window):
                try:
                    (HERE / SOURCES[src][2]).unlink(missing_ok=True)
                    states[src]["status"].set("已退出 Mod 登录。")
                    states[src]["value"].set("")
                except OSError:
                    states[src]["status"].set("无法移除登录信息，请确认安装目录可写。")

        for label, command in (("验证并保存", lambda r=run: r("save")),
                               ("检查已保存登录", lambda r=run: r("check")),
                               ("退出 Mod 登录", logout)):
            button = ttk.Button(buttons, text=label, command=command)
            button.pack(side="left", padx=(0, 8))
            states[source]["buttons"].append(button)
    ttk.Label(frame, text="保存后重新打开游戏以刷新歌单。会员与付费歌曲仍受账号权限限制。", wraplength=650).pack(anchor="w", pady=(14, 0))

    def poll():
        while True:
            try:
                source, success, message = results.get_nowait()
            except queue.Empty:
                break
            state = states[source]
            state["status"].set(message)
            if success:
                state["value"].set("")
            for button in state["buttons"]:
                button.configure(state="normal")
        window.after(100, poll)
    poll()
    window.mainloop()


if __name__ == "__main__":
    main()
