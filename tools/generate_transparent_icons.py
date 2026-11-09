"""Generate Project Eos facility icons through the local GPT Image Studio config.

The studio stores its OfoxAI key in settings.json. This script reads that file
directly, keeps the key only in process memory, and never prints it.

Outputs:
    assets/raw/transparent/<key>_raw.png   original 1024px generation
    assets/icons/<key>.png                 trimmed 320px transparent icon
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "assets" / "raw" / "transparent"
ICON_DIR = ROOT / "assets" / "icons"
SETTINGS_PATH = Path(
    os.environ.get(
        "GPT_IMAGE_STUDIO_SETTINGS",
        r"C:\Users\XD\Documents\GPT Image Studio\settings.json",
    )
)

STYLE = (
    "single isolated realistic micro-isometric game asset, compact floating diorama, "
    "high three-quarter view, studio lighting, crisp detail, earthy natural palette, "
    "centered composition with generous empty margin, no ground plane, no cast shadow, "
    "no frame, no card, no border, no text, no people. "
    "Transparent background: the object must be fully cut out with clean edges."
)

ICONS = {
    "farm": (
        "terraced farmland diorama with young golden wheat, green grass and a narrow "
        "stone-lined irrigation channel, dark rich soil cross-section sides"
    ),
    "mine": (
        "small copper and iron surface mine diorama, timber headframe, ore carts, exposed "
        "rock terraces and a few turquoise mineral veins, dark soil sides"
    ),
    "granary": (
        "early bronze age granary diorama, round clay storage silos with thatched caps, "
        "wooden ladders and grain sacks on a compact earth platform"
    ),
    "irrigation": (
        "ancient irrigation gate diorama, wooden sluice gate and stone canal lock with "
        "flowing water, reeds and packed earth banks"
    ),
    "workshop": (
        "bronze age artisan workshop diorama, open timber shed with anvil, clay forge, "
        "copper ingots and tools on a compact stone platform"
    ),
    "library": (
        "early library diorama, small mud-brick archive with clay tablets on shelves, "
        "open doorway and rolled scrolls, warm lamplight"
    ),
    "market": (
        "ancient market stall diorama, wooden awning, baskets of grain, pottery and cloth, "
        "coins and amphorae on a compact stone plaza"
    ),
    "temple": (
        "early temple diorama, stepped stone shrine with carved pillars, offering bowl and "
        "small eternal flame, weathered limestone"
    ),
    "great_granary": (
        "wonder-scale great granary diorama, massive tiered clay silos with bronze bands, "
        "wide stairs and grain carts, monumental but compact"
    ),
    "great_forge": (
        "wonder-scale great forge diorama, monumental bronze furnace with tall chimney, "
        "glowing crucible, massive anvil and timber crane"
    ),
    "great_library": (
        "wonder-scale great library diorama, grand mud-brick archive with arched entry, "
        "tall clay-tablet shelves and bronze braziers, scholarly monument"
    ),
}


def load_settings() -> dict:
    if not SETTINGS_PATH.is_file():
        raise SystemExit(f"找不到 GPT Image Studio 配置：{SETTINGS_PATH}")
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    key = str(data.get("apiKey") or "")
    if not key.isascii():
        # The studio may keep a localized display string in settings; the real
        # provider key lives in the configured key-source file. The stored path
        # can contain mojibake, so fall back to a search under the same drive.
        source = Path(str(data.get("keySource") or ""))
        candidates = [source] if source.is_file() else []
        if not candidates:
            for root in {Path("D:/AI picture"), Path(f"{source.drive}/AI picture")}:
                if root.is_dir():
                    candidates.extend(root.glob("**/api_providers.json"))
        for candidate in candidates[:8]:
            try:
                providers = json.loads(candidate.read_text(encoding="utf-8")).get("providers", [])
            except (OSError, json.JSONDecodeError):
                continue
            for provider in providers:
                if provider.get("id") == "ofox" and provider.get("apiKey"):
                    key = str(provider["apiKey"])
                    break
            if key.isascii():
                break
    if not key:
        raise SystemExit("GPT Image Studio 配置中没有可用的 API Key")
    data["apiKey"] = key
    data["baseUrl"] = str(data.get("baseUrl") or "https://api.ofox.io/v1").rstrip("/")
    return data


def request_icon(settings: dict, prompt: str) -> Image.Image:
    payload = {
        "model": settings.get("model") or "openai/gpt-image-2.5-flare",
        "prompt": prompt,
        "size": settings.get("sizeMode") or "1024x1024",
        "quality": settings.get("quality") or "low",
        "n": 1,
        "output_format": settings.get("outputFormat") or "png",
        "background": "transparent",
    }
    req = urllib.request.Request(
        settings["baseUrl"] + "/images/generations",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings['apiKey']}",
            "Content-Type": "application/json",
            "X-OfoxAI-Provider-Type": settings.get("providerType") or "openai",
        },
        method="POST",
    )
    timeout = int(settings.get("timeoutSeconds") or 900)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    item = (body.get("data") or [{}])[0]
    if item.get("b64_json"):
        return Image.open(io.BytesIO(base64.b64decode(item["b64_json"]))).convert("RGBA")
    if item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=timeout) as response:
            return Image.open(io.BytesIO(response.read())).convert("RGBA")
    raise RuntimeError(f"生图响应没有图片数据：{str(body)[:300]}")


def remove_flat_background(image: Image.Image) -> Image.Image:
    """Flood-remove a near-uniform light background, keeping interior whites."""
    rgba = image.convert("RGBA")
    if rgba.getchannel("A").getextrema()[0] < 250:
        return rgba
    rgb = rgba.convert("RGB")
    width, height = rgb.size
    px = rgb.load()
    corners = [px[0, 0], px[width - 1, 0], px[0, height - 1], px[width - 1, height - 1]]
    bg = tuple(sorted(c[i] for c in corners)[len(corners) // 2] for i in range(3))

    def distance(color: tuple[int, int, int]) -> float:
        return sum((color[i] - bg[i]) ** 2 for i in range(3)) ** 0.5

    limit = 18.0
    seen = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))
    while queue:
        x, y = queue.pop()
        index = y * width + x
        if seen[index]:
            continue
        seen[index] = 1
        if distance(px[x, y]) > limit:
            continue
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < width and 0 <= ny < height and not seen[ny * width + nx]:
                queue.append((nx, ny))

    alpha = Image.new("L", (width, height), 255)
    ap = alpha.load()
    for y in range(height):
        for x in range(width):
            if seen[y * width + x]:
                ap[x, y] = 0
    alpha = alpha.filter(ImageFilter.GaussianBlur(1.1))
    rgba.putalpha(alpha)
    return rgba


def trim_and_center(image: Image.Image, size: int = 320) -> Image.Image:
    bbox = image.getchannel("A").getbbox()
    if not bbox:
        raise RuntimeError("图标没有可见像素")
    image = image.crop(bbox)
    image.thumbnail((int(size * 0.9), int(size * 0.9)), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        image,
        ((size - image.width) // 2, (size - image.height) // 2),
    )
    return canvas


def generate(keys: list[str], force: bool) -> None:
    settings = load_settings()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for key in keys:
        raw_path = RAW_DIR / f"{key}_raw.png"
        out_path = ICON_DIR / f"{key}.png"
        if out_path.exists() and not force:
            print(f"skip {key} (exists)")
            continue
        prompt = f"{ICONS[key]}. {STYLE}"
        started = time.time()
        print(f"generate {key} ...", flush=True)
        image = request_icon(settings, prompt)
        image.save(raw_path)
        cut = remove_flat_background(image)
        icon = trim_and_center(cut)
        icon.save(out_path)
        print(f"  -> {out_path.relative_to(ROOT)} ({time.time() - started:.1f}s)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", choices=sorted(ICONS), help="只生成指定图标")
    parser.add_argument("--force", action="store_true", help="覆盖已有图标")
    args = parser.parse_args()
    generate(args.only or list(ICONS), args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
