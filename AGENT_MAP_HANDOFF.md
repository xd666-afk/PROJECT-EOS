# Project Eos v0.1 — 地图生成模块完整移交（含源代码）

> **给接手的开发 Agent 的说明：本文件与配套 ZIP 是同一套项目的地图/地理系统交接。**
>
> 如果你能拿到 ZIP，请以 ZIP 内实际源代码和 `output/world_2000BCE.json` 为准；此 Markdown 末尾还完整附有原始关键 Python 脚本，以便单独传入上下文时查阅。不要声称已完成实时国家模拟、经济规则引擎或 AI API 接入——这些尚未在本地图模块中实现。
>
> 移交日期：2026-11-05。原生成器版本：0.1.0；固定生成种子：`2000`。

## 1. 核心交付内容与当前状态

这是**真实可运行的代码及生成数据**，不是仅包含设计构想的报告。本包将地图、地形、季节气候、河网、灾害相对暴露层及四个公元前 2000 年国家的初始化地理数据交付给你。

- 主程序：`worldgen.py`（造大陆、海拔、气候、河网、灾害、国家核心区、地图 PNG 和 JSON）
- 天气试运行：`simulate_climate.py`（根据月气候态做 365 日逐日随机天气实验，汇总每月与事件）
- 离线交互地图：`build_viewer.py` → `output/viewer.html`（切换海拔、温度、降水、灾害、政区）
- 额外绘图：`plot_elevation.py`（本次交接新增，仅负责从现有世界 JSON 绘制海拔图，不修改生成模型）
- 单元测试：`tests/test_generated_world.py`（4 项测试，移交前已运行通过）
- 依赖：`requirements.txt`（NumPy、SciPy、Matplotlib）；测试另需 `pytest`
- 初始世界数据：`output/world_2000BCE.json`（**对接实时规则引擎时最重要的文件**）
- 摘要：`output/world_summary.json`
- 图片：`world_map.png`、`rainfall_map.png`、`hazard_map.png`、`elevation_map.png`
- 第一年度结果：`output/first_year_weather.json`
- 原生离线查看器：`output/viewer.html`

## 2. 真实世界规模与统计

| 指标 | 值 |
|---|---|
| 世界名 | 埃欧斯大陆（Eos Continent） |
| 起始日期 | 虚构统一历公元前 2000 年 1 月 1 日；天文学纪年 -1999 |
| 网格 | `odd-r pointy-top`、奇数行水平偏移的尖顶六边形 |
| 地图大小 | 72 列 × 54 行 = **3,888** 格 |
| 六边形外接圆半径 | 34 km |
| 单格面积 | 约 3,003.4 km² |
| 陆地格 | **2,703** |
| 海洋格 | **1,185** |
| 陆地总面积 | **8,118,126 km²** |
| 海拔最高值 | **3,931 m** |
| 主要河道格 | **289** |
| 未受国家控制的陆地格 | **2,634** |
| 初始政治实体 | **4** 个青铜时代早期国家 |
| 首年天气样本 | **365** 日，12 个按月汇总记录，31 条示例灾害事件 |

这里的“陆地面积”是由六边形栅格模型计算得到，并不代表现实地图投影的精确测量面积。没有声明精细的板块动力学或真实全球天气模式。

## 3. 地图的核心机制

### 3.1 六边形位置与寻邻

- 原始存储坐标：`col`, `row`（均从 0 开始）；另存 `q`, `r` 的轴向坐标，转换公式：`q = col - (row - (row & 1)) // 2`、`r = row`。
- 网格宽高：`W=72`, `H=54`。尖顶式六边形、奇数行右移半格。
- `neighbors(col,row)` 返回六个方向的有效相邻格，区分奇偶行；`hex_distance(a,b)` 计算六边形距离。
- 当前地块尺度相对较大，设计上适合地域尺度的国家模拟；不是逐米模拟。

### 3.2 地形与海拔（**已存在，绝非超级大平原**）

- `gen_base(seed)` 使用多尺度平滑随机噪声、宽尺度陆壳形状、西部主山脉、内陆山脊、高地等项叠加。
- 海岸线受陆块阈值和内海/海湾形态影响；所有地图边缘设为海洋。
- 海拔以米存储在每个 `tile.elevation_m`，约最高 3,931 m； `slope` 是近邻海拔差计算的无量纲地形梯度近似值。
- 地形并非科学板块碰撞模拟，山系和断裂带是程序化设计的；地图东部仍有较大缓丘/低地连续区域，后续如需更复杂地貌，可有意识加入支脉、盆地、河谷等；**但不要在首轮国家 AI 启动之前重做整套地形**。
- 四张地图中的海拔专题图 `output/elevation_map.png` 是既有独立补充图；`plot_elevation.py` 可以重新从 JSON 绘制同类海拔层，但绘图样式不保证逐像素相同。

### 3.3 气候（月气候态，非科学天气预报）

`gen_climate(...)` 为每格计算：

- 纬度范围约北纬 8°–51°，近似太阳辐射梯度。
- 海拔高度带来的平均降温项约 `-0.006 × 海拔米数`，即 6°C/千米。
- 海洋距离与内陆性影响温度季节振幅。
- 低纬热带湿润带、副热带偏干带、高纬西风带的降水基准；根据纬度切换主要水汽输送方向。
- 沿上风坡地形抬升增雨，内陆和背风区偏干；生成 `monthly_temp_c` 和 `monthly_precip_mm` 各 12 个值。
- 由气温、降水、海拔粗略分出 ocean / alpine / tundra / desert / steppe / savanna / grassland / forest / rainforest 等生物群系。

这是具物理启发的经验函数，不求解真实大气流体方程，也没有接受观测资料的统计校准。不能将其称作真实全球大气模式。

### 3.4 水文与河流

`gen_hydrology(...)` 使用 Priority Flood 形式的填洼/引流算法，为陆地格建立到海洋的 `downstream` 连接，按局地径流和汇水格数计算流域；当前主要河道显示门槛是 `basin >= 17` 且海拔低于 3,300 m。主河道共 **289 格**。

**重要限制：** 该算法强制陆地汇水最终入海，不会自然形成永久无出口内流湖泊；没有模拟精细的流水侵蚀、沉积、河宽水深、流速或季节洪峰。后续系统可以沿 `downstream` 构造流域图，但不要直接把 `drainage_area_km2` 当作水流量。

### 3.5 六种自然灾害相对暴露

每格 `hazards` 包含 `flood`、`drought`、`earthquake`、`volcano`、`wildfire`、`cyclone` 六项 **0–1 归一化相对暴露指数**。洪水由河网、坡度和湿润性近似；干旱由降水与温度；地震/火山由人为设置的活动断裂带；野火由植被和干燥；热带气旋由低纬暖区近海条件近似。

这六个数**不是**一年内发生灾害的概率；不能拿 0.7 解释为“70% 的概率发生地震”。灾害机制尚未与国家人口、农业库存、建筑损坏联动。

### 3.6 逐日天气实验

`simulate_climate.py` 读取固定初始世界的逐月气候态，每游戏日采样空间相关随机天气异常；每月底计算降雨和温度汇总，并抽样产生示例灾害记录。`seed=2000`、365 日得到 12 个月统计和 31 条灾害事件。它是**单次离线实验**，尚未接入任何正式实时主循环。

## 4. 起始四国的地图选址

都城位置由 `pick_polities(...)` 在不同地理适宜度条件下选取，不是手工直接把所有陆地分给四国；它们只控制首都周围的紧凑核心地区。

| 国家 ID | 国家名 | 首都（col,row） | 首都海拔 | 年均降水 | 核心控制格 | 初始人口（设定） |
|---|---|---|---:|---:|---:|---:|
| ELAR | 埃兰河谷城邦联盟 | (13,10) | 235 m | 854 mm | 19 | 37,000 |
| MARIS | 玛瑞斯海湾城邦 | (56,18) | 326 m | 911 mm | 12 | 21,000 |
| VAYR | 维尔山麓诸侯 | (17,20) | 715 m | 433 mm | 19 | 15,500 |
| SAHAR | 萨赫尔河岸王国 | (25,44) | 381 m | 562 mm | 19 | 28,000 |

其余大陆的未控制状态不等于无人居住；游戏中的部落/乡村/城市人口系统尚未建立。

## 5. 实际数据结构（给游戏引擎对接）

根对象：

```text
world_2000BCE.json
├── metadata                      地图尺寸、随机种子、公元前年份、日历、模型边界
├── world_summary                 统计信息
├── polities[]                    4 个早期政治实体与其首都/领土/初始设定
├── tiles[]                       3888 个地块，按 row-major 顺序存储
├── weather_samples[]             生成世界期间的示例天气快照
└── illustrative_hazard_events[]  初始化阶段抽样事件（不等于首年完整实验）
```

