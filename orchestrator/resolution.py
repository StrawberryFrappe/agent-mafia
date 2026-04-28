"""Resolution logic for the Mafia game.

Handles:
- Night resolution (kill vs heal)
- Vote tallying
- Win condition checks
- Rebuttal mention detection
"""

import re
from collections import Counter

from agents.base_agent import Agent
from contracts.intents import Role


def _extract_last_mentioned_target(
    text: str, 
    agents: list[Agent],
    none_patterns: list[str] = None,
    self_patterns: list[str] = None
) -> str | None:
    """Find the last mentioned agent or pattern in the text.
    
    This handles cases where an agent mentions multiple names (e.g. reasoning)
    but makes their final decision at the end.
    """
    text_lower = text.lower()
    mentions = []
    
    for agent in agents:
        # Check full name first
        idx = text_lower.rfind(agent.display_name.lower())
        if idx != -1:
            mentions.append((idx, agent.display_name))
            continue
            
        # Check first name
        first_name = agent.display_name.split()[0].lower()
        if len(first_name) > 2:
            matches = list(re.finditer(r'\b' + re.escape(first_name) + r'\b', text_lower))
            if matches:
                last_match_idx = matches[-1].start()
                mentions.append((last_match_idx, agent.display_name))
                
    if none_patterns:
        for pattern in none_patterns:
            matches = list(re.finditer(r'\b' + re.escape(pattern) + r'\b', text_lower))
            if matches:
                mentions.append((matches[-1].start(), None))
                
    if self_patterns:
        for pattern in self_patterns:
            matches = list(re.finditer(r'\b' + re.escape(pattern) + r'\b', text_lower))
            if matches:
                mentions.append((matches[-1].start(), "self"))

    if mentions:
        mentions.sort(key=lambda x: x[0], reverse=True)
        return mentions[0][1]
        
    return None


def resolve_night(
    kill_target: str | None,
    heal_target: str | None,
) -> dict:
    """Resolve the night phase.

    Args:
        kill_target: Name of the agent targeted for kill, or None for KILL_NONE.
        heal_target: Name of the agent healed, or None for HEAL_NONE.

    Returns:
        Dict with resolution details:
        - killed: Name of killed agent or None
        - healed: Whether the target was saved
        - kill_target: Original kill target
        - heal_target: Original heal target
    """
    if kill_target is None:
        return {
            "killed": None,
            "healed": False,
            "kill_target": None,
            "heal_target": heal_target,
        }

    if kill_target == heal_target:
        return {
            "killed": None,
            "healed": True,
            "kill_target": kill_target,
            "heal_target": heal_target,
        }

    return {
        "killed": kill_target,
        "healed": False,
        "kill_target": kill_target,
        "heal_target": heal_target,
    }


def tally_votes(votes: list[dict]) -> dict:
    """Tally votes and determine if there's a majority.

    Args:
        votes: List of dicts with keys: voter, target, justification

    Returns:
        Dict with:
        - counts: Counter of target -> vote count
        - total_voters: Number of voters
        - majority_target: Name of player with >50% or None
        - majority_reached: Boolean
    """
    targets = [v["target"] for v in votes if v["target"] and v["target"] != "no one"]
    counts = Counter(targets)
    total_voters = len(votes)

    majority_target = None
    majority_reached = False

    for target, count in counts.most_common(1):
        if count > total_voters / 2:
            majority_target = target
            majority_reached = True

    return {
        "counts": dict(counts),
        "total_voters": total_voters,
        "majority_target": majority_target,
        "majority_reached": majority_reached,
        "votes": votes,
    }


def check_win_condition(alive_agents: list[Agent]) -> dict | None:
    """Check if a win condition has been met.

    Args:
        alive_agents: List of currently alive agents.

    Returns:
        Dict with winner and reason, or None if game continues.
    """
    mafia_alive = sum(1 for a in alive_agents if a.role == Role.MAFIA)
    town_alive = sum(1 for a in alive_agents if a.role != Role.MAFIA)

    # Mafia wins: Mafia >= 50% of alive agents
    if mafia_alive >= town_alive:
        return {
            "winner": "MAFIA",
            "reason": (
                f"Mafia has achieved numerical dominance "
                f"({mafia_alive} Mafia vs {town_alive} Town)."
            ),
        }

    # Town wins: All Mafia eliminated
    if mafia_alive == 0:
        return {
            "winner": "TOWN",
            "reason": "All Mafia members have been eliminated. The town is safe.",
        }

    return None


