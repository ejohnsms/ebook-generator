"""Backend interface shared by the MLX and Ollama model runners."""

from typing import Protocol


class BackendError(Exception):
    """Base exception for model backend errors (generation, loading, connection)."""

    pass


class GenerationBackend(Protocol):
    """What pipeline components need from a model runner.

    Components depend on this interface rather than a concrete client, so the
    pipeline can run on MLX (in-process, Apple Silicon) or Ollama (HTTP).
    """

    def health_check(self) -> bool:
        """Return True if the backend can serve requests."""
        ...

    def generate_text(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> str:
        """Generate a text completion."""
        ...

    def generate_image(
        self,
        model: str,
        prompt: str,
        width: int = 1024,
        height: int = 768,
        seed: int = 42,
    ) -> bytes:
        """Generate an image and return PNG bytes."""
        ...

    def close(self) -> None:
        """Release resources (HTTP connections, loaded models)."""
        ...
