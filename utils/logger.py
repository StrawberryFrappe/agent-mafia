"""Colored terminal logger for the Mafia game.

Provides themed output with phase headers, speech bubbles,
death announcements, and debug contract dumps.
"""

import json
import sys
from datetime import datetime
from enum import Enum

from colorama import Fore, Back, Style, init as colorama_init

from contracts.intents import GamePhase, Role

# Initialize colorama for cross-platform support
colorama_init(autoreset=True)


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    GAME = "GAME"


# Color mapping for roles
ROLE_COLORS = {
    Role.MAFIA.value: Fore.RED,
    Role.DOCTOR.value: Fore.GREEN,
    Role.TOWN.value: Fore.CYAN,
    "ORCHESTRATOR": Fore.YELLOW,
}

# Color mapping for phases
PHASE_COLORS = {
    GamePhase.INIT.value: Fore.WHITE,
    GamePhase.DAY_ZERO.value: Fore.LIGHTYELLOW_EX,
    GamePhase.NIGHT.value: Fore.BLUE,
    GamePhase.DAWN.value: Fore.LIGHTYELLOW_EX,
    GamePhase.DAY_TALK.value: Fore.LIGHTWHITE_EX,
    GamePhase.VOTING_STEP1.value: Fore.MAGENTA,
    GamePhase.VOTING_STEP2.value: Fore.MAGENTA,
    GamePhase.TRIAL.value: Fore.LIGHTRED_EX,
    GamePhase.SENTENCING.value: Fore.RED,
    GamePhase.GAME_OVER.value: Fore.LIGHTYELLOW_EX,
}

# Subscribers for web UI broadcasting
_subscribers: list = []


def subscribe(callback) -> None:
    """Register a callback for log events (used by web UI)."""
    _subscribers.append(callback)


def unsubscribe(callback) -> None:
    """Remove a log event callback."""
    if callback in _subscribers:
        _subscribers.remove(callback)


def _broadcast(event: dict) -> None:
    """Send log event to all subscribers."""
    for cb in _subscribers:
        try:
            cb(event)
        except Exception:
            pass


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def phase_header(phase: str, round_number: int = 0) -> None:
    """Print a prominent phase transition header."""
    color = PHASE_COLORS.get(phase, Fore.WHITE)
    separator = "=" * 60
    label = f" {phase.replace('_', ' ')} "
    if round_number > 0:
        label += f"(Round {round_number}) "

    print(f"\n{color}{separator}")
    print(f"{color}{label:=^60}")
    print(f"{color}{separator}{Style.RESET_ALL}\n")

    _broadcast({
        "type": "phase",
        "phase": phase,
        "round": round_number,
        "timestamp": _timestamp(),
    })


def agent_speak(
    agent_name: str,
    display_name: str,
    role: str,
    text: str,
    intent: str = "",
) -> None:
    """Print an agent's speech with role-colored formatting."""
    color = ROLE_COLORS.get(role, Fore.WHITE)
    prefix = f"[{_timestamp()}] {color}{display_name}{Style.RESET_ALL}"

    if intent:
        prefix += f" {Fore.LIGHTBLACK_EX}({intent}){Style.RESET_ALL}"

    print(f"{prefix}: {text}")

    _broadcast({
        "type": "speak",
        "agent": agent_name,
        "display_name": display_name,
        "role": role,
        "text": text,
        "intent": intent,
        "timestamp": _timestamp(),
    })


def system_message(text: str) -> None:
    """Print a system/orchestrator announcement."""
    print(
        f"[{_timestamp()}] {Fore.YELLOW}{Style.BRIGHT}[SYSTEM]{Style.RESET_ALL} {text}"
    )
    _broadcast({
        "type": "system",
        "text": text,
        "timestamp": _timestamp(),
    })


def death_announcement(display_name: str, role: str, cause: str = "lynched") -> None:
    """Print a dramatic death announcement."""
    color = ROLE_COLORS.get(role, Fore.WHITE)
    skull = "DEATH"
    print(
        f"\n{Fore.RED}{Style.BRIGHT}  [{skull}] {display_name} "
        f"has been {cause}! They were {color}{role}{Fore.RED}.{Style.RESET_ALL}\n"
    )
    _broadcast({
        "type": "death",
        "display_name": display_name,
        "role": role,
        "cause": cause,
        "timestamp": _timestamp(),
    })


def vote_display(voter: str, target: str, justification: str = "") -> None:
    """Print a vote action."""
    msg = f"[{_timestamp()}] {Fore.MAGENTA}[VOTE]{Style.RESET_ALL} {voter} votes for {target}"
    if justification:
        msg += f" -- \"{justification}\""
    print(msg)
    _broadcast({
        "type": "vote",
        "voter": voter,
        "target": target,
        "justification": justification,
        "timestamp": _timestamp(),
    })


def error_log(text: str) -> None:
    """Print an error message."""
    print(f"[{_timestamp()}] {Fore.RED}{Style.BRIGHT}[ERROR]{Style.RESET_ALL} {text}")
    _broadcast({
        "type": "error",
        "text": text,
        "timestamp": _timestamp(),
    })


def debug_log(text: str, data: dict | None = None) -> None:
    """Print debug info (only when DEBUG_MODE is on)."""
    from config import DEBUG_MODE

    if not DEBUG_MODE:
        return

    print(f"[{_timestamp()}] {Fore.LIGHTBLACK_EX}[DEBUG] {text}{Style.RESET_ALL}")
    if data:
        print(
            f"{Fore.LIGHTBLACK_EX}{json.dumps(data, indent=2, ensure_ascii=False)}"
            f"{Style.RESET_ALL}"
        )


def win_announcement(winner: str, reason: str) -> None:
    """Print the game-over win announcement."""
    trophy = "VICTORY"
    color = Fore.RED if winner == "MAFIA" else Fore.CYAN

    print(f"\n{'*' * 60}")
    print(f"{color}{Style.BRIGHT}  [{trophy}] {winner} WINS!{Style.RESET_ALL}")
    print(f"  {reason}")
    print(f"{'*' * 60}\n")

    _broadcast({
        "type": "win",
        "winner": winner,
        "reason": reason,
        "timestamp": _timestamp(),
    })
