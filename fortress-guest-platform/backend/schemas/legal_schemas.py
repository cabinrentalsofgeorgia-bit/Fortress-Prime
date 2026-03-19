from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphNodeResponse(BaseModel):
    id: str
    entity_type: str
    label: str
    node_metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeResponse(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    relationship_type: str
    weight: float = 0.0
    source_ref: str | None = None


class GraphSnapshotResponse(BaseModel):
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]


class FunnelUpdateRequest(BaseModel):
    lock_in_questions: list[str] | None = None
    strike_script: str | None = None


class TargetStatusUpdateRequest(BaseModel):
    status: str

