# ChillPulse QQ Music Mod

Play your own QQ Music library (search, your playlists, your 绿钻/VIP tracks)
from inside **ChillPulse**'s own music panel — same UI, same window, no alt-tab.

一个把 **QQ 音乐**接进 **ChillPulse** 游戏内音乐面板的 mod：搜索歌曲、播放自建歌单、
绿钻曲目，界面与游戏原版保持一致。

---

## What it does / 功能

| In game / 游戏内 | Notes / 说明 |
| --- | --- |
| **QQ Music tab** next to 本地音乐 | 与游戏原有面板同一套 UI，不额外开窗口 |
| **Search** any song / artist | 点结果即插到「正在播放」后面并立刻播放 |
| **Your playlists** (`我喜欢` + 自建歌单) | 完整加载（实测 131 首的歌单也是全的） |
| **Queue view** 正在播放 / 播放队列 | 点行跳播，`▲▼` 调序，`×` 移除 |
| **Pause / next / previous** on the bottom bar | 控制的是 QQ 音乐；切回「本地音乐」即恢复原版卡带 |
| **VIP tracks** | 用你自己的 Cookie（绿钻会员可播） |
| Background transcoding + cache | mp3 → ogg，LRU 上限 1 GB，命中缓存秒开 |
| Look-ahead prefetch | 自动预热后面几首，顺序听歌单基本无缝 |

## How it works / 原理

```
ChillPulse (patched data.win)
      │  GML http_get, 127.0.0.1:38612
      ▼
qqbridge.py  ──►  QQ Music unofficial web API (u.y.qq.com)
      │             resolve vkey → download → ffmpeg → ogg
      ▼
<game>\qqmusic_cache\<mid>.ogg  ──►  audio_create_stream()
```

* The game side is injected into `obj_controller` with
  [UndertaleModTool](https://github.com/UndertaleModTool/UndertaleModTool) —
  see `mod/` and `mod/README_MOD.md`.
* The bridge is a single-file Python HTTP server on `127.0.0.1` (local only).
* Nothing is uploaded anywhere except QQ Music's own endpoints.

## Requirements / 依赖

* Windows, the game **ChillPulse** (Steam appid `2826180`)
* **Python 3.9+**
* **ffmpeg** on `PATH` (`winget install Gyan.FFmpeg`)
* A QQ Music account; for VIP tracks a valid login cookie
* UndertaleModTool CLI — only if you want to rebuild the patch yourself

## Install / 安装

```
1. copy bridge/ and mod/ next to your game (e.g. E:\ChillPulseQQMod\)
2. py -3 bridge\qqbridge.py --port 38612 --game-dir "<game folder>"    # first run
3. open http://127.0.0.1:38612/login in a browser OR paste a cookie:
      py -3 mod\set_auth.py            (see auth.json format below)
4. build + install the game patch:
      powershell -ExecutionPolicy Bypass -File mod\install_mod.ps1
5. start the game → ≡ → 「QQ音乐」
```

`auth.json` (next to the bridge, **never commit it**):

```json
{ "uin": "1234567890", "cookie": "qm_keyst=...; qqmusic_key=..." }
```

`qm_keyst` / `qqmusic_key` alone is enough for VIP playback. It expires after a
few days; re-paste when playback silently drops to free tracks only.

## Repository layout / 目录

```
bridge/     the local HTTP bridge (Python) — talks to QQ Music
mod/        the in-game patch: GML source, the UTMT patcher, installer, guards
launcher/   optional start/stop helper that runs the bridge per game session
docs/       troubleshooting notes
```

## Troubleshooting / 排错

* **"not signed in" in game** → the bridge is not running, or the cookie expired.
  Check `http://127.0.0.1:38612/status`.
* **Steam restores `data.win`** (verify integrity / game update) → the mod
  disappears; re-run `mod\reinstall_mod.bat`. `mod_guard.py` also repairs it at
  every launch.
* **Steam stops connecting entirely** → a local proxy (Clash etc.) is rejecting
  `*.steamserver.net`. See `docs/troubleshooting.md`.
* **Steam shows "stopping" forever after quitting** → a known Steam-side record
  issue with this game, unrelated to the mod; restart Steam.

## Legal / 免责

* **No game data is distributed here.** You patch your own legally owned copy.
* Uses QQ Music's *unofficial* web API with **your own** account, for personal
  use. Your cookie never leaves your machine except to QQ Music itself.
* Not affiliated with catosgame (the game's developer) or Tencent.

## License

MIT — see `LICENSE`.
