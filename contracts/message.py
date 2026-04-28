"""Message contract dataclass and builder for the Mafia game protocol."""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from contracts.intents import Intent, MessageState
from config import CONTRACT_VERSION


@dataclass
class GameMessage:
    """Structured message contract for all inter-agent communication.

    Every message in the system MUST be an instance of this class.
    No raw dicts or strings are allowed in the handoff pipeline.
    """

    version: str
    message_id: str
    correlation_id: str
    idempotency_key: str
    intent: str
    sender: str
    receiver: str
    state: str
    context: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    trace_history: list = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        """Serialize message to JSON string."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_dict(self) -> dict:
        """Serialize message to dictionary."""
        return asdict(self)

    @classmethod
    def from_json(cls, json_str: str) -> "GameMessage":
        """Deserialize message from JSON string."""
        data = json.loads(json_str)
        return cls(**data)

    @classmethod
    def from_dict(cls, data: dict) -> "GameMessage":
        """Deserialize message from dictionary."""
        return cls(**data)


class MessageBuilder:
    """Builder pattern for constructing GameMessage instances.

    Usage:
        msg = (MessageBuilder(correlation_id="game-123")
               .intent(Intent.ASSIGN_ROLE)
               .sender("agent.orchestrator")
               .receiver("agent.mafia_1")
               .state(MessageState.RECEIVED)
               .context({"role": "MAFIA"})
               .payload({"text": "You are Mafia."})
               .build())
    """

    def __init__(self, correlation_id: str):
        self._correlation_id = correlation_id
        self._intent: str | None = None
        self._sender: str | None = None
        self._receiver: str | None = None
        self._state: str | None = None
        self._context: dict = {}
        self._payload: dict = {}
        self._trace_history: list = []
        self._idempotency_key: str | None = None
        self._message_id: str | None = None

    def intent(self, intent: Intent | str) -> "MessageBuilder":
        self._intent = intent.value if isinstance(intent, Intent) else intent
        return self

    def sender(self, sender: str) -> "MessageBuilder":
        self._sender = sender
        return self

    def receiver(self, receiver: str) -> "MessageBuilder":
        self._receiver = receiver
        return self

    def state(self, state: MessageState | str) -> "MessageBuilder":
        self._state = state.value if isinstance(state, MessageState) else state
        return self

    def context(self, context: dict) -> "MessageBuilder":
        self._context = context
        return self

    def payload(self, payload: dict) -> "MessageBuilder":
        self._payload = payload
        return self

    def trace_history(self, trace: list) -> "MessageBuilder":
        self._trace_history = trace
        return self

    def add_trace(self, event_type: str) -> "MessageBuilder":
        self._trace_history.append(event_type)
        return self

    def idempotency_key(self, key: str) -> "MessageBuilder":
        self._idempotency_key = key
        return self

    def message_id(self, mid: str) -> "MessageBuilder":
        self._message_id = mid
        return self

    def build(self) -> GameMessage:
        """Construct the GameMessage. Raises ValueError if required fields are missing."""
        if not self._intent:
            raise ValueError("Intent is required")
        if not self._sender:
            raise ValueError("Sender is required")
        if not self._receiver:
            raise ValueError("Receiver is required")
        if not self._state:
            raise ValueError("State is required")

        msg_id = self._message_id or str(uuid.uuid4())
        idem_key = self._idempotency_key or f"{self._intent}_{self._sender}_{msg_id}"

        return GameMessage(
            version=CONTRACT_VERSION,
            message_id=msg_id,
            correlation_id=self._correlation_id,
            idempotency_key=idem_key,
            intent=self._intent,
            sender=self._sender,
            receiver=self._receiver,
            state=self._state,
            context=self._context,
            payload=self._payload,
            trace_history=list(self._trace_history),
        )


def create_orchestrator_message(
    correlation_id: str,
    intent: Intent,
    receiver: str,
    context: dict | None = None,
    payload: dict | None = None,
    trace_history: list | None = None,
    round_number: int = 0,
) -> GameMessage:
    """Convenience function for Orchestrator-sourced messages."""
    idem_key = f"{intent.value}_{receiver}_round{round_number}"
    return (
        MessageBuilder(correlation_id)
        .intent(intent)
        .sender("agent.orchestrator")
        .receiver(receiver)
        .state(MessageState.RECEIVED)
        .context(context or {})
        .payload(payload or {})
        .trace_history(trace_history or [])
        .idempotency_key(idem_key)
        .build()
    )
