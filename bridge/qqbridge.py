#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qqbridge -- local QQ Music (QQ音乐) bridge for the ChillPulse GameMaker mod.

A single-file, stdlib-only HTTP service that the game talks to with
``http_get`` / ``http_post_string``::

    http://127.0.0.1:38610/status
    http://127.0.0.1:38610/search?q=...&page=1&n=30
    http://127.0.0.1:38610/playlists
    http://127.0.0.1:38610/playlist?id=<disstid>&offset=0&count=50
    http://127.0.0.1:38610/play?id=<mid>&name=...&singer=...
    http://127.0.0.1:38610/playstate?id=<mid>
    http://127.0.0.1:38610/prefetch?id=<mid>&name=...&singer=...
    http://127.0.0.1:38610/stop
    http://127.0.0.1:38610/login   /loginstatus   /quit

Every response is UTF-8 JSON with ``Content-Type: application/json`` and an
``ok`` boolean.  Nothing here ever blocks the HTTP handler: ``/play`` hands the
download+transcode to a worker thread and returns ``state:"preparing"`` at
once, while a second HTTP thread keeps answering ``/playstate`` and ``/status``.

Run::

    python qqbridge.py --port 38610 --game-dir "E:\\steam\\...\\ChillPulse"

See ``bridge\\README.md`` for the endpoint contract and auth.json format.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import http.cookiejar
import json
import ctypes
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# QQ Music is a domestic service and must NOT go through whatever system proxy
# the user has configured.  urllib picks the system proxy up automatically, and
# a local Clash ruleset can reject or misroute these hosts - which shows up
# in-game as "not signed in" or as endless buffering.  Install an opener that
# ignores proxies for every request made through this module (and through
# qqmusic, which uses the same global opener).
urllib.request.install_opener(
    urllib.request.build_opener(urllib.request.ProxyHandler({})))

import providers as qqmusic  # noqa: E402  (source dispatcher: QQ + NetEase)

VERSION = "1.0"
DEFAULT_PORT = 38610
DEFAULT_GAME_DIR = r"E:\steam\steam\steamapps\common\ChillPulse"
HOST = "127.0.0.1"

#: Last-resort ffmpeg location (checked after PATH, before --ffmpeg).
KNOWN_FFMPEG = (r"C:\Users\wmcyh\AppData\Local\Microsoft\WinGet\Packages"
                r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
                r"\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe")

BRIDGE_DIR = HERE
CACHE_DIR = os.path.join(BRIDGE_DIR, "cache")
TMP_DIR = os.path.join(CACHE_DIR, "tmp")     # scratch: mp3 downloads, .part files
LOG_PATH = os.path.join(BRIDGE_DIR, "qqbridge.log")
AUTH_PATH = os.path.join(BRIDGE_DIR, "auth.json")
TRACKS_PATH = os.path.join(CACHE_DIR, "tracks.json")
QR_PATH = os.path.join(CACHE_DIR, "login_qr.png")
PIPELINE_PATH = os.path.join(CACHE_DIR, "pipeline.json")

OUT_SUBDIR = "qqmusic_cache"
#: Every quality the vkey endpoint knows, cheapest-first (fallback tail order).
QUALITY_CHAIN = ("128", "320", "flac")
#: `--quality X` -> the order vkeys are tried in *for that choice*.
#: The chosen tier is always tried first; the remaining tiers are the fallback
#: tail when the chosen one answers with no url (not probed speculatively).
QUALITY_PREFERENCE = {
    "320": ("320", "128", "flac"),
    "128": ("128", "320", "flac"),
    "flac": ("flac", "320", "128"),
}
DEFAULT_QUALITY = "128"
UPSTREAM_TIMEOUT = 12                    # seconds, per upstream HTTP call
DOWNLOAD_TIMEOUT = 20
FFMPEG_TIMEOUT = 180
KILL_GRACE = 8                           # seconds to wait for ffmpeg to die
OGG_MIN_BYTES = 8192                     # below this a transcode is unusable
MP3_MIN_BYTES = 16384                    # below this a download is unusable
PREPARE_KINDS = ("play", "prefetch")        # who owns the pipeline
PREPARE_STATES = ("preparing", "prefetching")   # a job that is still running

# --- prepare pipeline selection -------------------------------------------
# "url-in" : ffmpeg reads the CDN url itself (-user_agent/-headers/-i <url>)
# "pipe"   : python streams the CDN response into ffmpeg's stdin; the urllib
#            reader is several times faster than ffmpeg's own HTTP reader on
#            this CDN, and download still overlaps the encode
# "disk"   : download the whole mp3, then encode from the file
PIPELINE_ORDER = ("url-in", "pipe", "disk")
URL_IN_PROBE = 6.0                       # seconds before judging url-in speed
URL_IN_MIN_MBPS = 0.15                   # below this, url-in is demoted
# NB: the probe can only observe the *encoded output* growing, and libvorbis
# produces roughly 0.5 MB/s of ogg for a 4-minute track.  The threshold must
# therefore sit well under a healthy encode rate - at 1.5 MB/s it demoted a
# perfectly fast pipeline on every single track.
URL_IN_MAX_SECONDS = 18.0                # hard cap for the url-in attempt
#: When url-in is known to be slow in this environment it stays demoted across
#: restarts (cache/pipeline.json) instead of wasting the probe on every track.
URL_IN_SLOW = {"flag": False, "loaded": False, "saved": False}

# --- cache hygiene ---------------------------------------------------------
CACHE_MAX_MB = 500                       # ogg cache budget
CACHE_MAX_FILES = 300                    # ogg cache file budget
CACHE_KEEP_SECONDS = 600                 # never evict anything this fresh
EVICT_INTERVAL = 60                      # seconds between eviction sweeps
#: song ids may carry their source - "ne:347230", "qq:0022QuVR1LcRHN".
#: A bare id means QQ Music, so an already-patched game keeps working.
MID_RE = re.compile(r"^(?:(?:qq|ne):)?[A-Za-z0-9_-]{5,64}$")
FFMPEG_ARGS = ["-c:a", "libvorbis", "-q:a", "4"]

LOG = logging.getLogger("qqbridge")

# --------------------------------------------------------------------------
# globals / state
# --------------------------------------------------------------------------
GAME_DIR = DEFAULT_GAME_DIR
FFMPEG = None
FFPROBE = None
QUALITY = DEFAULT_QUALITY

JOBS: dict[str, dict] = {}          # mid -> job state dict
JOBS_LOCK = threading.RLock()
PLAY_LOCK = threading.RLock()       # serialises /play + /prefetch bookkeeping

#: The prepare that currently owns the network/CPU: ``kind`` is "play" (a user
#: request) or "prefetch" (low priority).  ``cancel`` is the event the owning
#: worker polls; ``proc`` is its live ffmpeg, killed on preemption.
CUR = {"mid": None, "cancel": None, "proc": None, "kind": None}
CUR_LOCK = threading.RLock()

#: Single-slot, low-priority prefetch queue.  Hover traffic replaces the slot
#: over and over; only the newest target is ever prepared.
PF_LOCK = threading.RLock()
PF_COND = threading.Condition(PF_LOCK)
PF_SLOT: "collections.deque[tuple]" = collections.deque()
PF_RUNNING: str | None = None
PF_GEN = 0

TRACKS: dict[str, dict] = {}        # mid -> metadata cache (media_mid, name, ...)
TRACKS_LOCK = threading.Lock()
TRACKS_DIRTY = False

SEARCH_CACHE: dict[tuple, tuple] = {}   # (q, page, n) -> (timestamp, hits)
SEARCH_LOCK = threading.Lock()
SEARCH_TTL = 900

EVICT_LOCK = threading.RLock()
LAST_EVICT = 0.0

# --- upstream vkey throttle -------------------------------------------------
# A prefetch flood (the game fires /prefetch on hover) used to hammer the vkey
# endpoint several times a second, which pushed resolve times from ~0.2s to
# ~5s.  Resolutions are serialised with a minimum spacing, deduplicated per
# (mid, quality), and a play never waits behind a prefetch.
VKEY_MIN_SPACING = 1.2
VKEY_WAIT_TIMEOUT = 12.0
VKEY_LOCK = threading.RLock()
VKEY_COND = threading.Condition(VKEY_LOCK)
VKEY_LAST = 0.0
VKEY_KIND = ""
VKEY_INFLIGHT: dict[tuple, dict] = {}
VKEY_STATS = {"calls": 0, "cached": 0, "waits": 0, "wait_seconds": 0.0}

AUTH = {"uin": "", "cookie": "", "nickname": "", "logged_in": False}
AUTH_LOCK = threading.Lock()
AUTH_MTIME = None

QR = {"state": "unsupported", "nickname": "", "msg": "", "ts": 0.0}
QR_LOCK = threading.Lock()
QR_TOKEN = 0


class BridgeError(Exception):
    """Recoverable, user-facing failure (short Chinese message)."""


