"""Intent definitions for the Mafia game message contract."""

from enum import Enum


class Intent(str, Enum):
    """All possible message intents in the game protocol."""

    # Phase 0: Initialization
    ASSIGN_ROLE = "ASSIGN_ROLE"
    DAY_INTRO = "DAY_INTRO"

    # Phase 1: Night
    NIGHT_CHAT = "NIGHT_CHAT"
    NIGHT_ACTION = "NIGHT_ACTION"
    KILL_TARGET = "KILL_TARGET"
    KILL_NONE = "KILL_NONE"
    HEAL_TARGET = "HEAL_TARGET"
    HEAL_NONE = "HEAL_NONE"
    HEAL_SELF = "HEAL_SELF"
    UPDATE_NOTEPAD = "UPDATE_NOTEPAD"

    # Phase 2: Dawn
    DAWN_RESOLUTION = "DAWN_RESOLUTION"

    # Phase 3: Day Talk
    DAY_TALK = "DAY_TALK"
    REBUTTAL = "REBUTTAL"
    COUNTER_REBUTTAL = "COUNTER_REBUTTAL"
    FINAL_CLOSURE = "FINAL_CLOSURE"
    IGNORED_MENTION = "IGNORED_MENTION"

    # Phase 4: Voting
    VOTE_PLAYER = "VOTE_PLAYER"
    VOTE_CHANGE = "VOTE_CHANGE"
    VOTE_CONFIRM = "VOTE_CONFIRM"

    # Phase 5: Trial & Sentencing
    STATE_DEFENSE = "STATE_DEFENSE"
    SENTENCE_VOTE = "SENTENCE_VOTE"
    FINAL_WORDS = "FINAL_WORDS"

    # System
    GAME_OVER = "GAME_OVER"
    ERROR = "ERROR"
    SYSTEM_ANNOUNCEMENT = "SYSTEM_ANNOUNCEMENT"


class MessageState(str, Enum):
    """Valid states for a message in the handoff protocol."""

    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(str, Enum):
    """Granular event types for the agent_message_events table."""

    MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
    MESSAGE_SENT = "MESSAGE_SENT"
    HANDOFF_PAUSED = "HANDOFF_PAUSED"
    HANDOFF_RESUMED = "HANDOFF_RESUMED"
    VOTE_LOCKED = "VOTE_LOCKED"
    VOTE_CHANGED = "VOTE_CHANGED"
    REBUTTAL_TRIGGERED = "REBUTTAL_TRIGGERED"
    IGNORED_MENTION = "IGNORED_MENTION"
    AGENT_ELIMINATED = "AGENT_ELIMINATED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"
    NIGHT_ACTION_RESOLVED = "NIGHT_ACTION_RESOLVED"
    PHASE_TRANSITION = "PHASE_TRANSITION"
    API_ERROR = "API_ERROR"
    API_RETRY = "API_RETRY"
    WIN_CONDITION_MET = "WIN_CONDITION_MET"


class GamePhase(str, Enum):
    """State machine phases for the game."""

    INIT = "INIT"
    DAY_ZERO = "DAY_ZERO"
    NIGHT = "NIGHT"
    DAWN = "DAWN"
    DAY_TALK = "DAY_TALK"
    VOTING_STEP1 = "VOTING_STEP1"
    VOTING_STEP2 = "VOTING_STEP2"
    TRIAL = "TRIAL"
    SENTENCING = "SENTENCING"
    GAME_OVER = "GAME_OVER"


class Role(str, Enum):
    """Agent roles in the game."""

    MAFIA = "MAFIA"
    DOCTOR = "DOCTOR"
    SHERIFF = "SHERIFF"
    TOWN = "TOWN"
