"""Restore the Steam entries in the Windows proxy bypass list.

Clash rejects *.steamserver.net (Steam's connection-manager servers), so while
the system proxy is on, Steam cannot log in at all.  Adding those domains to the
WinINET bypass list makes Steam talk to its CM servers directly while everything
else keeps using the proxy - both work at the same time.

Run this again whenever Steam stops connecting after you toggle Clash's
"system proxy": that toggle rewrites ProxyOverride and drops these entries.

    py -3 fix_proxy_bypass.py            # add the entries
    py -3 fix_proxy_bypass.py --remove   # take them back out
    py -3 fix_proxy_bypass.py --check    # just show the current list
"""
import ctypes
import sys
import winreg

KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
WANT = ["*.steamserver.net", "*.steamcontent.com",
        "*.steamstatic.com", "*.steampowered.com"]


def refresh():
    """Tell WinINET the settings changed so running apps pick them up."""
    try:
        ctypes.windll.wininet.InternetSetOptionW(None, 39, None, 0)   # settings changed
        ctypes.windll.wininet.InternetSetOptionW(None, 37, None, 0)   # refresh
    except OSError:
        pass


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--apply"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0,
                        winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        try:
            current = winreg.QueryValueEx(key, "ProxyOverride")[0]
        except OSError:
            current = ""
        try:
            enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
        except OSError:
            enabled = None
        server = ""
        try:
            server = winreg.QueryValueEx(key, "ProxyServer")[0]
        except OSError:
            pass

        parts = [p for p in current.split(";") if p.strip()]

        if mode == "--check":
            print(f"ProxyEnable  : {enabled}  (1 = system proxy on)")
            print(f"ProxyServer  : {server}")
            print(f"ProxyOverride: {current}")
            missing = [w for w in WANT if w not in parts]
            print(f"missing Steam bypass entries: {missing or 'none'}")
            return 0

        if mode == "--remove":
            parts = [p for p in parts if p not in WANT]
            action = "removed"
        else:
            for w in WANT:
                if w not in parts:
                    parts.append(w)
            action = "added"

        new = ";".join(parts)
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, new)
        refresh()
        print(f"{action} Steam bypass entries")
        print(f"ProxyEnable  : {enabled}  (1 = system proxy on)")
        print(f"ProxyOverride: {new}")
        print("restart Steam so it re-reads the proxy configuration")
        return 0


if __name__ == "__main__":
    sys.exit(main())