class Cancelled(Exception):
    """The job was cancelled by /stop or by a newer /play."""


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------
def setup_logging() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    # keep the log from growing without bound across many mod sessions
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 4 * 1024 * 1024:
            bak = LOG_PATH + ".1"
            if os.path.exists(bak):
                os.remove(bak)
            os.replace(LOG_PATH, bak)
    except OSError:
        pass
    LOG.setLevel(logging.DEBUG)
    LOG.propagate = False
    fh = logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    LOG.addHandler(fh)
    logging.raiseExceptions = False   # never dump tracebacks to stderr

    def _thread_hook(args):
        LOG.error("unhandled exception in thread %s: %s",
                  getattr(args.thread, "name", "?"), args.exc_value,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = _thread_hook


def log(msg: str, *args) -> None:
    LOG.info(msg, *args)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _fix_mojibake(value: str) -> str:
    """Repair raw UTF-8 bytes that the request line decoded as latin-1.

    GameMaker may put Chinese text in a URL un-escaped; ``BaseHTTPRequestHandler``
    decodes the request line as iso-8859-1, so such values arrive as mojibake.
    Percent-encoded values are already correct and pass through untouched.
    """
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _retry(fn, tries: int = 2, label: str = "upstream", delay: float = 0.6):
    """Call ``fn`` with one retry on transient failure.

    Cancellation and user-facing BridgeError are never retried.
    """
    last = None
    for attempt in range(1, max(1, tries) + 1):
        try:
            return fn()
        except (Cancelled, BridgeError):
            raise
        except Exception as exc:                      # noqa: BLE001
            last = exc
            LOG.warning("%s attempt %d/%d failed: %s: %s",
                        label, attempt, tries, type(exc).__name__, exc)
            if attempt < tries:
                time.sleep(delay)
    raise last                                        # type: ignore[misc]


def _int(value, default: int = 0, lo: int | None = None,
         hi: int | None = None) -> int:
    try:
        out = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def game_cache_dir() -> str:
    return os.path.join(GAME_DIR, OUT_SUBDIR)


def _cdn_referer(url: str) -> str:
    """The Referer the url's own CDN expects.

    Each service rejects a request that carries a foreign Referer: NetEase
    answers 403 Forbidden when it sees QQ Music's, which is why NetEase
    downloads failed while its url resolution worked.
    """
    host = urllib.parse.urlsplit(url or "").netloc.lower()
    if host.endswith("126.net") or "music.163.com" in host or host.endswith("163.com"):
        return "https://music.163.com/"
    return "https://y.qq.com/"


def out_path(mid: str) -> str:
    return os.path.join(game_cache_dir(), qqmusic.safe_name(mid) + ".ogg")


def rel_path(mid: str) -> str:
    return f"{OUT_SUBDIR}/{qqmusic.safe_name(mid)}.ogg"


def is_ready(mid: str) -> bool:
    try:
        return os.path.getsize(out_path(mid)) > 1024
    except OSError:
        return False


def cleanup_stale_parts(verbose: bool = False) -> int:
    """Drop scratch ``*.part`` files and dead source mp3s.

    Runs at startup, after an abort and after every prepare, in both
    ``cache\\tmp`` and the output ``qqmusic_cache`` folder.  Returns the number
    of files removed.
    """
    removed = 0
    for folder in (TMP_DIR, CACHE_DIR, game_cache_dir()):
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            if folder == CACHE_DIR and os.path.isdir(os.path.join(folder, name)):
                continue                     # cache\\tmp is handled on its own
            # .part = half-written; .mp3 = a source file we no longer keep
            # (the pipeline reads the CDN directly and scratch lives in tmp\\)
            if not (name.endswith(".part") or name.endswith(".mp3")):
                continue
            path = os.path.join(folder, name)
            try:
                size = os.path.getsize(path)
                os.remove(path)
                removed += 1
                if verbose:
                    LOG.info("removed stale scratch %s (%d bytes)", path, size)
            except OSError:
                pass
    if removed:
        LOG.info("cache hygiene: removed %d stale scratch file(s)", removed)
    return removed


def _is_output_name(name: str) -> bool:
    return name.endswith(".ogg") and not name.endswith(".part")


def cache_stats(folder: str | None = None) -> dict:
    """Sizes/counts of the ogg output cache and the bridge cache folder."""
    folder = folder or game_cache_dir()
    out = {"ogg_bytes": 0, "ogg_files": 0, "other_bytes": 0,
           "cache_bytes": 0, "tmp_bytes": 0}
    try:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if _is_output_name(name):
                out["ogg_bytes"] += size
                out["ogg_files"] += 1
            else:
                out["other_bytes"] += size
    except OSError:
        pass
    for sub in (CACHE_DIR, TMP_DIR):
        total = 0
        try:
            for name in os.listdir(sub):
                path = os.path.join(sub, name)
                if os.path.isfile(path):
                    total += _file_size(path)
        except OSError:
            pass
        if sub == CACHE_DIR:
            out["cache_bytes"] = total
        else:
            out["tmp_bytes"] = total
    return out


def evict_cache(force: bool = False, max_mb: int | None = None,
                max_files: int | None = None) -> int:
    """LRU-evict transcoded oggs down to the size/count budget.

    Anything modified within ``CACHE_KEEP_SECONDS`` is never touched -- that is
    what protects the track the game is playing right now and the one being
    prepared, neither of which the bridge can identify reliably.
    """
    global LAST_EVICT
    limit_mb = CACHE_MAX_MB if max_mb is None else max_mb
    limit_files = CACHE_MAX_FILES if max_files is None else max_files
    now = time.time()
    with CUR_LOCK:
        hold = {m for m in (CUR.get("mid"), PF_RUNNING) if m}
    with JOBS_LOCK:
        hold |= {m for m, j in JOBS.items() if j.get("state") == "preparing"}
    with EVICT_LOCK:
        if not force and now - LAST_EVICT < EVICT_INTERVAL:
            return 0
        LAST_EVICT = now
        folder = game_cache_dir()
        entries = []
        total = 0
        try:
            names = os.listdir(folder)
        except OSError:
            return 0
        for name in names:
            if not _is_output_name(name):
                continue
            path = os.path.join(folder, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, name, path))
            total += st.st_size
        entries.sort()                        # oldest first == LRU
        limit_bytes = max(0, limit_mb) * 1024 * 1024
        kept = len(entries)
        evicted = 0
        freed = 0
        for mtime, size, name, path in entries:
            over = (total > limit_bytes) or (kept > limit_files)
            if not over:
                break
            mid = name[:-4]
            if mid in hold:
                continue                          # currently playing/preparing
            age = now - mtime
            if age < CACHE_KEEP_SECONDS:
                continue                          # too fresh to judge
            try:
                os.remove(path)
            except OSError:
                continue
            total -= size
            kept -= 1
            freed += size
            evicted += 1
            LOG.info("evicted cached ogg %s (%.1f MB, age %.0f min)",
                     name, size / 1048576.0, age / 60.0)
        if evicted:
            LOG.info("cache eviction: removed %d file(s), freed %.1f MB; "
                     "now %.1f MB / %d files (limits %d MB / %d files)",
                     evicted, freed / 1048576.0, total / 1048576.0, kept,
                     limit_mb, limit_files)
        return evicted


def log_cache_stats(prefix: str = "cache stats") -> None:
    st = cache_stats()
    LOG.info("%s: ogg=%d files %.1f MB | other in qqmusic_cache %.1f MB | "
             "bridge cache %.1f MB (tmp %.1f MB)", prefix, st["ogg_files"],
             st["ogg_bytes"] / 1048576.0, st["other_bytes"] / 1048576.0,
             st["cache_bytes"] / 1048576.0, st["tmp_bytes"] / 1048576.0)


