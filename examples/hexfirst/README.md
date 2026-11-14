# 六边形地图整合试玩存档

这是交接世界 seed 50002 的第 0 日副本：四国、公元前 800 年、144×108 六边形、内湖、内流河与初始道路。原玩家存档不变。

在项目根目录运行：

```powershell
.venv/Scripts/python live_server.py --load examples/hexfirst/save.json --days 365 --paused --open
```

进入后选择“继续游戏”。军事系统在读档时自动迁移到新版；保存会另建本机 `runs/saves/` 槽位，不会覆盖这里的示例。`world.json` 与 `save.json` 必须一起保留，世界文件内容有 SHA-256 校验。
