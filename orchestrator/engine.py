"""Main game engine for the Mafia game.

Orchestrates the full game loop through all phases using
the state machine, handoff manager, and resolution logic.
"""

import asyncio
import json
import random
import uuid

from agents.base_agent import Agent
from agents.agent_factory import (
    create_agents,
    get_alive_agents,
    get_alive_by_role,
)
from contracts.intents import (
    Intent,
    GamePhase,
    Role,
    EventType,
    MessageState,
)
from orchestrator.state_machine import GameStateMachine
from orchestrator.handoff import HandoffManager
from orchestrator.resolution import (
    resolve_night,
    tally_votes,
    check_win_condition,
    detect_mentions,
    parse_vote_target,
    parse_night_action,
    parse_sentence_vote,
    parse_sheriff_investigation,
)
from persistence.database import GameDatabase, init_db_sync
from config import TOTAL_PLAYERS, MAFIA_COUNT, DOCTOR_COUNT, SHERIFF_COUNT, DB_PATH
from utils import logger
from utils.errors import GameOverError


class GameEngine:
    """Central game controller managing the full Mafia game lifecycle."""

    def __init__(
        self,
        total_players: int = TOTAL_PLAYERS,
        mafia_count: int = MAFIA_COUNT,
        doctor_count: int = DOCTOR_COUNT,
        seed: int | None = None,
    ):
        self.correlation_id = str(uuid.uuid4())
        self.total_players = total_players
        self.mafia_count = mafia_count
        self.doctor_count = doctor_count
        self.seed = seed

        self.agents: list[Agent] = []
        self.state_machine = GameStateMachine()
        self.db: GameDatabase | None = None
        self.handoff: HandoffManager | None = None

        # Event callback for web UI
        self._event_callback = None

    def set_event_callback(self, callback) -> None:
        """Set callback for broadcasting events to web UI."""
        self._event_callback = callback

    async def run(self) -> dict:
        """Run the complete game. Returns the game result."""
        init_db_sync(DB_PATH)

        async with GameDatabase(DB_PATH) as db:
            self.db = db
            self.handoff = HandoffManager(db, self.correlation_id)

            try:
                await self._phase_init()
                await self._phase_day_zero()

                while not self.state_machine.is_game_over():
                    await self._phase_night()
                    result = await self._phase_dawn()
                    if result:
                        return result

                    await self._phase_day_talk()
                    await self._phase_voting()
                    result = await self._check_and_handle_trial()
                    if result:
                        return result

            except GameOverError as e:
                logger.win_announcement(e.winner, e.reason)
                return {"winner": e.winner, "reason": e.reason}

        return {"winner": "NONE", "reason": "Game ended unexpectedly"}

    # -------------------------------------------------------------------------
    # PHASE 0: INITIALIZATION
    # -------------------------------------------------------------------------

    async def _phase_init(self) -> None:
        """Assign roles privately to all agents."""
        logger.phase_header("INIT")

        self.agents = create_agents(
            total_players=self.total_players,
            mafia_count=self.mafia_count,
            doctor_count=self.doctor_count,
            sheriff_count=SHERIFF_COUNT,
            seed=self.seed,
        )

        for agent in self.agents:
            await self.db.init_agent_state(
                agent.name,
                agent.display_name,
                agent.role.value,
                agent.personality.id if agent.personality else "",
            )

            # Send role assignment
            _, response = await self.handoff.send_and_receive(
                agent=agent,
                intent=Intent.ASSIGN_ROLE,
                context={
                    "role": agent.role.value,
                    "mafia_members": agent.private_context.get("mafia_members", []),
                },
                payload={"text": f"Your role is {agent.role.value}."},
                current_phase=GamePhase.INIT,
                round_number=0,
            )

            await self.db.log_event(
                str(uuid.uuid4()),
                EventType.ROLE_ASSIGNED,
                {"agent": agent.name, "role": agent.role.value},
            )

            logger.debug_log(f"Role assigned to {agent.display_name}: {agent.role.value}")

        self.state_machine.transition_to(GamePhase.DAY_ZERO)

    # -------------------------------------------------------------------------
    # PHASE 0.5: DAY ZERO
    # -------------------------------------------------------------------------

    async def _phase_day_zero(self) -> None:
        """Day 0: Randomized intro turns. No voting allowed."""
        logger.phase_header("DAY_ZERO")

        alive = get_alive_agents(self.agents)
        random.shuffle(alive)

        alive_names = [a.display_name for a in alive]

        await self.handoff.broadcast_system(
            alive,
            "Welcome to the town! Day 0: Introduce yourselves. No voting today.",
            GamePhase.DAY_ZERO,
        )

        for agent in alive:
            _, response = await self.handoff.send_and_receive(
                agent=agent,
                intent=Intent.DAY_INTRO,
                context={"alive_players": alive_names},
                payload={"text": "Introduce yourself to the town."},
                current_phase=GamePhase.DAY_ZERO,
                round_number=0,
            )
            logger.agent_speak(
                agent.name, agent.display_name, agent.role.value,
                response, Intent.DAY_INTRO.value,
            )

        self.state_machine.transition_to(GamePhase.NIGHT)

    # -------------------------------------------------------------------------
    # PHASE 1: NIGHT
    # -------------------------------------------------------------------------

    async def _phase_night(self) -> None:
        """Night phase: Mafia chat + Doctor action in parallel isolation."""
        logger.phase_header("NIGHT", self.state_machine.night_number)

        # Run Mafia, Doctor, and Sheriff chains concurrently
        mafia_task = self._night_mafia_chain()
        doctor_task = self._night_doctor_chain()
        sheriff_task = self._night_sheriff_chain()
        await asyncio.gather(mafia_task, doctor_task, sheriff_task)
        
        # Pre-calculate the night results so we can handle notepad edge cases
        kill_target = getattr(self, "_night_kill_target", None)
        heal_target = getattr(self, "_night_heal_target", None)
        self._night_result = resolve_night(kill_target, heal_target)

        # After night actions, all agents update their notepads
        await self._night_notepad_chain()

        self.state_machine.transition_to(GamePhase.DAWN)

    async def _night_mafia_chain(self) -> None:
        """Mafia night chat and kill decision. Isolated from Doctor."""
        mafia = get_alive_by_role(self.agents, Role.MAFIA)
        if not mafia:
            return

        alive = get_alive_agents(self.agents)
        non_mafia_names = [a.display_name for a in alive if a.role != Role.MAFIA]

        # Mafia chat round
        chat_log = []
        for agent in mafia:
            mafia_names = [a.display_name for a in mafia if a.name != agent.name]
            _, response = await self.handoff.send_and_receive(
                agent=agent,
                intent=Intent.NIGHT_CHAT,
                context={
                    "night_chat": "\n".join(chat_log),
                    "mafia_members": mafia_names,
                    "potential_targets": non_mafia_names,
                },
                payload={"text": "Discuss with your fellow Mafia. Who should we target tonight?"},
                current_phase=GamePhase.NIGHT,
                round_number=self.state_machine.night_number,
            )
            logger.agent_speak(
                agent.name, agent.display_name, agent.role.value,
                response, Intent.NIGHT_CHAT.value,
            )
            chat_log.append(f"{agent.display_name}: {response}")
            # Store in private context for day-phase contamination
            agent.private_context["night_chat_history"].append({
                "night": self.state_machine.night_number,
                "chat": response,
            })

        # Final kill decision from last Mafia member
        last_mafia = mafia[-1]
        _, kill_response = await self.handoff.send_and_receive(
            agent=last_mafia,
            intent=Intent.KILL_TARGET,
            context={
                "night_chat": "\n".join(chat_log),
                "potential_targets": non_mafia_names,
            },
            payload={"text": "Final decision: Who does the Mafia kill tonight? Provide your reasoning, then write 'kill [name]' at the very end. Or say 'kill none'."},
            current_phase=GamePhase.NIGHT,
            round_number=self.state_machine.night_number,
        )

        logger.agent_speak(
            last_mafia.name, last_mafia.display_name, last_mafia.role.value,
            kill_response, Intent.KILL_TARGET.value,
        )

        action = parse_night_action(kill_response, alive, is_mafia=True)
        self._night_kill_target = action.get("target")

        for agent in mafia:
            await self.db.record_night_action(agent.name, {
                "night": self.state_machine.night_number,
                "action": action,
            })

    async def _night_doctor_chain(self) -> None:
        """Doctor heal action. Isolated from Mafia."""
        doctors = get_alive_by_role(self.agents, Role.DOCTOR)
        if not doctors:
            self._night_heal_target = None
            return

        doctor = doctors[0]
        alive = get_alive_agents(self.agents)
        alive_names = [a.display_name for a in alive]

        can_self_heal = not doctor.private_context.get("self_heal_used", False)

        _, heal_response = await self.handoff.send_and_receive(
            agent=doctor,
            intent=Intent.NIGHT_ACTION,
            context={
                "alive_players": alive_names,
                "can_self_heal": can_self_heal,
            },
            payload={
                "text": (
                    "Choose someone to heal tonight. Provide your reasoning, then write 'heal [name]' at the very end. "
                    + ("You CAN still heal yourself (once per game)." if can_self_heal
                       else "You have ALREADY used your self-heal.")
                    + " Or say 'heal none'."
                )
            },
            current_phase=GamePhase.NIGHT,
            round_number=self.state_machine.night_number,
        )

        logger.agent_speak(
            doctor.name, doctor.display_name, doctor.role.value,
            heal_response, Intent.NIGHT_ACTION.value,
        )

        action = parse_night_action(heal_response, alive, is_mafia=False)
        heal_target = action.get("target")

        if action["action_type"] == "HEAL_SELF":
            heal_target = doctor.display_name
            doctor.private_context["self_heal_used"] = True
            await self.db.use_self_heal(doctor.name)

        self._night_heal_target = heal_target

        await self.db.record_night_action(doctor.name, {
            "night": self.state_machine.night_number,
            "action": action,
        })

    async def _night_sheriff_chain(self) -> None:
        """Sheriff investigation action. Isolated from Mafia and Doctor."""
        sheriffs = get_alive_by_role(self.agents, Role.SHERIFF)
        if not sheriffs:
            self._night_sheriff_target = None
            return

        sheriff = sheriffs[0]
        alive = get_alive_agents(self.agents)
        alive_names = [a.display_name for a in alive if a.name != sheriff.name]

        _, inv_response = await self.handoff.send_and_receive(
            agent=sheriff,
            intent=Intent.NIGHT_ACTION,
            context={"alive_players": alive_names},
            payload={"text": "Choose someone to investigate tonight to see if they are MAFIA. Provide your reasoning, then write 'investigate [name]' at the very end. Or say 'investigate none'."},
            current_phase=GamePhase.NIGHT,
            round_number=self.state_machine.night_number,
        )

        logger.agent_speak(
            sheriff.name, sheriff.display_name, sheriff.role.value,
            inv_response, Intent.NIGHT_ACTION.value,
        )

        target = parse_sheriff_investigation(inv_response, alive)
        self._night_sheriff_target = target

        await self.db.record_night_action(sheriff.name, {
            "night": self.state_machine.night_number,
            "action": {"action_type": "INVESTIGATE", "target": target},
        })

    async def _night_notepad_chain(self) -> None:
        """All agents update their notepads before Dawn."""
        alive = get_alive_agents(self.agents)
        victim_name = getattr(self, "_night_result", {}).get("killed")
        
        for agent in alive:
            ctx = {}
            if agent.role == Role.SHERIFF and getattr(self, "_night_sheriff_target", None):
                if agent.display_name != victim_name:
                    target = self._night_sheriff_target
                    target_agent = next((a for a in self.agents if a.display_name == target), None)
                    if target_agent:
                        role_str = "MAFIA" if target_agent.role == Role.MAFIA else "NOT MAFIA"
                        ctx["investigation_result"] = f"Investigation result: {target} is {role_str}!"

            _, notepad_response = await self.handoff.send_and_receive(
                agent=agent,
                intent=Intent.UPDATE_NOTEPAD,
                context=ctx,
                payload={
                    "text": (
                        "The night is ending. What do you want to write in your private notepad to remember for tomorrow? "
                        "Your response will become your EXACT new notepad contents. "
                        "Keep it brief and summarize your current suspicions/memories."
                    )
                },
                current_phase=GamePhase.NIGHT,
                round_number=self.state_machine.night_number,
            )
            
            logger.agent_speak(
                agent.name, agent.display_name, "HIDDEN",
                notepad_response, Intent.UPDATE_NOTEPAD.value,
            )
            
            # Update the agent's notepad
            agent.notepad = notepad_response

    # -------------------------------------------------------------------------
    # PHASE 2: DAWN
    # -------------------------------------------------------------------------

    async def _phase_dawn(self) -> dict | None:
        """Resolve night actions and announce results."""
        logger.phase_header("DAWN")

        result = getattr(self, "_night_result", None)
        if not result:
            kill_target = getattr(self, "_night_kill_target", None)
            heal_target = getattr(self, "_night_heal_target", None)
            result = resolve_night(kill_target, heal_target)

        alive = get_alive_agents(self.agents)

        if result["killed"]:
            victim = next(
                (a for a in self.agents if a.display_name == result["killed"]), None
            )
            if victim:
                victim.alive = False
                await self.db.kill_agent(victim.name)
                logger.death_announcement(
                    victim.display_name, victim.role.value, "killed by the Mafia"
                )
                
                announcement = f"{victim.display_name} was found dead this morning. They were a {victim.role.value}."
                if victim.role in [Role.TOWN, Role.DOCTOR, Role.SHERIFF] and victim.notepad:
                    announcement += f"\n\nNext to their body, you find their notepad:\n{victim.notepad}"

                await self.handoff.broadcast_system(
                    get_alive_agents(self.agents),
                    announcement,
                    GamePhase.DAWN,
                )
        elif result["healed"]:
            await self.handoff.broadcast_system(
                alive,
                f"Someone was attacked last night, but the Doctor saved them!",
                GamePhase.DAWN,
            )
        else:
            await self.handoff.broadcast_system(
                alive, "The night passed peacefully. No one was harmed.",
                GamePhase.DAWN,
            )

        # Check win condition
        win = check_win_condition(get_alive_agents(self.agents))
        if win:
            self.state_machine.transition_to(GamePhase.GAME_OVER)
            logger.win_announcement(win["winner"], win["reason"])
            return win

        # Inject Mafia night chat into their context for day (contamination)
        for agent in get_alive_by_role(self.agents, Role.MAFIA):
            recent_chat = agent.private_context.get("night_chat_history", [])
            if recent_chat:
                last = recent_chat[-1]
                agent.private_context["last_night_context"] = last.get("chat", "")

        self.state_machine.transition_to(GamePhase.DAY_TALK)
        return None

    # -------------------------------------------------------------------------
    # PHASE 3: DAY TALK
    # -------------------------------------------------------------------------

    async def _phase_day_talk(self) -> None:
        """Daytime discussion with randomized order and rebuttal mechanism."""
        logger.phase_header("DAY_TALK", self.state_machine.day_number)

        alive = get_alive_agents(self.agents)
        random.shuffle(alive)
        alive_names = [a.display_name for a in alive]

        talk_queue = list(alive)
        spoken = set()

        while talk_queue:
            agent = talk_queue.pop(0)
            if agent.name in spoken or not agent.alive:
                continue
            spoken.add(agent.name)

            # Build context with Mafia contamination
            ctx = {"alive_players": alive_names}
            if agent.role == Role.MAFIA:
                ctx["night_chat"] = agent.private_context.get("last_night_context", "")

            _, response = await self.handoff.send_and_receive(
                agent=agent,
                intent=Intent.DAY_TALK,
                context=ctx,
                payload={"text": "Share your thoughts with the town."},
                current_phase=GamePhase.DAY_TALK,
                round_number=self.state_machine.day_number,
            )

            logger.agent_speak(
                agent.name, agent.display_name, agent.role.value,
                response, Intent.DAY_TALK.value,
            )

            # Check for mentions -> rebuttal mechanism
            mentioned = detect_mentions(response, alive, agent.display_name)
            for mentioned_name in mentioned:
                mentioned_agent = next(
                    (a for a in alive if a.display_name == mentioned_name), None
                )
                if not mentioned_agent or not mentioned_agent.alive:
                    continue

                await self.db.log_event(
                    str(uuid.uuid4()),
                    EventType.REBUTTAL_TRIGGERED,
                    {"speaker": agent.display_name, "mentioned": mentioned_name},
                )

                # Rebuttal: mentioned agent responds
                _, rebuttal = await self.handoff.send_and_receive(
                    agent=mentioned_agent,
                    intent=Intent.REBUTTAL,
                    context={
                        "mentioned_by": agent.display_name,
                        "mention_text": response,
                        "alive_players": alive_names,
                    },
                    payload={"text": f"{agent.display_name} mentioned you. Respond."},
                    current_phase=GamePhase.DAY_TALK,
                    round_number=self.state_machine.day_number,
                )

                if "pass" in rebuttal.lower() or "no comment" in rebuttal.lower():
                    await self.db.log_event(
                        str(uuid.uuid4()), EventType.IGNORED_MENTION,
                        {"agent": mentioned_name},
                    )
                    continue

                logger.agent_speak(
                    mentioned_agent.name, mentioned_agent.display_name,
                    mentioned_agent.role.value, rebuttal, Intent.REBUTTAL.value,
                )

                # Counter-rebuttal: original speaker
                _, counter = await self.handoff.send_and_receive(
                    agent=agent,
                    intent=Intent.COUNTER_REBUTTAL,
                    context={
                        "rebuttal_from": mentioned_name,
                        "rebuttal_text": rebuttal,
                    },
                    payload={"text": f"{mentioned_name} responded. Your counter-argument."},
                    current_phase=GamePhase.DAY_TALK,
                    round_number=self.state_machine.day_number,
                )
                logger.agent_speak(
                    agent.name, agent.display_name, agent.role.value,
                    counter, Intent.COUNTER_REBUTTAL.value,
                )

                # Final closure: mentioned agent
                _, closure = await self.handoff.send_and_receive(
                    agent=mentioned_agent,
                    intent=Intent.FINAL_CLOSURE,
                    context={"counter_from": agent.display_name, "counter_text": counter},
                    payload={"text": "Final word on this exchange."},
                    current_phase=GamePhase.DAY_TALK,
                    round_number=self.state_machine.day_number,
                )
                logger.agent_speak(
                    mentioned_agent.name, mentioned_agent.display_name,
                    mentioned_agent.role.value, closure, Intent.FINAL_CLOSURE.value,
                )

                # Mark mentioned agent as having spoken
                spoken.add(mentioned_agent.name)

        self.state_machine.transition_to(GamePhase.VOTING_STEP1)

    # -------------------------------------------------------------------------
    # PHASE 4: VOTING
    # -------------------------------------------------------------------------

    async def _phase_voting(self) -> None:
        """Two-step sequential voting."""
        await self._voting_step(step=1)
        await self._voting_step(step=2)

    async def _voting_step(self, step: int) -> None:
        """Execute one step of voting."""
        phase = GamePhase.VOTING_STEP1 if step == 1 else GamePhase.VOTING_STEP2
        intent = Intent.VOTE_PLAYER if step == 1 else Intent.VOTE_CHANGE
        logger.phase_header(phase.value, self.state_machine.day_number)

        alive = get_alive_agents(self.agents)
        alive_names = [a.display_name for a in alive]
        votes: list[dict] = []

        # Reset vote change tracking for step 1
        if step == 1:
            for agent in alive:
                agent.reset_vote_change()

        for agent in alive:
            ctx = {
                "alive_players": alive_names,
                "previous_votes": votes,
                "step": step,
            }

            if step == 2:
                # Find their previous vote
                prev = next((v for v in self._step1_votes if v["voter"] == agent.display_name), None)
                if prev:
                    ctx["your_previous_vote"] = prev["target"]

            payload_text = (
                "Vote for a player to put on trial. Provide your reasoning, then write 'vote [name]' or 'vote no one' at the very end."
                if step == 1 else
                "You may CHANGE your vote (once) or CONFIRM it. Provide your reasoning, then write 'vote [name]' or 'vote no one' at the very end."
            )

            _, response = await self.handoff.send_and_receive(
                agent=agent,
                intent=intent,
                context=ctx,
                payload={"text": payload_text},
                current_phase=phase,
                round_number=self.state_machine.day_number,
            )

            target, justification = parse_vote_target(response, alive)

            # For step 2, check if vote changed
            if step == 2 and not agent.vote_changed_this_phase:
                prev = next(
                    (v for v in self._step1_votes if v["voter"] == agent.display_name),
                    None,
                )
                if prev and target != prev.get("target"):
                    agent.vote_changed_this_phase = True
                    await self.db.log_event(
                        str(uuid.uuid4()), EventType.VOTE_CHANGED,
                        {"agent": agent.display_name, "old": prev.get("target"), "new": target},
                    )

            vote_entry = {
                "voter": agent.display_name,
                "target": target,
                "justification": justification,
            }
            votes.append(vote_entry)

            logger.vote_display(
                agent.display_name, target or "no one", justification[:80],
            )

            await self.db.log_event(
                str(uuid.uuid4()), EventType.VOTE_LOCKED,
                vote_entry,
            )

        if step == 1:
            self._step1_votes = votes
            self.state_machine.transition_to(GamePhase.VOTING_STEP2)
        else:
            self._final_votes = votes

    # -------------------------------------------------------------------------
    # PHASE 5: TRIAL & SENTENCING
    # -------------------------------------------------------------------------

    async def _check_and_handle_trial(self) -> dict | None:
        """Check vote results and run trial if needed."""
        tally = tally_votes(self._final_votes)

        if not tally["majority_reached"]:
            logger.system_message("No majority reached. No one goes to trial.")
            self.state_machine.transition_to(GamePhase.NIGHT)
            return None

        accused_name = tally["majority_target"]
        accused = next(
            (a for a in self.agents if a.display_name == accused_name and a.alive),
            None,
        )

        if not accused:
            self.state_machine.transition_to(GamePhase.NIGHT)
            return None

        # Trial phase
        self.state_machine.transition_to(GamePhase.TRIAL)
        logger.phase_header("TRIAL")
        logger.system_message(f"{accused_name} is on trial!")

        alive = get_alive_agents(self.agents)
        alive_names = [a.display_name for a in alive]

        _, defense = await self.handoff.send_and_receive(
            agent=accused,
            intent=Intent.STATE_DEFENSE,
            context={
                "alive_players": alive_names,
                "votes_against_you": tally["counts"].get(accused_name, 0),
                "accusation": f"The town has voted to put you on trial.",
            },
            payload={"text": "You're on trial. Defend yourself!"},
            current_phase=GamePhase.TRIAL,
            round_number=self.state_machine.day_number,
        )

        logger.agent_speak(
            accused.name, accused.display_name, accused.role.value,
            defense, Intent.STATE_DEFENSE.value,
        )

        # Sentencing
        self.state_machine.transition_to(GamePhase.SENTENCING)
        logger.phase_header("SENTENCING")

        sentence_votes = []
        for agent in alive:
            if agent.name == accused.name:
                continue

            _, sv_response = await self.handoff.send_and_receive(
                agent=agent,
                intent=Intent.SENTENCE_VOTE,
                context={
                    "accused": accused_name,
                    "defense": defense,
                },
                payload={"text": f"Vote 'guilty' or 'not guilty' for {accused_name}. Provide your reasoning, then write your final decision at the very end."},
                current_phase=GamePhase.SENTENCING,
                round_number=self.state_machine.day_number,
            )

            verdict = parse_sentence_vote(sv_response)
            sentence_votes.append(verdict)
            logger.vote_display(agent.display_name, f"{verdict} ({accused_name})")

        guilty_count = sum(1 for v in sentence_votes if v == "guilty")
        total = len(sentence_votes)

        if guilty_count > total / 2:
            # Lynch: get final words
            _, final_words = await self.handoff.send_and_receive(
                agent=accused,
                intent=Intent.FINAL_WORDS,
                context={},
                payload={"text": "Any last words?"},
                current_phase=GamePhase.SENTENCING,
                round_number=self.state_machine.day_number,
            )

            logger.agent_speak(
                accused.name, accused.display_name, accused.role.value,
                final_words, Intent.FINAL_WORDS.value,
            )

            accused.alive = False
            await self.db.kill_agent(accused.name)
            logger.death_announcement(accused.display_name, accused.role.value, "lynched")

            announcement = f"{accused.display_name} has been lynched. They were a {accused.role.value}."
            if accused.role in [Role.TOWN, Role.DOCTOR, Role.SHERIFF] and accused.notepad:
                announcement += f"\n\nAmong their belongings, you find their notepad:\n{accused.notepad}"

            await self.handoff.broadcast_system(
                get_alive_agents(self.agents),
                announcement,
                GamePhase.SENTENCING,
            )

            # Check win
            win = check_win_condition(get_alive_agents(self.agents))
            if win:
                self.state_machine.transition_to(GamePhase.GAME_OVER)
                logger.win_announcement(win["winner"], win["reason"])
                return win
        else:
            logger.system_message(
                f"{accused_name} has been found not guilty ({guilty_count}/{total})."
            )

        self.state_machine.transition_to(GamePhase.NIGHT)
        return None