单个真实地块示例（埃兰都城所在六边形，直接摘自本包 JSON）：

```json
{
  "q": 8,
  "r": 10,
  "col": 13,
  "row": 10,
  "latitude_deg": 42.89,
  "land": true,
  "elevation_m": 235,
  "biome": "grassland",
  "annual_mean_temp_c": 7.0,
  "annual_precip_mm": 854,
  "monthly_temp_c": [
    -2.0,
    -0.8,
    2.5,
    7.0,
    11.5,
    14.7,
    15.9,
    14.7,
    11.5,
    7.0,
    2.5,
    -0.8
  ],
  "monthly_precip_mm": [
    95.3,
    92.1,
    83.2,
    71.1,
    59.1,
    50.2,
    47.0,
    50.2,
    59.1,
    71.1,
    83.2,
    92.1
  ],
  "slope": 0.0009,
  "river": true,
  "drainage_area_km2": 138155,
  "downstream": {
    "col": 13,
    "row": 9
  },
  "hazards": {
    "flood": 0.456,
    "drought": 0.037,
    "earthquake": 0.062,
    "volcano": 0.0,
    "wildfire": 0.119,
    "cyclone": 0.0
  },
  "owner_id": "ELAR"
}
```

关键对接规则：

1. 地形、海拔、固定地理结构和每月气候态作为初始静态数据加载；国家财政、人口、建筑、工程与库存放到独立可变世界状态中，不要直接在原始生成 JSON 上覆盖。
2. 通过 `(col,row)` 或 `(q,r)` 做唯一地块索引；`owner_id` 仅表示初始国家控制，不代表逐格全部国家人口。
3. `downstream` 指向一个相邻的下游格，陆地最终可沿链到海洋；海洋格没有下游。不要把 `river` 解释成所有地表水径流。
4. 规则引擎可以将气候态用作农业产量基线，逐日天气作为其扰动，但首次集成建议先保持简单，避免过度模拟。
5. 风险指数要由单独事件采样机制使用，不能直接乘到作物产量当作真实损害概率。
6. 日期采用无公元 0 的历史显示法，内部天文学年 `-1999`；游戏纪年与 `seed=2000` 不是同一概念。

## 6. 如何在新 Agent 的本地环境复现

Python >=3.10；需要 `numpy`, `scipy`, `matplotlib`。所有命令应从本包根目录执行：

```bash
python -m pip install -r requirements.txt
# 测试包若未装：python -m pip install pytest

# 重新生成世界、三张原始 PNG、完整 JSON、摘要（确定性的 seed）
python worldgen.py --seed 2000 --output output

# 可重复运行的首年天气实验
python simulate_climate.py --world output/world_2000BCE.json --out output/first_year_weather.json --seed 2000 --days 365

# 重建可离线运行的地图查看器
python build_viewer.py

# 从已生成世界数据绘制补充海拔图
python plot_elevation.py --world output/world_2000BCE.json --out output/elevation_map.png

# 运行现有地图测试
python -m pytest -q tests/test_generated_world.py
```

打开 `output/viewer.html` 即可用浏览器离线检查地图。这个 HTML 内含所需地块数据，**不是**游戏主界面或实时世界控制台。

### Windows 兼容性提醒

原始 `worldgen.py` 绘图函数中硬编码了 Linux 字体路径 `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`。在 Windows 或其他未安装该字体的环境中可能在 `plot_maps` 阶段报错。Agent 应先将此处改为“找到可用中文字体时使用，否则使用跨平台字体回退”的兼容逻辑；**不要为了修字体而改动世界种子和地理核心规则**。

此外 `build_viewer.py` 使用脚本所在目录解析世界 JSON，若在其他目录直接调用，要确保数据仍在对应的 `output/` 下。

## 7. 已测试/未测试，以及接手工作顺序

已检查：

- 文件均从现有真实项目及输出物复制，没有从名称猜测源码；所有初始地图与原 ZIP 中内容一致。
- `python -m pytest -q tests/test_generated_world.py`：**4 passed**。
- 校验值：3888 格、2703 陆地、289 主河道、3931 m 最高海拔、4 个互不冲突国家核心区、365 日天气实验 12 个月和 31 条事件。

未实现：

- 真实板块运动、大气动力学方程、湖泊闭合流域、河道侵蚀、可校准灾害重现期。
- 实时游戏 Tick 调度、AI Agent 接口、固定国家动作审核与执行、经济/人口/城市规则。

**Agent 下一步优先顺序（与用户“先跑起来”要求一致）：**

1. 解压 ZIP，原样运行四项测试并打开 `output/viewer.html`，核对世界数据确实加载成功。
2. 只修必要的可移植性/解析问题；地理与气候生成算法保留稳定基线，不急着扩建复杂地质。
3. 在 `world_2000BCE.json` 基础上构建可变世界状态，每游戏日推进 Tick，先让一个国家拥有资源、人口、建筑与政策状态。
4. 固定动作白名单初步支持 `BUILD`、`ALLOCATE_WORKERS`、`SET_TAX`、`SET_RESEARCH`、`TRADE`、`SET_POLICY`，完全由算法审核合法性；API/AI 后接。
5. 用传统脚本控制四国运行 365 日并检查快照/回放，再接入低价模型。这部分不属于地图模块已完成的内容。

不要把“有一张已生成的地图”误解为“已经有可运行的实时战略游戏”，也不要在没通过单元测试前擅自重写世界生成算法。

## 8. 关键入口和快速接入示例

```python
import json
from pathlib import Path

world = json.loads(Path("output/world_2000BCE.json").read_text(encoding="utf-8"))
meta = world["metadata"]
hextiles = {(t["col"], t["row"]): t for t in world["tiles"]}
polities = {p["id"]: p for p in world["polities"]}

print(meta["world_name"], len(hextiles), len(polities))
print(hextiles[(13, 10)]["elevation_m"])
```

**说明：** 真实 JSON 约 3 MB，离线 viewer 约 1.1 MB，图像为二进制文件。这些不能完整、可靠地塞入一个普通 Markdown，因此随 ZIP 附带；MD 末尾附原始源码以方便独立审阅。

## 9. 科学参考（仅为设计启发）

- 六边形坐标与寻邻：<https://www.redblobgames.com/grids/hexagons/>
- NOAA 大尺度大气环流概念：<https://www.noaa.gov/jetstream/global/global-atmospheric-circulations>
- USGS 地震与板块构造：<https://www.usgs.gov/faqs/where-do-earthquakes-occur>

这些资料不是该代码运行时调用的外部数据源；此世界是程序化生成的虚构大陆。

---

# 附录：可直接还原的完整代码

下面为真实源码原文（除明确标注新增的 `plot_elevation.py`），并非伪代码。大型地理数据和图像仍以 ZIP 中附件为准。

## 附录 — `worldgen.py`

````python
"""Project EOS v0.1: reproducible fictional continent, physically informed climate, hydrology, hazards.

Not a numerical weather prediction / general circulation model.
Requires: numpy, scipy, matplotlib. Run: python worldgen.py --output ./output --seed 2000
"""
from __future__ import annotations
import argparse
import heapq
import json
import math
from collections import deque
from pathlib import Path
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter, distance_transform_edt

W, H = 72, 54
R_KM = 34.0
CELL_AREA_KM2 = (3 * np.sqrt(3) / 2) * R_KM ** 2
DIR_EVEN = [(1,0),(0,-1),(-1,-1),(-1,0),(-1,1),(0,1)]
DIR_ODD = [(1,0),(1,-1),(0,-1),(-1,0),(0,1),(1,1)]
BIOME_COLORS = {
    'ocean':'#286486', 'alpine':'#a5abb6', 'tundra':'#adb6a2',
    'desert':'#ddb777','steppe':'#c7bc83','savanna':'#a5bd70',
    'grassland':'#8db579','forest':'#488b6c','rainforest':'#267559',
    'wetland':'#73a897'
}
POLITIES = [
    {'id':'ELAR','name':'埃兰河谷城邦联盟','type':'river_valley','government':'河谷城邦联盟','description':'依赖季节性河流泛滥与灌溉的粮食核心区；政治组织为若干城邦的盟约','population':37000},
    {'id':'MARIS','name':'玛瑞斯海湾城邦','type':'maritime','government':'沿海港口城邦','description':'依靠海湾贸易、渔业与沿海耕地的商贸聚落','population':21000},
    {'id':'VAYR','name':'维尔山麓诸侯','type':'highland','government':'山麓领主联盟','description':'控制山间谷地和浅层矿脉，冶金发展较快但农田有限','population':15500},
    {'id':'SAHAR','name':'萨赫尔河岸王国','type':'semiarid','government':'河岸灌溉王权','description':'在干旱边缘沿常流河布置灌溉田与聚落，依赖水利管理','population':28000},
]

