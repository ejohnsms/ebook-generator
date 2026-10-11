"""Tests for the host model server and the RemoteBackend that pipeline containers use."""

import threading

import pytest

from ebook_gen.backends import BackendError, create_backend
from ebook_gen.backends.remote_backend import RemoteBackend
from ebook_gen.config import BackendConfig, BackendKind, ModelServerConfig
from ebook_gen.model_server import ModelServer


class FakeBackend:
    """Records calls; fails when the prompt is 'fail'."""

    def __init__(self):
        self.calls = []
        self.closed = 0

    def generate_text(self, model, prompt, system="", temperature=0.7, max_tokens=8192):
        if prompt == "fail":
            raise BackendError("model exploded")
        self.calls.append(("text", model, prompt, system, temperature, max_tokens))
        return f"echo: {prompt}"

    def generate_image(self, model, prompt, width=1024, height=768, seed=42):
        self.calls.append(("image", model, prompt, width, height, seed))
        return b"\x89PNG fake"

    def close(self):
        self.closed += 1


@pytest.fixture
def server():
    backend = FakeBackend()
    srv = ModelServer(("127.0.0.1", 0), backend, token="secret", idle_unload_seconds=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def client_for(server, token="secret") -> RemoteBackend:
    host, port = server.server_address[:2]
    return RemoteBackend(ModelServerConfig(url=f"http://{host}:{port}", token=token))


class TestRemoteBackend:
    def test_selected_from_env(self, monkeypatch):
        monkeypatch.setenv("EBOOK_GEN_BACKEND", "remote")
        monkeypatch.setenv("EBOOK_GEN_MODEL_SERVER", "http://192.168.64.1:9999")
        config = BackendConfig.from_env()
        assert config.kind == BackendKind.REMOTE
        assert config.model_server.url == "http://192.168.64.1:9999"
        backend = create_backend(config)
        try:
            assert isinstance(backend, RemoteBackend)
        finally:
            backend.close()

    def test_text_round_trip(self, server):
        with client_for(server) as client:
            assert client.health_check()
            text = client.generate_text("m", "hi", system="sys", temperature=0.2, max_tokens=50)
        assert text == "echo: hi"
        assert server.backend.calls == [("text", "m", "hi", "sys", 0.2, 50)]

    def test_image_round_trip(self, server):
        with client_for(server) as client:
            png = client.generate_image("flux", "a goat", width=256, height=192, seed=7)
        assert png == b"\x89PNG fake"
        assert server.backend.calls == [("image", "flux", "a goat", 256, 192, 7)]

    def test_backend_error_is_reported(self, server):
        with client_for(server) as client:
            with pytest.raises(BackendError, match="model exploded"):
                client.generate_text("m", "fail")

    def test_wrong_token_is_rejected(self, server):
        with client_for(server, token="wrong") as client:
            assert not client.health_check()
            with pytest.raises(BackendError, match="401"):
                client.generate_text("m", "hi")
        assert server.backend.calls == []

    def test_unreachable_server(self):
        client = RemoteBackend(ModelServerConfig(url="http://127.0.0.1:1", timeout_seconds=2))
        with client:
            assert not client.health_check()
            with pytest.raises(BackendError, match="Cannot reach model server"):
                client.generate_text("m", "hi")


class TestIdleUnload:
    def test_releases_model_after_idle(self):
        backend = FakeBackend()
        srv = ModelServer(("127.0.0.1", 0), backend, idle_unload_seconds=0.05)
        try:
            srv.last_used = 0.0  # long ago
            for _ in range(100):
                if backend.closed:
                    break
                threading.Event().wait(0.02)
            assert backend.closed == 1
            assert srv.last_used is None
        finally:
            srv.server_close()
