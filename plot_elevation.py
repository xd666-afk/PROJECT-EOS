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
