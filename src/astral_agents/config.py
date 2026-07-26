from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

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
    except (OSError, yaml.YAMLError) as exc:
        raise ScenarioConfigError(f"cannot load YAML from {path}: {exc}") from exc


def _mapping_document(path: Path) -> dict[str, Any]:
    payload = _load_yaml(path)
    if not isinstance(payload, Mapping):
        raise ScenarioConfigError(f"YAML root must be a mapping in {path}")
    return dict(payload)


def _document_items(document: dict[str, Any], key: str, path: Path) -> list[Any]:
    items = document.get(key, [])
    if not isinstance(items, list):
        raise ScenarioConfigError(f"{key!r} must be a list in {path}")
    return items


def _stable_digest(payloads: list[Any]) -> str:
    raw = json.dumps(payloads, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_scenario(source_dir: str | Path = DEFAULT_SCENARIO_DIR) -> ScenarioBundle:
    directory = Path(source_dir).resolve()
    scenario_path = directory / "scenario.yaml"
    characters_path = directory / "characters.yaml"
    canon_path = directory / "canon_facts.yaml"
    opening_path = directory / "opening_events.yaml"
    scenario_raw = _mapping_document(scenario_path)
    characters_raw = _mapping_document(characters_path)
    canon_raw = _mapping_document(canon_path)
    opening_raw = _mapping_document(opening_path)

    try:
        scenario = ScenarioConfig.model_validate(scenario_raw)
        characters = [
            CharacterProfile.model_validate(item)
            for item in _document_items(characters_raw, "characters", characters_path)
        ]
        canon_facts = [
            CanonFact.model_validate(item)
            for item in _document_items(canon_raw, "canon_facts", canon_path)
        ]
        opening_events = [
            OpeningEvent.model_validate(item)
            for item in _document_items(opening_raw, "opening_events", opening_path)
        ]
    except ValidationError as exc:
        raise ScenarioConfigError(f"scenario schema validation failed: {exc}") from exc

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
    _ensure_unique("open thread", scenario.open_threads)
    _ensure_unique("repair resource", scenario.resolution.repaired_resources)

    for character in characters:
        _ensure_unique(
            f"private fact for {character.id}",
            [fact.id for fact in character.private_facts],
        )
        _ensure_unique(
            f"goal for {character.id}",
            [goal.id for goal in character.goals],
        )

    unknown_decay_resources = set(scenario.resource_decay) - resource_ids
    if unknown_decay_resources:
        raise ScenarioConfigError(
            f"resource decay references unknown resources: {sorted(unknown_decay_resources)}"
        )
    invalid_decay = {
        resource_id: amount
        for resource_id, amount in scenario.resource_decay.items()
        if not math.isfinite(amount) or amount > 0
    }
    if invalid_decay:
        raise ScenarioConfigError(
            f"resource decay values must be finite and non-positive: {invalid_decay}"
        )

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
    missing_adjacency = location_ids - set(scenario.adjacency)
    if missing_adjacency:
        raise ScenarioConfigError(
            f"adjacency is missing locations: {sorted(missing_adjacency)}"
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
    if scenario.resolution.evidence_resource not in resource_ids:
        raise ScenarioConfigError(
            "resolution references unknown evidence resource "
            f"{scenario.resolution.evidence_resource!r}"
        )
    evidence_definition = scenario.resource_map[scenario.resolution.evidence_resource]
    if scenario.resolution.evidence_required > evidence_definition.maximum:
        raise ScenarioConfigError(
            "resolution evidence requirement exceeds the evidence resource maximum"
        )
    unknown_repairs = set(scenario.resolution.repaired_resources) - resource_ids
    if unknown_repairs:
        raise ScenarioConfigError(
            f"resolution references unknown repair resources: {sorted(unknown_repairs)}"
        )
    for resource_id in scenario.resolution.repaired_resources:
        if scenario.resource_map[resource_id].maximum <= 0:
            raise ScenarioConfigError(
                f"resolution repair resource {resource_id!r} must have a positive maximum"
            )
    failure_definition = scenario.resource_map[scenario.resolution.failure_resource]
    if not (
        failure_definition.minimum
        <= scenario.resolution.failure_threshold
        <= failure_definition.maximum
    ):
        raise ScenarioConfigError(
            "resolution failure threshold is outside the failure resource bounds"
        )
    if scenario.resolution.earliest_success_round > scenario.max_rounds:
        raise ScenarioConfigError(
            "resolution earliest success round exceeds the scenario round limit"
        )

    resolvable_threads = {
        clue.resolves_thread for clue in scenario.clues if clue.resolves_thread
    }
    unknown_threads = resolvable_threads - set(scenario.open_threads)
    if unknown_threads:
        raise ScenarioConfigError(
            f"clues resolve unknown open threads: {sorted(unknown_threads)}"
        )
    unresolvable_threads = set(scenario.open_threads) - resolvable_threads
    if unresolvable_threads:
        raise ScenarioConfigError(
            f"open threads have no resolving clue: {sorted(unresolvable_threads)}"
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
        unauthorized_private = set(event.private_payloads) - (
            set(event.participants) | set(event.observers)
        )
        if unauthorized_private:
            raise ScenarioConfigError(
                f"opening event {index} has private recipients outside its visible set: "
                f"{sorted(unauthorized_private)}"
            )

    if not clue_ids:
        raise ScenarioConfigError("scenario must define at least one discoverable clue")

    canaries = [
        fact.canary
        for character in characters
        for fact in character.private_facts
        if fact.canary
    ]
    _ensure_unique("private canary", canaries)


def _ensure_unique(kind: str, values: list[str]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ScenarioConfigError(f"duplicate {kind} ids: {sorted(duplicates)}")

