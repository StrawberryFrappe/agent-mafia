"""Agent factory for creating game agents with roles and personalities.

Handles:
- Random role assignment
- Random personality assignment from the 20-character pool
- Agent creation with proper initialization
"""

import random
from typing import Any

from agents.base_agent import Agent
from agents.personalities import PERSONALITIES, Personality
from contracts.intents import Role
from config import MAFIA_COUNT, DOCTOR_COUNT, TOTAL_PLAYERS


def create_agents(
    total_players: int = TOTAL_PLAYERS,
    mafia_count: int = MAFIA_COUNT,
    doctor_count: int = DOCTOR_COUNT,
    sheriff_count: int = 1,
    seed: int | None = None,
) -> list[Agent]:
    """Create all game agents with random roles and personalities.

    Args:
        total_players: Total number of players in the game.
        mafia_count: Number of Mafia agents.
        doctor_count: Number of Doctor agents (usually 1).
        seed: Optional random seed for reproducible games.

    Returns:
        List of initialized Agent instances.
    """
    if seed is not None:
        random.seed(seed)

    town_count = total_players - mafia_count - doctor_count - sheriff_count

    if town_count < 1:
        raise ValueError(
            f"Invalid player config: {total_players} total, "
            f"{mafia_count} mafia, {doctor_count} doctor, {sheriff_count} sheriff leaves {town_count} town"
        )

    # Build role list and shuffle
    roles: list[Role] = (
        [Role.MAFIA] * mafia_count
        + [Role.DOCTOR] * doctor_count
        + [Role.SHERIFF] * sheriff_count
        + [Role.TOWN] * town_count
    )
    random.shuffle(roles)

    # Pick random personalities from the pool
    available_personalities = list(PERSONALITIES)
    random.shuffle(available_personalities)
    selected_personalities = available_personalities[:total_players]

    # Create agents
    agents: list[Agent] = []
    role_counters: dict[str, int] = {}

    for i, (role, personality) in enumerate(zip(roles, selected_personalities)):
        # Generate logical name like "agent.mafia_1", "agent.town_2"
        role_key = role.value.lower()
        role_counters[role_key] = role_counters.get(role_key, 0) + 1
        logical_name = f"agent.{role_key}_{role_counters[role_key]}"

        # Initialize private context
        private_context: dict[str, Any] = {}
        if role == Role.DOCTOR:
            private_context["self_heal_used"] = False
        elif role == Role.MAFIA:
            private_context["night_chat_history"] = []

        agent = Agent(
            name=logical_name,
            display_name=personality.name,
            role=role,
            alive=True,
            personality=personality,
            conversation_history=[],
            private_context=private_context,
        )

        agents.append(agent)

    # Give Mafia agents knowledge of each other
    mafia_agents = [a for a in agents if a.role == Role.MAFIA]
    mafia_names = [f"{a.display_name} ({a.name})" for a in mafia_agents]

    for agent in mafia_agents:
        agent.private_context["mafia_members"] = mafia_names

    return agents


def get_agents_by_role(agents: list[Agent], role: Role) -> list[Agent]:
    """Filter agents by role."""
    return [a for a in agents if a.role == role]


def get_alive_agents(agents: list[Agent]) -> list[Agent]:
    """Get all alive agents."""
    return [a for a in agents if a.alive]


def get_alive_by_role(agents: list[Agent], role: Role) -> list[Agent]:
    """Get alive agents of a specific role."""
    return [a for a in agents if a.alive and a.role == role]
