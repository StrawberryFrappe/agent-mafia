"""Base Agent class for the Mafia game.

Agents are data containers. They do NOT call the LLM directly.
The Orchestrator acts on their behalf through the MCP bridge.
"""

from dataclasses import dataclass, field
from typing import Any

from contracts.intents import Role
from agents.personalities import Personality


@dataclass
class Agent:
    """Represents a player in the Mafia game.

    Attributes:
        name: Logical identifier (e.g., "agent.mafia_1")
        display_name: Human-readable name from personality
        role: MAFIA, DOCTOR, or TOWN
        alive: Whether the agent is still in the game
        personality: The personality profile assigned to this agent
        conversation_history: Full message history for LLM context
        private_context: Role-specific private data
        vote_changed_this_phase: Whether agent has used their vote change
    """

    name: str
    display_name: str
    role: Role
    alive: bool = True
    personality: Personality | None = None
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    private_context: dict[str, Any] = field(default_factory=dict)
    vote_changed_this_phase: bool = False
    notepad: str = ""

    @property
    def role_system_prompt(self) -> str:
        """Generate the role-specific system prompt."""
        from config import MAX_RESPONSE_CHARS

        base = (
            "You are playing a game of Mafia (Town of Salem style). "
            "You must stay in character at all times. "
            "You will receive messages from the game orchestrator and must respond "
            "ONLY with your character's speech/action. "
            "Do NOT break character or discuss game mechanics directly. "
            f"HARD LIMIT: Keep responses under {MAX_RESPONSE_CHARS} characters. "
            "Be concise: 2-4 sentences max. Talk like a real person in a real game, "
            "not an essay writer.\n\n"
        )

        if self.role == Role.MAFIA:
            return base + (
                "YOUR ROLE: MAFIA\n"
                "You are a member of the Mafia. Your goal is to eliminate all Town members "
                "without being discovered. During the day, you must act like an innocent "
                "townsperson. During night chat with other Mafia, coordinate your kills. "
                "Be strategic: deflect suspicion, cast doubt on others, and protect your "
                "fellow Mafia members. You know who the other Mafia members are.\n"
                "CRITICAL: Never reveal that you are Mafia during the day. "
                "If accused, defend yourself convincingly."
            )
        elif self.role == Role.DOCTOR:
            return base + (
                "YOUR ROLE: DOCTOR\n"
                "You are the Doctor. Each night, you choose one player to heal (protect "
                "from being killed). If the Mafia targets the player you heal, they survive. "
                "You can heal yourself ONCE per game. Use this ability wisely. "
                "During the day, you are a regular townsperson. You may or may not reveal "
                "your role depending on strategy.\n"
                "CRITICAL: Be careful about claiming Doctor publicly, as the Mafia will "
                "target you if they know."
            )
        elif self.role == Role.SHERIFF:
            return base + (
                "YOUR ROLE: SHERIFF\n"
                "You are the Sheriff. Each night, you investigate one player to determine "
                "if they are MAFIA or NOT MAFIA. You work independently for the town. "
                "Use your investigations to find the Mafia and convince the town during the day. "
                "During the day, you are a regular townsperson. You may reveal your role "
                "if you think it will help hang a Mafia member, but be careful of drawing "
                "Mafia attention.\n"
                "CRITICAL: Trust your investigations and keep track of who you have cleared or caught."
            )
        else:
            return base + (
                "YOUR ROLE: TOWN\n"
                "You are a regular Townsperson. Your goal is to identify and eliminate all "
                "Mafia members through discussion and voting. Pay attention to behavioral "
                "patterns, contradictions, and suspicious statements. "
                "During the day, discuss and vote. You have no special night abilities.\n"
                "CRITICAL: Work with other town members to find the Mafia. "
                "Be wary of false accusations that might help the Mafia."
            )

    @property
    def character_system_prompt(self) -> str:
        """Generate the character/personality system prompt."""
        if not self.personality:
            return ""

        return (
            f"YOUR CHARACTER: {self.personality.name}\n"
            f"BACKSTORY: {self.personality.backstory}\n"
            f"PERSONALITY: {self.personality.personality}\n"
            f"SPEAKING STYLE: {self.personality.speaking_style}\n"
            f"SUSPICION PATTERNS: {self.personality.suspicion_bias}\n\n"
            "Stay true to this character in ALL responses. Your speech patterns, "
            "reasoning style, and emotional reactions should reflect this personality."
        )

    @property
    def full_system_prompt(self) -> str:
        """Combined role + character system prompt + notepad."""
        parts = [self.role_system_prompt]
        char_prompt = self.character_system_prompt
        if char_prompt:
            parts.append(char_prompt)
        
        if self.notepad:
            parts.append(f"YOUR PRIVATE NOTEPAD (MEMORIES & SUSPICIONS):\n{self.notepad}\n\n"
                         "Use these memories to inform your decisions. Only you can see this.")
            
        return "\n\n---\n\n".join(parts)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the agent's conversation history."""
        self.conversation_history.append({"role": role, "content": content})

    def add_user_message(self, content: str) -> None:
        """Add a user/orchestrator message to history."""
        self.add_message("user", content)

    def add_assistant_message(self, content: str) -> None:
        """Add the agent's own response to history."""
        self.add_message("assistant", content)

    def get_messages_json(self) -> str:
        """Get conversation history as JSON string for MCP call."""
        import json
        return json.dumps(self.conversation_history, ensure_ascii=False)

    def reset_vote_change(self) -> None:
        """Reset vote change tracking for a new voting phase."""
        self.vote_changed_this_phase = False

    def clear_history(self) -> None:
        """Clear conversation history (used between major phases if needed)."""
        self.conversation_history.clear()

    def get_context_summary(self, include_private: bool = False) -> dict:
        """Get a summary of the agent's current state."""
        summary = {
            "name": self.name,
            "display_name": self.display_name,
            "role": self.role.value if include_private else "HIDDEN",
            "alive": self.alive,
        }
        if include_private:
            summary["private_context"] = self.private_context
        return summary
