"""Game configuration constants."""

import os
from dotenv import load_dotenv

load_dotenv()

# --- DeepSeek API ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# --- Game Settings ---
TOTAL_PLAYERS = 10
MAFIA_COUNT = 2
DOCTOR_COUNT = 1
SHERIFF_COUNT = 1
TOWN_COUNT = TOTAL_PLAYERS - MAFIA_COUNT - DOCTOR_COUNT - SHERIFF_COUNT

# --- Retry Logic ---
MAX_API_RETRIES = 5
RETRY_DELAY_SECONDS = 2.0

# --- MCP Server ---
MCP_SERVER_SCRIPT = "mcp_server/deepseek_bridge.py"

# --- Persistence ---
DB_PATH = "mafia_game.db"

# --- Web UI ---
WEB_HOST = "127.0.0.1"
WEB_PORT = 8080

# --- Message Contract ---
CONTRACT_VERSION = "1.0"

# --- Agent Response Limits ---
MAX_RESPONSE_CHARS = 600  # Max characters per agent response

# --- Logging ---
DEBUG_MODE = False
