from pathlib import Path

import json

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (ROOT / "dashboard.html").read_text(encoding="utf-8")
LIVE_SERVER = (ROOT / "live_server.py").read_text(encoding="utf-8")
MAPGEN_CUSTOM = (ROOT / "mapgen_custom.py").read_text(encoding="utf-8")

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


def test_military_panel_reads_unit_specs_instead_of_hardcoding():
    assert '"unit_specs": self.simulation.state.config["units"]' in LIVE_SERVER
    assert '"military_specs": self.simulation.state.config["military"]' in LIVE_SERVER
    assert "const specs=STATE.unit_specs||{}" in DASHBOARD
    assert 'data-recruit="${id}"' in DASHBOARD
    assert ".unit-table" in DASHBOARD


def test_recruit_button_sends_the_unit_type():
    assert "operation:'RECRUIT',unit:b.dataset.recruit,strength:Number(b.dataset.size)" in DASHBOARD
    assert "unitLossText(e.attacker_units)" in DASHBOARD
    assert "unitName(e.unit)" in DASHBOARD


def test_tech_panel_derives_unlock_labels_from_content_tables():
    assert "function techUnlockIndex()" in DASHBOARD
    assert "collect(STATE.building_specs,'building')" in DASHBOARD
    assert "collect(STATE.unit_specs,'unit')" in DASHBOARD
    assert "const gates=unlocks[`${field}:${node.level}`]" in DASHBOARD
    # rules.json 的 unlocks 文案只做校验，不再当成界面数据源
    assert "node.unlocks" not in DASHBOARD


def test_tech_panel_has_military_unlock_index():
    assert 'data-tech-filter="military"' in DASHBOARD
    assert 'id="techIndex"' in DASHBOARD
    assert "function renderTechIndex()" in DASHBOARD
    assert "function applyTechFilter()" in DASHBOARD
    assert "bar=rules.barracks||{}" in DASHBOARD
    assert "barracks=buildings.BARRACKS||{}" in DASHBOARD
    assert "esc(gate(requirement))" in DASHBOARD
    assert "rules.peace_relation_reset" in DASHBOARD


def test_unit_counter_text_shared_between_panels():
    assert "function unitRelationText(u)" in DASHBOARD
    assert "esc(unitRelationText(u))" in DASHBOARD
    assert "esc(unitRelationText(spec))" in DASHBOARD
    assert "const relationText=" not in DASHBOARD


def test_movement_table_is_the_only_source_of_marching_numbers():
    assert '"movement_specs": self.simulation.state.config["movement"]' in LIVE_SERVER
    assert "const mv=STATE.movement_specs||{}" in DASHBOARD
    assert "const rules=STATE?.movement_specs||{}" in DASHBOARD
    # march_range 已被 movement 表取代，界面不能再引用它
    assert "march_range" not in DASHBOARD


def test_military_panel_lists_armies_instead_of_one_implicit_host_army():
    assert "const armies=c.armies||[]" in DASHBOARD
    assert "<th>兵营募兵</th>" in DASHBOARD
    assert "operation:'SET_RECRUITING'" in DASHBOARD
    assert "operation:'SET_RECRUIT_UNIT'" in DASHBOARD
    assert "for(const army of c.armies||[])" in DASHBOARD


def test_march_and_attack_orders_choose_the_army_and_queue_instead_of_teleporting():
    assert "operation:'MARCH',tile:{col:selectedTile[0],row:selectedTile[1]},army_id:selectedArmy" in DASHBOARD
    assert "operation:'ATTACK',target:b.dataset.attack,army_id:selectedArmy" in DASHBOARD
    assert "operation:'RECRUIT',unit:b.dataset.recruit,strength:Number(b.dataset.size),army_id:selectedArmy" in DASHBOARD
    assert "'行军令已下达'" in DASHBOARD
    assert "军队已行军" not in DASHBOARD


def test_war_card_offers_the_columns_the_engine_priced_per_army():
    assert '"campaign_quotes": self.campaign_quotes()' in LIVE_SERVER
    assert "return Military(self.simulation.state).strike_options(seat)" in LIVE_SERVER
    # A seat that has been annexed off the board quotes nothing: `seat()` is the only gate.
    assert 'return self.player_country if self.player_country in self.simulation.state.countries else None' in LIVE_SERVER
    assert "const quotes=STATE.campaign_quotes||{}" in DASHBOARD
    assert "operation:'ATTACK',target:b.dataset.attackArmy,army_id:b.dataset.army" in DASHBOARD
    assert "milRules.strike_columns||1" in DASHBOARD


def test_march_routes_are_drawn_from_the_order_the_engine_priced():
    assert "function drawMarchRoute(" in DASHBOARD
    assert "drawMarchRoute(army,cid,scale)" in DASHBOARD
    assert "function marchBreakdown(route)" in DASHBOARD
    assert "roadEntityCells().map(cell=>tileKey(cell.col,cell.row))" in DASHBOARD
    assert "case 'march_ordered'" in DASHBOARD
    assert "case 'army_arrived'" in DASHBOARD
    assert "case 'march_cancelled'" in DASHBOARD
    assert "army_marched" not in DASHBOARD


def test_painter_screen_is_reachable_and_escapable():
    assert 'id="painterMenuBtn"' in DASHBOARD
    assert 'id="painterScreen"' in DASHBOARD
    assert "$('painterMenuBtn').onclick=openPainter" in DASHBOARD
    assert "showOnlyScreen('painter')" in DASHBOARD
    assert "if(!$('painterScreen').hidden){$('painterBackBtn').click();return;}" in DASHBOARD
    assert "if(!$('painterScreen').hidden){painterFit();renderPainter();return;}" in DASHBOARD


