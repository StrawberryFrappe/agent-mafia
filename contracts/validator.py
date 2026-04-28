"""Message contract validator for the Mafia game protocol.

Enforces:
- All mandatory fields present and typed correctly
- sender/receiver match expected flow for current phase
- state transitions are valid
- No stage skipping
"""

from contracts.intents import Intent, MessageState, GamePhase
from contracts.message import GameMessage
from config import CONTRACT_VERSION


# Defines which intents are allowed per phase
PHASE_ALLOWED_INTENTS: dict[GamePhase, set[str]] = {
    GamePhase.INIT: {
        Intent.ASSIGN_ROLE.value,
        Intent.SYSTEM_ANNOUNCEMENT.value,
    },
    GamePhase.DAY_ZERO: {
        Intent.DAY_INTRO.value,
        Intent.SYSTEM_ANNOUNCEMENT.value,
    },
    GamePhase.NIGHT: {
        Intent.NIGHT_CHAT.value,
        Intent.NIGHT_ACTION.value,
        Intent.UPDATE_NOTEPAD.value,
        Intent.KILL_TARGET.value,
        Intent.KILL_NONE.value,
        Intent.HEAL_TARGET.value,
        Intent.HEAL_NONE.value,
        Intent.HEAL_SELF.value,
        Intent.SYSTEM_ANNOUNCEMENT.value,
    },
    GamePhase.DAWN: {
        Intent.DAWN_RESOLUTION.value,
        Intent.SYSTEM_ANNOUNCEMENT.value,
    },
    GamePhase.DAY_TALK: {
        Intent.DAY_TALK.value,
        Intent.REBUTTAL.value,
        Intent.COUNTER_REBUTTAL.value,
        Intent.FINAL_CLOSURE.value,
        Intent.IGNORED_MENTION.value,
        Intent.SYSTEM_ANNOUNCEMENT.value,
    },
    GamePhase.VOTING_STEP1: {
        Intent.VOTE_PLAYER.value,
        Intent.SYSTEM_ANNOUNCEMENT.value,
    },
    GamePhase.VOTING_STEP2: {
        Intent.VOTE_CHANGE.value,
        Intent.VOTE_CONFIRM.value,
        Intent.SYSTEM_ANNOUNCEMENT.value,
    },
    GamePhase.TRIAL: {
        Intent.STATE_DEFENSE.value,
        Intent.SYSTEM_ANNOUNCEMENT.value,
    },
    GamePhase.SENTENCING: {
        Intent.SENTENCE_VOTE.value,
        Intent.FINAL_WORDS.value,
        Intent.SYSTEM_ANNOUNCEMENT.value,
    },
    GamePhase.GAME_OVER: {
        Intent.GAME_OVER.value,
        Intent.SYSTEM_ANNOUNCEMENT.value,
    },
}

# Valid phase transitions
VALID_TRANSITIONS: dict[GamePhase, list[GamePhase]] = {
    GamePhase.INIT: [GamePhase.DAY_ZERO],
    GamePhase.DAY_ZERO: [GamePhase.NIGHT],
    GamePhase.NIGHT: [GamePhase.DAWN],
    GamePhase.DAWN: [GamePhase.DAY_TALK, GamePhase.GAME_OVER],
    GamePhase.DAY_TALK: [GamePhase.VOTING_STEP1],
    GamePhase.VOTING_STEP1: [GamePhase.VOTING_STEP2],
    GamePhase.VOTING_STEP2: [GamePhase.TRIAL, GamePhase.NIGHT],
    GamePhase.TRIAL: [GamePhase.SENTENCING],
    GamePhase.SENTENCING: [GamePhase.NIGHT, GamePhase.GAME_OVER],
    GamePhase.GAME_OVER: [],
}


class ContractValidationError(Exception):
    """Raised when a message fails contract validation."""
    pass


class PhaseViolationError(Exception):
    """Raised when an intent is used in the wrong phase."""
    pass


class HandoffViolationError(Exception):
    """Raised when sender/receiver don't match expected handoff."""
    pass


