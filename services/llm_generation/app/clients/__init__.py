"""LLM Clients module.

This module provides clients for various LLM providers:
- LiteLLMClient: Unified client supporting 100+ providers (recommended)
- OpenAIClient: Direct OpenAI API client
- AnthropicClient: Direct Anthropic API client
- LocalLLMClient: Client for local models (vLLM/Ollama)
"""

from .anthropic_client import AnthropicClient
from .base import BaseLLMClient
from .local_client import LocalLLMClient
from .openai_client import OpenAIClient

# LiteLLM client (optional - requires litellm package)
try:
    from .litellm_client import LiteLLMClient, get_litellm_client
except ImportError:
    LiteLLMClient = None
    get_litellm_client = None

__all__ = [
    "BaseLLMClient",
    "OpenAIClient",
    "AnthropicClient",
    "LocalLLMClient",
    "LiteLLMClient",
    "get_litellm_client",
]