def find_ffmpeg(explicit: str | None) -> str | None:
    """PATH first, then the known winget install, then --ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    if os.path.isfile(KNOWN_FFMPEG):
        return KNOWN_FFMPEG
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        alt = shutil.which(explicit)
        if alt:
            return alt
        LOG.warning("--ffmpeg %s not usable; treating ffmpeg as missing", explicit)
    return None


# --------------------------------------------------------------------------
# metadata cache (media_mid + display fields, survives restarts)
# --------------------------------------------------------------------------
def load_tracks() -> None:
    try:
        with open(TRACKS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            with TRACKS_LOCK:
                TRACKS.update({k: v for k, v in data.items() if isinstance(v, dict)})
        LOG.info("loaded %d cached track records", len(TRACKS))
    except FileNotFoundError:
        pass
    except Exception as exc:                          # noqa: BLE001
        LOG.warning("track cache unreadable: %s: %s", type(exc).__name__, exc)


def save_tracks() -> None:
    global TRACKS_DIRTY
    with TRACKS_LOCK:
        if not TRACKS_DIRTY:
            return
        snapshot = dict(TRACKS)
        TRACKS_DIRTY = False
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = TRACKS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False)
        os.replace(tmp, TRACKS_PATH)
    except OSError as exc:
        LOG.warning("could not persist track cache: %s", exc)


def remember(raw_tracks: list[dict]) -> None:
    """Store metadata (notably media_mid) for later /play + /playstate calls."""
    global TRACKS_DIRTY
    changed = False
    with TRACKS_LOCK:
        for t in raw_tracks:
            mid = (t.get("mid") or "").strip()
            if not mid:
                continue
            rec = {
                "name": t.get("name") or "",
                "singer": "/".join(s for s in (t.get("singers") or []) if s),
                "album": t.get("album") or "",
                "dur": _int(t.get("interval")),
                "vip": 1 if t.get("pay") else 0,
                "media_mid": t.get("file") or mid,
            }
            if TRACKS.get(mid) != rec:
                TRACKS[mid] = rec
                changed = True
    if changed:
        TRACKS_DIRTY = True
        save_tracks()


def track_meta(mid: str) -> dict:
    with TRACKS_LOCK:
        return dict(TRACKS.get(mid) or {})


def track_out(raw: dict) -> dict:
    """Normalise a client track dict to the frozen game-facing shape."""
    singers = raw.get("singers") or []
    if isinstance(singers, str):
        singer = singers
    else:
        singer = "/".join(s for s in singers if s)
    return {
        # The id carries its source so that /play, /playstate and /prefetch can
        # route without any extra parameter; QQ ids stay bare, which keeps an
        # already-patched game and the existing ogg cache working unchanged.
        "id": qqmusic.join_id(qqmusic.current_source(), raw.get("mid") or ""),
        "name": raw.get("name") or "",
        "singer": singer,
        "album": raw.get("album") or "",
        "dur": _int(raw.get("interval")),
        "vip": 1 if raw.get("pay") else 0,
    }


# --------------------------------------------------------------------------
# auth.json
# --------------------------------------------------------------------------
def reload_auth(force: bool = False) -> dict:
    """(Re)read bridge/auth.json when its mtime changes."""
    global AUTH_MTIME
    try:
        mtime = os.path.getmtime(AUTH_PATH)
    except OSError:
        mtime = None
    with AUTH_LOCK:
        if not force and mtime == AUTH_MTIME:
            return dict(AUTH)
        AUTH_MTIME = mtime
        data: dict = {}
        if mtime is not None:
            try:
                with open(AUTH_PATH, "r", encoding="utf-8-sig") as fh:
                    data = json.load(fh) or {}
                if not isinstance(data, dict):
                    raise ValueError("auth.json must contain a JSON object")
            except Exception as exc:                  # noqa: BLE001
                LOG.error("auth.json invalid: %s: %s", type(exc).__name__, exc)
                data = {}
        cookie = str(data.get("cookie") or "").strip()
        uin = str(data.get("uin") or "").strip()
        if not uin and cookie:
            m = re.search(r"(?:^|;\s*)uin=o?(\d+)", cookie)
            if m:
                uin = m.group(1)
        logged_in = bool(cookie and uin and uin not in ("0", "o0"))
        AUTH.update({
            "uin": uin or "0",
            "cookie": cookie,
            "nickname": str(data.get("nickname") or "").strip(),
            "logged_in": logged_in,
        })
        LOG.info("auth.json %s (uin=%s logged_in=%s)",
                 "loaded" if mtime is not None else "absent",
                 AUTH["uin"], logged_in)
        return dict(AUTH)


def write_auth_file(uin: str, cookie: str, nickname: str = "") -> None:
    payload = {"uin": uin, "cookie": cookie}
    if nickname:
        payload["nickname"] = nickname
    tmp = AUTH_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, AUTH_PATH)
    reload_auth(force=True)


# --------------------------------------------------------------------------
# audio pipeline
# --------------------------------------------------------------------------
def _set_job(mid: str, **fields) -> None:
    with JOBS_LOCK:
        job = JOBS.setdefault(mid, {})
        job.update(fields)


def _check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled()


def resolve_url(mid: str, cancel: threading.Event,
                qualities: tuple = QUALITY_CHAIN, kind: str = "play"
                ) -> tuple[str, str, dict]:
    """Resolve a CDN url by trying ``qualities`` in order (media_mid first).

    ``qualities`` defaults to the full chain, but /play and /prefetch pass the
    user's ``--quality`` preference so the chosen tier is asked for first and
    the higher tiers are only probed when it answers without a url.
    Raises BridgeError with a short Chinese message when nothing plays.
    """
    _t0 = time.time()
    au = reload_auth()
    _t1 = time.time()
    meta = track_meta(mid)
    _t2 = time.time()
    media_mid = (meta.get("media_mid") or "").strip()
    candidates: list[str] = []
    for cand in (media_mid, mid):
        if cand and cand not in candidates:
            candidates.append(cand)

    last: dict = {}
    for quality in qualities:
        for file_mid in candidates:
            _check_cancel(cancel)

            def _attempt(q=quality, m=file_mid):
                label = f"{mid} {q}"
                with vkey_gate(kind, label, cancel):
                    _check_cancel(cancel)
                    return vkey_for(mid, q, m, kind, cancel, uin=au["uin"],
                                    cookie=au["cookie"] or None,
                                    timeout=UPSTREAM_TIMEOUT)

            info = _retry(_attempt, label=f"vkey {mid} {quality}")
            LOG.info("resolve detail %s q=%s: auth=%.2fs meta=%.2fs vkey=%.2fs",
                     mid, quality, _t1 - _t0, _t2 - _t1, time.time() - _t2)
            last = info
            if info.get("url"):
                LOG.info("resolved %s at quality=%s via %s",
                         mid, quality, info.get("filename"))
                return info["url"], quality, info
            LOG.info("vkey %s quality=%s file=%s -> result=%s (no url)",
                     mid, quality, info.get("filename"), info.get("result"))

    result = last.get("result")
    if result in (qqmusic.RESULT_NEED_VIP, None) or not last.get("purl"):
        raise BridgeError("该歌曲需要绿钻或已下架")
    raise BridgeError(f"无法获取播放地址（错误码 {result}）")


def _create_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# --------------------------------------------------------------------------
# upstream vkey throttle + in-flight dedupe
# --------------------------------------------------------------------------
def reset_vkey_gate() -> None:
    """A fresh job starts outside any upstream spacing window."""
    global VKEY_LAST, VKEY_KIND
    with VKEY_LOCK:
        VKEY_LAST = 0.0
        VKEY_KIND = ""


def vkey_for(mid: str, quality: str, file_mid: str, kind: str,
             cancel: threading.Event, **kw) -> dict:
    """``qqmusic.song_url_ex`` behind the throttle, deduplicated per call.

    Two resolutions for the same (mid, quality, media_mid) are never in flight
    at once: the second caller waits for the first result instead of spending
    another upstream round-trip.
    """
    key = (mid, quality, file_mid)

    def _fn():
        return qqmusic.song_url_ex(mid, quality, media_mid=file_mid, **kw)

    with VKEY_LOCK:
        state = VKEY_INFLIGHT.get(key)
        if state is not None:
            VKEY_STATS["cached"] += 1
            LOG.info("vkey %s %s joined an in-flight resolve", mid, quality)
            owner = False
        else:
            state = {"event": threading.Event(), "value": None, "err": None}
            VKEY_INFLIGHT[key] = state
            owner = True
    if not owner:
        while not state["event"].wait(0.1):
            if cancel.is_set():
                raise Cancelled()
            state = VKEY_INFLIGHT.get(key) or state
        if state["err"] is not None:
            raise state["err"]
        return state["value"]
    try:
        value = _fn()
    except BaseException as exc:                      # noqa: BLE001
        state["err"] = exc
        raise
    else:
        state["value"] = value
        return value
    finally:
        with VKEY_LOCK:
            VKEY_INFLIGHT.pop(key, None)
            state["event"].set()


@contextlib.contextmanager
def vkey_gate(kind: str, label: str, cancel: threading.Event):
    """Serialise upstream vkey calls with ``VKEY_MIN_SPACING`` between them.

    A play never waits behind a prefetch: when the previous caller was a
    prefetch the spacing is skipped, and a cancelled wait (superseded
    prefetch, /stop, a new /play) releases the gate at once.
    """
    global VKEY_LAST, VKEY_KIND
    wait = 0.0
    try:
        deadline = time.time() + VKEY_WAIT_TIMEOUT
        with VKEY_LOCK:
            while True:
                now = time.time()
                prev = VKEY_KIND
                gap = VKEY_MIN_SPACING if prev == "prefetch" else 0.0
                wait = max(0.0, (VKEY_LAST + gap) - now)
                if wait <= 0.0 or now >= deadline:
                    break
                VKEY_COND.wait(min(wait, 0.25))
                if cancel.is_set():
                    raise Cancelled()
            VKEY_LAST = time.time()
            VKEY_KIND = kind
            VKEY_STATS["calls"] += 1
        if wait > 0.05:
            VKEY_STATS["waits"] += 1
            VKEY_STATS["wait_seconds"] += wait
            LOG.info("vkey throttle: %s %s waited %.2fs for the upstream slot",
                     kind, label, wait)
        yield
        return
    finally:
        with VKEY_LOCK:
            VKEY_LAST = time.time()
            VKEY_COND.notify_all()


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _drop_part(*paths: str) -> None:
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def _kill_tree(proc) -> None:
    """Best-effort kill of ffmpeg (and of ffmpeg's own children)."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, creationflags=_create_flags())
        else:
            proc.kill()
    except Exception:                                 # noqa: BLE001
        try:
            proc.kill()
        except OSError:
            pass


def ffprobe_codec(path: str) -> str:
    """``codec_name`` of ``path`` ('' when unknown) -- a cheap sanity check."""
    global FFPROBE
    if FFPROBE is None:
        found = shutil.which("ffprobe")
        if not found and FFMPEG:
            sibling = os.path.join(os.path.dirname(FFMPEG),
                                   "ffprobe.exe" if os.name == "nt" else "ffprobe")
            found = sibling if os.path.isfile(sibling) else None
        FFPROBE = found or ""
    if not FFPROBE:
        return ""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20,
            creationflags=_create_flags())
        return (out.stdout or b"").decode("utf-8", "replace").strip().splitlines()[0] \
            if out.stdout else ""
    except Exception:                                 # noqa: BLE001
        return ""


def _spawn_ffmpeg(cmd: list, stdin_pipe: bool = False):
    """Popen ffmpeg with stderr captured (for diagnostics) and registered."""
    if not FFMPEG:
        raise BridgeError("未找到 ffmpeg")
    LOG.debug("ffmpeg: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=_create_flags())
    with CUR_LOCK:
        CUR["proc"] = proc
    return proc


def _drain_stderr(proc, sink: list) -> None:
    try:
        sink.append(proc.stderr.read() or b"")
    except Exception:                                 # noqa: BLE001
        pass


def _finish_ffmpeg(proc, reader, cancel: threading.Event, errs: list,
                   label: str, stdout_used: bool = False) -> int:
    """Join ``proc`` (+ its stderr reader); kill it on cancel/timeout."""
    try:
        deadline = time.time() + FFMPEG_TIMEOUT
        while proc.poll() is None:
            if cancel.is_set():
                _kill_tree(proc)
                raise Cancelled()
            if time.time() > deadline:
                _kill_tree(proc)
                raise BridgeError("转码超时")
            time.sleep(0.05)
        try:
            proc.wait(timeout=KILL_GRACE)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
        if not stdout_used:
            reader.join(timeout=KILL_GRACE)
        return proc.returncode
    finally:
        with CUR_LOCK:
            if CUR.get("proc") is proc:
                CUR["proc"] = None


def _stderr_tail(errs: list, limit: int = 90) -> str:
    if not errs:
        return ""
    lines = (errs[0] or b"").decode("utf-8", "replace").strip().splitlines()
    return lines[-1][:limit] if lines else ""


def _validate_ogg(part: str, label: str) -> int:
    """Size + (when available) codec validation of a freshly written .part."""
    size = _file_size(part)
    if size < OGG_MIN_BYTES:
        _drop_part(part)
        raise BridgeError(f"{label}失败（输出 {size} 字节，过小）")
    codec = ffprobe_codec(part)
    if codec and codec != "vorbis":
        _drop_part(part)
        raise BridgeError(f"{label}失败（编码为 {codec} 而非 vorbis）")
    return size


def mark_url_in_slow(reason: str) -> None:
    """Remember that ffmpeg's own HTTP reader is the slow way in, this host."""
    if not URL_IN_SLOW["flag"]:
        LOG.warning("demoting the url-in pipeline for this session: %s", reason)
    URL_IN_SLOW["flag"] = True
    if URL_IN_SLOW["saved"]:
        return
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(PIPELINE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"url_in_slow": True, "reason": reason[:200],
                       "ts": int(time.time())}, fh, ensure_ascii=False)
        URL_IN_SLOW["saved"] = True
    except OSError as exc:
        LOG.debug("could not persist pipeline state: %s", exc)


