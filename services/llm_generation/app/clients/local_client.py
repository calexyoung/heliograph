"""Local LLM client implementation (vLLM/Ollama)."""

import time
from typing import AsyncIterator

import httpx
import structlog

from ..config import Settings
from ..core.schemas import GenerationResponse, Message, StreamChunk
from .base import BaseLLMClient

logger = structlog.get_logger()


class LocalLLMClient(BaseLLMClient):
    """Client for local LLM servers (vLLM, Ollama, etc.)."""

    def __init__(self, settings: Settings):
        """Initialize the local LLM client."""
        self.settings = settings
        self.base_url = settings.LOCAL_MODEL_URL
        self.model = settings.LOCAL_MODEL_NAME
        self.http_client = httpx.AsyncClient(timeout=300.0)  # Longer timeout for local

    @property
    def provider_name(self) -> str:
        """Get the provider name."""
        return "local"

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
        """Generate a response from local LLM."""
        start_time = time.time()

        # Try OpenAI-compatible endpoint first (vLLM)
        try:
            return await self._generate_openai_compat(messages, temperature, max_tokens, start_time)
        except Exception as e:
            logger.debug("OpenAI-compat endpoint failed, trying Ollama", error=str(e))

        # Fall back to Ollama endpoint
        try:
            return await self._generate_ollama(messages, temperature, max_tokens, start_time)
        except Exception as e:
            logger.error("Local LLM generation failed", error=str(e))
            raise

    async def _generate_openai_compat(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        start_time: float,
    ) -> GenerationResponse:
        """Generate using OpenAI-compatible endpoint (vLLM)."""
        response = await self.http_client.post(
            f"{self.base_url}/v1/chat/completions",
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
        citations_used = self._extract_citations(content)

        return GenerationResponse(
            answer=content,
            confidence=self._calculate_confidence(content, citations_used),
            citations_used=citations_used,
            model_used=self.model,
            provider_used=self.provider_name,
            tokens_used=usage.get("total_tokens", 0),
            generation_time_ms=generation_time,
        )

    async def _generate_ollama(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        start_time: float,
    ) -> GenerationResponse:
        """Generate using Ollama endpoint."""
        # Build prompt from messages
        prompt_parts = []
        for msg in messages:
            if msg.role == "system":
                prompt_parts.append(f"System: {msg.content}")
            elif msg.role == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"Assistant: {msg.content}")

        prompt = "\n\n".join(prompt_parts) + "\n\nAssistant:"

        response = await self.http_client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "temperature": temperature,
                "num_predict": max_tokens,
                "stream": False,
            },
        )
        response.raise_for_status()
        result = response.json()

        content = result.get("response", "")
        generation_time = (time.time() - start_time) * 1000
        citations_used = self._extract_citations(content)

        return GenerationResponse(
            answer=content,
            confidence=self._calculate_confidence(content, citations_used),
            citations_used=citations_used,
            model_used=self.model,
            provider_used=self.provider_name,
            tokens_used=result.get("eval_count", 0),
            generation_time_ms=generation_time,
        )

    async def generate_stream(
        self,
        messages: list[Message],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response from local LLM."""
        # Try OpenAI-compatible streaming first
        try:
            async for chunk in self._stream_openai_compat(messages, temperature, max_tokens):
                yield chunk
            return
        except Exception as e:
            logger.debug("OpenAI-compat streaming failed, trying Ollama", error=str(e))

        # Fall back to Ollama streaming
        try:
            async for chunk in self._stream_ollama(messages, temperature, max_tokens):
                yield chunk
        except Exception as e:
            logger.error("Local LLM streaming failed", error=str(e))
            yield StreamChunk(type="error", content=str(e))

    async def _stream_openai_compat(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[StreamChunk]:
        """Stream using OpenAI-compatible endpoint."""
        async with self.http_client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
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
                            if len(buffer) > 20:
                                yield StreamChunk(type="text", content=buffer)
                                buffer = ""

                    except json.JSONDecodeError:
                        continue

            if buffer:
                yield StreamChunk(type="text", content=buffer)

            yield StreamChunk(type="done")

    async def _stream_ollama(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[StreamChunk]:
        """Stream using Ollama endpoint."""
        # Build prompt
        prompt_parts = []
        for msg in messages:
            if msg.role == "system":
                prompt_parts.append(f"System: {msg.content}")
            elif msg.role == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"Assistant: {msg.content}")

        prompt = "\n\n".join(prompt_parts) + "\n\nAssistant:"

        async with self.http_client.stream(
            "POST",
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "temperature": temperature,
                "num_predict": max_tokens,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()

            buffer = ""
            async for line in response.aiter_lines():
                if line:
                    import json

                    try:
                        data = json.loads(line)
                        content = data.get("response", "")

                        if content:
                            buffer += content
                            if len(buffer) > 20:
                                yield StreamChunk(type="text", content=buffer)
                                buffer = ""

                        if data.get("done"):
                            break

                    except json.JSONDecodeError:
                        continue

            if buffer:
                yield StreamChunk(type="text", content=buffer)

            yield StreamChunk(type="done")

    async def is_available(self) -> bool:
        """Check if local LLM server is available."""
        try:
            # Try health endpoint
            response = await self.http_client.get(
                f"{self.base_url}/health",
                timeout=5.0,
            )
            if response.status_code == 200:
                return True
        except Exception:
            pass

        try:
            # Try Ollama tags endpoint
            response = await self.http_client.get(
                f"{self.base_url}/api/tags",
                timeout=5.0,
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
        """Calculate confidence score."""
        confidence = 0.4  # Slightly lower baseline for local models

        if citations:
            confidence += min(0.35, len(citations) * 0.1)

        uncertainty_phrases = [
            "i'm not sure",
            "i don't have",
            "insufficient information",
            "cannot determine",
        ]
        text_lower = text.lower()
        for phrase in uncertainty_phrases:
            if phrase in text_lower:
                confidence -= 0.2
                break

        return max(0.1, min(0.9, confidence))
