# Agent Mafia Arena

A Multi-Agent System (MAS) that simulates a **Mafia / Town of Salem** style game using DeepSeek AI agents coordinated by a strict orchestration protocol.

Built for the *Desarrollo de Agentes de IA* university course as a demonstration of structured interoperability and coordination governance between autonomous AI agents.

---

## Architecture

- **Orchestrator** - Python state machine that governs all phase transitions and enforces message contracts.
- **Agent Brains** - All agents call DeepSeek via an MCP (Model Context Protocol) stdio bridge. Agents never call the LLM directly.
- **Contracts** - Every message follows a strict JSON schema with `intent`, `context`, `payload`, `correlation_id`, `state`, and `error` fields.
- **Persistence** - SQLite database with `agent_messages`, `agent_message_events`, and `game_state` tables.

## Roles

| Role    | Count | Night Action                          |
|---------|-------|---------------------------------------|
| Mafia   | 2     | Discuss and choose one player to kill |
| Doctor  | 1     | Choose one player to heal             |
| Sheriff | 1     | Investigate one player (MAFIA / NOT MAFIA) |
| Town    | 6     | No night action                       |

## Features

- Web UI with real-time WebSocket event streaming
- Start / Stop server controls from the browser
- Terminal mode with ANSI color support (`--terminal` flag)
- 20 distinct agent personalities with unique names, backstories, and temperatures
- Persistent notepad memory - agents summarize suspicions each night
- Sheriff investigation results injected into the Sheriff's private memory
- Parallel night execution (Mafia, Doctor, Sheriff all act concurrently)
- Dynamic rebuttal queue - if agent A mentions agent B, B gets to immediately respond
- Idempotency keys prevent duplicate actions on API retries
- Fail-fast degradation with blank response fallback

## Setup

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/agent-mafia.git
cd agent-mafia

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set API key
cp .env.example .env
# Edit .env and add your DEEPSEEK_API_KEY

# Run (Web UI)
python main.py

# Run (Terminal)
python main.py --terminal
```

## Configuration

Edit `config.py` to adjust player counts, retry limits, and server settings.

| Variable          | Default          | Description                 |
|-------------------|------------------|-----------------------------|
| `TOTAL_PLAYERS`   | 10               | Total agents in the game    |
| `MAFIA_COUNT`     | 2                | Number of Mafia agents      |
| `SHERIFF_COUNT`   | 1                | Number of Sheriff agents    |
| `DOCTOR_COUNT`    | 1                | Number of Doctor agents     |
| `MAX_API_RETRIES` | 5                | Retries on MCP/API failure  |
| `WEB_PORT`        | 8080             | Web UI port                 |

## Evidence Report

See [`evidence_report.md`](./evidence_report.md) for a full technical breakdown of the interoperability contracts, coordination patterns, and governance mechanisms used in this system.
