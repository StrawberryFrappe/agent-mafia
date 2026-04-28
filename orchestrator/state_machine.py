"""State machine for the Mafia game phases.

Manages phase transitions, validation, and round tracking.
"""

from contracts.intents import GamePhase
from contracts.validator import validate_phase_transition


class GameStateMachine:
    """Tracks the current game phase and enforces valid transitions."""

    def __init__(self):
        self.current_phase: GamePhase = GamePhase.INIT
        self.round_number: int = 0
        self.day_number: int = 0
        self.night_number: int = 0
        self.phase_history: list[dict] = []

    def transition_to(self, next_phase: GamePhase) -> None:
        """Transition to a new phase. Validates the transition is legal.

        Raises PhaseViolationError if the transition is invalid.
        """
        validate_phase_transition(self.current_phase, next_phase)

        self.phase_history.append({
            "from": self.current_phase.value,
            "to": next_phase.value,
            "round": self.round_number,
        })

        self.current_phase = next_phase

        # Track day/night numbers
        if next_phase == GamePhase.DAY_ZERO:
            self.day_number = 0
        elif next_phase == GamePhase.DAY_TALK:
            self.day_number += 1
        elif next_phase == GamePhase.NIGHT:
            self.night_number += 1

        self.round_number += 1

    def can_transition_to(self, next_phase: GamePhase) -> bool:
        """Check if a transition is valid without raising."""
        try:
            validate_phase_transition(self.current_phase, next_phase)
            return True
        except Exception:
            return False

    def is_day_zero(self) -> bool:
        return self.current_phase == GamePhase.DAY_ZERO

    def is_night(self) -> bool:
        return self.current_phase == GamePhase.NIGHT

    def is_game_over(self) -> bool:
        return self.current_phase == GamePhase.GAME_OVER

    def get_state_summary(self) -> dict:
        return {
            "current_phase": self.current_phase.value,
            "round_number": self.round_number,
            "day_number": self.day_number,
            "night_number": self.night_number,
        }
