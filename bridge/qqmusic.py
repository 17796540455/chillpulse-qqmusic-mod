"""Minimal read-only QQ Music (y.qq.com) client.

Uses the public-web musicu.fcg endpoints. Read-only by design:
search, own playlists, playlist detail, and song CDN URLs.
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

# Default network timeout for every upstream call, in seconds.
TIMEOUT = 15

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BASE_COMM = {
    "ct": 24,
    "cv": 4747474,
    "v": 8848,
    "format": "json",
    "platform": "yqq.json",
    "uin": "0",
    "g_tk": 5381,
    "g_tk_new_20200303": 5381,
}
MUSICU = "https://u.y.qq.com/cgi-bin/musicu.fcg"

# quality -> filename prefix
QUALITY = {
    "128": "M500",
    "320": "M800",
    "flac": "F000",
    "hires": "RS01",
    "aac": "C400",
}

# quality -> CDN filename extension
QUALITY_EXT = {
    "128": ".mp3",
    "320": ".mp3",
    "flac": ".flac",
    "hires": ".flac",
    "aac": ".m4a",
}

# vkey `result` codes worth naming (0 == success).
RESULT_OK = 0
RESULT_NEED_VIP = 104003


def _post(payload: dict, timeout: int = TIMEOUT,
          cookie: str | None = None) -> dict:
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Referer": "https://y.qq.com/",
        "Origin": "https://y.qq.com",
    }
    if cookie:
        headers["Cookie"] = cookie
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(MUSICU, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def search(keyword: str, page: int = 1, num: int = 20,
           retries: int = 6, timeout: int = TIMEOUT) -> list[dict]:
    """Song search. Returns a list of track dicts.

    The endpoint intermittently answers business code 2001 with empty lists
    (per-request rate limiting); the same query succeeds a moment later, so
    retry with a growing, jittered backoff before giving up.
    """
    payload = {
        "req_0": {
            "module": "music.search.SearchCgiService",
            "method": "DoSearchForQQMusicDesktop",
            "param": {
                "query": keyword,
                "num_per_page": num,
                "page_num": page,
                "search_type": 0,
                "searchid": "0",
                "grp": 1,
            },
        }
    }
    items = []
    last_code = None
    for attempt in range(max(1, retries)):
        j = _post(payload, timeout=timeout)
        req0 = j.get("req_0") or {}
        last_code = req0.get("code")
        data = req0.get("data") or {}
        body = data.get("body") or {}
        items = ((body.get("song") or {}).get("list")) or []
        if items:
            break
        time.sleep(0.6 * (attempt + 1) + random.uniform(0.0, 0.4))
    if not items and last_code not in (0, None, 2001):
        raise RuntimeError(f"search failed: code={last_code}")
    out = []
    for it in items:
        singers = it.get("singer") or []
        out.append({
            "mid": it.get("mid") or it.get("songmid"),
            "name": (it.get("name") or it.get("title") or "").strip(),
            "singers": [s.get("name") for s in singers if s.get("name")],
            "album": ((it.get("album") or {}).get("name") or "").strip(),
            "interval": it.get("interval"),
            "id": it.get("id"),
            "file": ((it.get("file") or {}).get("media_mid")),
            "pay": ((it.get("pay") or {}).get("pay_play")),
        })
    return out


def song_url_ex(mid: str, quality: str = "128", uin: str = "0",
                cookie: str | None = None, media_mid: str | None = None,
                timeout: int = TIMEOUT) -> dict:
    """Resolve a CDN url *and* return why it failed.

    Returns a dict:
        {"url": str|None, "result": int|None, "purl": str, "code": int|None,
         "filename": str, "quality": str, "sip": str}

    ``result`` is the vkey business code: 0 == ok, 104003 == the track needs
    VIP / has no permission for the requested quality (``purl`` is empty).

    ``media_mid`` is the CDN file id from search results (``file.media_mid``);
    for some tracks it differs from the song ``mid`` and the filename must use
    it. Falls back to ``mid``.
    """
    prefix = QUALITY.get(quality, "M500")
    ext = QUALITY_EXT.get(quality, ".mp3")
    file_mid = media_mid or mid
    file_name = f"{prefix}{file_mid}{ext}"
    payload = {
        "req_0": {
            "module": "vkey.GetVkeyServer",
            "method": "CgiGetVkey",
            "param": {
                "guid": "10000",
                "songmid": [mid],
                "songtype": [0],
                "uin": uin,
                "loginflag": 1,
                "platform": "20",
                "filename": [file_name],
            },
        },
        "comm": dict(BASE_COMM, uin=uin),
    }
    headers = {"User-Agent": UA, "Referer": "https://y.qq.com/",
               "Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(MUSICU, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    req0 = j.get("req_0") or {}
    data = req0.get("data") or {}
    infos = data.get("midurlinfo") or []
    info = infos[0] if infos else {}
    purl = info.get("purl") or ""
    sip = data.get("sip") or []
    host = sip[0] if sip else "https://dl.stream.qqmusic.qq.com/"
    if not host.endswith("/"):
        host += "/"
    return {
        "url": (host + purl) if purl else None,
        "purl": purl,
        "result": info.get("result"),
        "code": req0.get("code"),
        "filename": file_name,
        "quality": quality,
        "sip": host,
    }


def song_url(mid: str, quality: str = "128", uin: str = "0",
             cookie: str | None = None, media_mid: str | None = None,
             timeout: int = TIMEOUT) -> str | None:
    """Resolve a playable CDN url for a song mid (None when unavailable)."""
    try:
        return song_url_ex(mid, quality, uin, cookie, media_mid, timeout)["url"]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _first(d: dict, *names):
    """First non-empty value among ``names`` (upstream renames fields at will)."""
    for n in names:
        v = d.get(n)
        if v not in (None, ""):
            return v
    return None


def _int_or(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def user_playlists(uin: str, cookie: str, timeout: int = TIMEOUT) -> list[dict]:
    """Self-created playlists of a logged-in user.

    Live shape (2024+)::

        {"req_0":{"code":0,"data":{"total":4,"v_playlist":[
          {"dirId":201,"dirName":"我喜欢","tid":1967605675,"songNum":7,...}]}}}

    The older payload used ``dissid`` / ``diss_name`` / ``song_cnt``; both name
    sets are read here (new names win) so an upstream rollback keeps working.
    """
    payload = {
        "req_0": {
            "module": "music.musicasset.PlaylistBaseRead",
            "method": "GetPlaylistByUin",
            "param": {"uin": uin},
        },
        "comm": dict(BASE_COMM, uin=uin),
    }
    j = _post(payload, timeout=timeout, cookie=cookie)
    data = ((j.get("req_0") or {}).get("data") or {})
    out = []
    for pl in (data.get("v_playlist") or data.get("playlist") or []):
        tid = _first(pl, "tid", "dissid", "disstid", "dirId")
        out.append({
            "disstid": str(tid) if tid is not None else "",
            "name": _first(pl, "dirName", "diss_name", "title") or "",
            "count": _int_or(_first(pl, "songNum", "song_cnt", "songnum"), 0),
            "dirid": _int_or(_first(pl, "dirId", "dirid"), 0),
        })
    return out


def playlist_detail(disstid: str, song_begin: int = 0, song_num: int = 100,
                    cookie: str | None = None, uin: str = "0",
                    timeout: int = TIMEOUT, dirid: int = 0) -> dict:
    """Playlist contents.

    Two upstream addressing modes, both served by
    ``music.srfDissInfo.DissInfo`` / ``CgiGetDiss``:

    * a normal playlist by ``{"disstid": <tid>, "dirid": 0}``
    * 我喜欢 (the built-in favourites list) by ``{"disstid": 0, "dirid": 201}``

    ``dirid`` defaults to 0 so every existing caller keeps the old behaviour.
    """
    payload = {
        "req_0": {
            "module": "music.srfDissInfo.DissInfo",
            "method": "CgiGetDiss",
            "param": {
                "disstid": int(disstid),
                "dirid": int(dirid),
                "tag": 1,
                "song_begin": song_begin,
                "song_num": song_num,
                "userinfo": 1,
            },
        },
        "comm": dict(BASE_COMM, uin=uin),
    }
    j = _post(payload, timeout=timeout, cookie=cookie)
    data = ((j.get("req_0") or {}).get("data") or {})
    tracks = []
    for s in (data.get("songlist") or []):
        singers = s.get("singer") or []
        tracks.append({
            "mid": s.get("mid") or s.get("songmid"),
            "name": (s.get("name") or s.get("title") or "").strip(),
            "singers": [x.get("name") for x in singers if x.get("name")],
            "album": ((s.get("album") or {}).get("name") or "").strip(),
            "interval": s.get("interval"),
            "file": ((s.get("file") or {}).get("media_mid")),
            "pay": ((s.get("pay") or {}).get("pay_play")),
        })
    return {
        "name": (data.get("dirinfo") or {}).get("title"),
        "total": data.get("total_song_num") or data.get("songnum"),
        "tracks": tracks,
    }


if __name__ == "__main__":
    hits = search("周杰伦")
    print(f"search hits: {len(hits)}")
    for h in hits[:5]:
        print("  ", h["name"], "-", "/".join(h["singers"]), "| mid:", h["mid"])
    if hits:
        u = song_url(hits[0]["mid"])
        print("url:", (u or "NONE")[:140])
