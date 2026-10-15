# ChillPulse QQ Music Mod

在 **ChillPulse** 游戏内的音乐面板里直接播放 **QQ 音乐**：搜索歌曲、播放自建歌单、
绿钻曲目，界面和游戏原版完全一体，不用切窗口。


---

## 功能

| 功能 | 说明 |
| --- | --- |
| **QQ音乐标签页** | 就在游戏原来的音乐面板里，与原版 UI 同一套风格，旁边是「本地音乐」 |
| **搜索** | 搜歌名/歌手，点结果**立刻播放**，并插到「正在播放」的后面，不打乱原有队列 |
| **歌单** | 读取你账号里的「我喜欢」和全部自建歌单（实测 131 首的歌单也能完整加载） |
| **播放队列** | 「正在播放 / 播放队列」视图：点行跳播，`▲▼` 调整顺序，`×` 从队列移除 |
| **暂停 / 上一首 / 下一首** | 底部播放条控制 QQ 音乐；点「本地音乐」即切回游戏原版卡带 |
| **绿钻曲目** | 用你自己的登录 Cookie，会员歌曲正常播放 |
| **自动转码 + 缓存** | 后台 mp3 → ogg，LRU 上限 1 GB；播过的歌**秒开** |
| **向后预热** | 自动预取后面 3 首，顺序听歌单基本无缝衔接 |
| **补丁自愈** | Steam 「验证游戏文件完整性」或更新后 `data.win` 被还原时，启动时自动修复 |

**原理**：游戏通过 `127.0.0.1:38612` 问本地桥接服务要歌，桥接去 QQ 音乐取直链、
下载、用 ffmpeg 转成 ogg，游戏再用 `audio_create_stream` 流式播放。

---

## 安装

### 0. 前置要求

| 需要 | 说明 |
| --- | --- |
| Windows + 正版游戏 | Steam 库里的 **ChillPulse**（AppID `2826180`） |
| **Python 3.9+** | <https://www.python.org/downloads/>（安装时勾选 Add to PATH） |
| **ffmpeg** | `winget install Gyan.FFmpeg` |
| QQ 音乐账号 | 播绿钻歌曲需要登录（免费歌曲不登录也能放） |

### 1. 放置文件

把 `bridge/` 和 `mod/` 两个目录放到同一个文件夹里，例如：

```
E:\ChillPulseQQMod\
    bridge\     qqbridge.py  qqmusic.py  start_bridge.bat
    mod\        gml_Script_qqm_mod.gml  apply_mod.csx  install_mod.ps1  ...
```

### 2. 登录 QQ 音乐

浏览器打开 <http://127.0.0.1:38612/login> 扫码，或手动写 `bridge/auth.json`：

```json
{ "uin": "你的QQ号", "cookie": "qm_keyst=...; qqmusic_key=..." }
```

> 只需 `qm_keyst` / `qqmusic_key` 就够（绿钻可播）。Cookie 有效期通常几天，
> 过期后播放会退回只能听免费歌曲，重新粘贴即可。

### 3. 给游戏打补丁

补丁需要 [UndertaleModTool](https://github.com/UndertaleModTool/UndertaleModTool/releases)
的**命令行版**（`UndertaleModCli.exe`）：

```powershell
# 1) 备份原版
copy "<游戏目录>\data.win" "<游戏目录>\data.win.qqmod-backup"

# 2) 应用补丁
UndertaleModCli.exe load "<游戏目录>\data.win" -s mod\apply_mod.csx -o data_patched.win

# 3) 装进游戏（会保留一份原版备份，可随时卸载）
powershell -ExecutionPolicy Bypass -File mod\install_mod.ps1
```

### 4. 启动

```powershell
bridge\start_bridge.bat          # 起桥接服务（保持窗口开着）
# 然后正常启动游戏 → 点左下角 ≡ → 「QQ音乐」
```

想要**自动启动**（推荐）：`mod\launcher\` 里的启动器可让桥接随游戏会话起停，
或用 `mod\install_autostart.ps1` 做登录自启。

---



---


