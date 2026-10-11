"""Model backends: MLX (default, in-process), the host model server and Ollama (HTTP)."""

from ..config import BackendConfig, BackendKind
from .base import BackendError, GenerationBackend


def create_backend(config: BackendConfig) -> GenerationBackend:
    """Build the backend selected by config (EBOOK_GEN_BACKEND)."""
    if config.kind == BackendKind.OLLAMA:
        from ..ollama.client import OllamaClient

        return OllamaClient(config.ollama)

    if config.kind == BackendKind.REMOTE:
        from .remote_backend import RemoteBackend

        return RemoteBackend(config.model_server)

    from .mlx_backend import MLXBackend

    return MLXBackend()


__all__ = ["BackendError", "GenerationBackend", "create_backend"]
