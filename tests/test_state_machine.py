"""Tests for the game state machine."""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.state_machine import GameStateMachine
from contracts.intents import GamePhase
from contracts.validator import PhaseViolationError


class TestStateMachine:
    def test_initial_state(self):
        sm = GameStateMachine()
        assert sm.current_phase == GamePhase.INIT

    def test_valid_transition_chain(self):
        sm = GameStateMachine()
        sm.transition_to(GamePhase.DAY_ZERO)
        assert sm.current_phase == GamePhase.DAY_ZERO

        sm.transition_to(GamePhase.NIGHT)
        assert sm.current_phase == GamePhase.NIGHT
        assert sm.night_number == 1

        sm.transition_to(GamePhase.DAWN)
        sm.transition_to(GamePhase.DAY_TALK)
        assert sm.day_number == 1

        sm.transition_to(GamePhase.VOTING_STEP1)
        sm.transition_to(GamePhase.VOTING_STEP2)

    def test_invalid_transition_raises(self):
        sm = GameStateMachine()
        with pytest.raises(PhaseViolationError):
            sm.transition_to(GamePhase.NIGHT)  # Can't skip DAY_ZERO

    def test_cannot_skip_phases(self):
        sm = GameStateMachine()
        with pytest.raises(PhaseViolationError):
            sm.transition_to(GamePhase.DAY_TALK)

    def test_can_transition_to(self):
        sm = GameStateMachine()
        assert sm.can_transition_to(GamePhase.DAY_ZERO)
        assert not sm.can_transition_to(GamePhase.NIGHT)

    def test_phase_history_tracking(self):
        sm = GameStateMachine()
        sm.transition_to(GamePhase.DAY_ZERO)
        sm.transition_to(GamePhase.NIGHT)
        assert len(sm.phase_history) == 2
        assert sm.phase_history[0]["from"] == "INIT"
        assert sm.phase_history[0]["to"] == "DAY_ZERO"

    def test_game_over_from_dawn(self):
        sm = GameStateMachine()
        sm.transition_to(GamePhase.DAY_ZERO)
        sm.transition_to(GamePhase.NIGHT)
        sm.transition_to(GamePhase.DAWN)
        sm.transition_to(GamePhase.GAME_OVER)
        assert sm.is_game_over()

    def test_voting_to_trial(self):
        sm = GameStateMachine()
        sm.transition_to(GamePhase.DAY_ZERO)
        sm.transition_to(GamePhase.NIGHT)
        sm.transition_to(GamePhase.DAWN)
        sm.transition_to(GamePhase.DAY_TALK)
        sm.transition_to(GamePhase.VOTING_STEP1)
        sm.transition_to(GamePhase.VOTING_STEP2)
        sm.transition_to(GamePhase.TRIAL)
        sm.transition_to(GamePhase.SENTENCING)
        assert sm.current_phase == GamePhase.SENTENCING
