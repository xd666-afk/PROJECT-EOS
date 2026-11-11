from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (ROOT / "dashboard.html").read_text(encoding="utf-8")

ICONS = [
    "farm", "mine", "granary", "irrigation", "workshop", "library",
    "market", "temple", "great_granary", "great_forge", "great_library",
]


def test_dashboard_has_primary_and_secondary_navigation():
    for deck in (
        "world", "nation", "city", "tech", "diplo", "military", "ai", "system",
    ):
        assert f'data-deck="{deck}"' in DASHBOARD
    assert 'id="primaryRail"' in DASHBOARD
    assert 'id="nationTabs"' in DASHBOARD
    assert 'id="techTabs"' in DASHBOARD
    assert 'id="cityTabs"' in DASHBOARD
    assert 'id="notifyModal"' in DASHBOARD
    assert 'id="noticeStack"' in DASHBOARD


def test_icons_are_trimmed_transparent_assets():
    for key in ICONS:
        path = ROOT / "assets" / "icons" / f"{key}.png"
        assert path.is_file(), key
        image = Image.open(path)
        assert image.mode == "RGBA"
        assert image.size == (320, 320)
        alpha = image.getchannel("A")
        assert alpha.getextrema()[0] == 0
        # Corners must be fully transparent, not baked into a rounded card.
        for point in ((0, 0), (319, 0), (0, 319), (319, 319)):
            assert alpha.getpixel(point) == 0


def test_satellite_layer_draws_owned_territory():
    assert "mapMode==='satellite'" in DASHBOARD
    assert "countryColor(owner)" in DASHBOARD


def test_rivers_are_curved_and_roads_draw_on_satellite():
    assert "function buildRiverChains()" in DASHBOARD
    assert "function drawRiverNetwork(" in DASHBOARD
    assert "function landNeighbors(" in DASHBOARD
    assert "landNeighbors(current)" in DASHBOARD
    assert "drawRoadNetwork(scale,mapMode==='routes'||mapMode==='satellite')" in DASHBOARD
    assert "riverCache={world:WORLD,chains}" in DASHBOARD


def test_v2_terrain_and_entity_layers_are_wired():
    assert "function loadTerrainTexture(" in DASHBOARD
    assert "terrain_texture_url" in DASHBOARD
    assert "function drawRiverCells(" in DASHBOARD
    assert "riverDepthColor" in DASHBOARD
    assert "WORLD?.river_cells" in DASHBOARD
    assert "roadEntityCells" in DASHBOARD
    assert "drawImage(terrainImage" in DASHBOARD


def test_v2_lakes_and_endorheic_rivers_are_wired():
    assert "function drawLakeCells(" in DASHBOARD
    assert "lakeDepthColor" in DASHBOARD
    assert "WORLD?.lake_cells" in DASHBOARD
    assert "endorheic_tint" in DASHBOARD
    assert "cell.kind==='endorheic'" in DASHBOARD
    assert "内流湖" in DASHBOARD
    assert "内流河" in DASHBOARD
