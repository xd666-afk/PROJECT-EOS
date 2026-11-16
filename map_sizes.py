"""Shared presets for randomly generated worlds; old and painted worlds keep their grids."""
DEFAULT_MAP_SIZE = "small"
MAP_SIZES = {
    "small": {"label": "小图", "width": 72, "height": 54, "description": "国家距离更近，适合紧凑对局"},
    "medium": {"label": "中图", "width": 108, "height": 81, "description": "扩张空间与接触节奏均衡"},
    "large": {"label": "大图", "width": 144, "height": 108, "description": "保留原有大地图，探索与扩张更充分"},
}


def map_size_spec(size):
    if not isinstance(size, str) or size not in MAP_SIZES:
        raise ValueError("地图尺寸必须为 small、medium 或 large")
    return MAP_SIZES[size]
