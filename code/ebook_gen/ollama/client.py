"""Ollama HTTP client for LLM and image generation."""

import time
from typing import Optional

import httpx

from ..backends.base import BackendError
from ..config import OllamaConfig, RetryConfig


class OllamaError(BackendError):
    """Base exception for Ollama errors."""

    pass


class OllamaConnectionError(OllamaError):
    """Cannot reach the Ollama service."""

    pass


class OllamaModelNotFoundError(OllamaError):
    """Requested model is not available in Ollama."""

    pass


class OllamaGenerationError(OllamaError):
    """Ollama model returned an error during generation."""

    pass


class OllamaClient:
    """Thin wrapper around the Ollama HTTP API.

    Provides methods for text generation, health checks, and model management
    with built-in retry logic and error handling.
    """

    def __init__(
        self,
        config: Optional[OllamaConfig] = None,
        retry_config: Optional[RetryConfig] = None,
    ):
        """Initialize Ollama client.

        Args:
            config: Ollama configuration (base_url, timeout, etc.)
            retry_config: Retry behavior configuration
        """
        self._config = config or OllamaConfig()
        self._retry_config = retry_config or RetryConfig()
        self._client = httpx.Client(
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
        )

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close client."""
        self.close()

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def health_check(self) -> bool:
        """Check if Ollama is reachable and responsive.

        Returns:
            True if Ollama is healthy, False otherwise
        """
        try:
            response = self._client.get("/api/tags")
            return response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    def list_models(self) -> list[str]:
        """List available models.

        Returns:
            List of model names

        Raises:
            OllamaConnectionError: Cannot reach Ollama service
            OllamaGenerationError: Unexpected response format
        """
        try:
            response = self._client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama at {self._config.base_url}"
            ) from e
        except (KeyError, ValueError) as e:
            raise OllamaGenerationError(
                f"Unexpected response format from /api/tags"
            ) from e

    def generate_text(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> str:
        """Generate text completion.

        Args:
            model: Model name (e.g., "gemma4:12b")
            prompt: User prompt
            system: System prompt (optional)
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Cap on generated tokens (Ollama num_predict)
            stream: Whether to stream response (not implemented)

        Returns:
            Generated text

        Raises:
            OllamaConnectionError: Cannot reach Ollama service
            OllamaModelNotFoundError: Requested model is not pulled
            OllamaGenerationError: Model returned an error
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,  # We always use non-streaming for simplicity
            "think": False,  # skip reasoning on thinking models (gemma4); ignored by others
        }

        if system:
            payload["system"] = system

        payload["options"] = {"num_predict": max_tokens}
        if temperature != 0.7:
            payload["options"]["temperature"] = temperature

        # Retry logic
        for attempt in range(self._retry_config.max_attempts):
            try:
                response = self._client.post("/api/generate", json=payload)

                # Check for specific errors
                if response.status_code == 404:
                    raise OllamaModelNotFoundError(
                        f"Model '{model}' not found. Pull it with: ollama pull {model}"
                    )

                response.raise_for_status()
                data = response.json()

                # Extract response text
                if "response" not in data:
                    raise OllamaGenerationError(
                        f"Unexpected response format: {data}"
                    )

                return data["response"]

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                # Retry on connection errors
                if attempt < self._retry_config.max_attempts - 1:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                else:
                    raise OllamaConnectionError(
                        f"Cannot connect to Ollama after {self._retry_config.max_attempts} attempts"
                    ) from e

            except httpx.HTTPStatusError as e:
                # Don't retry on 4xx errors (client errors)
                if 400 <= e.response.status_code < 500:
                    raise OllamaGenerationError(
                        f"Ollama returned error: {e.response.text}"
                    ) from e
                # Retry on 5xx errors (server errors)
                if attempt < self._retry_config.max_attempts - 1:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                else:
                    raise OllamaGenerationError(
                        f"Ollama server error after {self._retry_config.max_attempts} attempts"
                    ) from e

        # Should not reach here, but just in case
        raise OllamaGenerationError("Generation failed after all retry attempts")

    def generate_image(
        self,
        model: str,
        prompt: str,
        width: int = 1024,
        height: int = 768,
        seed: int = 42,
    ) -> bytes:
        """Generate an image from a text prompt.

        Args:
            model: Model name (e.g., "x/flux2-klein:4b")
            prompt: Image generation prompt
            width: Image width in pixels
            height: Image height in pixels
            seed: Random seed for reproducibility

        Returns:
            Raw image bytes (PNG format)

        Raises:
            OllamaConnectionError: Cannot reach Ollama service
            OllamaModelNotFoundError: Requested model is not available
            OllamaGenerationError: Image generation failed
        """
        import base64
        import json as _json

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,  # Must stream: image arrives in a specific chunk, not final response
            "options": {
                "seed": seed,
                "width": width,
                "height": height,
            },
        }

        for attempt in range(self._retry_config.max_attempts):
            try:
                # Stream the response; the image chunk has an "image" key (singular)
                with self._client.stream("POST", "/api/generate", json=payload) as response:
                    if response.status_code == 404:
                        raise OllamaModelNotFoundError(
                            f"Model '{model}' not found. Pull it with: ollama pull {model}"
                        )

                    if response.is_error:
                        response.read()  # load the body so the error handler can read .text
                    response.raise_for_status()

                    image_b64: str | None = None
                    for line in response.iter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
                        if chunk.get("image"):
                            image_b64 = chunk["image"]
                            break  # found it; no need to read more chunks

                if not image_b64:
                    raise OllamaGenerationError(
                        f"No image data received from model '{model}'. "
                        f"Ensure the model is an image-generation model."
                    )

                # Strip data: URL prefix if present (e.g. "data:image/png;base64,...")
                if image_b64.startswith("data:") and "," in image_b64:
                    image_b64 = image_b64.split(",", 1)[1]

                try:
                    return base64.b64decode(image_b64)
                except Exception as decode_err:
                    raise OllamaGenerationError(
                        f"Failed to base64-decode image from model '{model}': {decode_err}"
                    ) from decode_err

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt < self._retry_config.max_attempts - 1:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                else:
                    raise OllamaConnectionError(
                        f"Cannot connect to Ollama after {self._retry_config.max_attempts} attempts"
                    ) from e

            except OllamaModelNotFoundError:
                raise  # Don't retry model-not-found errors

            except OllamaGenerationError:
                raise  # Don't retry generation errors

            except httpx.HTTPStatusError as e:
                if 400 <= e.response.status_code < 500:
                    raise OllamaGenerationError(
                        f"Ollama returned error: {e.response.text}"
                    ) from e
                if attempt < self._retry_config.max_attempts - 1:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                else:
                    raise OllamaGenerationError(
                        f"Ollama server error after {self._retry_config.max_attempts} attempts"
                    ) from e

        raise OllamaGenerationError("Image generation failed after all retry attempts")

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay.

        Args:
            attempt: Attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        delay = self._retry_config.base_delay_seconds * (
            self._retry_config.exponential_base ** attempt
        )
        return min(delay, self._retry_config.max_delay_seconds)