def validate_message_structure(msg: GameMessage) -> None:
    """Validate that a message has all required fields with correct types.

    Raises ContractValidationError on failure.
    """
    if msg.version != CONTRACT_VERSION:
        raise ContractValidationError(
            f"Invalid version: {msg.version}, expected {CONTRACT_VERSION}"
        )

    required_strings = {
        "message_id": msg.message_id,
        "correlation_id": msg.correlation_id,
        "idempotency_key": msg.idempotency_key,
        "intent": msg.intent,
        "sender": msg.sender,
        "receiver": msg.receiver,
        "state": msg.state,
    }

    for field_name, value in required_strings.items():
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(
                f"Field '{field_name}' must be a non-empty string, got: {value!r}"
            )

    # Validate state is a known value
    valid_states = {s.value for s in MessageState}
    if msg.state not in valid_states:
        raise ContractValidationError(
            f"Invalid state: {msg.state}, must be one of {valid_states}"
        )

    if not isinstance(msg.context, dict):
        raise ContractValidationError(f"'context' must be dict, got {type(msg.context)}")

    if not isinstance(msg.payload, dict):
        raise ContractValidationError(f"'payload' must be dict, got {type(msg.payload)}")

    if not isinstance(msg.trace_history, list):
        raise ContractValidationError(
            f"'trace_history' must be list, got {type(msg.trace_history)}"
        )


def validate_intent_for_phase(msg: GameMessage, current_phase: GamePhase) -> None:
    """Validate that the message intent is allowed in the current game phase.

    Raises PhaseViolationError on failure.
    """
    # Error intents are always allowed
    if msg.intent == Intent.ERROR.value:
        return

    allowed = PHASE_ALLOWED_INTENTS.get(current_phase, set())
    if msg.intent not in allowed:
        raise PhaseViolationError(
            f"Intent '{msg.intent}' not allowed in phase '{current_phase.value}'. "
            f"Allowed: {allowed}"
        )


def validate_phase_transition(
    current_phase: GamePhase, next_phase: GamePhase
) -> None:
    """Validate that a phase transition is legal.

    Raises PhaseViolationError on invalid transition.
    """
    valid_next = VALID_TRANSITIONS.get(current_phase, [])
    if next_phase not in valid_next:
        raise PhaseViolationError(
            f"Cannot transition from '{current_phase.value}' to '{next_phase.value}'. "
            f"Valid transitions: {[p.value for p in valid_next]}"
        )


def validate_handoff(
    msg: GameMessage,
    expected_sender: str | None = None,
    expected_receiver: str | None = None,
) -> None:
    """Validate sender/receiver match expected handoff flow.

    Raises HandoffViolationError on mismatch.
    """
    if expected_sender and msg.sender != expected_sender:
        raise HandoffViolationError(
            f"Expected sender '{expected_sender}', got '{msg.sender}'"
        )
    if expected_receiver and msg.receiver != expected_receiver:
        raise HandoffViolationError(
            f"Expected receiver '{expected_receiver}', got '{msg.receiver}'"
        )


def validate_no_voting_day_zero(msg: GameMessage, current_phase: GamePhase) -> None:
    """Block all voting intents during Day 0.

    Raises PhaseViolationError if voting is attempted on Day 0.
    """
    voting_intents = {
        Intent.VOTE_PLAYER.value,
        Intent.VOTE_CHANGE.value,
        Intent.VOTE_CONFIRM.value,
        Intent.SENTENCE_VOTE.value,
    }
    if current_phase == GamePhase.DAY_ZERO and msg.intent in voting_intents:
        raise PhaseViolationError("Voting intents are blocked during Day 0")


def validate_full(
    msg: GameMessage,
    current_phase: GamePhase,
    expected_sender: str | None = None,
    expected_receiver: str | None = None,
) -> None:
    """Run all validations on a message.

    Raises appropriate exceptions on any failure.
    """
    validate_message_structure(msg)
    validate_intent_for_phase(msg, current_phase)
    validate_no_voting_day_zero(msg, current_phase)
    validate_handoff(msg, expected_sender, expected_receiver)
