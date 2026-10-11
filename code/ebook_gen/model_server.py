"""Model server: runs MLX text and image models natively on the macOS host.

The pipeline containers are Linux VMs without access to Metal, so they send
generation requests here (EBOOK_GEN_BACKEND=remote) instead of loading models
themselves. Started by the ./ebook-gen wrapper; standard library only apart
from the MLX backend's own dependencies.

    POST /v1/text   {model, prompt, system, temperature, max_tokens} -> {"text": ...}
    POST /v1/image  {model, prompt, width, height, seed}             -> PNG bytes
    GET  /health                                                     -> {"status": "ok"}

Requests must carry "Authorization: Bearer <EBOOK_GEN_MODEL_SERVER_TOKEN>"
when a token is set, since the server listens on all interfaces: the
container network's host address only exists while a container is running.
"""

import argparse
import hmac
import json
import logging
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .backends.base import BackendError, GenerationBackend

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8765
DEFAULT_IDLE_UNLOAD_SECONDS = 600


class ModelServer(ThreadingHTTPServer):
    """HTTP server around one backend; generation requests run one at a time.

    The loaded model is released after idle_unload_seconds without requests,
    so a server left running doesn't hold ~8 GB of unified memory.
    """

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        backend: GenerationBackend,
        token: str = "",
        idle_unload_seconds: float = DEFAULT_IDLE_UNLOAD_SECONDS,
    ):
        super().__init__(address, _Handler)
        self.backend = backend
        self.token = token
        # MLX holds one model at a time; serialize generation so /health still
        # answers while an image is being rendered.
        self.generation_lock = threading.Lock()
        self.last_used: float | None = None  # None: nothing loaded since last unload
        self._idle_unload_seconds = idle_unload_seconds
        if idle_unload_seconds > 0:
            threading.Thread(target=self._unload_when_idle, daemon=True).start()

    def _unload_when_idle(self) -> None:
        while True:
            time.sleep(min(30.0, self._idle_unload_seconds))
            with self.generation_lock:
                if self.last_used is None:
                    continue
                if time.monotonic() - self.last_used >= self._idle_unload_seconds:
                    logger.info("Idle; releasing the loaded model")
                    self.backend.close()
                    self.last_used = None


class _Handler(BaseHTTPRequestHandler):
    server: ModelServer

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_error(HTTPStatus.NOT_FOUND, f"Unknown path: {self.path}")
        elif not self._authorized():
            self._send_error(HTTPStatus.UNAUTHORIZED, "Missing or wrong model server token")
        else:
            self._send_json({"status": "ok"})

    def do_POST(self) -> None:
        if self.path not in ("/v1/text", "/v1/image"):
            self._send_error(HTTPStatus.NOT_FOUND, f"Unknown path: {self.path}")
            return
        if not self._authorized():
            self._send_error(HTTPStatus.UNAUTHORIZED, "Missing or wrong model server token")
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            request = json.loads(self.rfile.read(length) or b"{}")
            model, prompt = request["model"], request["prompt"]
        except (ValueError, KeyError, TypeError) as e:
            self._send_error(HTTPStatus.BAD_REQUEST, f"Bad request body: {e}")
            return

        try:
            with self.server.generation_lock:
                try:
                    if self.path == "/v1/text":
                        text = self.server.backend.generate_text(
                            model,
                            prompt,
                            system=request.get("system", ""),
                            temperature=float(request.get("temperature", 0.7)),
                            max_tokens=int(request.get("max_tokens", 8192)),
                        )
                    else:
                        png = self.server.backend.generate_image(
                            model,
                            prompt,
                            width=int(request.get("width", 1024)),
                            height=int(request.get("height", 768)),
                            seed=int(request.get("seed", 42)),
                        )
                finally:
                    self.server.last_used = time.monotonic()
        except BackendError as e:
            logger.error(str(e))
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))
            return

        if self.path == "/v1/text":
            self._send_json({"text": text})
        else:
            self._send(HTTPStatus.OK, "image/png", png)

    def _authorized(self) -> bool:
        if not self.server.token:
            return True
        expected = f"Bearer {self.server.token}"
        return hmac.compare_digest(self.headers.get("Authorization", ""), expected)

    def _send_json(self, body: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(status, "application/json", json.dumps(body).encode())

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status)

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        logger.info(f"{self.address_string()} {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve MLX text and image models over HTTP")
    parser.add_argument("--host", default=os.getenv("EBOOK_GEN_MODEL_SERVER_BIND", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    from .backends.mlx_backend import MLXBackend

    backend = MLXBackend()
    if not backend.health_check():
        raise SystemExit("MLX is unavailable: the model server needs macOS on Apple Silicon")

    token = os.getenv("EBOOK_GEN_MODEL_SERVER_TOKEN", "")
    if not token:
        logger.warning("EBOOK_GEN_MODEL_SERVER_TOKEN is not set; accepting unauthenticated requests")

    idle = float(os.getenv("EBOOK_GEN_MODEL_IDLE_SECONDS", DEFAULT_IDLE_UNLOAD_SECONDS))
    server = ModelServer((args.host, args.port), backend, token, idle_unload_seconds=idle)
    logger.info(f"Model server listening on {args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        backend.close()


if __name__ == "__main__":
    main()
