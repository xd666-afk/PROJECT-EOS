"""Isolated browser verification for the real-time strategy interface.

Run with the project Python, Playwright, and Microsoft Edge installed. The
fixture has extra funds and one existing barracks; it never edits player saves.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify(output: Path) -> dict:
    from playwright.sync_api import sync_playwright
    import live_server

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eos-strategy-") as temp:
        live_server.SAVE_DIR = Path(temp) / "saves"
        session = live_server.LiveSession(paused=True, load_path=ROOT / "examples/civil_networks/save.json")
        country = session.simulation.state.countries["A"]
        country.treasury = 10000.0
        capital = country.cities[0].center
        country.buildings[capital] = "BARRACKS"
        army = country.armies[0]
        result = session.simulation.engine.apply_action("A", {
            "type": "MILITARY", "operation": "RECRUIT", "unit": "MILITIA",
            "strength": 1, "army_id": army.army_id,
        })
        assert result.accepted, result.reason_text
        session.save_current("交互验证专用世界")

        class Handler(live_server.Handler):
            def log_message(self, *_args):
                pass

        Handler.session = session
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        errors, actions, controls = [], [], []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.on("pageerror", lambda error: errors.append(str(error)))

                def track(request):
                    if request.method != "POST":
                        return
                    if request.url.endswith("/api/control"):
                        controls.append(request.post_data_json)
                    elif request.url.endswith("/api/action"):
                        actions.append(request.post_data_json)

                page.on("request", track)
                page.goto(base + "/?play=latest")
                page.wait_for_function("STATE?.countries && document.querySelector('#realmName').textContent")
                assert page.request.get(base + "/assets/ui/strategy.css").headers["content-type"].startswith("text/css")
                assert "javascript" in page.request.get(base + "/assets/ui/strategy.js").headers["content-type"]
                page.locator("#realmPicker").select_option("A")
                page.locator("#interveneBtn").click()
                page.wait_for_function('STATE.player_country==="A"')
                assert page.evaluate("STATE.paused")

                def click_hex(coord):
                    page.evaluate("p=>focusTile(...p)", list(coord))
                    point = page.evaluate("""p=>{
                        const r=canvas.getBoundingClientRect(),s=fitScale*zoom;
                        return {x:r.left+baseOffX+panX+cx(p)*s,y:r.top+baseOffY+panY+cy(p)*s};
                    }""", list(coord))
                    page.mouse.click(point["x"], point["y"])

                # Clicking a foreign city changes the viewed realm, never the actor.
                foreign = page.evaluate("STATE.countries.B.cities[0].center")
                click_hex(foreign)
                assert page.evaluate('selectedCountry==="B" && STATE.player_country==="A"')
                assert page.locator("#realmName").inner_text() == "国家A"
                page.locator('#primaryRail [data-deck="nation"]').click()
                page.locator('[data-nation-tab="finance"]').click()
                assert page.locator('#financeTaxRate').is_disabled()
                assert page.locator('#financeWorkersApply').is_disabled()
                assert page.evaluate('STATE.player_country==="A"')
                page.keyboard.press('Escape')
                page.locator('[data-command="diplomacy"]').click()
                page.wait_for_selector('#diploModal:not([hidden]) .diplo-row.focus-target[data-diplo-country="B"]')
                assert page.evaluate('selectedCountry==="A" && STATE.player_country==="A"')
                page.screenshot(path=str(output / "diplomacy.png"))
                page.keyboard.press("Escape")

                # Read-only panels do not generate pause/resume requests during live play.
                page.keyboard.press("Space")
                page.wait_for_function("!STATE.paused")
                initial_day, baseline = page.evaluate("STATE.day"), len(controls)
                for deck in ("nation", "tech", "diplo", "military", "city"):
                    page.locator(f'#primaryRail [data-deck="{deck}"]').click()
                    page.wait_for_timeout(80)
                    assert page.evaluate("!STATE.paused"), deck
                    page.keyboard.press("Escape")
                page.wait_for_function("day=>STATE.day>day", arg=initial_day)
                assert not any(row["action"] in {"pause", "resume"} for row in controls[baseline:])
                page.keyboard.press("Space")
                page.wait_for_function("STATE.paused")

                # Finance controls write real rules and maintain a 100% labor split.
                page.locator('[data-hud="finance"]').click()
                page.wait_for_selector("#financeTaxRate")
                page.locator("#financeTaxRate").fill("15")
                page.locator("#financeTaxApply").click()
                page.wait_for_function("Math.abs(STATE.countries.A.tax_rate-.15)<1e-9")
                page.locator("#financeAgriculture").fill("55")
                page.locator("#financeMining").fill("25")
                assert "建筑劳动力 20%" in page.locator("#financeConstruction").inner_text()
                page.locator("#financeWorkersApply").click()
                page.wait_for_function("STATE.countries.A.workers.agriculture===.55 && STATE.countries.A.workers.mining===.25")
                page.locator("#financeAgriculture").fill("90")
                assert page.locator("#financeWorkersApply").is_disabled()
                page.locator("#financeAgriculture").fill("55")
                page.screenshot(path=str(output / "finance.png"))
                page.locator('[data-hud="food"]').click()
                page.wait_for_function('document.querySelector("#nationModal").hidden && mapMode==="logistics"')
                page.locator('[data-layer="satellite"]').click()

                # Context construction uses the same backend and actual project queue.
                click_hex((13, 20))
                page.locator('[data-command="build"]').click()
                page.locator('[data-build="FARM"]').click()
                page.wait_for_function('STATE.projects.some(p=>p[0]===13&&p[1]===20&&p[2]==="FARM")')

                # Whole-road planning can share the pending farm's tile.
                click_hex(capital)
                page.locator('[data-command="road"]').click()
                click_hex((13, 20))
                page.wait_for_function("roadPlan?.quote&&!roadPlan.loading")
                page.screenshot(path=str(output / "road.png"))
                page.locator('[data-command="confirm-road"]').click()
                page.wait_for_function('!roadPlan && STATE.projects.some(p=>p[2]==="ROAD"&&p[3]==="A")')

                # Recruit at the selected barracks, then select a move destination.
                click_hex(capital)
                page.locator('[data-command="recruit"]').click()
                before = page.evaluate("STATE.countries.A.army_strength")
                recruit = page.locator("#panel-tile [data-camp-recruit]").first
                assert recruit.is_enabled()
                recruit.click()
                page.wait_for_function("n=>STATE.countries.A.army_strength>n", arg=before)
                page.locator('[data-command="move"]').click()
                click_hex((13, 20))
                page.wait_for_function('!document.querySelector(\'[data-command="confirm-move"]\').disabled')
                page.keyboard.press('Escape')
                assert page.evaluate('strategyCommand==="inspect" && !STATE.countries.A.armies.some(a=>a.march)')
                assert page.locator('#pauseMenu').is_hidden()
                count = len(actions)
                point = page.evaluate("""()=>{
                    const r=canvas.getBoundingClientRect(),s=fitScale*zoom;
                    return {x:r.left+baseOffX+panX+cx([13,20])*s,y:r.top+baseOffY+panY+cy([13,20])*s};
                }""")
                page.mouse.click(point['x'],point['y'],button='right')
                page.wait_for_function('strategyCommand==="move" && !document.querySelector(\'[data-command="confirm-move"]\').disabled')
                assert len(actions)==count
                page.screenshot(path=str(output / "march_preview.png"))
                page.locator('[data-command="confirm-move"]').click()
                page.wait_for_function("STATE.countries.A.armies.some(a=>a.march)")
                moving = page.evaluate("STATE.countries.A.armies.find(a=>a.march)")
                assert moving["tile"] != [13, 20]
                for _ in range(moving["march"]["days_left"] + 1):
                    page.locator("#stepBtn").click()
                    page.wait_for_timeout(75)
                page.wait_for_function('STATE.countries.A.armies.some(a=>a.tile?.[0]===13&&a.tile?.[1]===20&&!a.march)')

                # Space does not pause the world while entering a fiscal value.
                page.locator('[data-hud="finance"]').click()
                control_count = len(controls)
                page.locator("#financeAgriculture").focus()
                page.keyboard.press("Space")
                assert len(controls) == control_count
                page.keyboard.press("Tab")
                page.keyboard.press("Escape")

                # Responsive controls remain within the viewport and usable.
                page.locator('[data-command="clear"]').click()
                for width in (1440, 1024, 800, 390):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.wait_for_timeout(100)
                    for selector in ("#timeDock", "#commandDock", "#realmHome", "#pauseBtn"):
                        bounds = page.locator(selector).bounding_box()
                        assert bounds and bounds["x"] >= -1 and bounds["x"] + bounds["width"] <= width + 1, (width, selector, bounds)
                    assert page.locator("#pauseBtn").is_visible()
                    page.screenshot(path=str(output / f"workspace_{width}.png"))
                assert not errors, errors
                browser.close()

            assert all(row["actor"] == "A" for row in actions)
            return {"javascript_errors": errors, "verified_action_types": sorted({row["action"]["type"] for row in actions}),
                    "viewports": [1440, 1024, 800, 390], "live_time_preserved": True,
                    "foreign_selection_keeps_actor": True, "screenshots": str(output)}
        finally:
            server.shutdown()
            server.server_close()
            session.stop()
            thread.join(timeout=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/ui_checks/strategy")
    args = parser.parse_args()
    print(json.dumps(verify(args.output.resolve()), ensure_ascii=False, indent=2))
