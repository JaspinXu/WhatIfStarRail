from pathlib import Path

import pytest

from astral_agents.config import load_scenario
from astral_agents.domain.models import ScenarioBundle
from astral_agents.storage.repository import SQLiteRepository


@pytest.fixture()
def bundle() -> ScenarioBundle:
    return load_scenario()


@pytest.fixture()
def repository(tmp_path: Path) -> SQLiteRepository:
    return SQLiteRepository(tmp_path / "test.sqlite")

