"""Delivery base: Channel protocol and shared types.

Channels (feishu, dingtalk) implement the Channel protocol. The runner
renders messages via formatter and sends each via the channel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SendResult:
    """Result of sending one message via a channel."""

    ok: bool
    status: int = 0
    error: str | None = None
    message: str = ""


@runtime_checkable
class Channel(Protocol):
    """A push channel. send() delivers one payload, returns result."""

    name: str

    def send(self, content: str) -> SendResult: ...


