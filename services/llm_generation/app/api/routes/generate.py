"""Generation API routes for LLM Generation service."""

from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ...config import Settings, get_settings
from ...core.generator import GenerationService
from ...core.schemas import (
    ConversationRequest,
    ConversationResponse,
    GenerationRequest,
    GenerationResponse,
    Message,
    ProviderStatus,
    StreamChunk,
)

router = APIRouter(prefix="/generate", tags=["generate"])

# Global service instance
_service: GenerationService | None = None


async def get_service(settings: Settings = Depends(get_settings)) -> GenerationService:
    """Get the generation service instance."""
    global _service
    if _service is None:
        _service = GenerationService(settings)
    return _service


@router.post("", response_model=GenerationResponse)
async def generate(
    request: GenerationRequest,
    service: GenerationService = Depends(get_service),
) -> GenerationResponse:
    """Generate a response from the LLM.

    Takes a query, context, and citations and generates an answer
    with inline citations.

    Args:
        request: Generation request with query and context

    Returns:
        Generated response with citations
    """
    try:
        return await service.generate(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def generate_stream(
    request: GenerationRequest,
    service: GenerationService = Depends(get_service),
) -> StreamingResponse:
    """Generate a streaming response from the LLM.

    Returns a server-sent events stream with:
    - text: Generated text chunks
    - citation: Citation markers as they appear
    - error: Error messages
    - done: End of stream
    """
    async def generate() -> AsyncIterator[str]:
        import json

        try:
            async for chunk in service.generate_stream(request):
                yield f"data: {json.dumps(chunk.model_dump())}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/conversation", response_model=ConversationResponse)
async def conversation(
    request: ConversationRequest,
    service: GenerationService = Depends(get_service),
) -> ConversationResponse:
    """Handle multi-turn conversation.

    Takes a list of messages and optional context/citations,
    and generates a response continuing the conversation.
    """
    from ...prompts.templates import build_conversation_prompt, build_system_prompt

    # Build messages for the LLM
    messages = []

    # Add system message
    system_prompt = build_system_prompt("relaxed")  # Use relaxed mode for conversation
    messages.append(Message(role="system", content=system_prompt))

    # Add context if provided
    if request.context or request.citations:
        context_prompt = build_conversation_prompt(request.context, request.citations)
        if context_prompt:
            messages.append(Message(role="user", content=f"Context:\n{context_prompt}"))
            messages.append(Message(role="assistant", content="I'll use this context to help answer your questions."))

    # Add conversation messages
    for msg in request.messages:
        messages.append(msg)

    # Get client and generate
    client = service.get_client(request.provider)
    temperature = request.temperature or 0.5
    max_tokens = request.max_tokens or 2000

    response = await client.generate(messages, temperature, max_tokens)

    return ConversationResponse(
        message=Message(role="assistant", content=response.answer),
        confidence=response.confidence,
        citations_used=response.citations_used,
        model_used=response.model_used,
        tokens_used=response.tokens_used,
    )


@router.get("/providers", response_model=list[ProviderStatus])
async def get_providers(
    service: GenerationService = Depends(get_service),
) -> list[ProviderStatus]:
    """Get status of available LLM providers."""
    return await service.get_provider_status()


@router.get("/providers/{provider}/status", response_model=ProviderStatus)
async def get_provider_status(
    provider: str,
    service: GenerationService = Depends(get_service),
) -> ProviderStatus:
    """Get status of a specific provider."""
    try:
        client = service.get_client(provider)
        available = await client.is_available()
        return ProviderStatus(
            provider=provider,
            available=available,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        return ProviderStatus(
            provider=provider,
            available=False,
            error=str(e),
        )
