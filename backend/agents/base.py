"""Base agent class for AI agents."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import logging
from pydantic import BaseModel


class AgentResult(BaseModel):
    """Base result model for agent outputs."""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"agent.{name}")

    @abstractmethod
    async def execute(self, **kwargs) -> AgentResult:
        """Execute the agent's main task."""
        pass

    def log_info(self, message: str):
        """Log info message."""
        self.logger.info(f"[{self.name}] {message}")

    def log_error(self, message: str):
        """Log error message."""
        self.logger.error(f"[{self.name}] {message}")

    def log_debug(self, message: str):
        """Log debug message."""
        self.logger.debug(f"[{self.name}] {message}")
