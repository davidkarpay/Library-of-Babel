#!/usr/bin/env python3
"""
llm_client.py

Unified LLM client supporting local and cloud Ollama instances.
Provides both single-turn generation and multi-turn chat capabilities.

Usage:
    from llm_client import LLMClient

    llm = LLMClient()
    response = llm.generate("Explain quantum computing")

    # Or with system prompt
    response = llm.generate("Explain this code", system="You are a code reviewer")

    # Multi-turn chat
    response = llm.chat([
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "What's 2+2?"}
    ])

Environment Variables:
    OLLAMA_URL - Ollama server URL (default: http://localhost:11434)
    OLLAMA_MODEL - Model to use (default: llama3.1:8b)
"""

import os
import requests
from typing import Optional


class LLMClient:
    """Unified LLM client for local and cloud Ollama."""

    def __init__(self, url: str = None, model: str = None, api_key: str = None):
        """
        Initialize the LLM client.

        Args:
            url: Ollama server URL (overrides OLLAMA_URL env var)
            model: Model name (overrides OLLAMA_MODEL env var)
            api_key: Backend API key for authenticated requests (overrides OLLAMA_API_KEY env var)
        """
        self.url = url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        self.model = model or os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
        self.timeout = int(os.environ.get("OLLAMA_TIMEOUT", "120"))
        self.api_key = api_key or os.environ.get("OLLAMA_API_KEY", "")

    def _get_headers(self) -> dict:
        """Get request headers including authentication if configured."""
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-Backend-Key'] = self.api_key
        return headers

    def generate(self, prompt: str, system: str = None, timeout: int = None) -> str:
        """
        Generate a response from a single prompt.

        Args:
            prompt: The user prompt
            system: Optional system prompt for context
            timeout: Request timeout in seconds (default: self.timeout)

        Returns:
            Generated text response, or empty string on error
        """
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False
            }

            if system:
                payload["system"] = system

            response = requests.post(
                f"{self.url}/api/generate",
                headers=self._get_headers(),
                json=payload,
                timeout=timeout or self.timeout
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()

        except requests.exceptions.Timeout:
            print(f"Warning: LLM request timed out after {timeout or self.timeout}s")
            return ""
        except requests.exceptions.ConnectionError:
            print(f"Warning: Could not connect to Ollama at {self.url}")
            return ""
        except Exception as e:
            print(f"Warning: LLM request failed: {e}")
            return ""

    def chat(self, messages: list, system: str = None, timeout: int = None) -> str:
        """
        Multi-turn chat conversation.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
                      Roles: 'user', 'assistant', 'system'
            system: Optional system prompt (prepended to messages)
            timeout: Request timeout in seconds

        Returns:
            Assistant's response text, or empty string on error
        """
        try:
            # Build messages list with optional system prompt
            chat_messages = []
            if system:
                chat_messages.append({"role": "system", "content": system})
            chat_messages.extend(messages)

            response = requests.post(
                f"{self.url}/api/chat",
                headers=self._get_headers(),
                json={
                    "model": self.model,
                    "messages": chat_messages,
                    "stream": False
                },
                timeout=timeout or self.timeout
            )
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "").strip()

        except requests.exceptions.Timeout:
            print(f"Warning: LLM chat request timed out after {timeout or self.timeout}s")
            return ""
        except requests.exceptions.ConnectionError:
            print(f"Warning: Could not connect to Ollama at {self.url}")
            return ""
        except Exception as e:
            print(f"Warning: LLM chat request failed: {e}")
            return ""

    def is_available(self) -> bool:
        """Check if the Ollama server is reachable."""
        try:
            response = requests.get(
                f"{self.url}/api/tags",
                headers=self._get_headers(),
                timeout=5
            )
            return response.status_code == 200
        except:
            return False

    def list_models(self) -> list:
        """Get list of available models on the server."""
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=10)
            response.raise_for_status()
            models = response.json().get("models", [])
            return [m.get("name", "") for m in models]
        except:
            return []

    def __repr__(self):
        return f"LLMClient(url='{self.url}', model='{self.model}')"


# Convenience function for backward compatibility
def ollama_generate(prompt: str, timeout: int = 60) -> str:
    """
    Legacy function for backward compatibility with existing code.

    Args:
        prompt: The prompt to send
        timeout: Request timeout

    Returns:
        Generated response
    """
    client = LLMClient()
    return client.generate(prompt, timeout=timeout)


if __name__ == "__main__":
    # Quick test
    print("Testing LLM Client...")
    llm = LLMClient()
    print(f"Client: {llm}")
    print(f"Available: {llm.is_available()}")

    if llm.is_available():
        print(f"Models: {llm.list_models()}")
        print("\nTest generation:")
        response = llm.generate("Say 'Hello, world!' and nothing else.")
        print(f"Response: {response}")