def neighbors(x,y,w=W,h=H):
    for dx,dy in (DIR_ODD if y & 1 else DIR_EVEN):
        xx,yy=x+dx,y+dy
        if 0<=xx<w and 0<=yy<h:
            yield xx, yy

def hex_distance(a,b):
    x,y=a; x2,y2=b
    q=x-(y-(y&1))//2; q2=x2-(y2-(y2&1))//2
    dq=q-q2; dr=y-y2
    return (abs(dq)+abs(dr)+abs(dq+dr))//2

def smooth_noise(rng,h,w,sy,sx):
    from scipy.ndimage import zoom
    a=rng.normal(size=(sy,sx))
    b=zoom(a,(h/sy,w/sx),order=3)
    b=b[:h,:w]
    return (b-b.mean())/max(b.std(),1e-6)

def gen_base(seed):
    rng=np.random.default_rng(seed)
    Y,X=np.mgrid[0:H,0:W].astype(float)
    X=(X+(Y%2)*.5)/(W-.5); Y=Y/(H-1)
    lat=51.0 - Y*43.0
    n1=smooth_noise(rng,H,W,7,9)
    n2=smooth_noise(rng,H,W,15,18)
    n3=smooth_noise(rng,H,W,27,35)
    # Broad cratonic interior with gulfs and irregular coastal peninsulas.
    continental=(1.42*np.exp(-((abs((X-.49)/.45)**3.6)+(abs((Y-.49)/.54)**3.3)))
                +.23*np.exp(-(((X-.69)/.17)**2+((Y-.79)/.17)**2))
                -.30*np.exp(-(((X-.82)/.12)**2+((Y-.44)/.19)**2))
                +.16*n1+.075*n2+.035*n3)
    land=continental>.69
    # Simulated ocean beyond every map edge (no artificial edge-only continents).
    land[0,:]=False; land[-1,:]=False; land[:,0]=False; land[:,-1]=False
    main_ridge_x=.286+.057*np.sin(4.8*Y+0.2)
    west_ridge=np.exp(-((X-main_ridge_x)/.046)**2)*np.exp(-((Y-.47)/.34)**6)
    interior_x=.52+.22*(.56-Y)
    interior_ridge=np.exp(-((X-interior_x)/.035)**2)*np.exp(-((Y-.73)/.21)**4)
    upland=np.exp(-(((X-.53)/.17)**2+((Y-.32)/.18)**2))
    elev=(np.maximum(continental-.69,0)*820 + 2830*west_ridge
          + 1640*interior_ridge + 530*upland+130*np.maximum(n3,0))
    elev=np.where(land,elev,-(100+1400*np.maximum(.69-continental,0)))
    # Crude boundary / fault field; active arc approximates west ridge.
    fault=np.exp(-((X-main_ridge_x)/.065)**2)*np.exp(-((Y-.46)/.37)**6)
    fault=np.where(land,np.clip(fault,0,1),0)
    return rng,X,Y,lat,land,elev,fault,west_ridge

def gen_climate(rng,lat,land,elev):
    # Maritime / continental moderation. East-west moisture carriage in simplified
    # Hadley/trade wind and mid-latitude westerly regimes.
    dist_ocean=distance_transform_edt(land)*R_KM*1.7
    inland=np.minimum(dist_ocean/1000,1)
    tmean=30.8-.53*lat-.0060*np.maximum(elev,0)+.8*inland
    amp=1.2 + 7.2*lat/51 + 4.2*inland
    mtemp=np.stack([tmean-amp*np.cos(2*np.pi*m/12) for m in range(12)])
    # Broad latitude precipitation: ITCZ, subtropical dry belt, westerly storm belt.
    target=(520+970*np.exp(-((lat-11)/11)**2)
            +660*np.exp(-((lat-47)/12)**2)-390*np.exp(-((lat-28)/9)**2))
    p=np.zeros_like(elev)
    for y in range(H):
        order=range(W) if float(lat[y,0])>=29 else range(W-1,-1,-1)
        humidity=1.0; prev_h=0
        for x in order:
            if not land[y,x]:
                humidity=1.0;prev_h=0
                p[y,x]=max(900,target[y,x])
                continue
            z=max(float(elev[y,x]),0)
            uplift=max(0,z-prev_h)
            precip=(max(130,target[y,x])*(0.24+0.87*humidity)
                    *(1+1.5*min(uplift/1200,1.5)))
            p[y,x]=precip
            humidity=max(.22,humidity*.94-0.12*min(uplift/900,1))
            if z<prev_h-500:
                humidity=max(.22,humidity-.05)
            prev_h=z
    # Smoothed regional precipitation microstructure, including leeward drying.
    p *= np.clip(1+.13*gaussian_filter(rng.normal(size=(H,W)),sigma=2.0),.7,1.4)
    p=np.clip(p,70,3300)
    # Seasonal rainfall: summer monsoon at low latitudes, winter storms at high latitudes.
    monthly=[]
    for m in range(12):
        if m<12:
            # month 0 January, 6 July
            summer=np.cos(2*np.pi*(m-6)/12)
            lowlat=np.clip((32-lat)/20,0,1)
            winter=1-lowlat
            seas=(1+.59*lowlat*summer-.34*winter*summer)
            monthly.append(p/12*np.maximum(.14,seas))
    monthly=np.stack(monthly)
    monthly*=p/np.maximum(monthly.sum(axis=0),1)
    # Simplified biome classes: water availability, temperature and alpine climate.
    biome=np.full((H,W),'grassland',dtype=object)
    biome[~land]='ocean'
    dry_idx=p/np.maximum(250+18*np.maximum(tmean,0),1)
    biome[land & (dry_idx<.42)]='desert'
    biome[land & (dry_idx>=.42) & (dry_idx<.86)]='steppe'
    biome[land & (dry_idx>=.86) & (p<930)]='grassland'
    biome[land & (dry_idx>=.86) & (p>=930)]='forest'
    biome[land & (tmean>22) & (p>=950) & (p<1550)]='savanna'
    biome[land & (tmean>22) & (p>=1550)]='rainforest'
    biome[land & (tmean<3) & (elev<1800)]='tundra'
    biome[land & ((elev>2650)|(tmean<-4))]='alpine'
    return p,tmean,mtemp,monthly,biome,dist_ocean

def gen_hydrology(land,elev,p):
    # Priority flood ensures every flow path terminates in ocean; artificially
    # fills local pits to spill elevation. Tracks a parent for each land tile.
    visited=np.zeros((H,W),bool)
    fill=elev.copy(); parent=np.full((H,W,2),-1,int)
    heap=[]; order=[]
    for y in range(H):
        for x in range(W):
            if not land[y,x]:
                visited[y,x]=True
                heapq.heappush(heap,(float(elev[y,x]),y,x))
    while heap:
        level,y,x=heapq.heappop(heap)
        for nx,ny in neighbors(x,y):
            if visited[ny,nx]:continue
            visited[ny,nx]=True
            fill[ny,nx]=max(float(elev[ny,nx]),level+1e-4)
            parent[ny,nx]=[x,y]
            heapq.heappush(heap,(float(fill[ny,nx]),ny,nx))
            order.append((nx,ny))
    # Approx annual runoff: precipitation minus evapotranspiration and infiltration.
    local=np.where(land,np.maximum(p-310,20)/1000*CELL_AREA_KM2*1e6*.36,0)
    flow=local.copy(); basin=np.where(land,1,0).astype(int)
    for x,y in reversed(order):
        px,py=parent[y,x]
        if px<0:continue
        flow[py,px]+=flow[y,x]; basin[py,px]+=basin[y,x]
    # Channel headwater threshold 17 upstream cells; meanders not modeled.
    river=land & (basin>=17) & (elev<3300)
    # Slope is max gradient to immediate neighboring tile, in km/km
    slope=np.zeros((H,W))
    for y in range(H):
        for x in range(W):
            slope[y,x]=max([abs(float(elev[y,x])-float(elev[ny,nx]))/(R_KM*1.732*1000) for nx,ny in neighbors(x,y)] or [0])
    return parent,flow,basin,river,slope