def load_pipeline_state() -> None:
    URL_IN_SLOW["loaded"] = True
    try:
        with open(PIPELINE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except FileNotFoundError:
        return
    except Exception as exc:                          # noqa: BLE001
        LOG.debug("pipeline state unreadable: %s", exc)
        return
    if data.get("url_in_slow"):
        URL_IN_SLOW["flag"] = True
        URL_IN_SLOW["saved"] = True
        LOG.info("url-in pipeline is demoted from a previous run (%s)",
                 data.get("reason") or "no reason recorded")


def enable_url_in() -> None:
    """--pipeline url-in: forget the demotion and persist that choice."""
    URL_IN_SLOW["flag"] = False
    URL_IN_SLOW["saved"] = False
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(PIPELINE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"url_in_slow": False, "reason": "--pipeline url-in",
                       "ts": int(time.time())}, fh, ensure_ascii=False)
        URL_IN_SLOW["saved"] = True
    except OSError:
        pass


def encode_from_url(url: str, dst: str, cancel: threading.Event) -> int:
    """ffmpeg pulls the CDN url and encodes in one pass (download/encode overlap).

    The game's own UA/Referer are replayed to the CDN, otherwise it 403s.
    A throughput watchdog demotes this pipeline when ffmpeg's HTTP reader is
    slow, so the caller can fall back to a faster path.
    """
    if not FFMPEG:
        raise BridgeError("未找到 ffmpeg")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + ".part"
    _drop_part(part)
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-user_agent", qqmusic.UA,
           "-headers", "Referer: " + _cdn_referer(url) + "\r\n",
           "-i", url, *FFMPEG_ARGS, "-f", "ogg", part]
    errs: list = []
    proc = _spawn_ffmpeg(cmd)
    reader = threading.Thread(target=_drain_stderr, args=(proc, errs),
                              name="ffmpeg-err", daemon=True)
    reader.start()
    t0 = time.time()
    slow = False
    elapsed = 0.0
    mbps = 0.0
    try:
        while proc.poll() is None:
            if cancel.is_set():
                _kill_tree(proc)
                raise Cancelled()
            elapsed = time.time() - t0
            size = _file_size(part)
            mbps = (size / 1048576.0) / elapsed if elapsed > 0.2 else 99.0
            if (elapsed > URL_IN_PROBE and size > 262144
                    and mbps < URL_IN_MIN_MBPS):
                slow = True
                break
            if elapsed > URL_IN_MAX_SECONDS:
                slow = True
                break
            time.sleep(0.2)
        if slow:
            _kill_tree(proc)
            try:
                proc.wait(timeout=KILL_GRACE)
            except subprocess.TimeoutExpired:
                pass
            reader.join(timeout=KILL_GRACE)
            _drop_part(part)
            mark_url_in_slow(f"url-in managed only {mbps:.2f} MB/s after "
                             f"{elapsed:.1f}s")
            raise BridgeError(f"URL 直转过慢（{mbps:.2f} MB/s）")
        rc = _finish_ffmpeg(proc, reader, cancel, errs, "url-in")
    finally:
        with CUR_LOCK:
            if CUR.get("proc") is proc:
                CUR["proc"] = None
    if rc != 0:
        _drop_part(part)
        raise BridgeError("URL 直转失败（退出码 %d%s）"
                          % (rc, ("：" + _stderr_tail(errs)) if _stderr_tail(errs) else ""))
    size = _validate_ogg(part, "URL 直转")
    os.replace(part, dst)
    return size


def encode_from_pipe(url: str, dst: str, cancel: threading.Event) -> int:
    """python streams the CDN response into ffmpeg's stdin, encoding as it goes.

    The urllib reader is several times faster than ffmpeg's own HTTP reader on
    this CDN, and download and encode still overlap (the pipe is filled while
    ffmpeg decodes what has already arrived).
    """
    if not FFMPEG:
        raise BridgeError("未找到 ffmpeg")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + ".part"
    _drop_part(part)
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-i", "pipe:0", *FFMPEG_ARGS, "-f", "ogg", part]
    errs: list = []
    proc = _spawn_ffmpeg(cmd, stdin_pipe=True)
    reader = threading.Thread(target=_drain_stderr, args=(proc, errs),
                              name="ffmpeg-err", daemon=True)
    reader.start()
    req = urllib.request.Request(url, headers={
        "User-Agent": qqmusic.UA,
        "Referer": _cdn_referer(url),
        "Accept": "*/*",
    })
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype.startswith("text/") or "html" in ctype:
                raise BridgeError("下载失败（服务器返回了网页）")
            while True:
                _check_cancel(cancel)
                chunk = resp.read(65536)
                if not chunk:
                    break
                proc.stdin.write(chunk)
                total += len(chunk)
    except BridgeError:
        _kill_tree(proc)
        raise
    except Cancelled:
        _kill_tree(proc)
        raise
    except (BrokenPipeError, ConnectionResetError) as exc:
        LOG.debug("ffmpeg closed the pipe early: %s", exc)
    except Exception as exc:                          # noqa: BLE001
        _kill_tree(proc)
        raise BridgeError(f"下载失败（{type(exc).__name__}）") from exc
    finally:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
    rc = _finish_ffmpeg(proc, reader, cancel, errs, "pipe")
    if rc != 0:
        _drop_part(part)
        raise BridgeError("转码失败（退出码 %d%s）"
                          % (rc, ("：" + _stderr_tail(errs)) if _stderr_tail(errs) else ""))
    if total < 65536:
        _drop_part(part)
        raise BridgeError("下载失败（文件过小或为空）")
    size = _validate_ogg(part, "转码")
    os.replace(part, dst)
    return size


def encode_from_disk(url: str, dst: str, cancel: threading.Event) -> int:
    """Legacy path: download the whole mp3 into cache\\tmp, then encode."""
    tmp = os.path.join(TMP_DIR, os.path.basename(dst) + ".src.mp3")
    os.makedirs(TMP_DIR, exist_ok=True)
    _drop_part(tmp, tmp + ".part")
    try:
        _retry(lambda: download(url, tmp, cancel), label="download")
        _check_cancel(cancel)
        return transcode(tmp, dst, cancel)
    finally:
        _drop_part(tmp, tmp + ".part")


def download(url: str, dest: str, cancel: threading.Event) -> int:
    """Stream ``url`` to ``dest``; returns bytes written."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    req = urllib.request.Request(url, headers={
        "User-Agent": qqmusic.UA,
        "Referer": _cdn_referer(url),
        "Accept": "*/*",
    })
    total = 0
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if ctype.startswith("text/") or "html" in ctype:
            raise BridgeError("下载失败（服务器返回了网页）")
        with open(part, "wb") as fh:
            while True:
                _check_cancel(cancel)
                chunk = resp.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
                total += len(chunk)
    if total < MP3_MIN_BYTES:
        _drop_part(part)
        raise BridgeError("下载失败（文件过小或为空）")
    os.replace(part, dest)
    return total


def transcode(src: str, dst: str, cancel: threading.Event) -> int:
    """ffmpeg -y -i src -c:a libvorbis -q:a 4 dst (atomic .part -> dst)."""
    if not FFMPEG:
        raise BridgeError("未找到 ffmpeg")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + ".part"
    _drop_part(part)
    # -f ogg is required: the .part suffix hides the container from ffmpeg
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-i", src, *FFMPEG_ARGS, "-f", "ogg", part]
    errs: list = []
    proc = _spawn_ffmpeg(cmd)
    reader = threading.Thread(target=_drain_stderr, args=(proc, errs),
                              name="ffmpeg-err", daemon=True)
    reader.start()
    rc = _finish_ffmpeg(proc, reader, cancel, errs, "file-in")
    if rc != 0:
        _drop_part(part)
        raise BridgeError("转码失败（退出码 %d%s）"
                          % (rc, ("：" + _stderr_tail(errs)) if _stderr_tail(errs) else ""))
    size = _validate_ogg(part, "转码")
    os.replace(part, dst)
    return size


def ensure_writable_dir(path: str) -> None:
    """Create ``path`` and prove we can actually write into it."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".qqbridge_write_test")
        with open(probe, "wb") as fh:
            fh.write(b"x")
        os.remove(probe)
    except OSError as exc:
        raise BridgeError(f"无法写入游戏目录（{exc.strerror or exc}）") from exc


def _publish_ready(mid: str, name: str, singer: str, size: int) -> None:
    meta = track_meta(mid)
    _set_job(mid, state="ready", file=rel_path(mid), msg="", bytes=size,
             title=name or meta.get("name") or "",
             singer=singer or meta.get("singer") or "",
             dur=_int(meta.get("dur")))


