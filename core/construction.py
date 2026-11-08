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
            for project in country.projects:
                project["remaining_days"] = max(
                    0.0, project["remaining_days"] - daily_progress
                )
                if project["remaining_days"] <= 1e-12:
                    coord = tuple(project["tile"])
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
