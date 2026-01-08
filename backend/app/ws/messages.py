from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class WSIn(BaseModel):
    action: Literal[
        "create_room",
        "join_room",
        "leave_room",
        "start_game",
        "ping",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class WSOut(BaseModel):
    type: Literal[
        "room_created",
        "room_joined",
        "room_state",
        "game_started",
        "error",
        "pong",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


def err(code: str, message: str, extra: Optional[dict[str, Any]] = None) -> WSOut:
    payload: dict[str, Any] = {"code": code, "message": message}
    if extra:
        payload.update(extra)
    return WSOut(type="error", payload=payload)
