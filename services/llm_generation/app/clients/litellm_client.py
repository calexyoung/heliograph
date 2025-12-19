"""Unified LLM client using LiteLLM.

LiteLLM provides a unified interface for 100+ LLM providers including:
- OpenAI (gpt-4, gpt-3.5-turbo, etc.)
- Anthropic (claude-3-opus, claude-3-sonnet, etc.)
- Azure OpenAI
- AWS Bedrock
- Google Vertex AI
- Ollama (local models)
- vLLM (local models)
- And many more

This replaces the separate OpenAI, Anthropic, and Local clients with a single
implementation that can seamlessly switch between providers.
"""

import re
import time
from typing import Any, AsyncIterator

import structlog

from ..config import Settings
from ..core.schemas import GenerationResponse, Message, StreamChunk
from .base import BaseLLMClient

logger = structlog.get_logger()

# Provider model prefixes for LiteLLM
# See: https://docs.litellm.ai/docs/providers
PROVIDER_MODEL_MAP = {
    "openai": "",  # No prefix needed for OpenAI
    "anthropic": "anthropic/",  # e.g., anthropic/claude-3-5-sonnet-20241022
    "azure": "azure/",  # e.g., azure/gpt-4
    "bedrock": "bedrock/",  # e.g., bedrock/anthropic.claude-3-sonnet
    "vertex_ai": "vertex_ai/",  # e.g., vertex_ai/gemini-pro
    "ollama": "ollama/",  # e.g., ollama/llama2
    "vllm": "openai/",  # vLLM uses OpenAI-compatible API
    "local": "ollama/",  # Default local models to Ollama
}