def gen_hazards(land,elev,fault,biome,p,tmean,lat,river,basin,slope,dist_ocean):
    # The following are relative exposure indices, NOT calibrated return periods.
    wetness=np.clip(p/1500,0,1)
    flat=np.exp(-slope*19)
    flood=np.clip((np.log1p(basin)/np.log(180))*flat*wetness*1.1,0,1)
    flood*=np.where(river,1,0.42)
    flood=np.where(land,flood,0)
    drought=np.where(land,np.clip((950-p)/780,0,1)*np.clip((tmean+2)/30,.2,1),0)
    coast=land & (dist_ocean<R_KM*2.5)
    cyclone=np.where(coast & (lat<30) & (lat>8),np.clip((30-lat)/22,0,1)*.72,0)
    wildfire=np.where(land & np.isin(biome,['forest','savanna','grassland','steppe']),
                      np.clip((1100-p)/750,0,1)*np.clip((tmean+5)/33,0,1),0)
    earthquake=np.clip(.06+.86*fault,0,1)*land
    # Volcanic arc along active tectonic belt: deterministic point sources, geological not meteorological.
    eruption=np.zeros((H,W))
    fault_candidates=np.argwhere(land & (fault>.64) & (elev>1200))
    if len(fault_candidates):
        for idx in np.linspace(0,len(fault_candidates)-1,min(5,len(fault_candidates)),dtype=int):
            yy,xx=fault_candidates[idx]
            yyarr,xxarr=np.mgrid[:H,:W]
            eruption=np.maximum(eruption,np.exp(-(((xxarr-xx)/4.3)**2+((yyarr-yy)/4.3)**2)))
    eruption*=fault*land
    return {'flood':flood,'drought':drought,'earthquake':earthquake,'volcano':eruption,
            'wildfire':wildfire,'cyclone':cyclone}