def _best_error(errors: list) -> BaseException:
    """The most informative failure out of a multi-attempt prepare."""
    for want_vip in (False, True):
        for e in errors:
            is_vip = isinstance(e, BridgeError) and "绿钻" in str(e)
            if is_vip is want_vip:
                return e
    return BridgeError("该歌曲需要绿钻或已下架")


def _encode_with_paths(url: str, dst: str, cancel: threading.Event,
                       errors: list) -> int:
    """Try the configured pipelines in order; returns the ogg byte count."""
    if PIPELINE_ORDER == ("url-in", "pipe", "disk") and not URL_IN_SLOW["loaded"]:
        load_pipeline_state()                 # 'auto': honour a learned demotion
    paths = PIPELINE_ORDER
    if URL_IN_SLOW["flag"]:
        paths = ("pipe", "disk")
    for name in paths:
        _check_cancel(cancel)
        try:
            if name == "url-in":
                return encode_from_url(url, dst, cancel)
            if name == "pipe":
                return encode_from_pipe(url, dst, cancel)
            return encode_from_disk(url, dst, cancel)
        except Cancelled:
            raise
        except BridgeError as exc:
            errors.append(exc)
            LOG.warning("pipeline %s failed for %s (%s); trying the next path",
                        name, os.path.basename(dst), exc)
    raise _best_error(errors)


def _prepare_track(mid: str, name: str, singer: str, cancel: threading.Event,
                   qualities: tuple, kind: str = "play") -> None:
    """Resolve -> encode via the configured pipeline -> atomic publish.

    Every prepare logs the ``resolve=/encode=/total=`` breakdown, deletes its
    scratch files and keeps the ogg cache inside its budget.
    """
    if not FFMPEG:
        raise BridgeError("未找到 ffmpeg")
    started = time.time()
    ensure_writable_dir(game_cache_dir())
    dst = out_path(mid)
    errors: list = []

    url = None
    quality = ""
    t_resolve = started
    reset_vkey_gate()
    for q in qualities:
        _check_cancel(cancel)
        try:
            url, quality, _info = resolve_url(mid, cancel, (q,), kind=kind)
        except BridgeError as exc:
            errors.append(exc)
            LOG.info("quality %s unavailable for %s: %s", q, mid, exc)
            continue
        t_resolve = time.time()
        LOG.info("resolved %s quality=%s resolve=%.2fs", mid, quality,
                 t_resolve - started)
        break

    if url is None:
        raise _best_error(errors)

    t_enc0 = time.time()
    size = _encode_with_paths(url, dst, cancel, errors)
    t_done = time.time()
    _publish_ready(mid, name, singer, size)
    LOG.info("prepare done mid=%s kind=%s quality=%s file=%s bytes=%d | "
             "resolve=%.2fs encode=%.2fs total=%.2fs",
             mid, kind, quality, dst, size, t_resolve - started,
             t_done - t_enc0, t_done - started)
    cleanup_stale_parts()
    evict_cache()


def _apply_job_error(mid: str, exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, BridgeError):
        return "error", str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        return "error", f"网络错误（HTTP {exc.code}）"
    if isinstance(exc, urllib.error.URLError):
        return "error", "网络连接失败"
    LOG.exception("prepare crashed mid=%s: %s", mid, exc)
    return "error", "内部错误，请查看 qqbridge.log"


def worker(mid: str, name: str, singer: str, cancel: threading.Event) -> None:
    """User-initiated /play prepare (normal priority)."""
    _run_prepare(mid, name, singer, cancel, kind="play")


def _run_prepare(mid: str, name: str, singer: str, cancel: threading.Event,
                 kind: str) -> None:
    started = time.time()
    LOG.info("prepare start mid=%s kind=%s name=%s singer=%s",
             mid, kind, name, singer)
    try:
        _prepare_track(mid, name, singer, cancel, QUALITY_PREFERENCE[QUALITY], kind)
    except Cancelled:
        with JOBS_LOCK:
            job = JOBS.setdefault(mid, {})
            if job.get("state") in PREPARE_STATES:
                job.update(state="error", msg="已取消", bytes=0)
        LOG.info("prepare cancelled mid=%s kind=%s after %.2fs",
                 mid, kind, time.time() - started)
    except BaseException as exc:                      # noqa: BLE001
        state, msg = _apply_job_error(mid, exc)
        with JOBS_LOCK:
            job = JOBS.setdefault(mid, {})
            if job.get("state") != "error" or not job.get("msg"):
                job.update(state=state, msg=msg)
        LOG.warning("prepare failed mid=%s kind=%s: %s", mid, kind, msg)
    finally:
        release_current(cancel)
        cleanup_stale_parts()


def release_current(cancel: threading.Event) -> None:
    """Drop the CUR registration iff it still belongs to ``cancel``."""
    with CUR_LOCK:
        if CUR.get("cancel") is cancel:
            CUR.update(mid=None, cancel=None, proc=None, kind=None)


def cancel_play(kind: str = "play", reason: str = "已取消") -> None:
    """Cancel the prepare that currently owns the pipeline.

    ``kind`` must match the running job's kind *exactly* -- only a /play (or
    /stop, /quit) may cancel a play.  A prefetch never cancels anything but a
    prefetch, otherwise hover traffic would kill the user's track.
    """
    with CUR_LOCK:
        mid = CUR.get("mid")
        event = CUR.get("cancel")
        proc = CUR.get("proc")
        cur_kind = CUR.get("kind")
    if event is None or cur_kind != kind:
        return
    event.set()
    _kill_tree(proc)
    cleanup_stale_parts()
    if mid:
        with JOBS_LOCK:
            job = JOBS.get(mid)
            if job and job.get("state") in PREPARE_STATES:
                job.update(state="error", msg=reason)
        LOG.info("cancelled %s prepare mid=%s (%s)", cur_kind, mid, reason)


def play_in_flight() -> bool:
    """True while a user /play owns the pipeline (or is about to)."""
    with CUR_LOCK:
        if CUR.get("kind") == "play" and CUR.get("cancel") is not None:
            return True
    with JOBS_LOCK:
        for mid, job in JOBS.items():
            if job.get("state") == "preparing":
                return True
    return False


# --------------------------------------------------------------------------
# low-priority single-slot prefetch queue
#
# The game fires /prefetch on hover, so requests can change target several
# times a second.  At most one prefetch is queued and one is running; a newer
# request replaces both.  A /play preempts (cancels) it immediately, so a
# prefetch can never delay a user-visible response.
# --------------------------------------------------------------------------
def drop_queued_prefetch(reason: str = "已被新的播放请求取消") -> None:
    try:
        while True:
            _g, mid, _n, _s = PF_SLOT.popleft()
            with JOBS_LOCK:
                job = JOBS.get(mid)
                if job and job.get("state") == "prefetching":
                    job.update(state="error", msg=reason)
            LOG.info("dropped queued prefetch mid=%s (%s)", mid, reason)
    except IndexError:
        pass


def prefetch_worker() -> None:
    """Single long-lived consumer for the prefetch slot."""
    global PF_RUNNING
    last_mid = None
    while True:
        with PF_COND:
            while not PF_SLOT:
                PF_COND.wait(timeout=1.0)
            _gen, mid, name, singer = PF_SLOT[0]
        PF_RUNNING = mid
        cancel = threading.Event()
        # A play ALWAYS owns the pipeline.  Taking the CUR slot while a play is
        # preparing would orphan that play's cancel event, so /stop and a later
        # /play could no longer find (or cancel) it.  Check and take atomically.
        with CUR_LOCK:
            play_owns = (CUR.get("kind") == "play"
                         and CUR.get("cancel") is not None)
            if not play_owns:
                CUR.update(mid=mid, cancel=cancel, proc=None, kind="prefetch")
        if play_owns:
            drop_queued_prefetch("播放进行中，跳过预取")
            PF_RUNNING = None
            continue
        drop_queued_prefetch("已被更新的预取请求取代")
        if mid != last_mid:
            LOG.info("prefetch start mid=%s", mid)
        last_mid = mid
        try:
            _run_prepare(mid, name, singer, cancel, kind="prefetch")
        except BaseException as exc:                      # noqa: BLE001
            LOG.warning("prefetch crashed mid=%s: %s", mid, exc)
        finally:
            PF_RUNNING = None


def prefetch_enqueue(mid: str, name: str, singer: str) -> None:
    """Arm ``mid`` as the one and only queued prefetch."""
    global PF_GEN
    with PF_COND:
        PF_GEN += 1
        PF_SLOT.append((PF_GEN, mid, name, singer))
        PF_COND.notify_all()


def prefetch_running_mid() -> str | None:
    return PF_RUNNING


# --------------------------------------------------------------------------
# QR login (best effort; auth.json is the supported path)
# --------------------------------------------------------------------------
def _hash33(text: str) -> int:
    value = 0
    for ch in text:
        value += (value << 5) + ord(ch)
    return 2147483647 & value


