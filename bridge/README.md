# qqbridge — QQ音乐 local bridge for ChillPulse

A single-file, **stdlib-only** HTTP service that lets the ChillPulse GameMaker mod
search QQ音乐, browse playlists and turn a song into a Godot/GameMaker-friendly
**Ogg Vorbis** file in the game folder.

```
bridge\
  qqbridge.py        the service (deliverable)
  start_bridge.bat   double-click launcher
  qqmusic.py         read-only QQ Music API client used by the service
  test_bridge.py     end-to-end acceptance test (2nd process, urllib only)
  auth.json          optional login credentials (you create this)
  qqbridge.log       timestamped activity log (UTF-8, appended)
  cache\             <mid>.mp3 downloads, login_qr.png, tracks.json metadata
```

## Start it

```bat
bridge\start_bridge.bat
```

or directly (defaults: port 38610, game dir `E:\steam\steam\steamapps\common\ChillPulse`):

```bat
"C:\Users\wmcyh\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" ^
  bridge\qqbridge.py --port 38610 --game-dir "E:\steam\steam\steamapps\common\ChillPulse"
```

| flag | default | meaning |
|---|---|---|
| `--port` | `38610` | TCP port, bound to `127.0.0.1` only |
| `--game-dir` | `E:\steam\steam\steamapps\common\ChillPulse` | root of the game install; the bridge writes `<game-dir>\qqmusic_cache\<mid>.ogg` |
| `--ffmpeg` | auto | explicit `ffmpeg.exe` (only used when PATH and the known winget path both miss) |

ffmpeg discovery order: `PATH` → the known winget install →
`--ffmpeg`. `/status` reports `ffmpeg:true|false`.

## Endpoints (frozen contract)

Every response is `Content-Type: application/json; charset=utf-8`, UTF-8 encoded,
HTTP 200 for all bridge-level results, and always carries `"ok"` (bool).
`POST` is accepted on the same paths (form-encoded or JSON body) as well as `GET`.

| endpoint | response |
|---|---|
| `GET /status` | `{"ok":true,"logged_in":false,"nickname":"","ffmpeg":true,"game_dir":"...","version":"1.0"}` |
| `GET /search?q=<kw>&page=1&n=30` | `{"ok":true,"tracks":[{"id":"<mid>","name":"...","singer":"...","album":"...","dur":269,"vip":0}]}` |
| `GET /playlists` | `{"ok":true,"logged_in":true,"playlists":[{"id":"<disstid>","name":"...","count":123,"special":"fav"}]}` — `special` is `"fav"` only for 我喜欢, and that entry is sorted first |
| `GET /playlist?id=<disstid>&offset=0&count=50` | `{"ok":true,"name":"...","total":123,"tracks":[ …same track shape… ]}` |
| `GET /play?id=<mid>&name=…&singer=…` | `{"ok":true,"state":"preparing"}` → later `{"ok":true,"state":"ready","file":"qqmusic_cache/<mid>.ogg"}` |
| `GET /playstate?id=<mid>` | `{"ok":true,"state":"preparing"}` / `{"ok":true,"state":"ready","file":"qqmusic_cache/<mid>.ogg","title":"...","singer":"...","dur":269}` / `{"ok":false,"state":"error","msg":"该歌曲需要绿钻或已下架"}` |
| `GET /stop` | `{"ok":true}` — cancels the in-flight prepare |
| `GET /login` | starts QR login → `{"ok":true,"state":"waiting","qr":"cache/login_qr.png","msg":"…"}` ; `{"ok":true,"state":"unsupported","msg":"…"}` when the QR flow is unreachable |
| `GET /loginstatus` | `{"ok":true,"state":"waiting|ok|fail|unsupported","nickname":"..."}` |
| `GET /quit` | `{"ok":true}`, then the process shuts down |

Error shape used everywhere: `{"ok":false,"msg":"<short Chinese reason>", …}`.

Notes / deliberate deviations:

