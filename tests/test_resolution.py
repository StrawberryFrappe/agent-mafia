"""Tests for resolution logic."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.resolution import (
    resolve_night,
    tally_votes,
    check_win_condition,
    detect_mentions,
    parse_vote_target,
    parse_night_action,
    parse_sentence_vote,
)
from agents.base_agent import Agent
from agents.personalities import PERSONALITIES
from contracts.intents import Role


def _make_agent(name, display_name, role, alive=True):
    return Agent(
        name=name,
        display_name=display_name,
        role=role,
        alive=alive,
        personality=PERSONALITIES[0],
    )


class TestNightResolution:
    def test_kill_no_heal(self):
        result = resolve_night("Alice", None)
        assert result["killed"] == "Alice"
        assert not result["healed"]

    def test_kill_different_heal(self):
        result = resolve_night("Alice", "Bob")
        assert result["killed"] == "Alice"
        assert not result["healed"]

    def test_kill_same_heal(self):
        result = resolve_night("Alice", "Alice")
        assert result["killed"] is None
        assert result["healed"]

    def test_no_kill(self):
        result = resolve_night(None, "Alice")
        assert result["killed"] is None
        assert not result["healed"]


class TestVoteTally:
    def test_majority(self):
        votes = [
            {"voter": "A", "target": "X", "justification": ""},
            {"voter": "B", "target": "X", "justification": ""},
            {"voter": "C", "target": "Y", "justification": ""},
        ]
        result = tally_votes(votes)
        assert result["majority_reached"]
        assert result["majority_target"] == "X"

    def test_no_majority(self):
        votes = [
            {"voter": "A", "target": "X", "justification": ""},
            {"voter": "B", "target": "Y", "justification": ""},
            {"voter": "C", "target": "Z", "justification": ""},
        ]
        result = tally_votes(votes)
        assert not result["majority_reached"]

    def test_no_one_votes(self):
        votes = [
            {"voter": "A", "target": "no one", "justification": ""},
            {"voter": "B", "target": "no one", "justification": ""},
        ]
        result = tally_votes(votes)
        assert not result["majority_reached"]


class TestWinCondition:
    def test_mafia_wins(self):
        agents = [
            _make_agent("a1", "M1", Role.MAFIA),
            _make_agent("a2", "T1", Role.TOWN),
        ]
        result = check_win_condition(agents)
        assert result is not None
        assert result["winner"] == "MAFIA"

    def test_town_wins(self):
        agents = [
            _make_agent("a1", "T1", Role.TOWN),
            _make_agent("a2", "T2", Role.TOWN),
            _make_agent("a3", "D1", Role.DOCTOR),
        ]
        result = check_win_condition(agents)
        assert result is not None
        assert result["winner"] == "TOWN"

    def test_game_continues(self):
        agents = [
            _make_agent("a1", "M1", Role.MAFIA),
            _make_agent("a2", "T1", Role.TOWN),
            _make_agent("a3", "T2", Role.TOWN),
            _make_agent("a4", "D1", Role.DOCTOR),
        ]
        result = check_win_condition(agents)
        assert result is None


class TestMentionDetection:
    def test_detects_full_name(self):
        agents = [
            _make_agent("a1", "Alice Johnson", Role.TOWN),
            _make_agent("a2", "Bob Smith", Role.TOWN),
        ]
        mentions = detect_mentions("I think Alice Johnson is suspicious", agents, "Bob Smith")
        assert "Alice Johnson" in mentions

    def test_detects_first_name(self):
        agents = [
            _make_agent("a1", "Alice Johnson", Role.TOWN),
            _make_agent("a2", "Bob Smith", Role.TOWN),
        ]
        mentions = detect_mentions("I think Alice is suspicious", agents, "Bob Smith")
        assert "Alice Johnson" in mentions

    def test_no_self_mention(self):
        agents = [
            _make_agent("a1", "Alice Johnson", Role.TOWN),
        ]
        mentions = detect_mentions("I am Alice", agents, "Alice Johnson")
        assert len(mentions) == 0


class TestParsing:
    def test_parse_vote_no_one(self):
        agents = [_make_agent("a1", "Alice", Role.TOWN)]
        target, _ = parse_vote_target("I vote for no one today", agents)
        assert target is None

    def test_parse_vote_target(self):
        agents = [
            _make_agent("a1", "Alice Johnson", Role.TOWN),
            _make_agent("a2", "Bob Smith", Role.TOWN),
        ]
        target, _ = parse_vote_target("I vote for Alice Johnson", agents)
        assert target == "Alice Johnson"

    def test_parse_sentence_guilty(self):
        assert parse_sentence_vote("GUILTY! Hang them!") == "guilty"

    def test_parse_sentence_not_guilty(self):
        assert parse_sentence_vote("I believe they are not guilty") == "not_guilty"

    def test_parse_night_kill(self):
        agents = [_make_agent("a1", "Alice", Role.TOWN)]
        result = parse_night_action("Let's kill Alice tonight", agents, is_mafia=True)
        assert result["action_type"] == "KILL_TARGET"
        assert result["target"] == "Alice"

    def test_parse_night_heal_self(self):
        agents = [_make_agent("a1", "Doctor", Role.DOCTOR)]
        result = parse_night_action("I'll heal myself tonight", agents, is_mafia=False)
        assert result["action_type"] == "HEAL_SELF"
