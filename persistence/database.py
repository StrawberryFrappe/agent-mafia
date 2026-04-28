"""SQLite database schema and operations for the Mafia game.

Tables:
- agent_messages: Full JSON of every message exchanged
- agent_message_events: Granular events (MESSAGE_RECEIVED, VOTE_LOCKED, etc.)
- game_state: Alive status, roles, historical night actions
"""

import json
import sqlite3
import aiosqlite
from datetime import datetime, timezone

from config import DB_PATH
from contracts.message import GameMessage
from contracts.intents import EventType


def init_db_sync(db_path: str = DB_PATH) -> None:
    """Create tables synchronously. Used at startup."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            correlation_id TEXT NOT NULL,
            intent TEXT NOT NULL,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            state TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            full_json TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_message_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY (message_id) REFERENCES agent_messages(message_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL,
            alive INTEGER NOT NULL DEFAULT 1,
            night_actions TEXT DEFAULT '[]',
            self_heal_used INTEGER NOT NULL DEFAULT 0,
            personality_id TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
    """)

    # Indexes for common queries
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_correlation ON agent_messages(correlation_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_message ON agent_message_events(message_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_game_state_alive ON game_state(alive)"
    )

    conn.commit()
    conn.close()


class GameDatabase:
    """Async database interface for the Mafia game."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # --- agent_messages ---

    async def store_message(self, msg: GameMessage) -> None:
        """Store a complete message JSON in agent_messages."""
        await self._conn.execute(
            """INSERT OR REPLACE INTO agent_messages
               (message_id, correlation_id, intent, sender, receiver, state, timestamp, full_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.message_id,
                msg.correlation_id,
                msg.intent,
                msg.sender,
                msg.receiver,
                msg.state,
                msg.timestamp,
                msg.to_json(),
            ),
        )
        await self._conn.commit()

    async def get_message(self, message_id: str) -> GameMessage | None:
        """Retrieve a message by ID."""
        cursor = await self._conn.execute(
            "SELECT full_json FROM agent_messages WHERE message_id = ?",
            (message_id,),
        )
        row = await cursor.fetchone()
        if row:
            return GameMessage.from_json(row[0])
        return None

    async def get_messages_by_correlation(self, correlation_id: str) -> list[GameMessage]:
        """Get all messages for a game session."""
        cursor = await self._conn.execute(
            "SELECT full_json FROM agent_messages WHERE correlation_id = ? ORDER BY id",
            (correlation_id,),
        )
        rows = await cursor.fetchall()
        return [GameMessage.from_json(row[0]) for row in rows]

    async def check_idempotency(self, idempotency_key: str) -> GameMessage | None:
        """Check if an idempotency key already exists, return cached response."""
        cursor = await self._conn.execute(
            """SELECT full_json FROM agent_messages
               WHERE full_json LIKE ? AND state = 'completed'
               ORDER BY id DESC LIMIT 1""",
            (f'%"idempotency_key": "{idempotency_key}"%',),
        )
        row = await cursor.fetchone()
        if row:
            return GameMessage.from_json(row[0])
        return None

    # --- agent_message_events ---

    async def log_event(
        self,
        message_id: str,
        event_type: EventType | str,
        metadata: dict | None = None,
    ) -> None:
        """Log a granular event."""
        evt = event_type.value if isinstance(event_type, EventType) else event_type
        await self._conn.execute(
            """INSERT INTO agent_message_events (message_id, event_type, timestamp, metadata)
               VALUES (?, ?, ?, ?)""",
            (
                message_id,
                evt,
                self._now(),
                json.dumps(metadata or {}),
            ),
        )
        await self._conn.commit()

    async def get_events(self, message_id: str) -> list[dict]:
        """Get all events for a message."""
        cursor = await self._conn.execute(
            "SELECT * FROM agent_message_events WHERE message_id = ? ORDER BY id",
            (message_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- game_state ---

    async def init_agent_state(
        self,
        agent_name: str,
        display_name: str,
        role: str,
        personality_id: str = "",
    ) -> None:
        """Initialize agent state at game start."""
        await self._conn.execute(
            """INSERT OR REPLACE INTO game_state
               (agent_name, display_name, role, alive, night_actions, self_heal_used, personality_id, updated_at)
               VALUES (?, ?, ?, 1, '[]', 0, ?, ?)""",
            (agent_name, display_name, role, personality_id, self._now()),
        )
        await self._conn.commit()

    async def kill_agent(self, agent_name: str) -> None:
        """Mark an agent as dead."""
        await self._conn.execute(
            "UPDATE game_state SET alive = 0, updated_at = ? WHERE agent_name = ?",
            (self._now(), agent_name),
        )
        await self._conn.commit()

    async def get_alive_agents(self) -> list[dict]:
        """Get all alive agents."""
        cursor = await self._conn.execute(
            "SELECT * FROM game_state WHERE alive = 1"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_agent_state(self, agent_name: str) -> dict | None:
        """Get full state for a specific agent."""
        cursor = await self._conn.execute(
            "SELECT * FROM game_state WHERE agent_name = ?",
            (agent_name,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def record_night_action(self, agent_name: str, action: dict) -> None:
        """Append a night action to the agent's history."""
        cursor = await self._conn.execute(
            "SELECT night_actions FROM game_state WHERE agent_name = ?",
            (agent_name,),
        )
        row = await cursor.fetchone()
        if row:
            actions = json.loads(row[0])
            actions.append(action)
            await self._conn.execute(
                "UPDATE game_state SET night_actions = ?, updated_at = ? WHERE agent_name = ?",
                (json.dumps(actions), self._now(), agent_name),
            )
            await self._conn.commit()

    async def use_self_heal(self, agent_name: str) -> None:
        """Mark that the Doctor has used their self-heal."""
        await self._conn.execute(
            "UPDATE game_state SET self_heal_used = 1, updated_at = ? WHERE agent_name = ?",
            (self._now(), agent_name),
        )
        await self._conn.commit()

    async def has_used_self_heal(self, agent_name: str) -> bool:
        """Check if Doctor has already used self-heal."""
        cursor = await self._conn.execute(
            "SELECT self_heal_used FROM game_state WHERE agent_name = ?",
            (agent_name,),
        )
        row = await cursor.fetchone()
        return bool(row[0]) if row else False

    async def get_all_states(self) -> list[dict]:
        """Get all agent states."""
        cursor = await self._conn.execute("SELECT * FROM game_state ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