* `/playstate` for a mid that was never `/play`ed answers
  `{"ok":false,"state":"error","msg":"尚未开始播放，请先调用 /play"}` (the documented
  error shape, not a new state).
* `/stop` answers `{"ok":true}` and leaves the cancelled mid in
  `state:"error"` with `msg:"已取消"` / `"已停止"`, so a poller stops.
* `/playlists` without credentials is `{"ok":true,"logged_in":false,"playlists":[]}`.
* Unknown paths answer HTTP 404 with `{"ok":false,"msg":"未知接口 …"}` (still JSON).

## GameMaker usage

```gml
var _r = http_get("http://127.0.0.1:38610/search?q=" + url_encode(kw) + "&page=1&n=30");
// ... Async - HTTP event ...
var _doc = json_parse(async_load[? "result"]);
if (_doc[? "ok"]) { /* _doc[? "tracks"] */ }
```

`file` is a forward-slash path relative to the game directory
(`qqmusic_cache/0039MnYb0qxYhV.ogg`) so it can be fed straight into an
`audio_create_stream`-style path join with `working_directory`.

## Login (optional)

Anonymous mode works for search and for free tracks. VIP/绿钻 tracks answer
`该歌曲需要绿钻或已下架` until real credentials are supplied. Drop a cookie into
`bridge\auth.json` (**re-read automatically when the file changes**, no restart):

```json
{
  "uin": "123456789",
  "cookie": "uin=o123456789; qm_keyst=...; qqmusic_key=...",
  "nickname": "optional, display only"
}
```

Grab the cookie from a logged-in <https://y.qq.com> browser session
(DevTools → Application → Cookies → copy `qm_keyst`/`qqmusic_key`, or the whole
`document.cookie` string). `uin` may be omitted — it is parsed from `cookie`.

`/login` also implements the QQ `ptlogin2` QR flow (`ptqrshow` + `ptqrlogin`,
QR written to `bridge\cache\login_qr.png`) and, on success, writes `auth.json`
automatically. That path needs a phone to complete and has not been verified
end-to-end; `auth.json` is the supported route.

## Audio pipeline

`/play` returns instantly and a worker thread does:

1. `vkey.GetVkeyServer` for qualities **320 → flac → 128** (each tried with the
   track's `media_mid` and its `mid`), so VIP tracks fail cleanly instead of
   crashing.
2. download to `bridge\cache\<mid>.mp3` (reused on a later prepare of the same mid).
3. `ffmpeg -y -i <in> -c:a libvorbis -q:a 4 -f ogg <out>.part` → atomic rename to
   `<game-dir>\qqmusic_cache\<mid>.ogg`.

One download at a time; a new `/play` or `/stop` kills the previous job. The HTTP
threads are never blocked, so `/status` and `/playstate` stay sub-millisecond even
while ffmpeg is running.

## Troubleshooting

| symptom | cause / fix |
|---|---|
| `该歌曲需要绿钻或已下架` | VIP-only or delisted track, or no `auth.json` |
| `未找到 ffmpeg` | install ffmpeg or pass `--ffmpeg` |
| `无法写入游戏目录` | `--game-dir` is wrong or read-only |
| `/search` returns `tracks: []` | QQ Music rate-limits bursts with an empty `code=2001` reply; the bridge retries with backoff and falls back to the local metadata cache. Repeated identical queries are cached for 2 minutes |
| `{"ok":false,"msg":"搜索失败，请检查网络连接"}` | upstream unreachable |

Log: `bridge\qqbridge.log` (timestamped, UTF-8, includes upstream failures).

## Acceptance test

```bat
python bridge\test_bridge.py --port 38610 ^
  --game-dir "C:\...\mods\testgame" ^
  --ffprobe "<path>\ffprobe.exe" [--quit]
```

Checks `/status`, `/search`, a full free-track prepare verified with `ffprobe`
(codec must be `vorbis`, plausible duration), the VIP error path and server
responsiveness from a second thread while a download runs.
