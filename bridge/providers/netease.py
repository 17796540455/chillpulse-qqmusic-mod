"""NetEase Cloud Music (网易云音乐) provider.

Mirrors the QQ Music module's surface so the bridge can treat both the same:

    search(keyword, page, num) -> [raw track]      raw uses qqmusic's field names
    playlists(uid)             -> [raw playlist]
    playlist(pid, count)       -> {"name","total","tracks":[raw]}
    song_url_ex(mid, quality, uin, cookie, media_mid, timeout) -> {"url", ...}

Verified live (see netease_notes.md):
  * search and playlist detail need NO login
  * /song/enhance/player/url and its v1 variant answer
    data[0].code == -110 without a valid MUSIC_U cookie, so playback needs one

NetEase uses two different field spellings: search returns
``artists/album/duration`` while playlist detail returns ``ar/al/dt``.  Both are
normalised here into the QQ-shaped keys the bridge already understands.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from ._aes import encrypt as _aes_encrypt

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_DIR = os.path.dirname(HERE)
AUTH_PATH = os.path.join(BRIDGE_DIR, "auth_netease.json")

BASE = "https://music.163.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 15

#: level -> (label, approximate bitrate) - the bridge passes its own quality
#: names, so accept both spellings.
LEVELS = {
    "128": "standard", "standard": "standard",
    "192": "higher", "higher": "higher",
    "320": "exhigh", "exhigh": "exhigh",
    "flac": "lossless", "lossless": "lossless",
    "hires": "hires",
}
DEFAULT_LEVEL = "exhigh"

# the bridge turns any failure into a Chinese message for the game
class BridgeError(Exception):
    pass


def _opener():
    """Direct connection: the bridge must not use a system proxy."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _cookie() -> str:
    try:
        with open(AUTH_PATH, encoding="utf-8-sig") as fh:
            return str((json.load(fh) or {}).get("cookie") or "")
    except (OSError, ValueError):
        return ""