def _decode_ptlogin(raw: bytes) -> str:
    """ptlogin answers UTF-8 nowadays but has served GBK historically."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", "replace")


def _qr_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _qr_cookie(opener, name: str) -> str:
    for handler in opener.handlers:
        if isinstance(handler, urllib.request.HTTPCookieProcessor):
            for cookie in handler.cookiejar:
                if cookie.name == name:
                    return cookie.value
    return ""


def _qr_begin() -> dict:
    """Fetch a QQ login QR code and start polling. Returns a status dict."""
    opener = _qr_opener()
    url = ("https://ssl.ptlogin2.qq.com/ptqrshow?appid=716027609&e=2&l=M&s=3"
           "&d=72&v=4&t=%.17f&daid=383&pt_3rd_aid=0" % time.time())
    req = urllib.request.Request(url, headers={"User-Agent": qqmusic.UA,
                                               "Referer": "https://xui.ptlogin2.qq.com/"})
    with opener.open(req, timeout=UPSTREAM_TIMEOUT) as resp:
        png = resp.read()
    if not png.startswith(b"\x89PNG"):
        raise BridgeError("ptqrshow 未返回图片")
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(QR_PATH, "wb") as fh:
        fh.write(png)
    qrsig = _qr_cookie(opener, "qrsig")
    if not qrsig:
        raise BridgeError("未取得 qrsig")
    token = _hash33(qrsig)
    LOG.info("QR code fetched (%d bytes), qrsig len=%d", len(png), len(qrsig))

    global QR_TOKEN
    QR_TOKEN += 1
    threading.Thread(target=_qr_poll, args=(opener, token, QR_TOKEN),
                     name="qr-poll", daemon=True).start()
    return {"state": "waiting", "nickname": "",
            "msg": f"请用手机QQ扫描 {os.path.join('cache', 'login_qr.png')}",
            "qr": "cache/login_qr.png"}


def _qr_poll(opener, token: int, my_token: int) -> None:
    try:
        _qr_poll_inner(opener, token, my_token)
    except Exception as exc:                          # noqa: BLE001
        LOG.exception("QR poller crashed: %s", exc)
        with QR_LOCK:
            QR.update(state="fail", msg="二维码登录失败，请改用 auth.json")


def _qr_poll_inner(opener, token: int, my_token: int) -> None:
    # NOTE: never %-format this URL -- it is full of literal percent escapes.
    poll_url = ("https://ssl.ptlogin2.qq.com/ptqrlogin?u1="
                "https%3A%2F%2Fgraph.qq.com%2Foauth2.0%2Flogin_jump"
                f"&ptqrtoken={token}&ptredirect=0&h=1&t=1&g=1&from_ui=1"
                "&ptlang=2052&action=0-0-" + str(int(time.time() * 1000)) +
                "&js_ver=10233&js_type=1&login_sig=&pt_uistyle=40"
                "&aid=716027609&daid=383&pt_3rd_aid=0&has_onekey=1")
    headers = {"User-Agent": qqmusic.UA,
               "Referer": "https://xui.ptlogin2.qq.com/"}
    for _ in range(90):           # ~3 minutes
        time.sleep(2)
        if my_token != QR_TOKEN:
            return
        try:
            req = urllib.request.Request(poll_url, headers=headers)
            with opener.open(req, timeout=UPSTREAM_TIMEOUT) as resp:
                raw = resp.read()
            body = _decode_ptlogin(raw)
        except Exception as exc:                      # noqa: BLE001
            LOG.warning("ptqrlogin poll failed: %s: %s", type(exc).__name__, exc)
            continue
        args = re.findall(r"'([^']*)'", body)
        code = args[0] if args else ""
        msg = args[4] if len(args) > 4 else body[:60]
        nick = args[5] if len(args) > 5 else ""
        LOG.debug("ptqrlogin code=%s msg=%s", code, msg)
        if code == "65":
            with QR_LOCK:
                QR.update(state="waiting", msg="已扫描，请在手机上确认")
        elif code == "66":
            with QR_LOCK:
                QR.update(state="waiting", msg="等待扫码")
        elif code == "67":
            with QR_LOCK:
                QR.update(state="fail", msg="二维码已失效，请重新 /login")
            return
        elif code == "0":
            redirect = args[2] if len(args) > 2 else ""
            try:
                _qr_finish(opener, redirect, nick)
            except Exception as exc:                  # noqa: BLE001
                LOG.exception("QR login finish failed: %s", exc)
                with QR_LOCK:
                    QR.update(state="fail",
                              msg="登录成功但未取得音乐Cookie，请手动填写 auth.json")
            return
        else:
            with QR_LOCK:
                QR.update(state="fail", msg=f"登录失败（{msg}）")
            return
    with QR_LOCK:
        QR.update(state="fail", msg="二维码超时，请重新 /login")


def _qr_finish(opener, redirect: str, nick: str) -> None:
    """Follow the ptlogin redirect and harvest y.qq.com cookies."""
    headers = {"User-Agent": qqmusic.UA, "Referer": "https://y.qq.com/"}
    if redirect:
        try:
            with opener.open(urllib.request.Request(redirect, headers=headers),
                             timeout=UPSTREAM_TIMEOUT) as resp:
                resp.read(65536)
        except Exception as exc:                      # noqa: BLE001
            LOG.warning("login redirect failed: %s: %s", type(exc).__name__, exc)
    for follow in ("https://y.qq.com/portal/profile.html", "https://y.qq.com/"):
        try:
            with opener.open(urllib.request.Request(follow, headers=headers),
                             timeout=UPSTREAM_TIMEOUT) as resp:
                resp.read(65536)
        except Exception as exc:                      # noqa: BLE001
            LOG.warning("cookie harvest failed for %s: %s: %s",
                        follow, type(exc).__name__, exc)

    jar = []
    for handler in opener.handlers:
        if isinstance(handler, urllib.request.HTTPCookieProcessor):
            jar = list(handler.cookiejar)
    pairs = {c.name: c.value for c in jar}
    uin = re.sub(r"^o", "", pairs.get("uin", "") or pairs.get("p_uin", ""))
    key = (pairs.get("qm_keyst") or pairs.get("qqmusic_key")
           or pairs.get("p_skey") or "")
    cookie = "; ".join(f"{c.name}={c.value}" for c in jar)
    LOG.info("QR login cookies: %s", ", ".join(sorted(pairs)))
    if not uin or not key:
        raise BridgeError("缺少 qm_keyst/uin")
    write_auth_file(uin, cookie, nick)
    with QR_LOCK:
        QR.update(state="ok", nickname=nick, msg="登录成功")
    LOG.info("QR login OK uin=%s nick=%s", uin, nick)


# --------------------------------------------------------------------------
# endpoint handlers -- each returns (http_status, payload) or
# (http_status, payload, after_response_callable)
# --------------------------------------------------------------------------
def api_status(_p: dict):
    au = reload_auth()
    return 200, {
        "ok": True,
        # the launcher matches this against the process it spawned, so that a
        # bridge left over from an earlier session is never mistaken for its own
        "pid": os.getpid(),
        "sources": qqmusic.installed(),
        "logged_in": bool(au["logged_in"]),
        "nickname": au["nickname"],
        "ffmpeg": bool(FFMPEG),
        "game_dir": GAME_DIR,
        "version": VERSION,
    }

def api_search(p: dict):
    keyword = _fix_mojibake((p.get("q") or p.get("keyword") or "").strip())
    if not keyword:
        return 200, {"ok": False, "msg": "缺少参数 q", "tracks": []}
    page = _int(p.get("page"), 1, 1, 100)
    num = _int(p.get("n"), 30, 1, 50)
    qqmusic.set_source(p.get("src"))
    LOG.info("search src=%s (raw=%r) q=%r", qqmusic.current_source(),
             p.get("src"), keyword)

    key = (qqmusic.current_source(), keyword, page, num)
    now = time.time()
    with SEARCH_LOCK:
        hit = SEARCH_CACHE.get(key)
    if hit and now - hit[0] < SEARCH_TTL:
        hits, cached = hit[1], True
    else:
        # the upstream search endpoint rate-limits (empty code=2001 replies);
        # qqmusic.search already backs off, we simply give it more attempts.
        err = None
        try:
            hits = _retry(lambda: qqmusic.search(keyword, page=page, num=num,
                                                 retries=6,
                                                 timeout=UPSTREAM_TIMEOUT),
                          label="search", tries=1)
        except Exception as exc:                      # noqa: BLE001
            err = exc
            hits = []
            LOG.warning("search upstream error: %s: %s", type(exc).__name__, exc)
        cached = False
        if hits:
            with SEARCH_LOCK:
                SEARCH_CACHE[key] = (now, hits)
                if len(SEARCH_CACHE) > 64:
                    oldest = sorted(SEARCH_CACHE, key=lambda k: SEARCH_CACHE[k][0])
                    for stale in oldest[:16]:
                        SEARCH_CACHE.pop(stale, None)
        else:
            # last resort: answer from what previous searches/playlists taught us.
            # QQ only - that cache holds QQ metadata, so serving it for another
            # source would hand the game tracks from the wrong service.
            hits = local_search(keyword, num) if qqmusic.current_source() == "qq" else []
            if hits:
                LOG.warning("search upstream empty for %r; served %d tracks "
                            "from the local metadata cache", keyword, len(hits))
            elif err is not None:
                return 200, {"ok": False, "msg": "搜索失败，请检查网络连接",
                             "tracks": []}

    remember(hits)
    tracks = [track_out(t) for t in hits]
    LOG.info("search q=%r page=%d n=%d -> %d tracks%s",
             keyword, page, num, len(tracks), " (cached)" if cached else "")
    return 200, {"ok": True, "tracks": tracks}


def local_search(keyword: str, num: int) -> list[dict]:
    """Substring match over the persisted track metadata (offline fallback)."""
    needle = keyword.lower()
    out = []
    with TRACKS_LOCK:
        records = list(TRACKS.items())
    for mid, rec in records:
        haystack = f"{rec.get('name','')} {rec.get('singer','')} {rec.get('album','')}".lower()
        if needle in haystack:
            out.append({"mid": mid, "name": rec.get("name"), "album": rec.get("album"),
                        "singers": (rec.get("singer") or "").split("/"),
                        "interval": rec.get("dur"),
                        "file": rec.get("media_mid"),
                        "pay": rec.get("vip")})
    out.sort(key=lambda t: len(t.get("name") or ""))
    return out[:num]


def api_playlists(_p: dict):
    qqmusic.set_source(_p.get("src") if isinstance(_p, dict) else None)
    au = reload_auth()
    if not au["logged_in"]:
        return 200, {"ok": True, "logged_in": False, "playlists": []}
    raw = _retry(lambda: qqmusic.user_playlists(au["uin"], au["cookie"],
                                                timeout=UPSTREAM_TIMEOUT),
                 label="playlists")
    out = []
    for pl in raw:
        # upstream (live 2024+) sends dirId/dirName/tid/songNum; qqmusic already
        # maps those, and keeps the legacy dissid/diss_name/song_cnt fallbacks.
        # `id` is ALWAYS str(tid) -- including for dirId 201 (我喜欢), which is
        # addressable by its tid like any other playlist.
        disstid = str(pl.get("disstid") or "").strip()
        if not disstid:
            continue          # upstream emits placeholder rows for bad uins
        name = pl.get("name") or ""
        fav = (str(pl.get("dirid")) == "201"
               or "我喜欢" in name or "喜欢的歌曲" in name)
        item = {
            "id": disstid,
            "name": name,
            "count": _int(pl.get("count")),
            "special": "fav" if fav else "",
        }
        out.append(item)
    out.sort(key=lambda x: (x["special"] != "fav", x["name"]))
    LOG.info("playlists -> %d: %s", len(out),
             ", ".join(f"{p['name']}={p['count']}" for p in out))
    return 200, {"ok": True, "logged_in": True, "playlists": out}


def api_playlist(p: dict):
    qqmusic.set_source(p.get("src"))
    playlist_id = (p.get("id") or "").strip()
    if not re.fullmatch(r"\d{1,20}", playlist_id or ""):
        return 200, {"ok": False, "msg": "缺少或非法的歌单 id",
                     "name": "", "total": 0, "tracks": []}
    offset = _int(p.get("offset"), 0, 0, 100000)
    count = _int(p.get("count"), 200, 1, 500)
    au = reload_auth()

    def fetch(disstid, dirid):
        return _retry(lambda: qqmusic.playlist_detail(
            str(disstid), offset, count, cookie=au["cookie"] or None,
            uin=au["uin"], timeout=UPSTREAM_TIMEOUT, dirid=dirid),
            label="playlist")

    # Primary: the plain disstid form, which is how every row (including
    # 我喜欢 / dirId 201) is addressed by its tid.
    detail = fetch(playlist_id, 0)
    # Fallback for callers that pass the literal legacy id "201" or whose
    # upstream answers with no songs: 我喜欢 is also served by the
    # dirid form {"disstid": 0, "dirid": 201}.
    if not (detail.get("tracks") or []) and playlist_id == "201":
        alt = fetch(0, 201)
        if alt.get("tracks"):
            LOG.info("playlist id=201 served via the dirid form")
            detail = alt

    tracks_raw = detail.get("tracks") or []
    remember(tracks_raw)
    payload = {
        "ok": True,
        "name": detail.get("name") or "",
        "total": _int(detail.get("total")),
        "tracks": [track_out(t) for t in tracks_raw],
    }
    LOG.info("playlist id=%s offset=%d count=%d -> %d/%s tracks",
             playlist_id, offset, count, len(payload["tracks"]), payload["total"])
    return 200, payload


def api_play(p: dict):
    mid = (p.get("id") or "").strip()
    if not MID_RE.match(mid or ""):
        return 200, {"ok": False, "state": "error", "msg": "缺少或非法的歌曲 id"}
    name = _fix_mojibake((p.get("name") or "").strip())
    singer = _fix_mojibake((p.get("singer") or "").strip())

    if is_ready(mid):
        meta = track_meta(mid)
        _set_job(mid, state="ready", file=rel_path(mid), msg="",
                 title=name or meta.get("name") or "",
                 singer=singer or meta.get("singer") or "",
                 dur=_int(meta.get("dur")))
        LOG.info("play %s -> already ready", mid)
        return 200, {"ok": True, "state": "ready", "file": rel_path(mid)}

    with PLAY_LOCK:
        with JOBS_LOCK:
            job = JOBS.get(mid)
            qmid = PF_SLOT[0][1] if PF_SLOT else None
            run = prefetch_running_mid()
            same_pf = (qmid == mid) or (run == mid)
            if job and job.get("state") == "preparing":
                return 200, {"ok": True, "state": "preparing"}
            if same_pf:
                # our own prefetch is already producing exactly this file;
                # let it finish and report "preparing" meanwhile
                return 200, {"ok": True, "state": "preparing"}
            if is_ready(mid):
                # a prefetch may have completed since the check at the top
                meta = track_meta(mid)
                _set_job(mid, state="ready", file=rel_path(mid), msg="",
                         title=name or meta.get("name") or "",
                         singer=singer or meta.get("singer") or "",
                         dur=_int(meta.get("dur")))
                LOG.info("play %s -> ready (prefetch had finished)", mid)
                return 200, {"ok": True, "state": "ready", "file": rel_path(mid)}

        # a user-issued play always wins: kill the prefetch (running or queued)
        cancel_play("prefetch", "已被播放请求取消")
        drop_queued_prefetch("已被播放请求取消")

        cancel = threading.Event()
        _set_job(mid, state="preparing", msg="", file="", title=name,
                 singer=singer, dur=_int(track_meta(mid).get("dur")))
        with CUR_LOCK:
            CUR.update(mid=mid, cancel=cancel, proc=None, kind="play")
        threading.Thread(target=worker, args=(mid, name, singer, cancel),
                         name=f"prepare-{mid}", daemon=True).start()
    LOG.info("play %s (%s - %s) -> preparing (quality=%s)",
             mid, name, singer, QUALITY)
    return 200, {"ok": True, "state": "preparing"}


def api_prefetch(p: dict):
    """Arm ``mid`` as the single low-priority prefetch; answers immediately.

    Never blocks and never disturbs a play: a newer /prefetch replaces only the
    queued prefetch, and while a play is preparing prefetches are dropped.
    """
    mid = (p.get("id") or "").strip()
    if not MID_RE.match(mid or ""):
        return 200, {"ok": False, "state": "error", "msg": "缺少或非法的歌曲 id"}
    name = _fix_mojibake((p.get("name") or "").strip())
    singer = _fix_mojibake((p.get("singer") or "").strip())

    if is_ready(mid):
        return 200, {"ok": True, "state": "ready", "file": rel_path(mid)}

    with PLAY_LOCK:
        with JOBS_LOCK:
            job = JOBS.get(mid)
            jstate = (job or {}).get("state")
            if jstate == "ready":
                return 200, {"ok": True, "state": "ready", "file": rel_path(mid)}
            if jstate == "preparing":
                return 200, {"ok": True, "state": "preparing"}
            if jstate == "prefetching" and (
                    (PF_SLOT and PF_SLOT[0][1] == mid)
                    or prefetch_running_mid() == mid):
                return 200, {"ok": True, "state": "queued"}
            if PF_SLOT and PF_SLOT[0][1] == mid:
                return 200, {"ok": True, "state": "queued"}
        # rule: a prefetch never interferes with a play -- not even to queue
        # itself next to one (it would only be cancelled microseconds later)
        if play_in_flight():
            LOG.info("prefetch %s dropped: a play owns the pipeline", mid)
            return 200, {"ok": True, "state": "queued"}
        # supersede the previous *prefetch* only (cancel_play is kind-exact)
        cancel_play("prefetch", "已被更新的预取请求取代")
        drop_queued_prefetch("已被更新的预取请求取代")
        if play_in_flight():
            LOG.info("prefetch %s dropped: a play started meanwhile", mid)
            return 200, {"ok": True, "state": "queued"}
        _set_job(mid, state="prefetching", msg="", file="", title=name,
                 singer=singer, dur=_int(track_meta(mid).get("dur")))
        prefetch_enqueue(mid, name, singer)
    LOG.info("prefetch %s (%s - %s) -> queued", mid, name, singer)
    return 200, {"ok": True, "state": "queued"}


def api_playstate(p: dict):
    mid = (p.get("id") or "").strip()
    if not MID_RE.match(mid or ""):
        return 200, {"ok": False, "state": "error", "msg": "缺少或非法的歌曲 id"}
    with JOBS_LOCK:
        job = dict(JOBS.get(mid) or {})
    state = job.get("state") or ""
    if state != "preparing" and is_ready(mid):
        # the file on disk wins: a cancelled/preempted job must never hide a
        # finished prepare (e.g. a prefetch that a later request superseded
        # in the bookkeeping while its ogg was already published)
        meta = track_meta(mid)
        return 200, {"ok": True, "state": "ready", "file": rel_path(mid),
                     "title": job.get("title") or meta.get("name") or "",
                     "singer": job.get("singer") or meta.get("singer") or "",
                     "dur": _int(job.get("dur") or meta.get("dur"))}
    if job:
        if state == "ready":
            meta = track_meta(mid)
            return 200, {"ok": True, "state": "ready", "file": rel_path(mid),
                         "title": job.get("title") or meta.get("name") or "",
                         "singer": job.get("singer") or meta.get("singer") or "",
                         "dur": _int(job.get("dur") or meta.get("dur"))}
        if state == "error":
            return 200, {"ok": False, "state": "error",
                         "msg": job.get("msg") or "未知错误"}
        return 200, {"ok": True, "state": "preparing"}
    if is_ready(mid):
        meta = track_meta(mid)
        return 200, {"ok": True, "state": "ready", "file": rel_path(mid),
                     "title": meta.get("name") or "",
                     "singer": meta.get("singer") or "",
                     "dur": _int(meta.get("dur"))}
    return 200, {"ok": False, "state": "error", "msg": "尚未开始播放，请先调用 /play"}


def api_stop(_p: dict):
    cancel_play("play", "已停止")
    cancel_play("prefetch", "已停止")
    drop_queued_prefetch("已停止")
    return 200, {"ok": True}


def api_login(_p: dict):
    with QR_LOCK:
        if QR["state"] == "waiting" and time.time() - QR["ts"] < 180:
            return 200, {"ok": True, "state": "waiting", "nickname": QR["nickname"],
                         "msg": QR["msg"], "qr": "cache/login_qr.png"}
    try:
        result = _qr_begin()
    except Exception as exc:                          # noqa: BLE001
        LOG.warning("QR login unavailable: %s: %s", type(exc).__name__, exc)
        with QR_LOCK:
            QR.update(state="unsupported", ts=time.time(),
                      msg="二维码登录不可用；请把 cookie 写入 bridge/auth.json")
            msg = QR["msg"]
        return 200, {"ok": True, "state": "unsupported", "nickname": "", "msg": msg}
    with QR_LOCK:
        QR.update(state="waiting", ts=time.time(), nickname="",
                  msg=result["msg"])
    return 200, {"ok": True, **result}


def api_loginstatus(_p: dict):
    au = reload_auth()
    if au["logged_in"]:
        return 200, {"ok": True, "state": "ok", "nickname": au["nickname"]}
    with QR_LOCK:
        return 200, {"ok": True, "state": QR["state"], "nickname": QR["nickname"]}


def api_quit(_p: dict):
    cancel_play("play", "服务已退出")
    cancel_play("prefetch", "服务已退出")
    drop_queued_prefetch("服务已退出")
    return 200, {"ok": True}, shutdown_server


def shutdown_server() -> None:
    LOG.info("shutdown requested")
    server = SERVER
    if server is not None:
        threading.Thread(target=server.shutdown, name="shutdown",
                         daemon=True).start()


ROUTES = {
    "/status": api_status,
    "/search": api_search,
    "/playlists": api_playlists,
    "/playlist": api_playlist,
    "/play": api_play,
    "/playstate": api_playstate,
    "/prefetch": api_prefetch,
    "/stop": api_stop,
    "/login": api_login,
    "/loginstatus": api_loginstatus,
    "/quit": api_quit,
}


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = f"QQBridge/{VERSION}"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 30

    # keep stderr clean; everything goes to qqbridge.log
    def log_message(self, fmt, *args):                # noqa: A003
        LOG.debug("http %s %s", self.address_string(), fmt % args)

    def log_error(self, fmt, *args):
        LOG.warning("http %s %s", self.address_string(), fmt % args)

    def do_GET(self):                                 # noqa: N802
        self._handle("GET")

    def do_POST(self):                                # noqa: N802
        self._handle("POST")

    def _params(self, method: str) -> dict:
        parsed = urllib.parse.urlsplit(self.path)
        raw = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if method == "POST":
            length = _int(self.headers.get("Content-Length"), 0, 0, 8 * 1024 * 1024)
            body = self.rfile.read(length) if length else b""
            text = body.decode("utf-8", "replace")
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "json" in ctype:
                try:
                    data = json.loads(text or "{}")
                    if isinstance(data, dict):
                        raw.update({k: [str(v)] for k, v in data.items()})
                except ValueError:
                    pass
            else:
                for key, values in urllib.parse.parse_qs(text, keep_blank_values=True).items():
                    raw.setdefault(key, []).extend(values)
        params = {}
        for key, values in raw.items():
            params[key] = _fix_mojibake(values[-1] if values else "")
        return parsed.path, params

    def _handle(self, method: str) -> None:
        after = None
        try:
            path, params = self._params(method)
            route = path.rstrip("/") or "/"
            handler = ROUTES.get(route)
            if handler is None:
                status, payload = 404, {"ok": False, "msg": f"未知接口 {path}"}
            else:
                result = handler(params)
                if len(result) == 3:
                    status, payload, after = result
                else:
                    status, payload = result
        except Cancelled:
            LOG.info("handler cancelled")
            status, payload = 200, {"ok": False, "msg": "已取消"}
        except BridgeError as exc:
            # a provider's own explanation (needs login, needs VIP, ...) is far
            # more useful to the player than a generic failure
            LOG.warning("handler rejected: %s", exc)
            status, payload = 200, {"ok": False, "msg": str(exc) or "请求被拒绝"}
        except Exception as exc:                      # noqa: BLE001
            LOG.exception("handler error: %s", exc)
            status, payload = 200, {"ok": False, "msg": "服务器内部错误"}
        self._send(status, payload)
        if after is not None:
            after()

    def _send(self, status: int, payload: dict) -> None:
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            body = b'{"ok":false,"msg":"\\u5e8f\\u5217\\u5316\\u5931\\u8d25"}'
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            LOG.debug("client went away before the response was written")


SERVER: ThreadingHTTPServer | None = None


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="QQ Music local bridge for ChillPulse")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"listen port on 127.0.0.1 (default {DEFAULT_PORT})")
    ap.add_argument("--game-dir", default=DEFAULT_GAME_DIR,
                    help="ChillPulse install folder (holds qqmusic_cache/)")
    ap.add_argument("--ffmpeg", default=None, help="explicit ffmpeg.exe path")
    ap.add_argument("--quality", choices=sorted(QUALITY_PREFERENCE),
                    default=DEFAULT_QUALITY,
                    help="preferred source quality (default "
                         f"{DEFAULT_QUALITY}); the chosen tier is tried first "
                         "and the others only when it yields no url")
    ap.add_argument("--cache-mb", type=int, default=1024,
                    help="ogg cache budget in MB (default "
                         f"{CACHE_MAX_MB}); LRU-evicted by mtime")
    ap.add_argument("--cache-files", type=int, default=CACHE_MAX_FILES,
                    help=f"ogg cache file budget (default {CACHE_MAX_FILES})")
    ap.add_argument("--pipeline", choices=("auto", "url-in", "pipe", "disk"),
                    default="auto",
                    help="prepare pipeline: 'auto' (default) tries ffmpeg "
                         "reading the CDN url, then a piped overlap, then "
                         "download-then-encode; 'url-in'/'pipe'/'disk' pin one")
    ap.add_argument("--watch-pid", type=int, default=0,
                    help="exit as soon as this process id is gone - used by the "
                         "launcher so an orphaned bridge never lingers")
    return ap.parse_args(argv)


def watch_pid(pid: int) -> None:
    """Shut the bridge down when ``pid`` (the launcher) disappears.

    The launcher normally stops the bridge itself, but if it is killed - or the
    machine drops the session - the bridge would otherwise stay bound to the
    port and block the next launch.
    """
    if pid <= 0:
        return
    try:
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            LOG.warning("watch-pid %s: cannot open the process, not watching", pid)
            return
        LOG.info("watching pid %s - the bridge will exit when it does", pid)
        ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
    except Exception as exc:                              # noqa: BLE001
        LOG.error("watch-pid %s failed: %s: %s", pid, type(exc).__name__, exc)
        return
    LOG.info("watched pid %s exited - shutting the bridge down", pid)
    logging.shutdown()
    os._exit(0)


def main(argv=None) -> int:
    global SERVER, GAME_DIR, FFMPEG, QUALITY, CACHE_MAX_MB, CACHE_MAX_FILES
    global PIPELINE_ORDER
    args = parse_args(argv)
    setup_logging()
    if args.watch_pid:
        threading.Thread(target=watch_pid, args=(args.watch_pid,),
                         name="watch-pid", daemon=True).start()
    GAME_DIR = os.path.abspath(args.game_dir)
    FFMPEG = find_ffmpeg(args.ffmpeg)
    QUALITY = args.quality
    CACHE_MAX_MB = max(0, args.cache_mb)
    CACHE_MAX_FILES = max(0, args.cache_files)
    if args.pipeline == "url-in":
        PIPELINE_ORDER = ("url-in", "pipe", "disk")
        enable_url_in()
    elif args.pipeline == "pipe":
        PIPELINE_ORDER = ("pipe", "disk")
    elif args.pipeline == "disk":
        PIPELINE_ORDER = ("disk",)
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)
    load_tracks()
    reload_auth(force=True)
    if PIPELINE_ORDER == ("url-in", "pipe", "disk"):
        load_pipeline_state()

    try:
        os.makedirs(game_cache_dir(), exist_ok=True)
    except OSError as exc:
        LOG.warning("game cache dir not creatable (%s): %s",
                    game_cache_dir(), exc)
    cleanup_stale_parts(verbose=True)
    log_cache_stats("cache stats at startup")

    LOG.info("=" * 70)
    LOG.info("qqbridge %s starting: port=%d game_dir=%s ffmpeg=%s auth=%s "
             "quality=%s (order=%s) pipeline=%s cache=%dMB/%dfiles",
             VERSION, args.port, GAME_DIR, FFMPEG or "NOT FOUND",
             "yes" if AUTH["logged_in"] else "no", QUALITY,
             "->".join(QUALITY_PREFERENCE[QUALITY]), "->".join(PIPELINE_ORDER),
             CACHE_MAX_MB, CACHE_MAX_FILES)

    try:
        SERVER = ThreadingHTTPServer((HOST, args.port), Handler)
    except OSError as exc:
        LOG.error("cannot bind %s:%d -> %s", HOST, args.port, exc)
        print(f"qqbridge: cannot bind {HOST}:{args.port} ({exc})", file=sys.stderr)
        return 2
    SERVER.daemon_threads = True
    SERVER.allow_reuse_address = True
    threading.Thread(target=prefetch_worker, name="prefetch", daemon=True).start()

    print(f"qqbridge {VERSION} listening on http://{HOST}:{args.port}/  "
          f"game_dir={GAME_DIR}  ffmpeg={'ok' if FFMPEG else 'MISSING'}  "
          f"logged_in={AUTH['logged_in']}  quality={QUALITY}")
    LOG.info("listening on http://%s:%d/", HOST, args.port)
    try:
        SERVER.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        LOG.info("interrupted by user")
    finally:
        cancel_play("play", "服务已退出")
        cancel_play("prefetch", "服务已退出")
        try:
            SERVER.server_close()
        except Exception:                             # noqa: BLE001
            pass
        save_tracks()
        LOG.info("qqbridge stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
