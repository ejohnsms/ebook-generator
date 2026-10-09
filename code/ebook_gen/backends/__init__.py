"""Model backends: MLX (default, in-process) and Ollama (HTTP)."""

from ..config import BackendConfig, BackendKind
from .base import BackendError, GenerationBackend


def create_backend(config: BackendConfig) -> GenerationBackend:
    """Build the backend selected by config (EBOOK_GEN_BACKEND)."""
    if config.kind == BackendKind.OLLAMA:
        from ..ollama.client import OllamaClient

        return OllamaClient(config.ollama)

    from .mlx_backend import MLXBackend

    return MLXBackend()


__all__ = ["BackendError", "GenerationBackend", "create_backend"]