class LiteLLMClient(BaseLLMClient):
    """Unified LLM client using LiteLLM.

    Provides a single interface to all supported LLM providers with:
    - Automatic fallbacks between providers
    - Consistent API across providers
    - Built-in retries and error handling
    - Streaming support
    - Cost tracking
    """

    def __init__(
        self,
        settings: Settings,
        provider: str | None = None,
        model: str | None = None,
        fallback_models: list[str] | None = None,
    ):
        """Initialize the LiteLLM client.

        Args:
            settings: Service settings
            provider: Provider to use (openai, anthropic, local, etc.)
            model: Model name override
            fallback_models: List of fallback models if primary fails
        """
        self.settings = settings
        self._provider = provider or settings.DEFAULT_PROVIDER
        self._model = model or self._get_default_model()
        self._fallback_models = fallback_models or []
        self._litellm = None

        # Configure API keys based on provider
        self._configure_environment()

    def _get_default_model(self) -> str:
        """Get default model based on provider."""
        if self._provider == "openai":
            return self.settings.OPENAI_MODEL
        elif self._provider == "anthropic":
            return self.settings.ANTHROPIC_MODEL
        elif self._provider in ("local", "ollama", "vllm"):
            return self.settings.LOCAL_MODEL_NAME
        else:
            return self.settings.OPENAI_MODEL

    def _configure_environment(self) -> None:
        """Configure environment variables for LiteLLM."""
        import os

        # LiteLLM reads from environment variables
        if self.settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = self.settings.OPENAI_API_KEY

        if self.settings.ANTHROPIC_API_KEY:
            os.environ["ANTHROPIC_API_KEY"] = self.settings.ANTHROPIC_API_KEY

        # For local models, configure the base URL
        if self._provider in ("local", "ollama", "vllm"):
            # Ollama default
            os.environ.setdefault("OLLAMA_API_BASE", "http://localhost:11434")

    def _get_litellm(self):
        """Lazy import LiteLLM to avoid import errors if not installed."""
        if self._litellm is None:
            try:
                import litellm

                # Configure LiteLLM settings
                litellm.drop_params = True  # Drop unsupported params gracefully
                litellm.set_verbose = self.settings.DEBUG

                self._litellm = litellm
            except ImportError:
                raise RuntimeError(
                    "litellm not installed. Install with: pip install litellm"
                )
        return self._litellm

    def _get_model_name(self) -> str:
        """Get the full model name with provider prefix."""
        prefix = PROVIDER_MODEL_MAP.get(self._provider, "")
        return f"{prefix}{self._model}"

    @property
    def provider_name(self) -> str:
        """Get the provider name."""
        return self._provider

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self._model

    async def generate(
        self,
        messages: list[Message],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> GenerationResponse:
        """Generate a response using LiteLLM.

        Args:
            messages: List of messages in the conversation
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            GenerationResponse with the generated text
        """
        start_time = time.time()
        litellm = self._get_litellm()

        # Convert messages to dict format
        message_dicts = [{"role": m.role, "content": m.content} for m in messages]

        model_name = self._get_model_name()

        # Build kwargs based on provider
        kwargs = self._build_completion_kwargs(
            model_name, message_dicts, temperature, max_tokens
        )

        try:
            logger.debug(
                "litellm_generate",
                model=model_name,
                provider=self._provider,
                message_count=len(messages),
            )

            # Use acompletion for async
            response = await litellm.acompletion(**kwargs)

            content = response.choices[0].message.content
            usage = response.usage

            generation_time = (time.time() - start_time) * 1000

            # Extract citations used from response
            citations_used = self._extract_citations(content)

            # Calculate confidence based on response characteristics
            confidence = self._calculate_confidence(content, citations_used)

            return GenerationResponse(
                answer=content,
                confidence=confidence,
                citations_used=citations_used,
                model_used=self._model,
                provider_used=self._provider,
                tokens_used=usage.total_tokens if usage else 0,
                generation_time_ms=generation_time,
            )

        except Exception as e:
            logger.error(
                "litellm_generate_failed",
                model=model_name,
                error=str(e),
                provider=self._provider,
            )

            # Try fallback models if available
            if self._fallback_models:
                return await self._try_fallbacks(
                    messages, temperature, max_tokens, start_time
                )

            raise

    async def _try_fallbacks(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        start_time: float,
    ) -> GenerationResponse:
        """Try fallback models if primary fails."""
        litellm = self._get_litellm()
        message_dicts = [{"role": m.role, "content": m.content} for m in messages]

        for fallback_model in self._fallback_models:
            try:
                logger.info("litellm_trying_fallback", model=fallback_model)

                kwargs = self._build_completion_kwargs(
                    fallback_model, message_dicts, temperature, max_tokens
                )
                response = await litellm.acompletion(**kwargs)

                content = response.choices[0].message.content
                usage = response.usage

                generation_time = (time.time() - start_time) * 1000

                citations_used = self._extract_citations(content)
                confidence = self._calculate_confidence(content, citations_used)

                # Extract provider from fallback model name
                provider = "unknown"
                for p, prefix in PROVIDER_MODEL_MAP.items():
                    if fallback_model.startswith(prefix):
                        provider = p
                        break

                return GenerationResponse(
                    answer=content,
                    confidence=confidence,
                    citations_used=citations_used,
                    model_used=fallback_model,
                    provider_used=provider,
                    tokens_used=usage.total_tokens if usage else 0,
                    generation_time_ms=generation_time,
                )

            except Exception as e:
                logger.warning(
                    "litellm_fallback_failed",
                    model=fallback_model,
                    error=str(e),
                )
                continue

        raise RuntimeError("All fallback models failed")

    async def generate_stream(
        self,
        messages: list[Message],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response using LiteLLM.

        Args:
            messages: List of messages in the conversation
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Yields:
            StreamChunk objects with generated content
        """
        litellm = self._get_litellm()

        message_dicts = [{"role": m.role, "content": m.content} for m in messages]
        model_name = self._get_model_name()

        kwargs = self._build_completion_kwargs(
            model_name, message_dicts, temperature, max_tokens, stream=True
        )

        try:
            response = await litellm.acompletion(**kwargs)

            buffer = ""
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    content = chunk.choices[0].delta.content or ""

                    if content:
                        buffer += content

                        # Check for citation markers
                        citation_match = re.search(r"\[(\d+)\]", buffer)
                        if citation_match:
                            # Emit text before citation
                            pre_citation = buffer[: citation_match.start()]
                            if pre_citation:
                                yield StreamChunk(type="text", content=pre_citation)

                            # Emit citation
                            citation_id = int(citation_match.group(1))
                            yield StreamChunk(type="citation", citation_id=citation_id)

                            # Keep text after citation in buffer
                            buffer = buffer[citation_match.end() :]
                        elif len(buffer) > 50:
                            # Emit accumulated text
                            yield StreamChunk(type="text", content=buffer)
                            buffer = ""

            # Emit remaining buffer
            if buffer:
                yield StreamChunk(type="text", content=buffer)

            yield StreamChunk(type="done")

        except Exception as e:
            logger.error(
                "litellm_stream_failed",
                model=model_name,
                error=str(e),
            )
            yield StreamChunk(type="error", content=str(e))

    async def is_available(self) -> bool:
        """Check if the LLM provider is available.

        Returns:
            True if the provider can make requests
        """
        try:
            litellm = self._get_litellm()

            # Quick test with minimal tokens
            response = await litellm.acompletion(
                model=self._get_model_name(),
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            return response is not None

        except Exception as e:
            logger.debug(
                "litellm_availability_check_failed",
                provider=self._provider,
                error=str(e),
            )
            return False

    async def close(self) -> None:
        """Clean up resources."""
        # LiteLLM manages its own connections
        pass

    def _build_completion_kwargs(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Build kwargs for LiteLLM completion call.

        Args:
            model: Model name with provider prefix
            messages: Messages in dict format
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            stream: Whether to stream

        Returns:
            Dict of kwargs for acompletion
        """
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        # Add provider-specific configurations
        if self._provider in ("local", "ollama"):
            kwargs["api_base"] = self.settings.LOCAL_MODEL_URL

        elif self._provider == "vllm":
            kwargs["api_base"] = self.settings.LOCAL_MODEL_URL
            # vLLM uses OpenAI-compatible API
            kwargs["custom_llm_provider"] = "openai"

        return kwargs

    def _extract_citations(self, text: str) -> list[int]:
        """Extract citation IDs from generated text."""
        citations = re.findall(r"\[(\d+)\]", text)
        return sorted(set(int(c) for c in citations))

    def _calculate_confidence(self, text: str, citations: list[int]) -> float:
        """Calculate confidence score based on response quality."""
        # Base confidence
        confidence = 0.5

        # Boost for citations
        if citations:
            confidence += min(0.3, len(citations) * 0.1)

        # Reduce if response contains uncertainty markers
        uncertainty_phrases = [
            "i'm not sure",
            "i don't have",
            "insufficient information",
            "cannot determine",
            "unclear from",
        ]
        text_lower = text.lower()
        for phrase in uncertainty_phrases:
            if phrase in text_lower:
                confidence -= 0.2
                break

        # Ensure bounds
        return max(0.1, min(0.95, confidence))


def get_litellm_client(
    settings: Settings,
    provider: str | None = None,
    with_fallbacks: bool = True,
) -> LiteLLMClient:
    """Factory function to create a LiteLLM client with optional fallbacks.

    Args:
        settings: Service settings
        provider: Primary provider (defaults to settings.DEFAULT_PROVIDER)
        with_fallbacks: Whether to enable automatic fallbacks

    Returns:
        Configured LiteLLMClient instance
    """
    fallback_models = []

    if with_fallbacks:
        # Configure fallbacks based on available API keys
        if settings.OPENAI_API_KEY:
            fallback_models.append(f"{settings.OPENAI_MODEL}")

        if settings.ANTHROPIC_API_KEY:
            fallback_models.append(f"anthropic/{settings.ANTHROPIC_MODEL}")

        # Local models as last resort
        fallback_models.append(f"ollama/{settings.LOCAL_MODEL_NAME}")

    return LiteLLMClient(
        settings=settings,
        provider=provider,
        fallback_models=fallback_models,
    )
