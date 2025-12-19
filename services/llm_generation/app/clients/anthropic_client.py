"""Anthropic LLM client implementation."""

import time
from typing import AsyncIterator

import httpx
import structlog

from ..config import Settings
from ..core.schemas import GenerationResponse, Message, StreamChunk
from .base import BaseLLMClient

logger = structlog.get_logger()


class AnthropicClient(BaseLLMClient):
    """Client for Anthropic API (Claude)."""

    def __init__(self, settings: Settings):
        """Initialize the Anthropic client."""
        self.settings = settings
        self.api_key = settings.ANTHROPIC_API_KEY
        self.model = settings.ANTHROPIC_MODEL
        self.http_client = httpx.AsyncClient(timeout=120.0)

    @property
    def provider_name(self) -> str:
        """Get the provider name."""
        return "anthropic"

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self.model

    async def generate(
        self,
        messages: list[Message],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> GenerationResponse:
        """Generate a response from Anthropic."""
        start_time = time.time()

        if not self.api_key:
            raise ValueError("Anthropic API key not configured")

        # Extract system message and convert format
        system_content = ""
        api_messages = []

        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            else:
                api_messages.append({"role": msg.role, "content": msg.content})

        try:
            response = await self.http_client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "system": system_content,
                    "messages": api_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            result = response.json()

            content = result["content"][0]["text"]
            usage = result.get("usage", {})

            generation_time = (time.time() - start_time) * 1000

            # Extract citations used from response
            citations_used = self._extract_citations(content)

            # Calculate confidence
            confidence = self._calculate_confidence(content, citations_used)

            return GenerationResponse(
                answer=content,
                confidence=confidence,
                citations_used=citations_used,
                model_used=self.model,
                provider_used=self.provider_name,
                tokens_used=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                generation_time_ms=generation_time,
            )

        except httpx.HTTPStatusError as e:
            logger.error("Anthropic API error", status=e.response.status_code, detail=str(e))
            raise
        except Exception as e:
            logger.error("Anthropic generation failed", error=str(e))
            raise

    async def generate_stream(
        self,
        messages: list[Message],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response from Anthropic."""
        if not self.api_key:
            yield StreamChunk(type="error", content="Anthropic API key not configured")
            return

        # Extract system message
        system_content = ""
        api_messages = []

        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            else:
                api_messages.append({"role": msg.role, "content": msg.content})

        try:
            async with self.http_client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "system": system_content,
                    "messages": api_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()

                buffer = ""
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json

                        try:
                            data = json.loads(line[6:])
                            event_type = data.get("type")

                            if event_type == "content_block_delta":
                                delta = data.get("delta", {})
                                text = delta.get("text", "")

                                if text:
                                    buffer += text

                                    # Check for citation markers
                                    import re

                                    citation_match = re.search(r"\[(\d+)\]", buffer)
                                    if citation_match:
                                        pre_citation = buffer[: citation_match.start()]
                                        if pre_citation:
                                            yield StreamChunk(type="text", content=pre_citation)

                                        citation_id = int(citation_match.group(1))
                                        yield StreamChunk(type="citation", citation_id=citation_id)

                                        buffer = buffer[citation_match.end() :]
                                    elif len(buffer) > 50:
                                        yield StreamChunk(type="text", content=buffer)
                                        buffer = ""

                            elif event_type == "message_stop":
                                break

                        except json.JSONDecodeError:
                            continue

                # Emit remaining buffer
                if buffer:
                    yield StreamChunk(type="text", content=buffer)

                yield StreamChunk(type="done")

        except Exception as e:
            logger.error("Anthropic streaming failed", error=str(e))
            yield StreamChunk(type="error", content=str(e))

    async def is_available(self) -> bool:
        """Check if Anthropic API is available."""
        if not self.api_key:
            return False

        try:
            # Simple check - Anthropic doesn't have a models endpoint like OpenAI
            # We'll do a minimal completion request
            response = await self.http_client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5,
                },
                timeout=10.0,
            )
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.http_client.aclose()

    def _extract_citations(self, text: str) -> list[int]:
        """Extract citation IDs from generated text."""
        import re

        citations = re.findall(r"\[(\d+)\]", text)
        return sorted(set(int(c) for c in citations))

    def _calculate_confidence(self, text: str, citations: list[int]) -> float:
        """Calculate confidence score based on response quality."""
        confidence = 0.5

        if citations:
            confidence += min(0.3, len(citations) * 0.1)

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

        return max(0.1, min(0.95, confidence))
