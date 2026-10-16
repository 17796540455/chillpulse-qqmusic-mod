# 网易云播放修复

已定位到播放地址的请求方式：普通 Web 接口会对部分歌曲返回 `code=200`，但所给地址被 CDN 以 HTTP 403 拒绝。保持同一账号和歌曲，使用客户端 EAPI 请求后返回有效音频。

修复内容：

- 播放地址改用客户端 EAPI，登录凭证仍只发给网易云官方接口。
- 使用 Windows 自带 CNG 完成请求编码，无需另装 Python 依赖。
- 校验播放结果和试听权限；30 秒试听不会伪装成完整歌曲，错误不再一律解释为“会员或已下架”。
- 合入前一轮修复：本地音乐页隐藏在线登录提示；浏览新歌单保留播放位置，新歌单插在当前歌曲后；重叠歌曲不重复。
- 同步运行文件、Mod 源码、重装模板和补丁 SHA256；旧版本会先备份。

验证：8 项 provider 测试通过；从编译后游戏数据反编译的实际方法通过 15 项面板/队列检查；实际桥接完整下载并转码三首网易云歌曲，时长为 275.5 秒、246.1 秒、190.9 秒。仅获准试听的样本返回明确提示，QQ provider 和混合音源 ID 路由保留。

请求编码格式参考了上游项目的 [EAPI 实现](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/main/util/crypto.js)。本次不使用第三方替代音源，也不改变账号本身的播放权限。

## 本地回归检查

在 Windows 下从仓库根目录运行：

```powershell
python bridge/test_netease_provider.py
node mod/tests/test_ui_queue.cjs
```

第一组测试不需要登录或网络；第二组需要 Node.js，仅作为开发期检查工具。实机界面与音频输出仍以游戏运行结果为准。
