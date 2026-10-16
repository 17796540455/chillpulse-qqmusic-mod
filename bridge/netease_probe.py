"""Minimal NetEase Cloud Music (网易云音乐) API probe - stdlib only.

Answers the questions the bridge needs before a provider can be written:
  * does the plain (unencrypted) web API still work?
  * what do search / playlist / song-url return, exactly?
  * what changes with a login cookie (MUSIC_U) for VIP tracks?

Direct connection only: a local proxy (Clash) rejects some hosts, so urllib's
proxy autodetection is switched off.

    py -3 netease_probe.py search "周杰伦"
    py -3 netease_probe.py playlist 3778678
    py -3 netease_probe.py url 347230
    py -3 netease_probe.py cookie "MUSIC_U=...; __csrf=..."   (store a login)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
AUTH = os.path.join(HERE, "auth_netease.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BASE = "https://music.163.com"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def cookie() -> str:
    try:
        with open(AUTH, encoding="utf-8-sig") as fh:
            return (json.load(fh) or {}).get("cookie", "")
    except (OSError, ValueError):
        return ""


def api(path: str, params: dict, timeout: int = 15):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": UA, "Referer": BASE + "/",
               "Accept": "application/json, text/plain, */*"}
    ck = cookie()
    if ck:
        headers["Cookie"] = ck
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    with OPENER.open(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw), (time.time() - t0) * 1000


def show(label, value, limit=180):
    text = str(value)
    print(f"    {label:<22} {text[:limit]}")


def cmd_search(kw, n=5):
    print(f"[search] {kw!r}")
    try:
        j, ms = api("/api/search/get/web", {"s": kw, "type": 1, "limit": n, "offset": 0})
    except Exception as exc:                                  # noqa: BLE001
        print(f"    FAIL {type(exc).__name__}: {exc}")
        return 1
    print(f"    OK   {ms:.0f} ms   code={j.get('code')}")
    songs = ((j.get("result") or {}).get("songs")) or []
    print(f"    songs: {len(songs)}")
    for s in songs[:n]:
        artists = "/".join(a.get("name", "") for a in (s.get("artists") or s.get("ar") or []))
        album = ((s.get("album") or s.get("al") or {}) or {}).get("name", "")
        print(f"      id={s.get('id')}  {s.get('name')} - {artists}  [{album}] "
              f"dur={s.get('duration') or s.get('dt')} fee={s.get('fee')}")
    print(f"    raw keys of one song: {sorted(songs[0].keys())[:14] if songs else '-'}")
    return 0


def cmd_playlist(pid, n=5):
    print(f"[playlist] id={pid}")
    for path in ("/api/v6/playlist/detail", "/api/playlist/detail"):
        try:
            j, ms = api(path, {"id": pid, "n": 1000})
        except Exception as exc:                              # noqa: BLE001
            print(f"    {path} FAIL {type(exc).__name__}: {exc}")
            continue
        pl = j.get("playlist") or (j.get("result") or {}).get("playlist") or {}
        tracks = pl.get("tracks") or []
        print(f"    OK   {path}  {ms:.0f} ms  code={j.get('code')}")
        show("name", pl.get("name"))
        show("trackCount", pl.get("trackCount"))
        show("tracks returned", len(tracks))
        for t in tracks[:n]:
            artists = "/".join(a.get("name", "") for a in ((t.get("ar") or t.get("artists")) or []))
            print(f"      id={t.get('id')}  {t.get('name')} - {artists}  fee={t.get('fee')}")
        if tracks:
            print(f"    raw keys of one track: {sorted(tracks[0].keys())[:14]}")
        return 0
    return 1


def cmd_url(song_id, br=320000):
    print(f"[url] song={song_id} br={br}" + ("  (with cookie)" if cookie() else "  (no cookie)"))
    try:
        j, ms = api("/api/song/enhance/player/url",
                    {"ids": f"[{song_id}]", "br": br})
    except Exception as exc:                                  # noqa: BLE001
        print(f"    FAIL {type(exc).__name__}: {exc}")
        return 1
    print(f"    OK   {ms:.0f} ms  code={j.get('code')}")
    data = j.get("data") or []
    if not data:
        print("    no data[] in the response")
        return 1
    d = data[0]
    show("code", d.get("code"))
    show("url", (d.get("url") or "")[:110])
    show("br / size", f"{d.get('br')} / {d.get('size')}")
    show("fee / payed", f"{d.get('fee')} / {d.get('payed')}")
    show("level", d.get("level"))
    show("freeTrialInfo", d.get("freeTrialInfo"))
    if d.get("url"):
        print("    -> playable")
        return 0
    print("    -> NOT playable without a valid login cookie (VIP only, or region locked)")
    return 1


def cmd_cookie(raw):
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    keep = [p for p in parts if p.split("=")[0].strip() in
            ("MUSIC_U", "__csrf", "MUSIC_A", "NMTID", "__remember_me")]
    if not keep:
        print("  no MUSIC_U / __csrf found in that string")
        return 1
    with open(AUTH, "w", encoding="utf-8") as fh:
        json.dump({"cookie": "; ".join(keep)}, fh, ensure_ascii=False, indent=2)
    print(f"  saved {len(keep)} cookie field(s) to {AUTH}")
    try:
        j, ms = api("/api/nuser/account/get", {})
        prof = j.get("profile") or {}
        print(f"  account check: code={j.get('code')} nickname={prof.get('nickname')!r} "
              f"vipType={prof.get('vipType')} ({ms:.0f} ms)")
    except Exception as exc:                                  # noqa: BLE001
        print(f"  account check failed: {type(exc).__name__}: {exc}")
    return 0


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "search":
        return cmd_search(rest[0] if rest else "周杰伦")
    if cmd == "playlist":
        return cmd_playlist(rest[0] if rest else "3778678")
    if cmd == "url":
        return cmd_url(rest[0] if rest else "347230",
                       int(rest[1]) if len(rest) > 1 else 320000)
    if cmd == "cookie":
        return cmd_cookie(rest[0] if rest else "")
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