def pick_polities(land,elev,biome,p,tmean,river,basin,slope,dist_ocean,hazards,lat):
    # Site choices are derived from geographical suitability; distinct ecological
    # niches prevent the four founding states having nearly identical conditions.
    near_river=distance_transform_edt(~river)
    soil=np.clip((p-220)/950,0,1)*np.clip((1900-p)/750,.2,1)
    safe=1-.34*hazards['earthquake']-.26*hazards['flood']-.2*hazards['drought']
    arable=np.isin(biome,['grassland','forest','savanna','steppe','wetland'])
    base=soil*2+safe+1/(1+near_river)+.35*(1-slope)
    specs=[
      (land & arable & (elev<750) & (lat>19)&(lat<43)&(near_river<3)&(dist_ocean>120),
       base+.65*np.clip(np.log1p(basin)/7,0,1)+.4*(p>650)+.2*np.clip(dist_ocean/300,0,1)),
      (land & (dist_ocean<100) & (elev<600) & (p>480)&(lat>23)&(lat<45),
       base+1.6*np.clip((100-dist_ocean)/100,0,1)-hazards['earthquake']),
      (land & (elev>650)&(elev<1800)&(p>420)&(tmean>6)&(lat>25)&(lat<51),
       base+.8*np.clip(elev/1800,0,1)+.5*hazards['earthquake']),
      (land & (p>=180)&(p<590)&(lat>13)&(lat<41)&(near_river<3)&(dist_ocean>110),
       base+1.1*np.clip((750-p)/600,0,1)+.6*np.log1p(basin)/7),
    ]
    placed=[]; used=np.zeros((H,W),bool)
    for i,(valid,score) in enumerate(specs):
        loc=None
        for minimum_sep in (13,10,7,4):
            scores=np.where(valid,score,-1e8).copy()
            for xx,yy in placed:
                for y in range(H):
                    for x in range(W):
                        if hex_distance((x,y),(xx,yy))<minimum_sep:scores[y,x]=-1e8
            scores[used]=-1e8
            y,x=np.unravel_index(np.argmax(scores),scores.shape)
            if scores[y,x]>-1e6:
                loc=(int(x),int(y));break
        if loc is None:raise RuntimeError(f'No usable capital for {POLITIES[i]["id"]}')
        placed.append(loc)
        for y in range(H):
            for x in range(W):
                if hex_distance((x,y),loc)<=3:used[y,x]=True
    # Early Bronze Age states own compact cores, not the entire continent.
    ownership=np.full((H,W),'',dtype=object)
    results=[]
    for i,(capital,info) in enumerate(zip(placed,POLITIES)):
        x0,y0=capital
        area=[]
        for y in range(H):
            for x in range(W):
                d=hex_distance((x,y),capital)
                if land[y,x] and d<=2 and ownership[y,x]=='':
                    ownership[y,x]=info['id'];area.append([x,y])
        row=dict(info)
        row.update(capital={'col':x0,'row':y0,'q':x0-(y0-(y0&1))//2,'r':y0},
                   initial_tiles=area,
                   territorial_area_km2=round(len(area)*CELL_AREA_KM2),
                   avg_annual_temp_c=round(float(tmean[y0,x0]),1),
                   avg_annual_precip_mm=round(float(p[y0,x0])),
                   elevation_m=round(float(elev[y0,x0])),
                   river_distance_tiles=round(float(near_river[y0,x0]),1),
                   dominant_biome=str(biome[y0,x0]),
                   technology={'agriculture':1,'bronze_metallurgy':(2 if i==2 else 1),
                               'writing':int(i in (0,3))},
                   treasury_units=100,food_storage_units=160,
                   diplomatic_status='no_contact')
        results.append(row)
    return results,ownership

def weather_day(rng,day,monthly_rain,monthly_temp,land,weather_anomaly):
    # Spatially-correlated AR(1) synoptic weather proxy, on top of monthly means.
    noise=gaussian_filter(rng.normal(size=(H,W)),sigma=2.0)
    noise=noise/max(noise.std(),1e-6)
    a=.86*weather_anomaly+.14*noise
    # Standard 365-day year, with 31/28/31/... day months.
    mdays=[31,28,31,30,31,30,31,31,30,31,30,31]
    d=day%365
    m=next(m for m,cutoff in enumerate(np.cumsum(mdays)) if d<cutoff)
    rainy_chance=np.clip(.34+monthly_rain[m]/400, .23,.69)
    wet=rng.random((H,W))<np.clip(rainy_chance+0.11*a,.10,.87)
    rain=(monthly_rain[m]/30)*wet/np.maximum(rainy_chance,.08)*np.exp(.25*np.clip(a,-2,2))
    temp=monthly_temp[m]+1.8*a+1.2*rng.normal(size=(H,W))
    snow=land & (temp<0) & (rain>0)
    return a,rain,temp,snow

def demo_weather_hazards(seed,land,monthly_rain,monthly_temp,hazards,polities):
    rng=np.random.default_rng(seed+91)
    a=np.zeros((H,W)); samples=[]; events=[]
    capital_lookup={p['id']:(p['capital']['row'],p['capital']['col']) for p in polities}
    recent_dry={k:0 for k in capital_lookup}
    # 360 days is illustrative climate variability, not an observational hindcast.
    mdays=[31,28,31,30,31,30,31,31,30,31,30,31]
    month_start=np.cumsum([0]+mdays)
    for day in range(365):
        a,rain,temp,snow=weather_day(rng,day,monthly_rain,monthly_temp,land,a)
        if day in (0,90,181,273,364):
            month=int(np.searchsorted(month_start,day,side='right'))
            samples.append({'day':day+1,'month':month,'capital_weather':{
                k:{'temperature_c':round(float(temp[y,x]),1),
                   'precipitation_mm':round(float(rain[y,x]),1),
                   'snow':bool(snow[y,x])}
                for k,(y,x) in capital_lookup.items()}})
        if day+1 in month_start[1:]:
            month=int(np.searchsorted(month_start,day,side='right'))
            for k,(y,x) in capital_lookup.items():
                # Weather-sensitive exposure is observed at capitals; event generation
                # avoids mechanically producing a disaster at every high-risk tile.
                dry=float(hazards['drought'][y,x])
                flood=float(hazards['flood'][y,x])
                quake=float(hazards['earthquake'][y,x])
                fire=float(hazards['wildfire'][y,x])
                risk_by_type={'洪涝':.014*flood,'干旱':.012*dry,
                              '地震':.004*quake,'野火':.006*fire}
                for typ,chance in risk_by_type.items():
                    if rng.random()<chance:
                        events.append({'day':day+1,'month':month,'polity_id':k,'type':typ,
                                       'relative_severity':round(float(rng.uniform(.15,.65)),2)})
    return samples,events

def package_world(seed,land,elev,lat,biome,p,tmean,monthly_rain,monthly_temp,parent,flow,basin,river,slope,hazards,polities,ownership,weather_samples,events):
    # Compact self-contained JSON, with a single tile object per hex.
    tiles=[]
    for y in range(H):
        for x in range(W):
            px,py=parent[y,x]
            tiles.append({'q':x-(y-(y&1))//2,'r':y,'col':x,'row':y,
                          'latitude_deg':round(float(lat[y,x]),2),
                          'land':bool(land[y,x]),'elevation_m':int(round(float(elev[y,x]))),
                          'biome':str(biome[y,x]),
                          'annual_mean_temp_c':round(float(tmean[y,x]),1),
                          'annual_precip_mm':int(round(float(p[y,x]))),
                          'monthly_temp_c':[round(float(v),1) for v in monthly_temp[:,y,x]],
                          'monthly_precip_mm':[round(float(v),1) for v in monthly_rain[:,y,x]],
                          'slope':round(float(slope[y,x]),4),
                          'river':bool(river[y,x]),'drainage_area_km2':int(basin[y,x]*CELL_AREA_KM2),
                          'downstream':{'col':int(px),'row':int(py)} if land[y,x] and px>=0 else None,
                          'hazards':{k:round(float(hazards[k][y,x]),3) for k in hazards},
                          'owner_id':str(ownership[y,x]) or None})
    return {'metadata':{'project':'Project Eos','version':'0.1.0','world_name':'埃欧斯大陆 / Eos Continent',
            'seed':seed,'world_year_bce':2000,'astronomical_year':-1999,'start_month':1,'day_count':0,
            'grid_type':'odd-r pointy-top hex','grid_width':W,'grid_height':H,
            'hex_radius_km':R_KM,'cell_area_km2':round(CELL_AREA_KM2,1),
            'assumed_planet':'Earth-like, 24h day, 365-day year, Northern Hemisphere',
            'latitude_range_deg':[8,51],
            'model_limitations':['not a general circulation model or weather forecast',
                'no physical plate dynamics / calibrated hazard return periods',
                'synthetic tectonic belts and monthly precipitation with stochastic daily perturbations',
                'sea level and orbital forcing fixed at initial epoch']},
            'world_summary':{'land_hexes':int(land.sum()),'ocean_hexes':int((~land).sum()),
                'land_area_km2':round(float(land.sum()*CELL_AREA_KM2)),
                'maximum_elevation_m':round(float(np.max(elev))),
                'river_hexes':int(river.sum()),
                'unclaimed_land_hexes':int(np.count_nonzero(land & (ownership=='')))},
            'polities':polities,'tiles':tiles,'weather_samples':weather_samples,
            'illustrative_hazard_events':events}

def plot_maps(out,land,elev,biome,p,river,parent,polities,hazards):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import Normalize
    from matplotlib.cm import ScalarMappable
    from matplotlib import font_manager
    font_manager.fontManager.addfont('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    plt.rcParams['font.family']='Noto Sans CJK JP'
    plt.rcParams['font.sans-serif']=['Noto Sans CJK JP','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    hexrad=1
    centers=np.zeros((H,W,2))
    vertices=[]
    for y in range(H):
        for x in range(W):
            cx=np.sqrt(3)*(x+.5*(y&1));cy=1.5*y
            centers[y,x]=[cx,cy]
            verts=[(cx+math.cos(math.radians(60*i-30)),cy+math.sin(math.radians(60*i-30))) for i in range(6)]
            vertices.append(verts)
    # note y coordinates grow toward south, render with inverted axis.
    def canvas(title,colors,river_overlay=True):
        fig,ax=plt.subplots(figsize=(17,12),dpi=160,facecolor='#f4f0e6')
        ax.set_facecolor('#f4f0e6')
        pc=PolyCollection(vertices,facecolors=colors,edgecolors=(.12,.24,.30,.12),linewidths=.18)
        ax.add_collection(pc)
        if river_overlay:
            for y in range(H):
                for x in range(W):
                    if not river[y,x]:continue
                    px,py=parent[y,x]
                    if px<0:continue
                    p0=centers[y,x];p1=centers[py,px]
                    ax.plot([p0[0],p1[0]],[p0[1],p1[1]],color='#3f98ce',lw=1.0,alpha=.92,zorder=3)
        ncolors=['#e8b365','#63a8b6','#cd817c','#b887c5']
        for i,poli in enumerate(polities):
            cp=poli['capital']; x=cp['col'];y=cp['row'];cx,cy=centers[y,x]
            for tx,ty in poli['initial_tiles']:
                txc,tyc=centers[ty,tx]
                ax.scatter([txc],[tyc],s=32,marker='h',facecolor=ncolors[i],edgecolor='#202e32',linewidth=.45,zorder=4)
            ax.scatter([cx],[cy],marker='*',s=170,c=ncolors[i],edgecolors='black',linewidth=.75,zorder=7)
            ox=8 if x<W/2 else -8
            ha='left' if ox>0 else 'right'
            ax.annotate(poli['name'],(cx,cy),xytext=(ox,(-12 if i%2 else 14)),textcoords='offset points',
                fontsize=11,fontweight='bold',color='#192d38',ha=ha,va='center',zorder=9,
                bbox=dict(facecolor='#fffaf0',alpha=.84,boxstyle='round,pad=.24',edgecolor='none'))
        ax.set_xlim(-2,np.sqrt(3)*(W+1));ax.set_ylim(1.5*(H+1),-2)
        ax.set_aspect('equal');ax.axis('off')
        ax.set_title(title,fontsize=21,fontweight='bold',pad=18,color='#172c3b')
        return fig,ax
    cols=[BIOME_COLORS[str(biome[y,x])] for y in range(H) for x in range(W)]
    fig,ax=canvas('埃欧斯大陆 · 公元前 2000 年 · 地形、生物群系与早期国家',cols)
    fig.text(.05,.045,'六边形尺度：半径 34 km  |  蓝线：主要河流  |  ★：初始都城  |  彩色六边形：国家核心领土',size=11,color='#304852')
    fig.savefig(out/'world_map.png',bbox_inches='tight',pad_inches=.22);plt.close(fig)
    norm=Normalize(vmin=0,vmax=2200)
    cm=plt.get_cmap('YlGnBu')
    cols=[cm(norm(p[y,x])) if land[y,x] else (.15,.37,.52,1) for y in range(H) for x in range(W)]
    fig,ax=canvas('埃欧斯大陆 · 年均降水量（毫米）',cols)
    cbar=fig.colorbar(ScalarMappable(norm=norm,cmap=cm),ax=ax,fraction=.025,pad=.02,shrink=.62)
    cbar.set_label('mm / year')
    fig.savefig(out/'rainfall_map.png',bbox_inches='tight',pad_inches=.22);plt.close(fig)
    norm=Normalize(vmin=0,vmax=1)
    cm=plt.get_cmap('OrRd')
    composite=np.maximum.reduce([hazards[k]*w for k,w in [('earthquake',1),('flood',1),('drought',1),('wildfire',.9),('cyclone',.9),('volcano',1)]])
    cols=[cm(norm(composite[y,x])) if land[y,x] else (.15,.37,.52,1) for y in range(H) for x in range(W)]
    fig,ax=canvas('埃欧斯大陆 · 综合自然灾害暴露指数（相对值）',cols,False)
    cbar=fig.colorbar(ScalarMappable(norm=norm,cmap=cm),ax=ax,fraction=.025,pad=.02,shrink=.62)
    cbar.set_label('Relative hazard exposure 0–1')
    fig.savefig(out/'hazard_map.png',bbox_inches='tight',pad_inches=.22);plt.close(fig)

def validate(world):
    assert len(world['tiles'])==W*H
    assert sum(t['land'] for t in world['tiles'])==world['world_summary']['land_hexes']
    all_occupied=set()
    for poli in world['polities']:
        assert poli['initial_tiles']
        capital=(poli['capital']['col'],poli['capital']['row'])
        assert capital in [tuple(c) for c in poli['initial_tiles']]
        for c in poli['initial_tiles']:
            assert tuple(c) not in all_occupied, 'overlapping states'
            all_occupied.add(tuple(c))
    tiles={(t['col'],t['row']):t for t in world['tiles']}
    for t in world['tiles']:
        if not t['land']:continue
        cur=t;seen=set()
        for i in range(W*H):
            key=(cur['col'],cur['row'])
            assert key not in seen,'river drainage loop'
            seen.add(key)
            dest=cur['downstream']
            assert dest is not None,'land not connected to downstream'
            nxt=tiles[(dest['col'],dest['row'])]
            assert hex_distance(key,(nxt['col'],nxt['row']))==1, 'nonlocal river flow'
            if not nxt['land']:break
            cur=nxt
        else:raise AssertionError('drainage not reaching sea')
    return True

def generate(out:Path, seed:int):
    out.mkdir(parents=True,exist_ok=True)
    rng,X,Y,lat,land,elev,fault,ridge=gen_base(seed)
    p,tmean,monthly_temp,monthly_rain,biome,dist_ocean=gen_climate(rng,lat,land,elev)
    parent,flow,basin,river,slope=gen_hydrology(land,elev,p)
    hazards=gen_hazards(land,elev,fault,biome,p,tmean,lat,river,basin,slope,dist_ocean)
    polities,ownership=pick_polities(land,elev,biome,p,tmean,river,basin,slope,dist_ocean,hazards,lat)
    weather_samples,events=demo_weather_hazards(seed,land,monthly_rain,monthly_temp,hazards,polities)
    world=package_world(seed,land,elev,lat,biome,p,tmean,monthly_rain,monthly_temp,parent,flow,basin,river,slope,hazards,polities,ownership,weather_samples,events)
    validate(world)
    (out/'world_2000BCE.json').write_text(json.dumps(world,ensure_ascii=False,indent=1),encoding='utf-8')
    plot_maps(out,land,elev,biome,p,river,parent,polities,hazards)
    summary={k:v for k,v in world.items() if k!='tiles'}
    (out/'world_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'seed':seed,**world['world_summary'],
          'polities':[{k:p[k] for k in ('name','capital','dominant_biome','avg_annual_precip_mm','territorial_area_km2')} for p in polities],
          'files':[x.name for x in out.iterdir()]},ensure_ascii=False,indent=2))
    return world

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--seed',type=int,default=2000)
    parser.add_argument('--output',type=Path,default=Path('output'))
    args=parser.parse_args()
    generate(args.output,args.seed)
````

## 附录 — `simulate_climate.py`

````python
"""Run a reproducible year of daily stochastic weather and hazard sampling.

This is a physically informed weather generator conditioned on seasonal climatology,
NOT a scientific forecasting model; hazards are exposure-weighted scenario events.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from worldgen import H,W,weather_day

MONTH_DAYS=[31,28,31,30,31,30,31,31,30,31,30,31]
MONTH_END=np.cumsum(MONTH_DAYS)

def run(world_path:Path,out:Path,seed:int,days:int=365):
    world=json.loads(world_path.read_text(encoding='utf-8'))
    tiles=world['tiles']
    assert len(tiles)==W*H
    land=np.array([t['land'] for t in tiles]).reshape(H,W)
    temp=np.array([t['monthly_temp_c'] for t in tiles]).reshape(H,W,12).transpose(2,0,1)
    rain_norm=np.array([t['monthly_precip_mm'] for t in tiles]).reshape(H,W,12).transpose(2,0,1)
    hazards={typ:np.array([t['hazards'][typ] for t in tiles]).reshape(H,W) for typ in tiles[0]['hazards']}
    owner=np.array([t['owner_id'] or '' for t in tiles],dtype=object).reshape(H,W)
    capitals={p['id']:(p['capital']['row'],p['capital']['col']) for p in world['polities']}
    rng=np.random.default_rng(seed)
    anom=np.zeros((H,W))
    month_rain=np.zeros((H,W));month_temp=np.zeros((H,W));month_days=0
    monthly_results=[];events=[]
    for day in range(days):
        anom,pr,tc,snow=weather_day(rng,day,rain_norm,temp,land,anom)
        month_rain+=pr;month_temp+=tc;month_days+=1
        doy=(day%365)+1
        if doy not in MONTH_END and day!=days-1:continue
        month=int(np.searchsorted(MONTH_END,doy,side='left'))
        observed=month_rain
        expected=rain_norm[month]*(month_days/MONTH_DAYS[month])
        rratio=observed/np.maximum(expected,1.0)
        tavg=month_temp/max(month_days,1)
        summary={'sim_day':day+1,'month':month+1,
            'average_land_temp_c':round(float(tavg[land].mean()),1),
            'average_land_rain_mm':round(float(observed[land].mean()),1),
            'polities':{k:{'temp_c':round(float(tavg[y,x]),1),
                            'rain_mm':round(float(observed[y,x]),1),
                            'expected_rain_mm':round(float(expected[y,x]),1),
                            'rain_anomaly_ratio':round(float(rratio[y,x]),2)}
                         for k,(y,x) in capitals.items()}}
        monthly_results.append(summary)
        # Each type generates possible continental events. Arbitrary relative
        # rates: for a playable prototype, not calibrated historical return periods.
        specs=[('洪水',.85,'flood'),('干旱',.48,'drought'),('地震',.30,'earthquake'),
               ('野火',.38,'wildfire'),('热带气旋',.24 if month in (5,6,7,8,9) else .015,'cyclone'),
               ('火山活动',.027,'volcano')]
        for label,rate,kind in specs:
            risk=hazards[kind]*land
            # Ignore negligible local exposure when drawing named incidents.
            min_exposure={'flood':.16,'drought':.19,'earthquake':.23,
                          'wildfire':.21,'cyclone':.18,'volcano':.25}[kind]
            risk=np.where(risk>=min_exposure,risk,0.0)
            if kind=='flood':risk=risk*np.clip(rratio-.72,0.06,2.0)
            if kind=='drought':risk=risk*np.clip(1.22-rratio,0.06,2.0)
            if kind=='wildfire':risk=risk*np.clip(1.1-rratio,0.1,2)*np.clip((tavg-10)/20,.05,1)
            if kind=='cyclone':risk=risk*np.clip((tavg-18)/11,0,1)
            flat=risk.ravel()
            if flat.sum()<=0:continue
            n=min(int(rng.poisson(rate)),4)
            for _ in range(n):
                idx=int(rng.choice(flat.size,p=flat/flat.sum()))
                y,x=divmod(idx,W)
                events.append({'sim_day':day+1,'month':month+1,'type':label,
                               'hex':{'col':x,'row':y},
                               'risk_index':round(float(hazards[kind][y,x]),3),
                               'severity':round(float(rng.uniform(.15,.88)),2),
                               'affected_polity_id':str(owner[y,x]) or None})
        month_rain.fill(0);month_temp.fill(0);month_days=0
    result={'model':'EOS stochastic weather + hazard exposure sampler v0.1',
            'seed':seed,'days':days,'starts_at':'公元前2000年1月1日（虚构统一历）',
            'notes':['365-day calendar (non-leap baseline)',
                     'synthetic weather, not reconstructed ancient weather',
                     'event rates are illustrative, not historical return periods',
                     'temperature and rain are climate-conditioned stochastic processes'],
            'monthly':monthly_results,'events':events}
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'days':days,'months':len(monthly_results),'events':len(events),
                      'event_types':sorted(set(e['type'] for e in events)),'file':str(out)},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--world',type=Path,default=Path('output/world_2000BCE.json'))
    p.add_argument('--out',type=Path,default=Path('output/first_year_weather.json'))
    p.add_argument('--seed',type=int,default=2000)
    p.add_argument('--days',type=int,default=365)
    args=p.parse_args();run(args.world,args.out,args.seed,args.days)
````

## 附录 — `build_viewer.py`

````python
"""Produce a self-contained, offline-interactive HTML hex map viewer."""
from pathlib import Path
import json

HERE=Path(__file__).resolve().parent
world=json.loads((HERE/'output/world_2000BCE.json').read_text(encoding='utf-8'))
mini={'metadata':world['metadata'],'polities':world['polities'],
      'tiles':[{k:v for k,v in t.items() if k in ('col','row','q','r','land','elevation_m','biome','annual_precip_mm','annual_mean_temp_c','river','hazards','owner_id','drainage_area_km2')} for t in world['tiles']]}
blob=json.dumps(mini,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
html=r'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Project Eos · 大陆观察器</title><style>
:root{color-scheme:dark} *{box-sizing:border-box} body{margin:0;background:#101d29;color:#ecf2f4;font:14px/1.5 system-ui,"Microsoft Yahei",sans-serif}
header{height:70px;padding:12px 22px;border-bottom:1px solid #314252;display:flex;align-items:center;justify-content:space-between;gap:16px}
h1{font-size:20px;letter-spacing:1px;margin:0} header small{color:#a7bec9} .main{display:grid;grid-template-columns:1fr 300px;height:calc(100vh - 70px);min-height:450px}
#stage{position:relative;overflow:hidden;background:#1b3e55;cursor:grab} #stage.grab{cursor:grabbing}canvas{width:100%;height:100%;display:block}
#guide{position:absolute;left:18px;bottom:16px;padding:8px 11px;border-radius:8px;background:#122331d9;color:#dbe8eb;font-size:12px;pointer-events:none}
aside{border-left:1px solid #304151;background:#172734;overflow:auto;padding:18px} h2{font-size:14px;margin:16px 0 9px;color:#d2e5e9}p{color:#afc1ca;margin:4px 0 9px;font-size:12px}
select,button{background:#253b4b;color:white;border:1px solid #455c69;border-radius:7px;padding:9px 10px;width:100%;font:inherit}
.card{margin:10px 0;border:1px solid #354c59;border-radius:10px;padding:11px 12px;background:#203340;min-height:106px}
.kv{display:flex;justify-content:space-between;border-bottom:1px solid #304754;padding:5px 0;gap:10px;font-size:12px}.kv span{color:#a6bcc9}.kv strong{font-weight:500;text-align:right}
.pill{border-radius:5px;padding:3px 7px;background:#304856;font-size:11px;margin-right:4px;display:inline-block}
.country{display:flex;gap:8px;padding:10px 6px;align-items:flex-start;border-bottom:1px solid #304351}.country>i{width:11px;height:11px;flex:none;border-radius:50%;margin-top:5px}.country b{font-size:13px}.country small{display:block;font-size:11px;color:#9eb4bd}
#legend{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.l{display:flex;gap:4px;align-items:center;font-size:11px;color:#a9bdc6}.l i{width:10px;height:10px;border-radius:2px}
@media(max-width:840px){header{height:auto;min-height:70px}.main{display:flex;flex-direction:column;height:auto}#stage{height:65vh;min-height:420px} aside{border-left:0;border-top:1px solid #304151}}
</style></head><body><header><div><h1>PROJECT EOS · 埃欧斯大陆</h1><small>公元前 2000 年 · 初始世界 / 可暂停实时战略模拟基础地图</small></div><div style="text-align:right"><span class="pill">SEED 2000</span><span class="pill">3,888 HEX</span></div></header><div class="main"><div id="stage"><canvas id="map"></canvas><div id="guide">拖动平移 · 滚轮缩放 · 点击地块查看环境数据</div></div><aside><h2>地图图层</h2><select id="layer"><option value="biome">地形与生物群系</option><option value="rain">年均降水量</option><option value="temperature">年均温度</option><option value="elevation">海拔高度</option><option value="hazard">自然灾害综合暴露指数</option><option value="political">国家控制区域</option></select><div id="legend"></div><h2>选中地块</h2><div class="card" id="info">点击六边形查看坐标、气候、地势、河流和灾害风险。</div><h2>初始国家（青铜时代）</h2><div id="countries"></div><p>四国只占据早期聚落核心区，大陆其余地块未被国家占有。</p><button id="reset">重置视角</button><p style="margin-top:16px">气候：纬度、季节性辐射、地形抬升与雨影的简化模型。灾害：相对暴露指数，尚未标定真实重现期。</p></aside></div><script>
const WORLD=__DATA__;
const c=document.getElementById('map'),ctx=c.getContext('2d');const stage=document.getElementById('stage');
const tiles=WORLD.tiles, polities=WORLD.polities;const map=new Map(tiles.map(t=>[t.col+','+t.row,t]));
const colors={ocean:'#286486',alpine:'#acb0b5',tundra:'#b2b8a3',desert:'#ddb777',steppe:'#c7bc83',savanna:'#afc87b',grassland:'#8db579',forest:'#488b6c',rainforest:'#267559',wetland:'#73a897'};
const polColors=['#ebbb6e','#65abc6','#dc877c','#be8bcc'], polityColor=Object.fromEntries(polities.map((p,i)=>[p.id,polColors[i]]));
const cx=t=>Math.sqrt(3)*(t.col+.5*(t.row%2)), cy=t=>1.5*t.row;
let w=1,h=1,s=1,offsetX=0,offsetY=0,mode='biome',active=null,drag=false,lastX=0,lastY=0,moved=false;
function clamp(a,b,v){return Math.max(a,Math.min(b,v))}
function rgb(r,g,b){return `rgb(${Math.round(r)},${Math.round(g)},${Math.round(b)})`}
function ramp(v,stops){v=clamp(0,1,v);const f=v*(stops.length-1),i=Math.min(Math.floor(f),stops.length-2),t=f-i;return rgb(...stops[i].map((n,k)=>n+(stops[i+1][k]-n)*t))}
function maxRisk(t){return Math.max(...Object.values(t.hazards))}
function tileColor(t){if(!t.land)return colors.ocean;if(mode==='political')return polityColor[t.owner_id]||'#8b9b8b';
if(mode==='biome')return colors[t.biome]||'#aaa';
if(mode==='rain')return ramp(t.annual_precip_mm/2400,[[227,195,127],[241,233,163],[116,194,154],[39,136,173],[26,67,116]]);
if(mode==='elevation')return ramp(t.elevation_m/3900,[[125,182,116],[207,188,124],[145,127,102],[154,145,134],[235,232,218]]);
if(mode==='temperature')return ramp((t.annual_mean_temp_c+8)/38,[[76,124,171],[154,191,198],[231,220,136],[220,139,87],[155,78,69]]);
return ramp(maxRisk(t),[[240,233,185],[233,177,118],[207,94,66],[131,37,54]]);}
function fit(){const boundX=Math.sqrt(3)*(WORLD.metadata.grid_width+.5),boundY=1.5*WORLD.metadata.grid_height;
s=Math.min((w-34)/boundX,(h-34)/boundY);offsetX=(w-boundX*s)/2;offsetY=(h-boundY*s)/2;render();}
function size(){let dpr=Math.min(window.devicePixelRatio||1,2);w=stage.clientWidth;h=stage.clientHeight;c.width=w*dpr;c.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);fit()}
function hex(x,y){ctx.beginPath();for(let i=0;i<6;i++){const angle=(60*i-30)*Math.PI/180,xx=x+.98*Math.cos(angle),yy=y+.98*Math.sin(angle);if(!i)ctx.moveTo(xx,yy);else ctx.lineTo(xx,yy)}ctx.closePath()}
function render(){ctx.setTransform(c.width/w,0,0,c.height/h,0,0);ctx.fillStyle='#1c415c';ctx.fillRect(0,0,w,h);ctx.save();ctx.translate(offsetX,offsetY);ctx.scale(s,s);
for(const t of tiles){hex(cx(t),cy(t));ctx.fillStyle=tileColor(t);ctx.fill();}
if(mode!=='political'){ctx.beginPath();for(const t of tiles){if(!t.river)continue;const down=WORLD._flow?.[t.col+','+t.row]; // river routes stored in source world, but optional here
 if(!down)continue;ctx.moveTo(cx(t),cy(t));ctx.lineTo(cx(down),cy(down));}ctx.strokeStyle='#61b5df';ctx.lineWidth=Math.max(.15,1/s);ctx.stroke();}
for(let i=0;i<polities.length;i++){const p=polities[i],t=map.get(p.capital.col+','+p.capital.row);if(!t)continue;const x=cx(t),y=cy(t);ctx.beginPath();ctx.arc(x,y,1.08,0,Math.PI*2);ctx.fillStyle=polColors[i];ctx.fill();ctx.lineWidth=.28;ctx.strokeStyle='#172632';ctx.stroke();ctx.fillStyle='#fff';ctx.font='bold 2px system-ui';ctx.textAlign='center';ctx.fillText('★',x,y+.7);}
if(active){hex(cx(active),cy(active));ctx.strokeStyle='#fff9a8';ctx.lineWidth=.5;ctx.stroke()}
ctx.restore();ctx.textAlign='left';ctx.fillStyle='rgba(20,38,50,.75)';ctx.fillRect(12,12,200,25);ctx.fillStyle='#e8f1f1';ctx.font='12px system-ui';ctx.fillText('大陆比例尺：六边形半径 34 km',20,29);}
function closest(px,py){const x=(px-offsetX)/s,y=(py-offsetY)/s;let best=null,d=1.2;let row=Math.round(y/1.5);for(let yy=row-2;yy<=row+2;yy++){if(yy<0||yy>=WORLD.metadata.grid_height)continue;let col=Math.round(x/Math.sqrt(3)-.5*(yy%2));for(let xx=col-2;xx<=col+2;xx++){let t=map.get(xx+','+yy);if(!t)continue;const dd=Math.hypot(cx(t)-x,cy(t)-y);if(dd<d){best=t;d=dd}}}return best}
const biomes={ocean:'海洋',alpine:'高山',tundra:'冻原',desert:'沙漠',steppe:'半干旱草原',savanna:'稀树草原',grassland:'草原',forest:'温带森林',rainforest:'雨林',wetland:'湿地'};
function show(t){active=t;const country=polities.find(p=>p.id===t.owner_id);document.getElementById('info').innerHTML=`<div class="kv"><span>坐标</span><strong>q=${t.q}, r=${t.r}</strong></div><div class="kv"><span>生物群系</span><strong>${biomes[t.biome]||t.biome}</strong></div><div class="kv"><span>海拔</span><strong>${t.elevation_m} m</strong></div><div class="kv"><span>年均温</span><strong>${t.annual_mean_temp_c} °C</strong></div><div class="kv"><span>年均降水</span><strong>${t.annual_precip_mm} mm</strong></div><div class="kv"><span>地表径流</span><strong>${t.river?'主要河道':'非主要河道'}</strong></div><div class="kv"><span>控制权</span><strong>${country?.name||'无国家控制'}</strong></div><h2>相对自然灾害暴露</h2>${Object.entries(t.hazards).map(([k,v])=>`<div class="kv"><span>${{flood:'洪水',drought:'干旱',earthquake:'地震',volcano:'火山',wildfire:'野火',cyclone:'热带气旋'}[k]}</span><strong>${(v*100).toFixed(1)}%</strong></div>`).join('')}<p>百分比是归一化指数，不是实际发生概率。</p>`;render()}
stage.addEventListener('pointerdown',e=>{drag=true;moved=false;lastX=e.clientX;lastY=e.clientY;stage.classList.add('grab');stage.setPointerCapture(e.pointerId)})
stage.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-lastX,dy=e.clientY-lastY;if(Math.abs(dx)+Math.abs(dy)>1)moved=true;offsetX+=dx;offsetY+=dy;lastX=e.clientX;lastY=e.clientY;render()})
stage.addEventListener('pointerup',e=>{if(!drag)return;drag=false;stage.classList.remove('grab');if(!moved){const rect=stage.getBoundingClientRect();const t=closest(e.clientX-rect.left,e.clientY-rect.top);if(t)show(t)}})
stage.addEventListener('wheel',e=>{e.preventDefault();const rect=stage.getBoundingClientRect(),px=e.clientX-rect.left,py=e.clientY-rect.top,scale=Math.exp(-e.deltaY*.001);const ns=clamp(2,60,s*scale),factor=ns/s;offsetX=px+(offsetX-px)*factor;offsetY=py+(offsetY-py)*factor;s=ns;render()},{passive:false})
const legend=document.getElementById('legend');const legendDict={biome:[['海洋',colors.ocean],['森林',colors.forest],['草原',colors.grassland],['干旱',colors.desert],['高山',colors.alpine]],rain:[['少雨','#e3c37f'],['多雨','#1a4374']],temperature:[['冷','#4c7cab'],['暖','#db8b57']],elevation:[['低','#7db674'],['高','#ebe8da']],hazard:[['低','#f0e9b9'],['高','#832536']],political:polities.map((p,i)=>[p.name,polColors[i]])};
function legendRender(){legend.innerHTML=legendDict[mode].map(([a,b])=>`<div class="l"><i style="background:${b}"></i>${a}</div>`).join('')}
document.getElementById('layer').addEventListener('change',e=>{mode=e.target.value;legendRender();render()});
document.getElementById('reset').addEventListener('click',fit);
document.getElementById('countries').innerHTML=polities.map((p,i)=>`<div class="country"><i style="background:${polColors[i]}"></i><div><b>${p.name}</b><small>${p.government} · ${p.population.toLocaleString()} 人 · ${p.territorial_area_km2.toLocaleString()} km²</small><small>都城 (${p.capital.col},${p.capital.row}) / 年雨量 ${p.avg_annual_precip_mm} mm</small></div></div>`).join('');
window.addEventListener('resize',size);legendRender();size();
</script></body></html>'''
# Make river flow visible in viewer through a small lookup map.
mini_flow={str(t['col'])+','+str(t['row']):t['downstream'] for t in world['tiles'] if t['river'] and t['downstream']}
# Keep rivers included in a second mapping; use object IDs of target tile.
viewer_data=mini
viewer_data['_flow']={k:{'col':v['col'],'row':v['row']} for k,v in mini_flow.items()}
blob=json.dumps(viewer_data,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
html=html.replace('__DATA__',blob)
(HERE/'output/viewer.html').write_text(html,encoding='utf-8')
print('viewer.html',len(html),'characters')
````

## 附录 — `plot_elevation.py`

````python
"""Plot an elevation layer from the existing world_2000BCE.json.

This add-on script does not alter the original world data or its generator.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.colors import LightSource, Normalize
from matplotlib.cm import ScalarMappable


def generate(world_path: Path, output_path: Path) -> None:
    world = json.loads(world_path.read_text(encoding="utf-8"))
    tiles = world["tiles"]
    polygons, colors = [], []
    cmap = plt.get_cmap("terrain")
    norm = Normalize(vmin=0, vmax=4000)
    for t in tiles:
        x, y = t["col"], t["row"]
        cx = math.sqrt(3) * (x + 0.5*(y % 2))
        cy = 1.5*y
        polygons.append([
            (cx + math.cos(math.radians(i*60-30)),
             cy + math.sin(math.radians(i*60-30))) for i in range(6)])
        colors.append(cmap(norm(max(t["elevation_m"], 0))) if t["land"] else (0.13,0.33,0.49,1))
    fig, ax = plt.subplots(figsize=(17,12), dpi=150)
    ax.add_collection(PolyCollection(polygons, facecolors=colors, edgecolors=(.1,.2,.3,.13), linewidths=.15))
    ax.set_xlim(-2, math.sqrt(3)*(world["metadata"]["grid_width"]+1))
    ax.set_ylim(1.5*(world["metadata"]["grid_height"]+1), -2)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Project Eos | Elevation map (m)", fontsize=17)
    bar = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, fraction=.025, pad=.02, shrink=.66)
    bar.set_label("Elevation (m)")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", pad_inches=.2)
    plt.close(fig)

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--world", type=Path, default=Path("output/world_2000BCE.json"))
    parser.add_argument("--out", type=Path, default=Path("output/elevation_map.png"))
    args=parser.parse_args()
    generate(args.world, args.out)
