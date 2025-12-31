"""Main generation service that coordinates LLM clients.

Supports two modes:
1. Unified LiteLLM client (recommended) - Single client for all providers
2. Legacy individual clients - Separate OpenAI/Anthropic/Local clients

Set USE_LITELLM=true in settings to use the unified client.
"""

from typing import AsyncIterator

import structlog

from ..clients.anthropic_client import AnthropicClient
from ..clients.base import BaseLLMClient
from ..clients.local_client import LocalLLMClient
from ..clients.openai_client import OpenAIClient
from ..config import Settings
from ..prompts.templates import build_system_prompt, build_user_prompt, sanitize_input
from .schemas import (
    CitationInfo,
    GenerationRequest,
    GenerationResponse,
    Message,
    ProviderStatus,
    StreamChunk,
)

logger = structlog.get_logger()


class GenerationService:
    """Main service for LLM generation.

    Supports both unified LiteLLM client and legacy individual clients.
    """

    def __init__(self, settings: Settings):
        """Initialize the generation service."""
        self.settings = settings
        self._use_litellm = getattr(settings, "USE_LITELLM", False)
        self._litellm_clients: dict[str, BaseLLMClient] = {}

        # Initialize legacy clients (always available for fallback)
        self.clients: dict[str, BaseLLMClient] = {
            "openai": OpenAIClient(settings),
            "anthropic": AnthropicClient(settings),
            "local": LocalLLMClient(settings),
        }

        # Initialize LiteLLM client if enabled
        if self._use_litellm:
            self._init_litellm_clients()

    def _init_litellm_clients(self) -> None:
        """Initialize LiteLLM clients for all providers."""
        try:
            from ..clients.litellm_client import LiteLLMClient

            # Create LiteLLM client for each provider
            for provider in ["openai", "anthropic", "local"]:
                self._litellm_clients[provider] = LiteLLMClient(
                    settings=self.settings,
                    provider=provider,
                    fallback_models=self._get_fallback_models(provider),
                )

            logger.info(
                "litellm_clients_initialized",
                providers=list(self._litellm_clients.keys()),
            )

        except ImportError:
            logger.warning(
                "litellm_not_installed",
                message="Falling back to legacy clients. Install with: pip install litellm",
            )
            self._use_litellm = False

    def _get_fallback_models(self, primary_provider: str) -> list[str]:
        """Get fallback models for a provider."""
        fallbacks = []

        # Add other providers as fallbacks
        if primary_provider != "openai" and self.settings.OPENAI_API_KEY:
            fallbacks.append(self.settings.OPENAI_MODEL)

        if primary_provider != "anthropic" and self.settings.ANTHROPIC_API_KEY:
            fallbacks.append(f"anthropic/{self.settings.ANTHROPIC_MODEL}")

        if primary_provider != "local":
            fallbacks.append(f"ollama/{self.settings.LOCAL_MODEL_NAME}")

        return fallbacks

    async def close(self) -> None:
        """Close all clients."""
        # Close legacy clients
        for client in self.clients.values():
            await client.close()

        # Close LiteLLM clients
        for client in self._litellm_clients.values():
            await client.close()

    def get_client(self, provider: str | None = None) -> BaseLLMClient:
        """Get the appropriate LLM client.

        Uses LiteLLM client if enabled, otherwise falls back to legacy clients.

        Args:
            provider: Optional provider override

        Returns:
            The LLM client to use
        """
        provider = provider or self.settings.DEFAULT_PROVIDER

        # Prefer LiteLLM client if enabled and available
        if self._use_litellm and provider in self._litellm_clients:
            return self._litellm_clients[provider]

        # Fall back to legacy clients
        if provider not in self.clients:
            raise ValueError(f"Unknown provider: {provider}")

        return self.clients[provider]

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Generate a response based on the request.

        Args:
            request: The generation request

        Returns:
            GenerationResponse with the answer
        """
        # Get client
        client = self.get_client(request.provider)

        # Build messages
        messages = self._build_messages(request)

        # Generate
        temperature = request.temperature or self.settings.OPENAI_TEMPERATURE
        max_tokens = request.max_tokens or self.settings.RESPONSE_MAX_TOKENS

        response = await client.generate(messages, temperature, max_tokens)

        return response

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response.

        Args:
            request: The generation request

        Yields:
            StreamChunk objects
        """
        # Get client
        client = self.get_client(request.provider)

        # Build messages
        messages = self._build_messages(request)

        # Stream
        temperature = request.temperature or self.settings.OPENAI_TEMPERATURE
        max_tokens = request.max_tokens or self.settings.RESPONSE_MAX_TOKENS

        async for chunk in client.generate_stream(messages, temperature, max_tokens):
            yield chunk

    async def get_provider_status(self) -> list[ProviderStatus]:
        """Get status of all providers.

        Returns:
            List of provider statuses
        """
        statuses = []

        # Check LiteLLM clients if enabled, otherwise check legacy clients
        clients_to_check = (
            self._litellm_clients if self._use_litellm else self.clients
        )

        for provider, client in clients_to_check.items():
            try:
                available = await client.is_available()
                backend = "litellm" if self._use_litellm else "legacy"
                statuses.append(
                    ProviderStatus(
                        provider=provider,
                        available=available,
                        models=[client.model_name],
                        backend=backend,
                    )
                )
            except Exception as e:
                statuses.append(
                    ProviderStatus(
                        provider=provider,
                        available=False,
                        error=str(e),
                    )
                )

        return statuses

    def _build_messages(self, request: GenerationRequest) -> list[Message]:
        """Build the message list for the LLM.

        Args:
            request: The generation request

        Returns:
            List of messages
        """
        # Sanitize inputs
        query = sanitize_input(request.query)
        context = sanitize_input(request.context)

        # Handle SUMMARIZE intent specially - the query IS the full prompt
        # This is used by evidence summarization where the prompt already
        # contains the chunk text and instructions
        if request.intent and request.intent.upper() == "SUMMARIZE":
            system_prompt = (
                "You are a helpful assistant that extracts relevant information "
                "from scientific documents. Follow the instructions in the user message."
            )
            return [
                Message(role="system", content=system_prompt),
                Message(role="user", content=query),
            ]

        # Get citation mode
        citation_mode = request.citation_mode or self.settings.CITATION_MODE

        # Build system prompt
        system_prompt = build_system_prompt(citation_mode, request.intent)

        # Build user prompt
        user_prompt = build_user_prompt(query, context, request.citations)

        # Check prompt length
        total_length = len(system_prompt) + len(user_prompt)
        if total_length > self.settings.MAX_PROMPT_LENGTH:
            logger.warning(
                "Prompt exceeds max length",
                length=total_length,
                max=self.settings.MAX_PROMPT_LENGTH,
            )
            # Truncate context if needed
            max_context = self.settings.MAX_PROMPT_LENGTH - len(system_prompt) - len(query) - 500
            if max_context > 0:
                truncated_context = context[:max_context] + "\n[Context truncated...]"
                user_prompt = build_user_prompt(query, truncated_context, request.citations)

        return [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]


