# 网易云音乐 API — 实测笔记

全部结论来自真实请求（`netease_probe.py`，直连不走代理，UA 为 Chrome，
`Referer: https://music.163.com/`）。测于 2026-10-16。

## 结论速览

| 能力 | 是否需要登录 | 实测结果 |
| --- | --- | --- |
| **搜索** | ❌ 不需要 | ✅ `code=200`，185 ms |
| **歌单详情** | ❌ 不需要 | ✅ 一次返回全部曲目（200 首 ✓，无需分页） |
| **歌曲直链** | ✅ **必须** | ❌ 免登录一律 `code=-110`（新旧接口 × 三种音质 × 三首歌，全部失败） |

> `-110` 是网易云「需要登录 / IP 不可用」的返回码。搜索与歌单都正常，
> 说明不是网络或 IP 问题，而是 **`/song/enhance/player/url` 系列接口已要求登录 Cookie**。

## 1. 搜索（免登录 ✓）

```
GET https://music.163.com/api/search/get/web?s=<关键词>&type=1&limit=<n>&offset=<页码*n>
```

字段路径：

```
result.songs[].id            歌曲 id
result.songs[].name          歌名
result.songs[].artists[].name  歌手（数组，需用 / 连接）
result.songs[].album.name    专辑
result.songs[].duration      时长（毫秒）
result.songs[].fee           付费标记：0/1 免费可播，8 需会员，4 低价专辑
```

一首歌的完整键：`album, alias, artists, copyrightId, duration, fee, ftype, id, mark, mvid, name, rtype, status`

## 2. 歌单（免登录 ✓）

```
GET https://music.163.com/api/v6/playlist/detail?id=<歌单id>&n=1000
```

字段路径：

```
playlist.name            歌单名
playlist.trackCount      曲目总数
playlist.tracks[]        曲目数组（实测 200 首一次性返回，无需分页）
playlist.tracks[].id
playlist.tracks[].name
playlist.tracks[].ar[].name    歌手（注意是 ar，不是 artists）
playlist.tracks[].al.name      专辑
playlist.tracks[].dt           时长（毫秒）
playlist.tracks[].fee          付费标记
```

> 注意字段名与搜索接口**不一致**（搜索用 `artists/album/duration`，歌单用 `ar/al/dt`）✓
> 网易云的 v6 接口字段是简写形式，两种都要兼容。

获取自己的歌单列表：需要登录后 `GET /api/user/playlist?uid=<自己的uid>&limit=1000`
（未实测，因无 Cookie；预期与 QQ音乐 的 `/playlists` 对应）。

## 3. 歌曲直链（必须登录 ✗）

尝试过的组合，全部 `code=-110`：

| 接口 | 参数 |
| --- | --- |
| `/api/song/enhance/player/url` | `ids=[<id>]&br=128000` / `br=320000` |
| `/api/song/enhance/player/url/v1` | `ids=[<id>]&level=standard&encodeType=mp3` |
| `/api/song/enhance/player/url/v1` | `ids=[<id>]&level=exhigh&encodeType=mp3` |

返回体（失败时）：

```json
{"data":[{"id":347230,"url":null,"br":0,"size":0,"code":-110,"fee":1,...}],"code":200}
```

注意**外层 `code=200` 但内层 `data[0].code=-110`** ✓ —— 判断可用性必须看内层 code 和 `url` 是否为空 ✓。

成功时的预期字段（按 QQ音乐 的经验与社区文档）：

```
data[0].url        直链（可能带鉴权参数，有时效）
data[0].br         实际码率
data[0].size       字节数
data[0].level      standard / higher / exhigh / lossless / hires
data[0].fee        0/1 免费，8 会员
data[0].freeTrialInfo  试听片段信息（会员曲目未登录时可能出现）
```

## 4. 登录（待用户提供 Cookie）

需要的 Cookie 字段（与 QQ音乐 的 `qm_keyst` 同性质）：

```
MUSIC_U     登录凭证（必需）
__csrf      配套字段
```

已提供工具：`py -3 netease_probe.py cookie "MUSIC_U=...; __csrf=..."` → 写入
`bridge/auth_netease.json`，并调用 `/api/nuser/account/get` 验证账号（打印昵称与 vipType）。

## 5. 音质档位（待有 Cookie 后实测确认）

```
standard  ≈128k   free 可播
higher    ≈192k   多数 free 可播
exhigh    ≈320k   常需会员
lossless  flac    黑胶 VIP
hires     24bit   黑胶 VIP
```

## 6. 给桥接的实现要点

1. **两套字段名**要兼容：搜索 `artists/album/duration`，歌单 `ar/al/dt` ✓
2. **直链必须带 Cookie** ✓，未登录时应对游戏返回明确错误（如「该歌曲需要网易云登录」✗）而不只是笼统失败
3. **歌单一次取全** ✓（`n=1000`），不需要像 QQ音乐 那样担心分页
4. 响应可能很慢（歌单 448 ms ✓，可接受），但要考虑 `_retry` 包裹 ✓
5. 仍然**直连不走代理** ✓（与 QQ音乐 一致 ✓）
6. 判断可播性：`data[0].url` 非空 **且** `data[0].code == 200` ✓

## 7. 未验证 / 待办

* 登录后直链能否成功（**只差一个 Cookie** ✓）
* 自己的歌单列表接口 `/api/user/playlist`（需要 uid ✓）
* 免费账号能拿到哪些音质档（`standard` 大概率可以 ✓）
* 是否需要 `deviceId` / 匿名 `MUSIC_A` token（社区提到无登录时部分接口需要，但**搜索和歌单实测不需要** ✓）
