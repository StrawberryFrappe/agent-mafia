"""MCP Server bridge wrapping DeepSeek v4 flash API.

This FastMCP server exposes a `chat_completion` tool that agents
connect to via MCP client. The model is treated as a standardized
external resource through the MCP protocol.

Run standalone: python -m mcp_server.deepseek_bridge
Used by orchestrator via stdio transport.
"""

import json
import os
import sys
import traceback

from fastmcp import FastMCP
from openai import OpenAI

# Load env for standalone runs
from dotenv import load_dotenv
load_dotenv()

mcp = FastMCP("DeepSeekBridge")


def _get_client() -> OpenAI:
    """Create OpenAI client pointed at DeepSeek API."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set in environment")
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


@mcp.tool()
def chat_completion(
    agent_name: str,
    system_prompt: str,
    messages_json: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """Send a chat completion request to DeepSeek for a specific agent.

    Args:
        agent_name: Logical name of the agent (for logging).
        system_prompt: The system-level instructions for the model.
        messages_json: JSON-encoded list of message dicts (role/content pairs).
        temperature: Sampling temperature (0.0-2.0).
        max_tokens: Maximum tokens in the response.

    Returns:
        The model's text response, or a JSON error object on failure.
    """
    try:
        client = _get_client()
        messages = json.loads(messages_json)

        # Prepend system prompt
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

        response = client.chat.completions.create(
            model=model,
            messages=full_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content
        return content if content else ""

    except json.JSONDecodeError as e:
        return json.dumps({
            "error": True,
            "error_type": "INVALID_JSON",
            "message": f"Failed to parse messages_json: {str(e)}",
            "agent_name": agent_name,
        })
    except Exception as e:
        return json.dumps({
            "error": True,
            "error_type": "API_ERROR",
            "message": str(e),
            "traceback": traceback.format_exc(),
            "agent_name": agent_name,
        })


@mcp.tool()
def health_check() -> str:
    """Check if the DeepSeek API is reachable.

    Returns:
        JSON with status and model info, or error details.
    """
    try:
        client = _get_client()
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

        # Minimal test call
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )

        return json.dumps({
            "status": "ok",
            "model": model,
            "response": response.choices[0].message.content,
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": str(e),
        })


if __name__ == "__main__":
    mcp.run()
