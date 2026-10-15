# Troubleshooting

## The panel says "not signed in" / 面板显示未登录

1. Is the bridge running? `http://127.0.0.1:38612/status`
   * no answer → start it (`bridge\start_bridge.bat`) or let the launcher do it
   * `"logged_in": false` → the cookie is missing or expired, re-paste it
2. A QQ Music login ticket (`qm_keyst` / `qqmusic_key`) lasts a few days. When it
   expires, playback silently drops to free tracks only.

## Sound does not start / 点了没声音

* The first play of a track needs a download + ffmpeg transcode (8–25 s
  depending on the CDN). The panel shows 加载中… / 缓冲中… meanwhile.
* A track that has been played once is cached and starts instantly.
* Look-ahead prefetch (`qqm_prefetch_ahead`, default 3) keeps the next few
  tracks warm, so listening through a playlist is seamless.

## Steam restored `data.win` and the QQ Music tab disappeared

Steam's *Verify integrity of game files* (and any game update) restores
files from its own manifest, which removes the patch.

* `mod\reinstall_mod.bat` puts it back in one double-click.
* `mod_guard.py` also runs on every launch and repairs it automatically —
  but only when the file is *exactly* the vanilla build the patch was made
  against. After a real game update it deliberately does nothing and says so in
  `mod_guard.log` (copying an old patched `data.win` over a new build would
  break the game). Rebuild the patch for the new version instead.

## Steam cannot connect at all

Check `E:\steam\steam\logs\connection_log.txt`: if every
`PingWebSocketCM()` line ends in `timeout/neterror`, a local proxy (Clash,
v2ray, …) is rejecting `*.steamserver.net`.

* Direct connections to those hosts are usually fine — measured 41–201 ms.
* Fix: add the Steam hosts to the WinINET bypass list
  (`mod\fix_proxy_bypass.py` does exactly that), or add
  `DOMAIN-SUFFIX,steamserver.net,DIRECT` to the proxy rules, then **restart
  Steam** (it reads proxy settings only at startup).
* The bridge itself always bypasses the system proxy, so QQ Music keeps working
  either way.

## Steam shows "stopping" forever after quitting the game

A Steam-side record issue with this game (it happens with the unmodified game
too; verified by comparing against a vanilla install, and the game's exit code
is a clean `0x00000000`). Nothing is actually running at that point.

* Restart Steam, or run `mod\steam_unstick.py`, which detects the state
  (Steam says running + no `ChillPulse.exe`) and restarts Steam for you.

## Rebuilding the patch yourself

```
tools\make_methods.py                       # gml_Script_qqm_mod.gml -> qqm_methods.gml
UndertaleModCli.exe load <pristine data.win> -s mod\apply_mod.csx -o data_patched.win
powershell -File mod\install_mod.ps1        # backs up once, installs, keeps the backup
```

The patcher fails loudly if an anchor does not match, which is how you find out
that the game was updated.

## Ports

The bridge listens on `127.0.0.1:38612` only. Nothing is exposed to the
network. `--port` changes it, but the patched game hard-codes the port in
`qqm_port` (`mod\gml_Script_qqm_mod.gml`), so both must agree.
