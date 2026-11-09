# Project Eos 美术资源

## 设施图标集 v2（透明背景）

- 来源：用户本地 `GPT Image Studio`
- 接口：OfoxAI `/v1/images/generations`
- 模型：`openai/gpt-image-2.5-flare`
- 画质：`low`，尺寸 1024×1024，`background: transparent`
- 风格：写实微等距游戏图标、单体悬浮底座、无文字/边框/人物
- 生成脚本：`tools/generate_transparent_icons.py`
- 原始图：本机 `raw/transparent/<key>_raw.png`（已在 `.gitignore` 中，不随仓库提交）
- 成品：`icons/<key>.png`，320×320 RGBA，四角 alpha = 0

图标：

`farm`、`mine`、`granary`、`irrigation`、`workshop`、`library`、`market`、
`temple`、`great_granary`、`great_forge`、`great_library`。

重新生成：

```bash
.venv/Scripts/python tools/generate_transparent_icons.py --only farm --force
.venv/Scripts/python tools/generate_transparent_icons.py --force
```

脚本优先读取 Studio `settings.json` 的 `apiKey`；如果该字段是本地化显示文本，则从
`keySource` 指向的 `api_providers.json` 中取 OfoxAI key。密钥只进入进程内存，不打印、
不写回仓库。若供应商返回白底，脚本会从边缘泛洪去背并羽化 alpha。

## 道路例外

`icons/road.png` 保留为历史素材，但地图与建造入口不使用它：道路始终在地图和城市
局部图上画成连续线稿，建造列表使用 CSS 道路缩略图。这是既定美术规则，不要把道路
改成图片标记。

## 旧版参考

`raw/facilities_sheet_v1_1.png` 与 `raw/civic_sheet_v1_1.png` 是不透明深蓝灰背景的
第一版接触表，仅作风格参考，不再进入界面。

## 游戏内使用

- 地块建造列表：38×38 缩略图
- 左侧施工队列：18×18 缩略图
- 地图已完成设施：按地块缩放绘制，施工中图标半透明并叠加国家色进度环
- 奇观复用独立图标并在进入建造队列后按相同方式显示
