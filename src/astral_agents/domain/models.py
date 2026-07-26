from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ENGINE_VERSION = "0.1.0"


class AstralModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FrozenAstralModel(AstralModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActionType(StrEnum):
    SPEAK = "speak"
    ASK = "ask"
    REVEAL = "reveal"
    CONCEAL = "conceal"
    INVESTIGATE = "investigate"
    MOVE = "move"
    USE_RESOURCE = "use_resource"
    NEGOTIATE = "negotiate"
    ASSIST = "assist"
    OPPOSE = "oppose"
    WAIT = "wait"


class RunStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class Visibility(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC = "public"


class MemoryKind(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATIONSHIP = "relationship"
    GOAL = "goal"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Goal(FrozenAstralModel):
    id: str
    description: str
    priority: int = Field(ge=1, le=10)
    private: bool = False
    completion_flag: str | None = None


class PrivateFact(FrozenAstralModel):
    id: str
    content: str
    tags: list[str] = Field(default_factory=list)
    canary: str | None = None


class SpeechStyle(FrozenAstralModel):
    formality: float = Field(ge=0, le=1)
    directness: float = Field(ge=0, le=1)
    warmth: float = Field(ge=0, le=1)
    humor: float = Field(ge=0, le=1)
    notes: str


class CharacterStrategy(FrozenAstralModel):
    role: str
    investigation_priorities: list[str]
    repair_resource: str | None = None
    reveal_after_round: int = Field(default=2, ge=1)
    risk_tolerance: float = Field(default=0.5, ge=0, le=1)


class CharacterProfile(FrozenAstralModel):
    id: str
    display_name: str
    color: str
    sigil: str
    public_summary: str
    values: list[str]
    behavioral_rules: list[str]
    hard_constraints: list[str]
    speech_style: SpeechStyle
    private_facts: list[PrivateFact]
    goals: list[Goal]
    strategy: CharacterStrategy
    starting_location: str


class CanonFact(FrozenAstralModel):
    id: str
    subject_id: str
    predicate: str
    value: str
    source_url: str
    source_version: str
    confidence: Literal["official", "verified_summary"] = "official"
    immutable: bool = True


class LocationDefinition(FrozenAstralModel):
    id: str
    display_name: str
    summary: str
    risk: float = Field(default=0, ge=0, le=1)


class ResourceDefinition(FrozenAstralModel):
    id: str
    display_name: str
    initial: float
    minimum: float = 0
    maximum: float
    unit: str = ""
    public: bool = True

    @model_validator(mode="after")
    def validate_bounds(self) -> ResourceDefinition:
        if not self.minimum <= self.initial <= self.maximum:
            raise ValueError(f"resource {self.id!r} initial value is outside its bounds")
        return self


class ClueDefinition(FrozenAstralModel):
    id: str
    display_name: str
    location_id: str
    discoverers: list[str] = Field(default_factory=list)
    earliest_round: int = Field(default=1, ge=1)
    public_summary: str
    private_detail: str
    tags: list[str] = Field(default_factory=list)
    evidence_points: float = Field(default=1, gt=0)
    resolves_thread: str | None = None
    sets_flag: str | None = None


class ResolutionRules(FrozenAstralModel):
    evidence_required: float = Field(gt=0)
    evidence_resource: str = "evidence"
    repaired_resources: list[str]
    minimum_resource_ratio: float = Field(default=0.4, ge=0, le=1)
    earliest_success_round: int = Field(default=8, ge=1)
    failure_resource: str
    failure_threshold: float


class ScenarioConfig(FrozenAstralModel):
    id: str
    version: str
    title: str
    subtitle: str
    premise: str
    opening_briefing: str
    max_rounds: int = Field(ge=5, le=100)
    episode_interval: int = Field(ge=1, le=10)
    start_phase: str
    locations: list[LocationDefinition]
    adjacency: dict[str, list[str]]
    resources: list[ResourceDefinition]
    resource_decay: dict[str, float] = Field(
        default_factory=lambda: {
            "power": -2.2,
            "life_support": -1.4,
            "phase_stability": -0.8,
        }
    )
    active_conflicts: list[str]
    open_threads: list[str]
    clues: list[ClueDefinition]
    resolution: ResolutionRules
    constraints: list[str]

    @property
    def location_map(self) -> dict[str, LocationDefinition]:
        return {item.id: item for item in self.locations}

    @property
    def resource_map(self) -> dict[str, ResourceDefinition]:
        return {item.id: item for item in self.resources}

    @property
    def clue_map(self) -> dict[str, ClueDefinition]:
        return {item.id: item for item in self.clues}


class OpeningEvent(FrozenAstralModel):
    event_type: str
    participants: list[str]
    observers: list[str]
    public_summary: str | None = None
    private_payloads: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class ScenarioBundle(FrozenAstralModel):
    scenario: ScenarioConfig
    characters: list[CharacterProfile]
    canon_facts: list[CanonFact]
    opening_events: list[OpeningEvent]
    source_dir: str
    config_digest: str

    @property
    def character_map(self) -> dict[str, CharacterProfile]:
        return {item.id: item for item in self.characters}


class RelationshipState(AstralModel):
    trust: float = Field(default=0, ge=-1, le=1)
    suspicion: float = Field(default=0, ge=-1, le=1)
    affinity: float = Field(default=0, ge=-1, le=1)
    obligation: float = Field(default=0, ge=-1, le=1)
    influence: float = Field(default=0, ge=-1, le=1)


class DiscoveryRecord(AstralModel):
    clue_id: str
    discovered_by: str
    event_id: str
    round_no: int
    shared: bool = False


class WorldState(AstralModel):
    run_id: str
    scenario_id: str
    seed: int
    round_no: int = Field(default=0, ge=0)
    phase: str
    status: RunStatus = RunStatus.READY
    locations: dict[str, str]
    resources: dict[str, float]
    resource_limits: dict[str, tuple[float, float]]
    relationships: dict[str, dict[str, RelationshipState]]
    active_conflicts: list[str]
    open_threads: list[str]
    resolved_threads: list[str] = Field(default_factory=list)
    public_fact_ids: list[str] = Field(default_factory=list)
    discovered_clues: dict[str, DiscoveryRecord] = Field(default_factory=dict)
    shared_clue_ids: list[str] = Field(default_factory=list)
    flags: dict[str, bool | str | float] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    timeline_hash: str = ""

    @field_validator("resources")
    @classmethod
    def finite_resources(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(number) for number in value.values()):
            raise ValueError("resources must be finite")
        return value

    @model_validator(mode="after")
    def resource_bounds(self) -> WorldState:
        for resource_id, value in self.resources.items():
            if resource_id not in self.resource_limits:
                raise ValueError(f"missing resource bounds for {resource_id!r}")
            minimum, maximum = self.resource_limits[resource_id]
            if value < minimum or value > maximum:
                raise ValueError(
                    f"resource {resource_id!r}={value} outside [{minimum}, {maximum}]"
                )
        return self

    def state_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"run_id", "timeline_hash"})
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


class ObservationPacket(FrozenAstralModel):
    character_id: str
    round_no: int
    phase: str
    current_location: str
    visible_characters: list[str]
    visible_resources: dict[str, float]
    public_events: list[dict[str, Any]]
    witnessed_events: list[dict[str, Any]]
    private_messages: list[dict[str, Any]]
    canon_facts: list[dict[str, str]]
    known_clue_ids: list[str]
    shared_clue_ids: list[str]
    accessible_event_ids: list[str]
    active_goals: list[Goal]
    open_threads: list[str]
    allowed_actions: list[ActionType]


class Memory(AstralModel):
    id: str
    owner_id: str
    kind: MemoryKind
    content: str
    source_event_ids: list[str]
    salience: float = Field(ge=0, le=1)
    emotional_valence: float = Field(default=0, ge=-1, le=1)
    visibility: Visibility
    created_round: int = Field(ge=0)
    tags: list[str] = Field(default_factory=list)
    last_accessed_round: int | None = None


class RetrievalHit(FrozenAstralModel):
    memory_id: str
    score: float = Field(ge=0)
    relevance: float = Field(ge=0, le=1)
    goal_match: float = Field(ge=0, le=1)
    salience: float = Field(ge=0, le=1)
    recency: float = Field(ge=0, le=1)
    relationship_match: float = Field(ge=0, le=1)


class Belief(AstralModel):
    id: str
    owner_id: str
    proposition: str
    confidence: float = Field(ge=0, le=1)
    stance: Literal["believes", "doubts", "disbelieves"]
    source_event_ids: list[str]
    last_updated_round: int


class ActionIntent(AstralModel):
    id: str
    actor_id: str
    round_no: int
    action_type: ActionType
    target_ids: list[str] = Field(default_factory=list)
    location_id: str | None = None
    public_content: str | None = None
    private_content: str | None = None
    intended_effects: list[str] = Field(default_factory=list)
    evidence_event_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    rationale: str = ""


class StateChange(FrozenAstralModel):
    kind: Literal[
        "set_location",
        "adjust_resource",
        "set_flag",
        "discover_clue",
        "share_clue",
        "adjust_relationship",
        "close_thread",
        "set_phase",
        "set_status",
    ]
    subject_id: str
    target_id: str | None = None
    value: str | float | bool | None = None
    dimension: str | None = None


class CanonicalEvent(AstralModel):
    id: str
    round_no: int
    event_type: str
    participants: list[str]
    observers: list[str]
    public_summary: str | None
    private_payloads: dict[str, str] = Field(default_factory=dict)
    changes: list[StateChange] = Field(default_factory=list)
    caused_by_action_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class StateDiff(FrozenAstralModel):
    path: str
    before: Any
    after: Any
    label: str


class ValidationFinding(AstralModel):
    code: str
    severity: Severity
    message: str
    round_no: int
    actor_id: str | None = None
    event_id: str | None = None
    blocked: bool = False


class ModelCallTrace(AstralModel):
    provider: str
    model: str
    actor_id: str
    round_no: int
    duration_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    retries: int = 0
    error: str | None = None


class NarrativeEpisode(AstralModel):
    id: str
    title: str
    start_round: int
    end_round: int
    point_of_view: str
    event_ids: list[str]
    body: str
    generated_by: Literal["template", "llm"] = "template"
    inferred_facts: list[str] = Field(default_factory=list)
    validation_passed: bool = True


class RoundRecord(AstralModel):
    run_id: str
    round_no: int
    actions: list[ActionIntent]
    events: list[CanonicalEvent]
    findings: list[ValidationFinding]
    state_before: WorldState
    state_after: WorldState
    diffs: list[StateDiff]
    retrievals: dict[str, list[RetrievalHit]] = Field(default_factory=dict)
    model_calls: list[ModelCallTrace] = Field(default_factory=list)
    episode_id: str | None = None
    duration_ms: int = 0


class RunConfig(FrozenAstralModel):
    scenario_id: str
    seed: int
    policy: Literal["heuristic", "scripted", "llm"] = "heuristic"
    model: str = "gpt-5.6-sol"
    max_rounds: int | None = Field(default=None, ge=1)
    memory_strategy: Literal["event_retrieval", "recent_only", "none"] = "event_retrieval"


class RunManifest(AstralModel):
    run_id: str
    engine_version: str = ENGINE_VERSION
    scenario_id: str
    scenario_version: str
    config_digest: str
    seed: int
    policy: str
    model: str
    memory_strategy: str
    max_rounds: int | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