````

## 附录 — `tests/test_generated_world.py`

````python
import json
from pathlib import Path
import numpy as np
from worldgen import W,H,hex_distance,validate

DIR=Path(__file__).resolve().parents[1]
WORLD=json.loads((DIR/'output/world_2000BCE.json').read_text(encoding='utf8'))
WEATHER=json.loads((DIR/'output/first_year_weather.json').read_text(encoding='utf8'))

def test_world_integrity():
    assert validate(WORLD)
    assert len(WORLD['polities'])==4
    assert 1500<WORLD['world_summary']['land_hexes']<3400
    assert WORLD['metadata']['world_year_bce']==2000
    assert WORLD['metadata']['astronomical_year']==-1999

def test_seasonality_risk_and_terrain():
    t=WORLD['tiles']
    assert len(t)==W*H
    assert all(len(x['monthly_temp_c'])==len(x['monthly_precip_mm'])==12 for x in t)
    assert all(0<=v<=1 for x in t for v in x['hazards'].values())
    assert all(abs(sum(x['monthly_precip_mm'])-x['annual_precip_mm'])<=2 for x in t)
    assert all(abs(sum(x['monthly_temp_c'])/12-x['annual_mean_temp_c'])<=.5 for x in t)
    assert any(x['biome']=='alpine' for x in t)
    assert any(x['biome']=='desert' for x in t)
    assert any(x['biome']=='forest' for x in t)

def test_polities_are_land_connected():
    t={(v['col'],v['row']):v for v in WORLD['tiles']}
    for p in WORLD['polities']:
        coords={tuple(x) for x in p['initial_tiles']}
        cp=(p['capital']['col'],p['capital']['row'])
        assert cp in coords and len(coords)>=8
        assert all(t[c]['land'] for c in coords)
        seen={cp}
        while True:
            nxt={x for x in coords if x not in seen and any(hex_distance(x,y)==1 for y in seen)}
            if not nxt: break
            seen|=nxt
        assert seen==coords, (p['id'],'non-contiguous polity core')

def test_year_2000_bce_weather():
    assert WEATHER['days']==365
    assert len(WEATHER['monthly'])==12
    assert WEATHER['monthly'][-1]['sim_day']==365
    for event in WEATHER['events']:
        assert 0<=event['hex']['col']<W
        assert 0<=event['hex']['row']<H
        assert 0<=event['risk_index']<=1
````

## 附录 — `requirements.txt`

````text
numpy>=1.24
scipy>=1.10
matplotlib>=3.7
````
