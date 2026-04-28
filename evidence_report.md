# Agent Mafia Arena: Evidence & Architecture Source Report
**Course**: Desarrollo de Agentes de IA - Week 5 Deliverable

This technical evidence report documents the structural integrity, interoperability standards, and coordination governance implemented in the "Agent Mafia Arena" Multi-Agent System.

---

## 1. Interoperability & Contract Audit

The system enforces strict interoperability by guaranteeing that all intra-agent and orchestrator-agent communication flows through a rigorous JSON contract.

### Contract Schema
The protocol mandates a uniform JSON structure defined in `contracts/message.py`. Every transaction requires the following mandatory fields:

```json
{
  "message_id": "msg-8f92-4f3b-...",
  "correlation_id": "game-12345678",
  "version": "1.0",
  "intent": "NIGHT_ACTION",
  "sender": "agent.orchestrator",
  "receiver": "agent.mafia_1",
  "state": "received",
  "timestamp": "2026-04-28T12:00:00Z",
  "context": {
    "role": "MAFIA",
    "alive_players": ["agent.mafia_1", "agent.town_1"]
  },
  "payload": {
    "text": "Choose your target."
  },
  "trace_history": [],
  "idempotency_key": "NIGHT_ACTION_agent.mafia_1_round1"
}
```

### Intent Inventory
Intents map ambiguous natural language to programmatic actions. Primary intents include:
- `DAY_TALK`: Triggers standard daytime dialogue.
- `NIGHT_ACTION`: Solicits programmatic targets (Kill/Heal/Investigate) from active night roles.
- `UPDATE_NOTEPAD`: Prompts agents to synthesize phase events into a private memory string before dawn.
- `REBUTTAL` / `COUNTER_REBUTTAL`: Interrupts the standard queue for dynamic conversational defense.
- `VOTE_PLAYER`: Forces the agent to output an explicit target in their response for tallying.
- `STATE_DEFENSE`: Solicits a final defense before `SENTENCE_VOTE`.

### State Handling
Transitions are governed by the `MessageState` enum:
1. `received`: The orchestrator dispatches a prompt to the MCP bridge.
2. `processing`: (Internal) The MCP bridge waits for the DeepSeek LLM generation.
3. `completed`: A valid response is received, validated against the schema, and stored.
4. `failed`: If API retries are exhausted or strict contract validation fails repeatedly.

---

## 2. Coordination & Handoff Patterns

### Handoff Analysis
- **Sequential Execution (Encadenamiento)**: Used during the `DAY_TALK` and `VOTING` phases. The Orchestrator queries each alive agent one-by-one, passing the accumulating public discussion history.
- **Parallel Execution**: Used during `NIGHT`. Mafia members, the Doctor, and the Sheriff are invoked concurrently. This three-way parallel isolation allows agents to evaluate targets simultaneously without blocking the Orchestrator loop.