def detect_mentions(
    speaker_text: str,
    alive_agents: list[Agent],
    speaker_name: str,
) -> list[str]:
    """Detect if a speaker mentions any other alive agent by display name.

    Args:
        speaker_text: The text spoken by the agent.
        alive_agents: List of alive agents.
        speaker_name: Display name of the speaking agent.

    Returns:
        List of display names that were mentioned.
    """
    mentioned = []
    text_lower = speaker_text.lower()

    for agent in alive_agents:
        if agent.display_name == speaker_name:
            continue
        # Check for full name or first name mention
        if agent.display_name.lower() in text_lower:
            mentioned.append(agent.display_name)
            continue
        # Check first name
        first_name = agent.display_name.split()[0].lower()
        if len(first_name) > 2:  # Avoid matching very short names
            # Use word boundary to avoid partial matches
            if re.search(r'\b' + re.escape(first_name) + r'\b', text_lower):
                mentioned.append(agent.display_name)

    return mentioned


def parse_vote_target(
    vote_text: str,
    alive_agents: list[Agent],
) -> tuple[str | None, str]:
    """Parse an agent's vote response to extract target and justification.

    Args:
        vote_text: Raw text from the agent's vote response.
        alive_agents: List of alive agents to match against.

    Returns:
        Tuple of (target_name or None, justification string)
    """
    none_patterns = ["no one", "nobody", "abstain", "pass", "skip"]
    target = _extract_last_mentioned_target(vote_text, alive_agents, none_patterns=none_patterns)
    return target, vote_text


def parse_night_action(
    action_text: str,
    alive_agents: list[Agent],
    is_mafia: bool = False,
) -> dict:
    """Parse a night action response to extract the target.

    Args:
        action_text: Raw text from the agent's night action.
        alive_agents: List of alive agents.
        is_mafia: Whether this is a Mafia kill action.

    Returns:
        Dict with action details (target, action_type).
    """
    none_patterns = ["kill none", "heal none", "no one", "nobody", "skip", "pass"]
    self_patterns = [] if is_mafia else ["heal myself", "heal self", "protect myself", "save myself", "myself"]
    
    target = _extract_last_mentioned_target(
        action_text, 
        alive_agents, 
        none_patterns=none_patterns, 
        self_patterns=self_patterns
    )
    
    if target == "self":
        return {"action_type": "HEAL_SELF", "target": "self"}
    elif target is None:
        action_type = "KILL_NONE" if is_mafia else "HEAL_NONE"
        return {"action_type": action_type, "target": None}
    else:
        action_type = "KILL_TARGET" if is_mafia else "HEAL_TARGET"
        return {"action_type": action_type, "target": target}


def parse_sheriff_investigation(
    action_text: str,
    alive_agents: list[Agent],
) -> str | None:
    """Parse a Sheriff's night action to extract the investigation target.

    Args:
        action_text: Raw text from the agent's night action.
        alive_agents: List of alive agents.

    Returns:
        The target agent's display name, or None if no valid target.
    """
    none_patterns = ["investigate none", "no one", "nobody", "skip", "pass"]
    return _extract_last_mentioned_target(action_text, alive_agents, none_patterns=none_patterns)


def parse_sentence_vote(vote_text: str) -> str:
    """Parse a sentence vote as guilty or not_guilty.

    Args:
        vote_text: Raw text from the agent's sentence vote.

    Returns:
        'guilty' or 'not_guilty'
    """
    text_lower = vote_text.lower()
    
    guilty_patterns = ["guilty", "hang", "execute", "lynch", "condemn", "punish"]
    not_guilty_patterns = ["not guilty", "innocent", "spare", "free", "acquit", "mercy"]
    
    mentions = []
    
    for pattern in not_guilty_patterns:
        matches = list(re.finditer(r'\b' + re.escape(pattern) + r'\b', text_lower))
        if matches:
            mentions.append((matches[-1].start(), "not_guilty"))
            
    for pattern in guilty_patterns:
        # Ensure we don't match "guilty" when it's part of "not guilty"
        matches = list(re.finditer(r'(?<!not\s)\b' + re.escape(pattern) + r'\b', text_lower))
        if matches:
            mentions.append((matches[-1].start(), "guilty"))

    if mentions:
        mentions.sort(key=lambda x: x[0], reverse=True)
        return mentions[0][1]
        
    return "not_guilty"

