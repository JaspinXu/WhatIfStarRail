from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from astral_agents.domain.models import (
    CanonFact,
    CharacterProfile,
    OpeningEvent,
    ScenarioBundle,
    ScenarioConfig,
)

DEFAULT_SCENARIO_DIR = (
    Path(__file__).resolve().parents[2] / "scenarios" / "sealed_transport"
)


class ScenarioConfigError(ValueError):
    """Raised when scenario files are valid YAML but inconsistent as a bundle."""


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        raise ScenarioConfigError(f"missing scenario file: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ScenarioConfigError(f"invalid YAML in {path}: {exc}") from exc


def _stable_digest(payloads: list[Any]) -> str:
    raw = json.dumps(payloads, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_scenario(source_dir: str | Path = DEFAULT_SCENARIO_DIR) -> ScenarioBundle:
    directory = Path(source_dir).resolve()
    scenario_raw = _load_yaml(directory / "scenario.yaml")
    characters_raw = _load_yaml(directory / "characters.yaml")
    canon_raw = _load_yaml(directory / "canon_facts.yaml")
    opening_raw = _load_yaml(directory / "opening_events.yaml")

    scenario = ScenarioConfig.model_validate(scenario_raw)
    characters = [
        CharacterProfile.model_validate(item) for item in characters_raw.get("characters", [])
    ]
    canon_facts = [CanonFact.model_validate(item) for item in canon_raw.get("canon_facts", [])]
    opening_events = [
        OpeningEvent.model_validate(item) for item in opening_raw.get("opening_events", [])
    ]

    if len(characters) < 4:
        raise ScenarioConfigError("a demo scenario requires at least four characters")

    _validate_cross_references(scenario, characters, canon_facts, opening_events)
    digest = _stable_digest([scenario_raw, characters_raw, canon_raw, opening_raw])
    return ScenarioBundle(
        scenario=scenario,
        characters=characters,
        canon_facts=canon_facts,
        opening_events=opening_events,
        source_dir=str(directory),
        config_digest=digest,
    )


def _validate_cross_references(
    scenario: ScenarioConfig,
    characters: list[CharacterProfile],
    canon_facts: list[CanonFact],
    opening_events: list[OpeningEvent],
) -> None:
    location_ids = {item.id for item in scenario.locations}
    resource_ids = {item.id for item in scenario.resources}
    character_ids = {item.id for item in characters}
    clue_ids = {item.id for item in scenario.clues}

    _ensure_unique("location", [item.id for item in scenario.locations])
    _ensure_unique("resource", [item.id for item in scenario.resources])
    _ensure_unique("character", [item.id for item in characters])
    _ensure_unique("clue", [item.id for item in scenario.clues])
    _ensure_unique("canon fact", [item.id for item in canon_facts])

    for location_id, neighbors in scenario.adjacency.items():
        if location_id not in location_ids:
            raise ScenarioConfigError(f"adjacency references unknown location {location_id!r}")
        unknown = set(neighbors) - location_ids
        if unknown:
            raise ScenarioConfigError(
                f"adjacency for {location_id!r} references unknown locations: {sorted(unknown)}"
            )
        for neighbor in neighbors:
            if location_id not in scenario.adjacency.get(neighbor, []):
                raise ScenarioConfigError(
                    f"adjacency must be symmetric: {location_id!r} -> {neighbor!r}"
                )

    for character in characters:
        if character.starting_location not in location_ids:
            raise ScenarioConfigError(
                f"character {character.id!r} starts at unknown location "
                f"{character.starting_location!r}"
            )
        unknown_priorities = set(character.strategy.investigation_priorities) - location_ids
        if unknown_priorities:
            raise ScenarioConfigError(
                f"character {character.id!r} has unknown location priorities: "
                f"{sorted(unknown_priorities)}"
            )
        if (
            character.strategy.repair_resource
            and character.strategy.repair_resource not in resource_ids
        ):
            raise ScenarioConfigError(
                f"character {character.id!r} repairs unknown resource "
                f"{character.strategy.repair_resource!r}"
            )

    for clue in scenario.clues:
        if clue.location_id not in location_ids:
            raise ScenarioConfigError(
                f"clue {clue.id!r} references unknown location {clue.location_id!r}"
            )
        unknown_discoverers = set(clue.discoverers) - character_ids
        if unknown_discoverers:
            raise ScenarioConfigError(
                f"clue {clue.id!r} references unknown discoverers: "
                f"{sorted(unknown_discoverers)}"
            )

    if scenario.resolution.failure_resource not in resource_ids:
        raise ScenarioConfigError(
            f"resolution references unknown failure resource "
            f"{scenario.resolution.failure_resource!r}"
        )
    unknown_repairs = set(scenario.resolution.repaired_resources) - resource_ids
    if unknown_repairs:
        raise ScenarioConfigError(
            f"resolution references unknown repair resources: {sorted(unknown_repairs)}"
        )

    for fact in canon_facts:
        if fact.subject_id not in character_ids:
            raise ScenarioConfigError(
                f"canon fact {fact.id!r} references unknown subject {fact.subject_id!r}"
            )

    for index, event in enumerate(opening_events):
        unknown_people = (set(event.participants) | set(event.observers)) - character_ids
        unknown_recipients = set(event.private_payloads) - character_ids
        if unknown_people or unknown_recipients:
            raise ScenarioConfigError(
                f"opening event {index} references unknown characters: "
                f"{sorted(unknown_people | unknown_recipients)}"
            )

    if not clue_ids:
        raise ScenarioConfigError("scenario must define at least one discoverable clue")


def _ensure_unique(kind: str, values: list[str]) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ScenarioConfigError(f"duplicate {kind} ids: {duplicates}")