class CitationParser:
    """Parses and validates citations in generated text."""

    @staticmethod
    def extract_citations(text: str) -> list[int]:
        """Extract citation IDs from text.

        Args:
            text: The generated text

        Returns:
            List of citation IDs found
        """
        import re

        citations = re.findall(r"\[(\d+)\]", text)
        return sorted(set(int(c) for c in citations))

    @staticmethod
    def validate_citations(
        text: str,
        available_citations: list[CitationInfo],
    ) -> tuple[list[int], list[int]]:
        """Validate that cited sources exist.

        Args:
            text: The generated text
            available_citations: List of available citations

        Returns:
            Tuple of (valid_citations, invalid_citations)
        """
        used = CitationParser.extract_citations(text)
        available_ids = {c.citation_id for c in available_citations}

        valid = [c for c in used if c in available_ids]
        invalid = [c for c in used if c not in available_ids]

        return valid, invalid

    @staticmethod
    def highlight_citations(
        text: str,
        citation_format: str = "markdown",
    ) -> str:
        """Add highlighting to citations in text.

        Args:
            text: The generated text
            citation_format: Output format ("markdown", "html", "plain")

        Returns:
            Text with highlighted citations
        """
        import re

        if citation_format == "markdown":
            return re.sub(r"\[(\d+)\]", r"**[\1]**", text)
        elif citation_format == "html":
            return re.sub(
                r"\[(\d+)\]",
                r'<span class="citation">[\1]</span>',
                text,
            )
        else:
            return text
