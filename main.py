"""Agent Mafia Arena - Entry Point

Usage:
    python main.py                    # Web UI mode (default)
    python main.py --terminal         # Terminal-only mode
    python main.py --players 9        # Custom player count
    python main.py --mafia 3          # Custom Mafia count
    python main.py --seed 42          # Reproducible game
    python main.py --debug            # Show contract dumps
"""

import argparse
import asyncio
import sys
import threading

from config import TOTAL_PLAYERS, MAFIA_COUNT, DOCTOR_COUNT, WEB_HOST, WEB_PORT
import config


def parse_args():
    parser = argparse.ArgumentParser(description="Agent Mafia Arena")
    parser.add_argument(
        "--terminal", action="store_true",
        help="Run in terminal-only mode (no web UI)"
    )
    parser.add_argument(
        "--players", type=int, default=TOTAL_PLAYERS,
        help=f"Total number of players (default: {TOTAL_PLAYERS})"
    )
    parser.add_argument(
        "--mafia", type=int, default=MAFIA_COUNT,
        help=f"Number of Mafia agents (default: {MAFIA_COUNT})"
    )
    parser.add_argument(
        "--doctor", type=int, default=DOCTOR_COUNT,
        help=f"Number of Doctor agents (default: {DOCTOR_COUNT})"
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducible games"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug logging with contract dumps"
    )
    parser.add_argument(
        "--host", type=str, default=WEB_HOST,
        help=f"Web UI host (default: {WEB_HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=WEB_PORT,
        help=f"Web UI port (default: {WEB_PORT})"
    )
    return parser.parse_args()


async def run_game(args):
    """Run the game engine."""
    from orchestrator.engine import GameEngine

    engine = GameEngine(
        total_players=args.players,
        mafia_count=args.mafia,
        doctor_count=args.doctor,
        seed=args.seed,
    )

    result = await engine.run()
    return result


current_game_task = None
game_loop = None

def run_web_and_game(args):
    """Run web server and game concurrently."""
    import uvicorn
    import os
    from web import server

    global game_loop
    game_loop = asyncio.new_event_loop()

    def game_thread_func():
        asyncio.set_event_loop(game_loop)
        game_loop.run_forever()

    # Start game thread
    t = threading.Thread(target=game_thread_func, daemon=True)
    t.start()
    
    async def _start_game():
        global current_game_task
        if current_game_task and not current_game_task.done():
            current_game_task.cancel()
            try:
                await current_game_task
            except asyncio.CancelledError:
                pass
        
        print(f"\n  Game starting... Open http://{args.host}:{args.port} in your browser.\n")
        current_game_task = game_loop.create_task(run_game(args))
        
        try:
            result = await current_game_task
            print(f"\nGame finished: {result}")
        except asyncio.CancelledError:
            print("\nGame cancelled.")

    def start_cb():
        asyncio.run_coroutine_threadsafe(_start_game(), game_loop)

    def stop_cb():
        os._exit(0)

    server.start_game_callback = start_cb
    server.stop_server_callback = stop_cb

    # Auto-start first game after delay
    async def delayed_start():
        await asyncio.sleep(2)
        await _start_game()
        
    asyncio.run_coroutine_threadsafe(delayed_start(), game_loop)

    # Run web server (blocking)
    uvicorn.run(server.app, host=args.host, port=args.port, log_level="warning")


def main():
    args = parse_args()

    if args.debug:
        config.DEBUG_MODE = True

    print("\n" + "=" * 50)
    print("  AGENT MAFIA ARENA")
    print("=" * 50)
    from config import SHERIFF_COUNT
    print(f"  Players: {args.players} ({args.mafia} Mafia, {args.doctor} Doctor, 1 Sheriff, "
          f"{args.players - args.mafia - args.doctor - SHERIFF_COUNT} Town)")
    print(f"  Mode: {'Terminal' if args.terminal else f'Web UI @ http://{args.host}:{args.port}'}")
    if args.seed is not None:
        print(f"  Seed: {args.seed}")
    print("=" * 50 + "\n")

    if args.terminal:
        result = asyncio.run(run_game(args))
        print(f"\nGame finished: {result}")
    else:
        run_web_and_game(args)


if __name__ == "__main__":
    main()
