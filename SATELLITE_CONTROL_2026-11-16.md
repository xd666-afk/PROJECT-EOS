# v0.52：卫星图中的国家轮廓与控制范围

卫星图现在同时呈现地形、国家控制区和国界。当前实际控制的六边形格子使用国家淡色覆盖，外缘以深色底线和彩色轮廓描绘；同一国家的相邻格不重复描绘国界。河流、湖泊、道路和设施继续可见。

地图标注显示“国家名 · 控制格数”，图例也列出各国当前控制格数。标注锚点位于该国最大连通控制区内部，避免分散领土的平均中心落在他国或海上；缩小时重叠标注会避让，所有飞地和内部空洞仍按实际边界绘制。

## 实时归属

- 绘制读取 `STATE.countries[*].tiles`。存档中的当前归属优先于底图初始归属；已失去或已消失国家的原领土不会被静态颜色重新填回。
- 领土内容进入地图与轮询的刷新签名，即使暂停时同一日发生归属变化，也会重新计算轮廓和格数。
- `assets/ui/territory.js` 缓存边界几何，仅在世界或领土归属改变后重建；缩放、平移只重新绘制。
- 非卫星图保留各自原有表达。当前紧凑布局、单焦点事态和实际模拟规则继续沿用。

## 验证

```powershell
.venv/Scripts/python -m pytest tests/test_dashboard_ui.py -q
.venv/Scripts/python scripts/verify_satellite_ui.py --output runs/ui_checks/satellite
```

真实 Edge 验证覆盖：奇偶行的 12 种相邻组合、内部共享边删除、洞与飞地、最大连通区标注、同日易主、无主地不恢复初始归属、国家消失、实际画布像素差异、程序地形与栅格纹理两种背景、手机宽度。测试使用独立临时存档，不修改玩家世界。

本轮验证结果：25 项地图界面回归通过，专项浏览器检查通过，页面脚本异常 0 条。

截图：[卫星全图](docs/report_assets/satellite_v052/satellite-world.png)、[领土近景](docs/report_assets/satellite_v052/satellite-detail.png)、[手机](docs/report_assets/satellite_v052/satellite-mobile.png)。`texture-overlay.png` 为纯色测试纹理，用于验证栅格纹理分支，不是实际世界截图。