def test_painter_asks_the_engine_for_every_march_number():
    # The day count is priced server-side by core.movement, so painting cannot drift
    # away from the settlement that will later run the same route.
    assert "fetch('/api/march_preview'" in DASHBOARD
    assert "body:JSON.stringify({draft:painterDraft(),from:start,to:target})" in DASHBOARD
    assert "${preview.days} 天" in DASHBOARD
    assert "preview.hint" in DASHBOARD
    assert "preview.single_order?'一条命令可达':'需分段下令'" in DASHBOARD
    assert "from mapgen_custom import march_preview" in LIVE_SERVER
    assert "return march_preview(draft, self.rules, start, target)" in LIVE_SERVER
    assert "from core.movement import Movement" in MAPGEN_CUSTOM


def test_painter_brushes_come_from_the_server_not_a_local_table():
    assert "PAINTER.brushes=draft.brushes||[]" in DASHBOARD
    assert "${b.land?fmtNum(b.march_cost,1):'—'}" in DASHBOARD
    assert "dict(brush, march_cost=costs.get(brush[\"biome\"]))" in LIVE_SERVER
    assert "for brush in palette()" in LIVE_SERVER


def test_painter_reuses_the_shared_hex_geometry():
    assert "function hexPath(x,y,r=.98,c=ctx)" in DASHBOARD
    assert "function painterXY(col,row)" in DASHBOARD
    assert "PAINTER.offX+cx([col,row])*PAINTER.scale" in DASHBOARD


def test_starting_a_game_from_the_draft_is_gated_on_validation():
    assert "const blocked=missing>0||!report||!report.ok" in DASHBOARD or \
        "let blocked=missing>0||!report||!report.ok" in DASHBOARD
    assert "先为 ${missing} 国落都" in DASHBOARD
    assert "body:JSON.stringify({draft:painterDraft(),start_year:" in DASHBOARD
    assert 'elif self.path == "/api/new_game"' in LIVE_SERVER
    assert "world = build_world_from_draft(draft, seed=base_seed)" in LIVE_SERVER


def test_painter_drops_stale_march_answers():
    assert "const seq=++PAINTER.marchSeq" in DASHBOARD
    assert "if(seq!==PAINTER.marchSeq)return" in DASHBOARD
    assert "PAINTER.marchTimer=setTimeout(()=>refreshPainterMarch(target),70)" in DASHBOARD


def test_border_alerts_paint_the_warning_the_settlement_already_priced():
    # One quote, three faces: the red route on the map, the arrival date in the left rail and
    # the dot over 军事. None of them re-times a march in the browser.
    assert "threats = Military(self.simulation.state).incoming_threats()" in LIVE_SERVER
    assert '"incoming_threats": threats' in LIVE_SERVER
    assert '"incoming": incoming' not in LIVE_SERVER, "one tile answer, not two"
    assert 'id="militaryDot"' in DASHBOARD
    assert "function updateMilitaryDot()" in DASHBOARD and "updateMilitaryDot();" in DASHBOARD
    assert "function drawThreatMarkers(scale)" in DASHBOARD
    assert "if(STATE)drawThreatMarkers(scale);" in DASHBOARD
    assert 'id="worldThreats"' in DASHBOARD
    assert "function threatCard(row)" in DASHBOARD
    assert "还剩 ${row.days_left} 天行军 · 抵达于 ${esc(row.arrival_date)}" in DASHBOARD
    assert "该处没有我方守军" in DASHBOARD
    assert 'class="tag threat"' in DASHBOARD
    assert "const alerts=threatRows()" in DASHBOARD
    assert "STATE?threatSignature():" in DASHBOARD, "a march ordered this second repaints"
    # The dot, the left rail and the map all answer to the realm on screen, so none of them
    # can read "no threats" while the deck one panel below reads one route.
    assert "function threatRealm(){\n  return STATE?.countries?.[selectedCountry]?selectedCountry" in DASHBOARD


def test_an_annexed_realm_leaves_the_panel_instead_of_crashing_it():
    # A realm taken at its capital is gone from `state.countries`, so every list that used to
    # be built off the seed roster has to be built off the living ones.
    assert "function livePolities()" in DASHBOARD
    assert "$('countries').innerHTML=livePolities().map" in DASHBOARD
    assert "const rows=livePolities().filter(p=>p.id!==selectedCountry)" in DASHBOARD
    assert "const others=livePolities().filter(p=>p.id!==selectedCountry)" in DASHBOARD
    assert "for(const p of livePolities()){\n    const c=p.capital" in DASHBOARD
    assert "function healSelection()" in DASHBOARD and "  healSelection();" in DASHBOARD
    assert "if(!c)return;" in DASHBOARD
    assert "已被吞并" in DASHBOARD and "Object.entries(STATE.eliminated||{})" in DASHBOARD
    assert "case 'realm_annexed'" in DASHBOARD, "the diary says a realm left the board"


def test_every_building_the_engine_can_raise_has_a_name_on_the_panel():
    # Seized camps and walls are printed by building id, so a key missing from the label
    # table shows the player `BARRACKS` instead of 兵营 -- and the annexation diary is
    # exactly where that list surfaces.
    rules = json.loads((ROOT / "config" / "rules.json").read_text(encoding="utf-8"))
    table = DASHBOARD.split("const BUILD_NAMES={", 1)[1].split("};", 1)[0]
    for key in rules["buildings"]:
        assert f"{key}:" in table, f"{key} has no Chinese label in BUILD_NAMES"
