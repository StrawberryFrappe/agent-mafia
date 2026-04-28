"""Custom error types for the Mafia game."""


class MafiaGameError(Exception):
    """Base error for all game errors."""
    pass


class APIError(MafiaGameError):
    """DeepSeek API failure."""

    def __init__(self, message: str, retries_remaining: int = 0, agent_name: str = ""):
        self.retries_remaining = retries_remaining
        self.agent_name = agent_name
        super().__init__(message)


class ContractValidationError(MafiaGameError):
    """Message contract validation failed."""
    pass


class HandoffViolationError(MafiaGameError):
    """Agent spoke out of turn or without orchestrator permission."""
    pass


class PhaseSkipError(MafiaGameError):
    """Attempted to skip a required game phase."""
    pass


class GameOverError(MafiaGameError):
    """Raised when a win condition is met to break the game loop."""

    def __init__(self, winner: str, reason: str):
        self.winner = winner
        self.reason = reason
        super().__init__(f"{winner} wins: {reason}")
