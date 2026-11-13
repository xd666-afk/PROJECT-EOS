import pytest

from core.rules import RuleEngine
from core.state import GameState


def set_roster(country, units, tile=None):
    """Armies own the roster: replace this nation's whole list with one field army."""
    country.armies = []
    country.army_serial = 0
    return country.new_army(tile=tile, units=dict(units))


@pytest.fixture
def state():
    return GameState.new(seed=2000)


@pytest.fixture
def engine(state):
    return RuleEngine(state)
