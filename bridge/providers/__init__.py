"""Source dispatcher: lets the bridge keep calling ``qqmusic.<name>`` while the
actual implementation is chosen per request.

The bridge handles each HTTP request in its own thread, so the "current source"
is kept in a thread-local.  Request handlers call :func:`set_source` once; every
provider call after that is routed to the right module.

    import providers as qqmusic          # one-line change in qqbridge.py
    providers.set_source("ne")           # from ?src=ne, or an "ne:123" id
    qqmusic.search("周杰伦", 1, 30)       # -> netease.search(...)

Song ids carry their source as a prefix: ``qq:0022QuVR1LcRHN`` / ``ne:347230``.
A bare id is treated as QQ, so an already-patched game keeps working.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_DIR = os.path.dirname(HERE)
if BRIDGE_DIR not in sys.path:
    sys.path.insert(0, BRIDGE_DIR)

DEFAULT_SOURCE = "qq"
SOURCES = ("qq", "ne")

#: id prefixes are "qq:" / "ne:"; a bare id means QQ (backward compatible)
_ID_RE = re.compile(r"^(?:(qq|ne):)?(.+)$")

_local = threading.local()


class Unsupported(Exception):
    """Raised when a source is requested but not installed/configured."""


# --------------------------------------------------------------------------
# module resolution
# --------------------------------------------------------------------------
def _load(src: str):
    if src == "qq":
        return importlib.import_module("qqmusic")
    if src == "ne":
        return importlib.import_module("providers.netease")
    raise Unsupported(f"未知音源 {src!r}")


def module(src: str | None = None):
    """The provider module for ``src`` (default: the current thread's source)."""
    return _load(src or current_source())


def installed() -> dict:
    """Which sources are present, without touching the network (/status polls)."""
    out = {}
    for src in SOURCES:
        try:
            _load(src)
            out[src] = True
        except Exception:                                     # noqa: BLE001
            out[src] = False
    return out


def available() -> dict:
    """Which sources can actually be used right now (for /status)."""
    out = {}
    for src in SOURCES:
        try:
            mod = _load(src)
        except Exception:                                     # noqa: BLE001
            out[src] = False
            continue
        try:
            out[src] = bool(mod.logged_in()) if hasattr(mod, "logged_in") else True
        except Exception:                                     # noqa: BLE001
            out[src] = False
    return out


# --------------------------------------------------------------------------
# current source (per thread)
# --------------------------------------------------------------------------
def current_source() -> str:
    return getattr(_local, "src", DEFAULT_SOURCE)


def set_source(src: str | None) -> str:
    src = (src or DEFAULT_SOURCE).strip().lower()
    if src not in SOURCES:
        src = DEFAULT_SOURCE
    _local.src = src
    return src


def split_id(song_id: str):
    """``"ne:347230"`` -> ``("ne", "347230")``; a bare id -> ``("qq", id)``."""
    m = _ID_RE.match(str(song_id or "").strip())
    if not m:
        return DEFAULT_SOURCE, str(song_id or "")
    return (m.group(1) or DEFAULT_SOURCE), m.group(2)


def join_id(src: str, song_id: str) -> str:
    """Prefix an id for storage.  QQ ids stay bare so old caches keep working."""
    src, bare = split_id(song_id) if ":" in str(song_id) else (src, str(song_id))
    return bare if src == DEFAULT_SOURCE else f"{src}:{bare}"


def safe_name(song_id: str) -> str:
    """A filesystem-safe form of a (possibly prefixed) id."""
    return str(song_id).replace(":", "_")


# --------------------------------------------------------------------------
# the surface the bridge uses - routed to the current provider
# --------------------------------------------------------------------------
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"

#: qqmusic uses this constant for "needs VIP"; the NetEase provider raises a
#: BridgeError with its own message instead, so the value only has to exist.
RESULT_NEED_VIP = -1


def _bridge_error_class():
    """The *running* bridge's BridgeError class.

    The bridge usually runs as a script (`__main__`), so `import qqbridge`
    would load a second copy of the module whose BridgeError is a different
    class - isinstance() would then never match and every provider message
    would degrade to "服务器内部错误".  Look the class up in sys.modules.
    """
    for name in ("qqbridge", "__main__"):
        mod = sys.modules.get(name)
        cls = getattr(mod, "BridgeError", None)
        if isinstance(cls, type) and issubclass(cls, Exception):
            return cls
    return None


def _wrap(exc: BaseException) -> BaseException:
    """Turn a provider error into the bridge's own BridgeError.

    Each provider raises its own exception class, and the bridge only turns
    *its* BridgeError into a readable Chinese message - anything else becomes
    "服务器内部错误".  Re-wrapping here keeps those messages intact.
    """
    cls = _bridge_error_class()
    if cls is not None:
        if isinstance(exc, cls):
            return exc
        message = str(exc).strip()
        if message:
            return cls(message)
    return exc


def _filtered(fn, *args, **kwargs):
    """Call ``fn`` with only the keyword arguments it actually accepts.

    The bridge passes QQ-specific tuning along every call (`retries=`,
    `timeout=`, `media_mid=` ...).  A provider that does not accept them would
    raise TypeError, which the bridge swallows - and then it silently falls
    back to its local metadata cache, which is exactly how a NetEase search
    ended up returning QQ Music tracks.  Filtering here keeps every provider
    usable without teaching the bridge about each one.
    """
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    allowed = {k: v for k, v in kwargs.items() if k in params}
    return fn(*args, **allowed)


def _call_adapted(fn, positional, kwargs):
    """Call ``fn`` with only as many positional args as it accepts.

    The bridge passes QQ-shaped positional arguments everywhere, e.g.
    ``playlist_detail(disstid, count, uin, cookie)``.  A provider whose
    function is ``playlist(pid, count=...)`` must not receive the trailing
    two, so they are trimmed here (keyword args are trimmed in _filtered).
    """
    import inspect
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return fn(*positional, **kwargs)
    if not any(p.kind == p.VAR_POSITIONAL for p in params):
        room = len([p for p in params
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
        positional = positional[:room]
    return _filtered(fn, *positional, **kwargs)


def _call(name, *args, **kwargs):
    mod = module()
    try:
        return _filtered(getattr(mod, name), *args, **kwargs)
    except Exception as exc:                                  # noqa: BLE001
        raise _wrap(exc) from None


def search(*args, **kwargs):
    return _call("search", *args, **kwargs)


def song_url_ex(song_id, *args, **kwargs):
    """Prefixed ids are handled here: the provider always sees a bare id."""
    src, bare = split_id(song_id)
    set_source(src)
    return _call("song_url_ex", bare, *args, **kwargs)


def user_playlists(uin="", cookie="", *args, **kwargs):
    """QQ takes (uin, cookie); NetEase takes (uid) - adapt transparently."""
    mod = module()
    try:
        if hasattr(mod, "user_playlists"):
            return _call_adapted(mod.user_playlists, (uin, cookie), kwargs)
        if hasattr(mod, "playlists"):
            return _call_adapted(mod.playlists, (uin,), kwargs)
        raise Unsupported("该音源不支持读取歌单列表")
    except Exception as exc:                                  # noqa: BLE001
        raise _wrap(exc) from None


def playlist_detail(pid, *args, **kwargs):
    mod = module()
    try:
        if hasattr(mod, "playlist_detail"):
            return _call_adapted(mod.playlist_detail, (pid,) + args, kwargs)
        if hasattr(mod, "playlist"):
            return _call_adapted(mod.playlist, (pid,) + args, kwargs)
        raise Unsupported("该音源不支持读取歌单")
    except Exception as exc:                                  # noqa: BLE001
        raise _wrap(exc) from None


def logged_in() -> bool:
    mod = module()
    if hasattr(mod, "logged_in"):
        return bool(mod.logged_in())
    return True


def nickname() -> str:
    mod = module()
    if hasattr(mod, "nickname"):
        return str(mod.nickname() or "")
    return ""
