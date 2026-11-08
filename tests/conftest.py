import pytest

from core.rules import RuleEngine
from core.state import GameState


@pytest.fixture
def state():
    return GameState.new(seed=2000)


@pytest.fixture
def engine(state):
    return RuleEngine(state)
