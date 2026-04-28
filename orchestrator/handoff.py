"""Handoff logic for the strict agent communication protocol.

Enforces:
- No agent speaks without an explicit `state: received` message
- All messages go through the MCP bridge
- Contract validation on every message
- Retry logic with idempotency
"""

import asyncio
import json
import traceback

from fastmcp import Client

from agents.base_agent import Agent
from contracts.message import GameMessage, MessageBuilder
from contracts.intents import Intent, MessageState, EventType, GamePhase
from contracts.validator import validate_full
from persistence.database import GameDatabase
from config import MAX_API_RETRIES, RETRY_DELAY_SECONDS, MCP_SERVER_SCRIPT, MAX_RESPONSE_CHARS
from utils import logger


class HandoffManager:
    """Manages the strict handoff protocol between Orchestrator and Agents."""

    def __init__(self, db: GameDatabase, correlation_id: str):
        self.db = db
        self.correlation_id = correlation_id
        self._mcp_client: Client | None = None

    async def _get_mcp_client(self) -> Client:
        """Get or create the MCP client connection."""
        if self._mcp_client is None:
            self._mcp_client = Client(MCP_SERVER_SCRIPT)
        return self._mcp_client

    async def send_and_receive(
        self,
        agent: Agent,
        intent: Intent,
        context: dict,
        payload: dict,
        current_phase: GamePhase,
        round_number: int = 0,
        trace_history: list | None = None,
    ) -> tuple[GameMessage, str]:
        """Send a handoff message to an agent and get their response via MCP.

        This is the core handoff flow:
        1. Build outgoing message (state: received)
        2. Validate contract
        3. Store in DB + log event
        4. Call MCP bridge for agent's LLM response
        5. Build response message (state: completed)
        6. Validate + store response
        7. Return both message and raw text

        Returns:
            Tuple of (response GameMessage, raw text from LLM)
        """
        # Step 1: Build outgoing message
        outgoing = (
            MessageBuilder(self.correlation_id)
            .intent(intent)
            .sender("agent.orchestrator")
            .receiver(agent.name)
            .state(MessageState.RECEIVED)
            .context(context)
            .payload(payload)
            .trace_history(trace_history or [])
            .idempotency_key(f"{intent.value}_{agent.name}_round{round_number}")
            .build()
        )

        # Step 2: Validate contract
        validate_full(
            outgoing,
            current_phase,
            expected_sender="agent.orchestrator",
            expected_receiver=agent.name,
        )

        # Step 3: Store + log
        await self.db.store_message(outgoing)
        await self.db.log_event(
            outgoing.message_id,
            EventType.MESSAGE_SENT,
            {"intent": intent.value, "receiver": agent.name},
        )

        # Step 4: Add orchestrator message to agent's conversation history
        prompt_text = self._build_prompt_text(intent, context, payload)
        agent.add_user_message(prompt_text)

        # Step 5: Call MCP for LLM response with retries
        response_text = await self._call_mcp_with_retry(agent, outgoing.message_id)

        # Step 6: Add response to agent's history
        agent.add_assistant_message(response_text)

        # Step 7: Build response message
        response_msg = (
            MessageBuilder(self.correlation_id)
            .intent(intent)
            .sender(agent.name)
            .receiver("agent.orchestrator")
            .state(MessageState.COMPLETED)
            .context(context)
            .payload({"text": response_text})
            .trace_history((trace_history or []) + [EventType.MESSAGE_RECEIVED.value])
            .build()
        )

        # Step 8: Store response
        await self.db.store_message(response_msg)
        await self.db.log_event(
            response_msg.message_id,
            EventType.MESSAGE_RECEIVED,
            {"intent": intent.value, "sender": agent.name},
        )

        return response_msg, response_text

    async def _call_mcp_with_retry(
        self, agent: Agent, message_id: str
    ) -> str:
        """Call the MCP bridge with retry logic.

        On total failure after MAX_API_RETRIES, returns a blank/pass action.
        """
        last_error = ""

        for attempt in range(1, MAX_API_RETRIES + 1):
            try:
                client = await self._get_mcp_client()

                async with client:
                    result = await client.call_tool(
                        "chat_completion",
                        {
                            "agent_name": agent.name,
                            "system_prompt": agent.full_system_prompt,
                            "messages_json": agent.get_messages_json(),
                            "temperature": agent.personality.temperature
                            if agent.personality
                            else 0.7,
                        },
                    )

                # Handle CallToolResult or similar objects from fastmcp
                if hasattr(result, 'content') and hasattr(result.content, '__iter__'):
                    parts = []
                    for item in result.content:
                        if hasattr(item, 'text'):
                            parts.append(item.text)
                        else:
                            parts.append(str(item))
                    response_text = ''.join(parts)
                elif hasattr(result, '__iter__') and not isinstance(result, str):
                    parts = []
                    for item in result:
                        if hasattr(item, 'text'):
                            parts.append(item.text)
                        else:
                            parts.append(str(item))
                    response_text = ''.join(parts)
                else:
                    response_text = str(result)

                try:
                    parsed = json.loads(response_text)
                    if isinstance(parsed, dict) and parsed.get("error"):
                        raise RuntimeError(parsed.get("message", "Unknown API error"))
                except json.JSONDecodeError:
                    pass  # Not JSON = actual response text, which is good

                if response_text.strip():
                    return self._truncate_response(response_text.strip())

                # If informational intent, accept empty responses to avoid retry spam
                if intent in [Intent.ASSIGN_ROLE, Intent.SYSTEM_ANNOUNCEMENT]:
                    return "*Nods silently in understanding.*"

                raise RuntimeError("Empty response from MCP bridge")

            except Exception as e:
                last_error = str(e)
                logger.error_log(
                    f"MCP call failed for {agent.display_name} "
                    f"(attempt {attempt}/{MAX_API_RETRIES}): {last_error}"
                )
                await self.db.log_event(
                    message_id,
                    EventType.API_RETRY,
                    {"attempt": attempt, "error": last_error},
                )

                if attempt < MAX_API_RETRIES:
                    await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

        # Total failure: return blank action
        logger.error_log(
            f"All {MAX_API_RETRIES} retries failed for {agent.display_name}. "
            f"Using blank response. Last error: {last_error}"
        )
        await self.db.log_event(
            message_id,
            EventType.API_ERROR,
            {"final_error": last_error, "action": "blank_fallback"},
        )

        return self._get_blank_response(agent)

    def _truncate_response(self, text: str) -> str:
        """Truncate response to MAX_RESPONSE_CHARS, cutting at sentence boundary."""
        if len(text) <= MAX_RESPONSE_CHARS:
            return text

        truncated = text[:MAX_RESPONSE_CHARS]

        # Try to cut at the last sentence-ending punctuation
        for punct in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
            last = truncated.rfind(punct)
            if last > MAX_RESPONSE_CHARS // 2:  # Don't cut too short
                return truncated[:last + 1].strip()

        # Fallback: cut at last space
        last_space = truncated.rfind(' ')
        if last_space > MAX_RESPONSE_CHARS // 2:
            return truncated[:last_space].strip() + "..."

        return truncated.strip() + "..."

    def _get_blank_response(self, agent: Agent) -> str:
        """Generate a blank/pass response when API is completely down."""
        return f"*{agent.display_name} remains silent, lost in thought.*"

    def _build_prompt_text(
        self, intent: Intent, context: dict, payload: dict
    ) -> str:
        """Build a human-readable prompt from intent, context, and payload."""
        parts = []

        # Intent-specific framing
        intent_frames = {
            Intent.ASSIGN_ROLE: "The game moderator assigns you your role.",
            Intent.DAY_INTRO: "It's the beginning of the day. Introduce yourself to the town.",
            Intent.NIGHT_CHAT: "It's nighttime. You're meeting with your fellow Mafia members in secret.",
            Intent.NIGHT_ACTION: "It's nighttime. Choose your action.",
            Intent.DAY_TALK: "It's daytime discussion. Share your thoughts with the town.",
            Intent.REBUTTAL: "You've been mentioned by another player. Respond to what they said.",
            Intent.COUNTER_REBUTTAL: "The player you mentioned has responded. Give your counter-argument.",
            Intent.FINAL_CLOSURE: "You have the final word on this exchange.",
            Intent.VOTE_PLAYER: "It's time to vote. Who do you want to vote for, and why?",
            Intent.VOTE_CHANGE: "You may change or confirm your vote.",
            Intent.STATE_DEFENSE: "You're on trial! Defend yourself to the town.",
            Intent.SENTENCE_VOTE: "Vote guilty or not guilty on the accused.",
            Intent.FINAL_WORDS: "You've been sentenced. Any last words?",
            Intent.DAWN_RESOLUTION: "Dawn breaks over the town.",
        }

        frame = intent_frames.get(intent, f"[{intent.value}]")
        parts.append(frame)

        # Add context info
        if context:
            if "alive_players" in context:
                names = context["alive_players"]
                parts.append(f"Alive players: {', '.join(names)}")
            if "previous_votes" in context:
                parts.append(f"Previous votes: {json.dumps(context['previous_votes'])}")
            if "mentioned_by" in context:
                parts.append(f"{context['mentioned_by']} mentioned you.")
            if "mention_text" in context:
                parts.append(f'They said: "{context["mention_text"]}"')
            if "accusation" in context:
                parts.append(f"Accusation: {context['accusation']}")
            if "night_chat" in context:
                parts.append(f"Mafia chat history:\n{context['night_chat']}")
            if "kill_result" in context:
                parts.append(context["kill_result"])

        # Add payload text
        if payload and payload.get("text"):
            parts.append(payload["text"])

        return "\n\n".join(parts)

    async def broadcast_system(
        self,
        agents: list[Agent],
        text: str,
        current_phase: GamePhase,
    ) -> None:
        """Send a system announcement to all agents (adds to their history)."""
        for agent in agents:
            if agent.alive:
                agent.add_user_message(f"[SYSTEM ANNOUNCEMENT] {text}")

        logger.system_message(text)
