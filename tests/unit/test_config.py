from pathlib import Path

import pytest

from astral_agents.config import ScenarioConfigError, load_scenario


def test_default_scenario_loads_with_cross_references() -> None:
    bundle = load_scenario()

    assert bundle.scenario.id == "sealed_transport"
    assert len(bundle.characters) == 4
    assert len(bundle.scenario.clues) >= 7
    assert bundle.config_digest
    assert all(fact.immutable for fact in bundle.canon_facts)


def test_config_digest_is_stable() -> None:
    assert load_scenario().config_digest == load_scenario().config_digest


def test_missing_directory_has_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ScenarioConfigError, match="missing scenario file"):
        load_scenario(tmp_path)


def test_private_canaries_are_unique() -> None:
    bundle = load_scenario()
    canaries = [
        fact.canary
        for character in bundle.characters
        for fact in character.private_facts
        if fact.canary
    ]
    assert len(canaries) == len(set(canaries)) == 4

