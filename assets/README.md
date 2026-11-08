# Project Eos 美术资源

## 设施图标集

- 来源：用户本地 `GPT Image Studio`
- 接口：OfoxAI `/v1/images/generations`
- 模型：`openai/gpt-image-2.5-flare`
- 画质：`low`
- 尺寸：1024×1024
- 风格：写实微等距游戏图标、深蓝灰背景、无文字/边框/人物
- 原始图：`raw/facilities_sheet_v1_1.png`
- 状态：第一张消耗 190 输入 + 196 输出图像 Token；第二张 171 + 196。实际货币按供应商低质量档估算约 $0.006/张。

独立图标：

- `icons/farm.png`
- `icons/mine.png`
- `icons/road.png`
- `icons/granary.png`
- `icons/irrigation.png`
- `icons/workshop.png`

## 文明建筑图标集

- 原始图：`raw/civic_sheet_v1_1.png`
- 风格与设施集保持一致
- 独立图标：`library.png`、`market.png`、`temple.png`、`great_granary.png`、`great_forge.png`、`great_library.png`

## 游戏内使用

- 地块建造列表：38×38 缩略图
- 左侧施工队列：18×18 缩略图
- 地图已完成设施：按地块缩放绘制，施工中图标半透明并叠加国家色进度环
- 奇观复用独立图标并在进入建造队列后按相同方式显示

图片背景暂保留深蓝灰色摄影棚底，并通过圆角透明遮罩融入界面。后续可以替换为真正透明的抠图版本，不需要修改游戏逻辑。