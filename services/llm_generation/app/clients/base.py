"""Base LLM client interface."""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from ..core.schemas import GenerationResponse, Message, StreamChunk


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the provider name."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Get the model name."""
        pass

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> GenerationResponse:
        """Generate a response from the LLM.

        Args:
            messages: List of messages in the conversation
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            GenerationResponse with the generated text
        """
        pass

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[Message],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response from the LLM.

        Args:
            messages: List of messages in the conversation
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Yields:
            StreamChunk objects with generated content
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the client is available and configured.

        Returns:
            True if the client can make requests
        """
        pass

    async def close(self) -> None:
        """Clean up any resources."""
        pass