def _api(path: str, params: dict, timeout: int = TIMEOUT):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": UA, "Referer": BASE + "/",
               "Accept": "application/json, text/plain, */*"}
    ck = _cookie()
    if ck:
        headers["Cookie"] = ck
    req = urllib.request.Request(url, headers=headers)
    try:
        with _opener().open(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise BridgeError(f"网易云返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise BridgeError("无法连接网易云音乐") from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise BridgeError("网易云返回了无法解析的内容") from exc


def _playback_api(params: dict, timeout: int = TIMEOUT) -> dict:
    """Use the authenticated client protocol to obtain CDN-valid play URLs.

    The plain web endpoint can return code=200 with a URL the CDN rejects.
    EAPI changes the request encoding; account playback permissions still apply.
    """
    path = "/api/song/enhance/player/url/v1"
    text = json.dumps(params, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.md5(("nobody" + path + "use" + text + "md5forencrypt").encode("utf-8")).hexdigest()
    plaintext = (path + "-36cd479b6b5-" + text + "-36cd479b6b5-" + digest).encode("utf-8")
    encrypted = _aes_encrypt(plaintext, b"e82ckenh8dichen8").hex().upper()
    # Set the client fields for this request without changing the stored login.
    cookies = [part.strip() for part in _cookie().split(";") if part.strip()
               and part.split("=", 1)[0].strip().lower() not in ("os", "appver")]
    cookies.extend(("os=pc", "appver=3.1.17.204416"))
    req = urllib.request.Request(
        "https://interface3.music.163.com/eapi/song/enhance/player/url/v1",
        data=urllib.parse.urlencode({"params": encrypted}).encode("ascii"),
        headers={"User-Agent": UA, "Referer": BASE + "/",
                 "Cookie": "; ".join(cookies),
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with _opener().open(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise BridgeError(f"网易云播放接口返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise BridgeError("无法连接网易云播放接口") from exc
    except ValueError as exc:
        raise BridgeError("网易云播放接口返回了无法解析的内容") from exc


# --------------------------------------------------------------------------
# normalisation: NetEase -> the QQ-shaped dict the bridge already consumes
# --------------------------------------------------------------------------
def _fee_is_vip(fee) -> int:
    """fee: 0/1 free, 4 cheap album, 8 VIP.  Anything but 0/1 counts as paid."""
    try:
        return 0 if int(fee) in (0, 1) else 1
    except (TypeError, ValueError):
        return 0


def _track(raw: dict) -> dict:
    artists = raw.get("ar") or raw.get("artists") or []
    if isinstance(artists, str):
        artists = [{"name": artists}]
    names = [a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name")]
    album = raw.get("al") or raw.get("album") or {}
    if isinstance(album, str):
        album = {"name": album}
    millis = raw.get("dt") or raw.get("duration") or 0
    try:
        seconds = int(millis) // 1000
    except (TypeError, ValueError):
        seconds = 0
    return {
        "mid": str(raw.get("id") or ""),          # QQ calls it mid
        "name": raw.get("name") or "",
        "singers": names,
        "album": album.get("name") or "",
        "interval": seconds,
        "pay": _fee_is_vip(raw.get("fee")),
        "file": "",                               # NetEase has no media_mid
    }


# --------------------------------------------------------------------------
# provider surface
# --------------------------------------------------------------------------
def search(keyword: str, page: int = 1, num: int = 30) -> list:
    page = max(1, int(page or 1))
    num = max(1, min(50, int(num or 30)))
    j = _api("/api/search/get/web", {"s": keyword, "type": 1,
                                     "limit": num, "offset": (page - 1) * num})
    if int(j.get("code") or 0) != 200:
        # 405 / 406 are NetEase's "too many requests" answers
        raise BridgeError(f"网易云搜索失败（code={j.get('code')}）")
    songs = ((j.get("result") or {}).get("songs")) or []
    if not songs:
        # a repeat of the exact same query can come back empty; one retry helps
        time.sleep(0.6)
        j = _api("/api/search/get/web", {"s": keyword, "type": 1,
                                         "limit": num, "offset": (page - 1) * num})
        songs = ((j.get("result") or {}).get("songs")) or []
    return [_track(s) for s in songs]


def playlists(uid: str = "") -> list:
    """The signed-in user's own playlists (including 我喜欢的音乐).

    The bridge hands every provider the QQ Music uin, which is meaningless
    here - the account id always comes from our own cookie.
    """
    if not _cookie():
        raise BridgeError("需要网易云登录")
    account = ""
    try:
        j = _api("/api/nuser/account/get", {})
        account = str((j.get("profile") or {}).get("userId") or "")
    except BridgeError:
        account = ""
    if not account:
        # no account endpoint answer -> the cookie is stale
        raise BridgeError("网易云登录已失效，请重新获取 MUSIC_U")
    j = _api("/api/user/playlist", {"uid": account, "limit": 1000, "offset": 0})
    out = []
    for p in (j.get("playlist") or []):
        pid = str(p.get("id") or "").strip()
        if not pid:
            continue
        name = p.get("name") or ""
        count = int(p.get("trackCount") or 0)
        # NetEase marks 我喜欢的音乐 with specialType 5, like QQ's 我喜欢(dirId 201)
        fav = int(p.get("specialType") or 0) == 5
        # The bridge reads disstid/name/dirid/song_cnt (that is the shape
        # qqmusic.user_playlists returns), so provide those - and the camelCase
        # spelling as well, in case other callers look for it.
        out.append({
            "disstid": pid, "tid": pid,
            "name": name, "dirName": name,
            "dirid": 201 if fav else 0,
            # the bridge has used several spellings for the track count over
            # time; give it all of them so the number shows up in game
            "song_cnt": count, "songNum": count, "songnum": count,
            "count": count, "total": count, "trackCount": count,
            "special": "fav" if fav else "",
        })
    return out


def playlist(pid: str, offset: int = 0, count: int = 1000) -> dict:
    """Playlist detail.

    The positional shape matches qqmusic.playlist_detail(disstid, offset, count)
    because the bridge calls providers that way - getting this wrong made every
    playlist return exactly one track (offset 0 was read as the count).
    """
    # ask NetEase for the whole list in one go, then slice here
    j = _api("/api/v6/playlist/detail", {"id": pid, "n": 1000})
    pl = j.get("playlist") or {}
    if not pl:
        raise BridgeError("网易云歌单不存在或不可访问")
    all_tracks = [_track(t) for t in (pl.get("tracks") or [])]
    total = int(pl.get("trackCount") or len(all_tracks))
    # Large playlists only carry the first ~20 tracks in the detail response;
    # the remainder has to come from the track/all endpoint.
    if total > len(all_tracks):
        try:
            more = _api("/api/playlist/track/all",
                        {"id": pid, "limit": 1000, "offset": len(all_tracks)})
            extra = [_track(t) for t in (more.get("songs") or [])]
            if extra:
                all_tracks += extra
        except BridgeError:
            pass                       # keep whatever the detail response gave us
    start = max(0, int(offset or 0))
    want = max(1, int(count or 1000))
    return {"name": pl.get("name") or "", "total": total,
            "tracks": all_tracks[start:start + want]}


def song_url_ex(mid: str, quality: str = "128", uin: str = "0",
                cookie: str | None = None, media_mid: str | None = None,
                timeout: int = TIMEOUT) -> dict:
    """Resolve a direct audio url.

    Returns the same dict shape as qqmusic.song_url_ex.  Without a login the
    inner code is -110 and ``url`` is empty; the bridge turns that into a clear
    message rather than a generic failure.
    """
    if not str(mid).isdigit():
        raise BridgeError("网易云歌曲 ID 无效")
    level = LEVELS.get(str(quality), DEFAULT_LEVEL)
    j = _playback_api({"ids": f"[{mid}]", "level": level, "encodeType": "flac"},
                      timeout=timeout)
    data = j.get("data") or [{}]
    d = data[0] if isinstance(data, list) and data else {}
    url = d.get("url") or ""
    inner = d.get("code")
    if d.get("freeTrialInfo"):
        raise BridgeError("该歌曲仅提供试听片段，当前账号没有完整播放权限")
    if url and inner == 200:
        return {"url": url, "purl": url, "result": inner, "code": j.get("code"),
                "filename": f"{mid}.mp3", "quality": level,
                "sip": urllib.parse.urlparse(url).netloc, "br": d.get("br"),
                "size": d.get("size"), "level": d.get("level")}
    # not playable: explain why as precisely as possible.
    # NB: only *our* cookie counts here - the bridge hands every provider the
    # QQ Music cookie, and treating that as a NetEase login made every VIP
    # track claim "needs membership" instead of "needs login".
    if inner == -110 or inner == -460:
        if not _cookie():
            raise BridgeError("该歌曲需要网易云登录")
        raise BridgeError(f"网易云未授予播放权限（code={inner}），请在官方客户端确认歌曲可播放并检查登录状态")
    raise BridgeError(f"网易云未返回播放地址（code={inner}）")


def logged_in() -> bool:
    """True when a cookie is present and the account endpoint accepts it."""
    if not _cookie():
        return False
    try:
        j = _api("/api/nuser/account/get", {})
    except BridgeError:
        return False
    return bool((j.get("profile") or {}).get("userId"))


def nickname() -> str:
    try:
        j = _api("/api/nuser/account/get", {})
    except BridgeError:
        return ""
    return str((j.get("profile") or {}).get("nickname") or "")


# --------------------------------------------------------------------------
# self test:  py -3 netease.py [keyword]
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    kw = sys.argv[1] if len(sys.argv) > 1 else "周杰伦"
    print(f"cookie present : {bool(_cookie())}   logged_in: {logged_in()}")
    hits = search(kw, 1, 5)
    print(f"search {kw!r} -> {len(hits)} hits")
    for h in hits:
        print(f"   {h['mid']:>12}  {h['name'][:26]:<28} {'/'.join(h['singers'])[:20]:<22} "
              f"{h['interval']}s  vip={h['pay']}")
    if hits:
        try:
            info = song_url_ex(hits[0]["mid"], "320")
            print(f"url  -> OK  br={info['br']}  {info['url'][:70]}")
        except BridgeError as exc:
            print(f"url  -> {exc}")
    try:
        pl = playlist("3778678", 200)
        print(f"playlist 3778678 -> {pl['name']!r} total={pl['total']} got={len(pl['tracks'])}")
        if pl["tracks"]:
            t = pl["tracks"][0]
            print(f"   first: {t['mid']} {t['name']} - {'/'.join(t['singers'])}")
    except BridgeError as exc:
        print(f"playlist -> {exc}")
