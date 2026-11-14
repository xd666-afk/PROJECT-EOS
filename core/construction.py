"""Construction queues with labor- and policy-dependent progress."""
from __future__ import annotations

from core.state import GameState, tile_key


class Construction:
    def __init__(self, state: GameState) -> None:
        self.state = state

    def advance_all(self) -> None:
        for country in self.state.countries.values():
            if not country.projects:
                continue
            baseline = self.state.config["workers_baseline"]["construction"]
            labor_factor = country.workers["construction"] / baseline if baseline else 1.0
            policy_factor = self.state.config["policies"][country.policy]["construction"]
            daily_progress = labor_factor * policy_factor
            completed = []
            pending_ids = {p["project_id"] for p in country.projects}
            for project in country.projects:
                if project.get("depends_on") in pending_ids:
                    project["blocked_reason"] = "等待前一段道路完工"
                    continue
                if project["building"] == "ROAD":
                    from core.road import road_permit, road_connection_status
                    permit = road_permit(self.state, country, tuple(project["tile"]))
                    connected = road_connection_status(self.state, country, tuple(project["tile"]), include_pending=False)[0]
                    if permit or not connected:
                        project["blocked_reason"] = permit[1] if permit else "道路接入点失效，等待重新连通"
                        continue
                project.pop("blocked_reason", None)
                project["remaining_days"] = max(
                    0.0, project["remaining_days"] - daily_progress
                )
                if project["remaining_days"] <= 1e-12:
                    coord = tuple(project["tile"])
                    if project["building"] == "ROAD":
                        country.roads.add(coord)
                    else:
                        country.buildings[coord] = project["building"]
                    completed.append(project)
                    self.state.record(
                        "construction_completed",
                        country_id=country.country_id,
                        project_id=project["project_id"],
                        tile={"col": coord[0], "row": coord[1]},
                        building=project["building"],
                    )
            if completed:
                completed_ids = {project["project_id"] for project in completed}
                country.projects = [
                    project for project in country.projects
                    if project["project_id"] not in completed_ids
                ]

    @staticmethod
    def project_for_tile(country, coord: tuple[int, int]):
        return next(
            (project for project in country.projects if tuple(project["tile"]) == coord),
            None,
        )

    @staticmethod
    def describe(country) -> list[dict]:
        return [
            {
                "project_id": project["project_id"],
                "tile": tile_key(tuple(project["tile"])),
                "building": project["building"],
                "remaining_days": round(project["remaining_days"], 4),
            }
            for project in country.projects
        ]
