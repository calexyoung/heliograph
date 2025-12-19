"""OpenAI LLM client implementation."""

import time
from typing import AsyncIterator

import httpx
import structlog

from ..config import Settings
from ..core.schemas import GenerationResponse, Message, StreamChunk
from .base import BaseLLMClient

logger = structlog.get_logger()


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI API."""

    def __init__(self, settings: Settings):
        """Initialize the OpenAI client."""
        self.settings = settings
        self.api_key = settings.OPENAI_API_KEY
        self.model = settings.OPENAI_MODEL
        self.http_client = httpx.AsyncClient(timeout=120.0)

    @property
    def provider_name(self) -> str:
        """Get the provider name."""
        return "openai"

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
        """Generate a response from OpenAI."""
        start_time = time.time()

        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        try:
            response = await self.http_client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            result = response.json()

            content = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})

            generation_time = (time.time() - start_time) * 1000

            # Extract citations used from response
            citations_used = self._extract_citations(content)

            # Calculate confidence based on response characteristics
            confidence = self._calculate_confidence(content, citations_used)

            return GenerationResponse(
                answer=content,
                confidence=confidence,
                citations_used=citations_used,
                model_used=self.model,
                provider_used=self.provider_name,
                tokens_used=usage.get("total_tokens", 0),
                generation_time_ms=generation_time,
            )

        except httpx.HTTPStatusError as e:
            logger.error("OpenAI API error", status=e.response.status_code, detail=str(e))
            raise
        except Exception as e:
            logger.error("OpenAI generation failed", error=str(e))
            raise

    async def generate_stream(
        self,
        messages: list[Message],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response from OpenAI."""
        if not self.api_key:
            yield StreamChunk(type="error", content="OpenAI API key not configured")
            return

        try:
            async with self.http_client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()

                buffer = ""
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break

                        import json

                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")

                            if content:
                                buffer += content

                                # Check for citation markers
                                import re

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

                        except json.JSONDecodeError:
                            continue

                # Emit remaining buffer
                if buffer:
                    yield StreamChunk(type="text", content=buffer)

                yield StreamChunk(type="done")

        except Exception as e:
            logger.error("OpenAI streaming failed", error=str(e))
            yield StreamChunk(type="error", content=str(e))

    async def is_available(self) -> bool:
        """Check if OpenAI API is available."""
        if not self.api_key:
            return False

        try:
            response = await self.http_client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
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