### Persistence of Agent Memory (The Notepad Pattern)
To counteract LLM context degradation and prevent agents from "forgetting" critical insights (e.g., a Sheriff's investigation result), the system employs a Notepad Pattern. During the `_night_notepad_chain`, every agent receives an `UPDATE_NOTEPAD` intent to summarize their suspicions. The Orchestrator injects exact programmatic findings (like "Bob is MAFIA") into this prompt for investigative roles. The resulting synthesis is appended to the agent's persistent `full_system_prompt` for all subsequent days.

### Dynamic Queue Management (Direct Mention Priority)
The Orchestrator actively parses agent payloads using NLP rules (`resolution.py:detect_mentions`). If Agent A mentions Agent B, the standard round-robin queue pauses. Agent B is immediately handed an `Intent.REBUTTAL`, creating organic conversational branches while remaining governed by the rigid State Machine.

### Information Isolation
The Orchestrator applies "Need-to-Know" security:
- `trace_history` explicitly excludes cross-role intent leaks. 
- The `context` dictionary injected into a Doctor's prompt during the Night phase contains zero data regarding the parallel Mafia chat.
- The `conversation_history` array stored within the agent's memory only appends public Day messages, or private Night messages relevant strictly to their faction.

---

## 3. Trazabilidad (Traceability) & Governance

### Data Persistence Evidence
The SQLite implementation (`persistence/database.py`) acts as the immutable ledger for governance.

**Table: `agent_messages` (Excerpt)**
```sql
SELECT intent, sender, state, timestamp FROM agent_messages;
-- RESULT:
-- "DAY_TALK" | "agent.town_1"       | "completed" | "2026-04-28T12:05:10Z"
-- "REBUTTAL" | "agent.mafia_1"      | "completed" | "2026-04-28T12:05:15Z"
```

**Table: `agent_message_events` (Excerpt)**
```sql
SELECT event_type, metadata FROM agent_message_events;
-- RESULT:
-- "MESSAGE_SENT" | {"intent": "VOTE_PLAYER", "receiver": "agent.town_2"}
-- "API_RETRY"    | {"attempt": 1, "error": "DeepSeek rate limit exceeded"}
```

### Correlation Logic
The `correlation_id` uniquely identifies the game session. Queries against this ID allow auditors to trace a `NIGHT_ACTION` kill decision straight to the `DAWN_RESOLUTION` announcement and the resulting `DAY_TALK` panic, linking discrete parallel steps into a singular causal chain.

### Audit Logs (Governance)
When an agent attempts to break protocol—such as mentioning a dead player, or triggering an infinite rebuttal loop—the system logs it and gracefully drops the action:
- `Event: IGNORED_MENTION`
- `Metadata: {"reason": "Target already in rebuttal stack"}`

---

## 4. Reliability & Idempotency

### Idempotency Proof
Network failures or LLM timeouts during the `_call_mcp_with_retry()` loop run the risk of an agent performing an action twice. This is prevented by the `idempotency_key` (e.g., `VOTE_PLAYER_agent.mafia_1_round2`). Before sending a message, `check_idempotency()` queries the database. If a completed message exists, the cached result is returned, ignoring the duplicate request.

### Error Handling & Fail-Fast
When the system encounters an unrecoverable exception (e.g., `API_TIMEOUT` after 5 retries defined in `config.py:MAX_API_RETRIES`), it executes a "Fail-Fast" degradation:
1. Logs an `API_ERROR` event to `agent_message_events`.
2. Emits a `_get_blank_response()` fallback (e.g., `*Agent remains silent, lost in thought.*`).
3. Transitions the handoff cleanly, ensuring that a single failing agent node does not crash the Orchestrator loop.

---

## 5. Win-Condition Logic

The `check_win_condition()` module evaluates the game board at the start of every phase transition (`DAWN` and `SENTENCING`):
- **Mafia Win**: Triggered when `len(alive_mafia) >= len(alive_town + alive_doctor)`.
- **Town Win**: Triggered when `len(alive_mafia) == 0`.

Once met, the State Machine enforces a terminal `GAME_OVER` phase. The Orchestrator dispatches a final `PROCESS_COMPLETED` intent detailing the victory reason, concluding the session's traceability lifecycle.

---

## 6. Contract Validation Hardening

### Phase-Intent Whitelist Fix
The contract validator (`contracts/validator.py`) enforces a strict whitelist of which intents are permitted per game phase. When the `UPDATE_NOTEPAD` intent was introduced for the Notepad memory system, it was initially missing from the `PHASE_ALLOWED_INTENTS[GamePhase.NIGHT]` set. This caused `PhaseViolationError` exceptions that silently crashed the game loop at the end of every night phase, preventing the transition to `DAWN`.

**Fix**: `Intent.UPDATE_NOTEPAD.value` was added to the `NIGHT` phase whitelist, alongside existing entries like `NIGHT_CHAT` and `NIGHT_ACTION`.

### Empty Response Graceful Degradation
The DeepSeek API occasionally returns empty content for informational intents (`ASSIGN_ROLE`, `SYSTEM_ANNOUNCEMENT`) where the agent has no meaningful question to answer. Previously, these triggered `RuntimeError("Empty response from MCP bridge")`, burning through all 5 retry attempts before falling back to a blank response.

**Fix**: The `_call_mcp_with_retry()` method in `handoff.py` now detects informational intents and returns a neutral placeholder (`*Nods silently in understanding.*`) immediately, avoiding unnecessary retry loops and API cost.

---

## 7. NLP Target Extraction (Last-Mention Algorithm)

### Problem: First-Match Ambiguity
The original `parse_night_action()` function iterated over the alive agents list and returned the **first** name it found in the agent's text. Because LLM agents reason in chain-of-thought style (e.g., a Doctor saying *"The Mafia will probably target Vinny, so I will heal Elena"*), the parser would incorrectly extract "Vinny" as the heal target instead of "Elena."

This caused observable bugs where the Doctor's heal target was misattributed, producing false "save" events.

### Solution: `_extract_last_mentioned_target()`
A new shared helper function (`resolution.py`) was introduced. It:
1. Scans the full text for all mentions of alive agent names (full name and first-name fallback).
2. Records the **character index** of the **last occurrence** of each name.
3. Returns the name with the highest index (i.e., mentioned latest in the text).

This reliably captures the agent's final decision, since chain-of-thought models place their conclusion at the end. The function is now used across all parsers:
- `parse_vote_target()` (voting phase)
- `parse_night_action()` (Mafia kill and Doctor heal)
- `parse_sheriff_investigation()` (Sheriff investigation)

---

## 8. Structured Night Action Prompts

### Prompt Engineering for Deterministic Extraction
To further reduce NLP parsing errors, all night action prompts were updated to instruct agents to use an explicit format for their final decision:

| Role    | Prompt instruction                                                        |
|---------|---------------------------------------------------------------------------|
| Mafia   | `"...Provide your reasoning, then write 'kill [name]' at the very end."` |
| Doctor  | `"...Provide your reasoning, then write 'heal [name]' at the very end."` |
| Sheriff | `"...Provide your reasoning, then write 'investigate [name]' at the very end."` |

This creates a two-part structure in agent responses: free-form reasoning followed by a machine-parseable directive. Combined with the last-mention extraction algorithm, this yields near-deterministic target resolution from otherwise unpredictable LLM output.
