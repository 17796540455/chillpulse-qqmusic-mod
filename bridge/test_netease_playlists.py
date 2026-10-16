"""Verify NetEase user playlists end to end (provider + bridge)."""
import json
import sys
import time
import urllib.request

NEW = r"E:\ChillPulseQQMod"
PORT = 38654
B = f"http://127.0.0.1:{PORT}"


def g(path, timeout=120):
    with urllib.request.urlopen(B + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


sys.path.insert(0, NEW + r"\providers")
import netease  # noqa: E402

print("=== 1) 直接调用 provider（绕过桥接）===")
try:
    pls = netease.playlists("1591517354")           # 故意传 QQ 的 uin，应被忽略
    print(f"  歌单数: {len(pls)}")
    for p in pls:
        tag = "♥ " if p.get("special") == "fav" else "  "
        print(f"    {tag}{p['tid']:<14} {p['dirName'][:26]:<28} {p['songNum']:>5} 首")
except Exception as exc:                              # noqa: BLE001
    print("  失败:", type(exc).__name__, exc)

print("=== 2) 走桥接（游戏真实链路）===")
try:
    r = g("/playlists?src=ne")
    print(f"  /playlists?src=ne -> ok={r.get('ok')} logged_in={r.get('logged_in')} "
          f"个数={len(r.get('playlists') or [])} {r.get('msg', '')}")
    for p in (r.get("playlists") or []):
        print(f"    {p.get('id'):<14} {str(p.get('name'))[:26]:<28} {p.get('count')} 首")
except Exception as exc:                              # noqa: BLE001
    print("  失败:", type(exc).__name__, exc)

print("=== 3) QQ 回归 ===")
try:
    r = g("/playlists?src=qq")
    print(f"  /playlists?src=qq -> {len(r.get('playlists') or [])} 个 "
          f"{[p['name'] for p in (r.get('playlists') or [])]}")
except Exception as exc:                              # noqa: BLE001
    print("  失败:", type(exc).__name__, exc)

print("=== 4) 取一首「我喜欢的音乐」里的歌（若存在）验证可播性 ===")
try:
    r = g("/playlists?src=ne")
    pls = r.get("playlists") or []
    fav = next((p for p in pls if p.get("count", 0) > 0), None)
    if fav:
        d = g(f"/playlist?src=ne&id={fav['id']}&count=20")
        tracks = d.get("tracks") or []
        print(f"  {fav['name']}: {d.get('name')} total={d.get('total')} 取回 {len(tracks)} 首")
        for t in tracks[:5]:
            print(f"    {t['id']:<16} {t['name'][:22]:<24} {t['singer'][:14]} vip={t.get('vip')}")
    else:
        print("  没有可用的歌单")
except Exception as exc:                              # noqa: BLE001
    print("  失败:", type(exc).__name__, exc)
