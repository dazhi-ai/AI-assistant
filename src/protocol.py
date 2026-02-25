"""WebSocket message protocol helpers."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class WSMessage:
    """Common message structure between server and tablet client."""

    type: str
    payload: dict[str, Any]
    trace_id: str
    timestamp: int

    def to_json(self) -> str:
        """Serialize the message into JSON text for WebSocket transport."""
        return json.dumps(
            {
                "type": self.type,
                "payload": self.payload,
                "trace_id": self.trace_id,
                "timestamp": self.timestamp,
            },
            ensure_ascii=False,
        )


def build_message(message_type: str, payload: dict[str, Any], trace_id: str | None = None) -> WSMessage:
    """Construct a protocol message with generated metadata."""
    return WSMessage(
        type=message_type,
        payload=payload,
        trace_id=trace_id or str(uuid.uuid4()),
        timestamp=int(time.time()),
    )


def parse_message(raw_text: str) -> WSMessage:
    """Parse and validate one client JSON message."""
    body = json.loads(raw_text)
    message_type = str(body.get("type", "")).strip().upper()
    if not message_type:
        raise ValueError("Message missing required field: type")
    payload = body.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("Message field 'payload' must be an object")
    trace_id = str(body.get("trace_id") or uuid.uuid4())
    timestamp = int(body.get("timestamp") or int(time.time()))
    return WSMessage(
        type=message_type,
        payload=payload,
        trace_id=trace_id,
        timestamp=timestamp,
    )
