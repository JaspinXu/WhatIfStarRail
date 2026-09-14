"""Versioned, transport-independent contracts for companion integrations."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NodeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=24000)
    cast: str = Field(min_length=1, max_length=1000)
    kind: Literal["manual", "capture", "fork", "continuation"] = "manual"
    parent: str | None = None

    @field_validator("cast")
    @classmethod
    def validate_cast(cls, value):
        names = [n.strip() for n in value.replace("，", ",").split(",") if n.strip()]
        if not names:
            raise ValueError("请至少填写一位在场人物")
        return "，".join(dict.fromkeys(names))


class ArchivedNode(NodeDraft):
    id: str = Field(min_length=1, max_length=128)
    created: str = Field(min_length=1, max_length=80)


class ArchivedChat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int | None = None
    node: str
    actor: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=24000)


class StoryArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    nodes: list[ArchivedNode] = Field(min_length=1, max_length=2000)
    chats: list[ArchivedChat] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def validate_graph(self):
        seen = set()
        for node in self.nodes:
            if node.id in seen or (node.parent and node.parent not in seen):
                raise ValueError("节点重复、循环或缺少祖先；请按时间顺序导出完整分支")
            seen.add(node.id)
        if any(chat.node not in seen for chat in self.chats):
            raise ValueError("对话引用了归档中不存在的节点")
        return self


class CharacterCard(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    identity: str = Field(default="", max_length=3000)
    voice: str = Field(default="", max_length=1500)
    boundaries: str = Field(default="只依据当前剧情，不预知未来。", max_length=1500)


class CaptureProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: int = Field(default=200, ge=-16000, le=16000)
    top: int = Field(default=750, ge=-16000, le=16000)
    width: int = Field(default=1500, ge=100, le=7680)
    height: int = Field(default=250, ge=50, le=2160)
    interval: float = Field(default=2.0, ge=0.5, le=30)
    confidence: float = Field(default=0.75, ge=0.1, le=1)
    cast: str = "三月七，丹恒"

    @field_validator("cast")
    @classmethod
    def validate_cast(cls, value):
        return NodeDraft.validate_cast(value)

    def region(self):
        return self.model_dump(include={"left", "top", "width", "height"})


class IngestEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: str = Field(min_length=1, max_length=100)
    event_id: str = Field(min_length=1, max_length=128)
    timeline: str = Field(min_length=1, max_length=128)
    title: str = Field(default="外部剧情", min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=24000)
    cast: str = Field(min_length=1, max_length=1000)

    @field_validator("cast")
    @classmethod
    def validate_cast(cls, value):
        return NodeDraft.validate_cast(value)
