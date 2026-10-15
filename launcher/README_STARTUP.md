# ChillPulse QQ 音乐 Mod：启动与退出修复

从 Steam 游戏库正常点击“开始游戏”即可。Steam 的启动选项由安装步骤写入：

```text
"C:\Users\wmcyh\AppData\Local\Programs\Python\Python39\pythonw.exe" "E:\ChillPulseQQMod\launcher.py" %command%
```

启动器先检查补丁，再启动桥接并等待服务就绪，然后运行 Steam 传入的游戏命令。游戏退出后会关闭并回收桥接。桥接同时监视启动器的进程句柄，启动器意外结束时也会退出。

桥接统一使用 `127.0.0.1:38612`。Windows 命名互斥量和独占端口绑定共同阻止重复实例。桥接不再继承 Steam 的游戏身份变量；游戏仍保留 Steam 原有的启动环境和参数。

现有桌面快捷方式和 `start_bridge.bat` 也转入同一启动逻辑。桌面入口调用 Steam 启动游戏，Steam 的启动器识别到已有监督进程后只启动实际游戏，不会再起一个桥接。

启动失败会显示错误，并清理已启动的桥接。日志位于本目录的 `launcher.log` 和 `qqbridge.log`。正常启动不再调用 `steam_unstick.py`，也不再自动重启 Steam。

安装前的脚本和 Steam 配置保存在本目录的 `startup-backup-*` 文件夹。回退时先退出游戏和 Steam，再还原备份中的脚本及 `localconfig.vdf`。新增文件为 `launcher.py`、`lifecycle.py` 和本说明。

原始 `data.win` 补丁、音乐缓存及 QQ 音乐登录信息不属于本次修改范围。
