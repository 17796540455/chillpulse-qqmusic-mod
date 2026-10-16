# Multi-source plan: 本地音乐 / QQ音乐 / 网易云音乐 / 播放列表

Status: **design agreed, implementation pending**. This file records the exact
decisions so the work can be finished in a few bounded steps.

## Target UI

Four top-level tabs in the game's music panel, all sharing the same window:

```
   本地音乐   │   QQ音乐   │   网易云音乐   │   播放列表
```

| Tab | `qqm_view` | Content |
| --- | --- | --- |
| 本地音乐 | `0` | the game's own cassette list — **unchanged** |
| QQ音乐 | `1` | sub-views: **搜索** / **歌单** (incl. 我喜欢) |
| 网易云音乐 | `2` | sub-views: **搜索** / **歌单** (incl. 我喜欢的音乐) |
| 播放列表 | `3` | the play queue — **promoted to its own tab** |

### View mapping change

Today: `0 = 本地音乐`, `1 = QQ音乐(歌单)`, `2 = 搜索`, `3 = 队列`.
The search view `2` is absorbed into each source as a **sub-view**, and `2`
becomes 网易云音乐:

```
qqm_source  = "qq" | "ne"      // current source for the list views
qqm_subview = 0 | 1            // 0 = 搜索, 1 = 歌单
```

The queue (`3`) stays where it is; it is now reachable as its own tab rather
than as a sub-page of the QQ view. **The queue is source-agnostic**: it can hold
QQ Music and NetEase tracks side by side, and playback dispatches on the track
id's source prefix.

## Bridge interface

Song ids become source-qualified. Everything else stays as it is.

| Route | Change |
| --- | --- |
| `/search?q=..&n=..&src=qq\|ne` | `src` selects the provider (default `qq`) |
| `/playlists?src=qq\|ne` | same |
| `/playlist?id=..&count=..&src=..` | same |
| `/play?id=<src>:<id>` | source read from the id prefix |
| `/playstate?id=<src>:<id>` | same |
| `/prefetch?id=<src>:<id>` | same |

* A bare id (no prefix) is treated as `qq:` for backward compatibility, so an
  already-patched `data.win` keeps working.
* The ogg cache filename sanitises `:` to `_` (`ne:1234567` → `ne_1234567.ogg`).
* `/status` gains `"sources": {"qq": true, "ne": false}` so the game can grey out
  a tab whose provider is not configured instead of showing an error.

### Provider layer (bridge/providers/)

```
providers/__init__.py   get(src) -> module, or raise BridgeError("未配置该音源")
providers/qq.py         current qqmusic.py, wrapped:
                          search(keyword, page, num) -> [track]
                          playlists() -> [playlist]
                          playlist(id, count) -> {name, total, tracks}
                          resolve(song_id, quality) -> {url, filename, ...}
providers/netease.py    new, same four functions
```

Track dict stays exactly as today (`id/name/singer/album/dur/vip`) — the game
side does not change shape, only the id gains its prefix.

### Auth

Per-source credential files next to the bridge:

```
bridge/auth.json           QQ Music   (existing: {"uin","cookie"})
bridge/auth_netease.json   NetEase    ({"cookie":"MUSIC_U=...; __csrf=..."})
```

`/status` reports each source's login state separately. A missing NetEase
cookie is not an error: free tracks still play, VIP tracks report
「该歌曲需要会员」.

## Implementation order

1. `providers/` extraction with QQ only — no behaviour change, verified by the
   existing test scripts (`bridge/test_bridge.py`, `verify_live.py`).
2. `src` plumbing + id prefixes + `/status.sources` — still QQ only.
3. `providers/netease.py` from the API probe
   (`bridge/netease_probe.py`, `bridge/netease_notes.md`).
4. Game side: 4 tabs, `qqm_source`, `qqm_subview`, queue as its own tab.
5. Rebuild + install `data.win`, verify in game, then sync
   `E:\ChillPulseQQMod` and the GitHub repo.

## Open questions

* Which quality tiers NetEase returns per account (free vs 黑胶 VIP) — the probe
  answers this.
* Whether the plain (unencrypted) NetEase endpoints are enough, or whether the
  weapi protocol is required — the probe answers this.
