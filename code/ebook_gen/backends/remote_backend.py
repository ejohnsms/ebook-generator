"""HTTP client for the host model server (ebook_gen.model_server).

Pipeline containers run Linux VMs without Metal, so they can't run MLX
themselves; they send text and image requests to the model server running
natively on the macOS host.
"""

import httpx

from ..config import ModelServerConfig
from .base import BackendError


class RemoteBackend:
    """GenerationBackend that forwards requests to the host model server."""

    def __init__(self, config: ModelServerConfig | None = None) -> None:
        self._config = config or ModelServerConfig()
        headers = {}
        if self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"
        self._client = httpx.Client(
            base_url=self._config.url,
            headers=headers,
            timeout=httpx.Timeout(self._config.timeout_seconds, connect=10.0),
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self) -> None:
        self._client.close()

    def health_check(self) -> bool:
        try:
            return self._client.get("/health", timeout=10.0).status_code == 200
        except httpx.HTTPError:
            return False

    def generate_text(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        return self._post("/v1/text", payload).json()["text"]

    def generate_image(
        self,
        model: str,
        prompt: str,
        width: int = 1024,
        height: int = 768,
        seed: int = 42,
    ) -> bytes:
        payload = {
            "model": model,
            "prompt": prompt,
            "width": width,
            "height": height,
            "seed": seed,
        }
        return self._post("/v1/image", payload).content

    def _post(self, path: str, payload: dict) -> httpx.Response:
        try:
            response = self._client.post(path, json=payload)
        except httpx.HTTPError as e:
            raise BackendError(f"Cannot reach model server at {self._config.url}: {e}") from e

        if response.is_error:
            try:
                detail = response.json().get("error", response.text)
            except ValueError:
                detail = response.text
            raise BackendError(f"Model server error ({response.status_code}): {detail}")
        return response
