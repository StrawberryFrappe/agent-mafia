"""Tests for message contracts and validation."""

import json
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contracts.message import GameMessage, MessageBuilder, create_orchestrator_message
from contracts.intents import Intent, MessageState, GamePhase
from contracts.validator import (
    validate_message_structure,
    validate_intent_for_phase,
    validate_phase_transition,
    validate_handoff,
    validate_no_voting_day_zero,
    validate_full,
    ContractValidationError,
    PhaseViolationError,
    HandoffViolationError,
)


class TestMessageBuilder:
    def test_build_basic_message(self):
        msg = (
            MessageBuilder("game-123")
            .intent(Intent.ASSIGN_ROLE)
            .sender("agent.orchestrator")
            .receiver("agent.mafia_1")
            .state(MessageState.RECEIVED)
            .build()
        )
        assert msg.version == "1.0"
        assert msg.intent == "ASSIGN_ROLE"
        assert msg.sender == "agent.orchestrator"
        assert msg.receiver == "agent.mafia_1"
        assert msg.state == "received"
        assert msg.correlation_id == "game-123"

    def test_build_with_context_and_payload(self):
        msg = (
            MessageBuilder("game-123")
            .intent(Intent.NIGHT_CHAT)
            .sender("agent.orchestrator")
            .receiver("agent.mafia_1")
            .state(MessageState.RECEIVED)
            .context({"role": "MAFIA"})
            .payload({"text": "Hello"})
            .build()
        )
        assert msg.context == {"role": "MAFIA"}
        assert msg.payload == {"text": "Hello"}

    def test_build_missing_intent_raises(self):
        with pytest.raises(ValueError, match="Intent"):
            MessageBuilder("game-123").sender("a").receiver("b").state(MessageState.RECEIVED).build()

    def test_build_missing_sender_raises(self):
        with pytest.raises(ValueError, match="Sender"):
            MessageBuilder("game-123").intent(Intent.ASSIGN_ROLE).receiver("b").state(MessageState.RECEIVED).build()

    def test_serialization_roundtrip(self):
        msg = create_orchestrator_message(
            "game-123", Intent.ASSIGN_ROLE, "agent.town_1",
            context={"role": "TOWN"}, payload={"text": "hi"},
        )
        json_str = msg.to_json()
        restored = GameMessage.from_json(json_str)
        assert restored.intent == msg.intent
        assert restored.context == msg.context

    def test_idempotency_key_generation(self):
        msg = create_orchestrator_message(
            "game-123", Intent.ASSIGN_ROLE, "agent.town_1", round_number=3,
        )
        assert msg.idempotency_key == "ASSIGN_ROLE_agent.town_1_round3"


class TestValidator:
    def _make_msg(self, intent="ASSIGN_ROLE", state="received", sender="agent.orchestrator", receiver="agent.town_1"):
        return (
            MessageBuilder("game-123")
            .intent(intent)
            .sender(sender)
            .receiver(receiver)
            .state(state)
            .build()
        )

    def test_valid_structure(self):
        msg = self._make_msg()
        validate_message_structure(msg)  # Should not raise

    def test_invalid_version(self):
        msg = self._make_msg()
        msg.version = "2.0"
        with pytest.raises(ContractValidationError, match="version"):
            validate_message_structure(msg)

    def test_invalid_state(self):
        msg = self._make_msg(state="invalid")
        with pytest.raises(ContractValidationError, match="state"):
            validate_message_structure(msg)

    def test_intent_allowed_in_phase(self):
        msg = self._make_msg(intent="ASSIGN_ROLE")
        validate_intent_for_phase(msg, GamePhase.INIT)

    def test_intent_blocked_in_wrong_phase(self):
        msg = self._make_msg(intent="VOTE_PLAYER")
        with pytest.raises(PhaseViolationError):
            validate_intent_for_phase(msg, GamePhase.INIT)

    def test_valid_phase_transition(self):
        validate_phase_transition(GamePhase.INIT, GamePhase.DAY_ZERO)

    def test_invalid_phase_transition(self):
        with pytest.raises(PhaseViolationError):
            validate_phase_transition(GamePhase.INIT, GamePhase.NIGHT)

    def test_handoff_expected_sender(self):
        msg = self._make_msg(sender="agent.orchestrator")
        validate_handoff(msg, expected_sender="agent.orchestrator")

    def test_handoff_wrong_sender(self):
        msg = self._make_msg(sender="agent.rogue")
        with pytest.raises(HandoffViolationError):
            validate_handoff(msg, expected_sender="agent.orchestrator")

    def test_no_voting_day_zero(self):
        msg = self._make_msg(intent="VOTE_PLAYER")
        with pytest.raises(PhaseViolationError):
            validate_no_voting_day_zero(msg, GamePhase.DAY_ZERO)

    def test_voting_allowed_after_day_zero(self):
        msg = self._make_msg(intent="VOTE_PLAYER")
        validate_no_voting_day_zero(msg, GamePhase.VOTING_STEP1)  # Should not raise
