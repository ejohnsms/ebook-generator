"""Tests for model backends (selection, MLX helpers, legacy model names)."""

import pytest

from ebook_gen.backends import BackendError, create_backend
from ebook_gen.backends.mlx_backend import MLXBackend, resolve_model_name
from ebook_gen.config import (
    DEFAULT_IMAGE_MODEL_FINAL,
    DEFAULT_IMAGE_MODEL_PREVIEW,
    DEFAULT_TEXT_MODEL,
    BackendConfig,
    BackendKind,
)
from ebook_gen.models import StoryConfig
from ebook_gen.ollama.client import OllamaClient, OllamaError


class FakeTokenizer:
    """Records chat messages; optionally rejects a system role like some templates do."""

    def __init__(self, reject_system: bool = False):
        self.reject_system = reject_system
        self.messages = None
        self.kwargs = None

    def apply_chat_template(self, messages, **kwargs):
        if self.reject_system and messages[0]["role"] == "system":
            raise ValueError("System role not supported")
        self.messages = messages
        self.kwargs = kwargs
        return "<prompt>"


class TestBackendSelection:
    def test_default_is_mlx(self, monkeypatch):
        monkeypatch.delenv("EBOOK_GEN_BACKEND", raising=False)
        assert BackendConfig.from_env().kind == BackendKind.MLX
        assert isinstance(create_backend(BackendConfig()), MLXBackend)

    def test_ollama_from_env(self, monkeypatch):
        monkeypatch.setenv("EBOOK_GEN_BACKEND", "ollama")
        backend = create_backend(BackendConfig.from_env())
        try:
            assert isinstance(backend, OllamaClient)
        finally:
            backend.close()

    def test_ollama_errors_are_backend_errors(self):
        assert issubclass(OllamaError, BackendError)


class TestLegacyModelNames:
    @pytest.mark.parametrize(
        "legacy, expected",
        [
            ("gemma4:12b", DEFAULT_TEXT_MODEL),
            ("llama3.1:8b", DEFAULT_TEXT_MODEL),
            ("brxce/stable-diffusion-prompt-generator", DEFAULT_TEXT_MODEL),
            ("x/flux2-klein:4b", DEFAULT_IMAGE_MODEL_PREVIEW),
            ("x/flux2-klein:9b", DEFAULT_IMAGE_MODEL_FINAL),
        ],
    )
    def test_ollama_tags_map_to_mlx(self, legacy, expected):
        assert resolve_model_name(legacy) == expected

    def test_repo_ids_pass_through(self):
        assert resolve_model_name("mlx-community/some-model") == "mlx-community/some-model"

    def test_story_config_reads_legacy_keys(self):
        config = StoryConfig.from_dict(
            {
                "story_id": "s",
                "title": "S",
                "source_file": "s.txt",
                "ollama_text_model": "llama3.1:8b",
                "ollama_image_model_final": "x/flux2-klein:9b",
                "created_at": "2026-01-01T00:00:00",
                "modified_at": "2026-01-01T00:00:00",
            }
        )
        assert config.text_model == "llama3.1:8b"
        assert config.image_model_final == "x/flux2-klein:9b"
        assert config.image_model_preview == DEFAULT_IMAGE_MODEL_PREVIEW
        assert "text_model" in config.to_dict()
        assert "ollama_text_model" not in config.to_dict()


class TestMLXChatPrompt:
    def test_system_and_user_messages(self):
        tokenizer = FakeTokenizer()
        MLXBackend._build_chat_prompt(tokenizer, "Hi", "Be brief")
        assert [m["role"] for m in tokenizer.messages] == ["system", "user"]
        assert tokenizer.kwargs["enable_thinking"] is False

    def test_system_folded_into_user_when_rejected(self):
        tokenizer = FakeTokenizer(reject_system=True)
        MLXBackend._build_chat_prompt(tokenizer, "Hi", "Be brief")
        assert tokenizer.messages == [{"role": "user", "content": "Be brief\n\nHi"}]


class TestMLXModelCache:
    def test_keeps_one_model_loaded(self):
        backend = MLXBackend()
        loads = []

        def loader(name):
            loads.append(name)
            return f"model:{name}"

        assert backend._load("a", loader) == "model:a"
        assert backend._load("a", loader) == "model:a"
        assert backend._load("b", loader) == "model:b"
        assert loads == ["a", "b"]
        assert backend._loaded_name == "b"

        backend.close()
        assert backend._loaded is None

    def test_load_failure_is_backend_error(self):
        def loader(name):
            raise OSError("no such repo")

        with pytest.raises(BackendError, match="Cannot load MLX model 'x'"):
            MLXBackend()._load("x", loader)


class TestMLXImageFamily:
    @pytest.fixture(autouse=True)
    def _needs_mflux(self):
        pytest.importorskip("mflux")

    @pytest.mark.parametrize(
        "name, family",
        [
            ("mflux-community/flux2-klein-4b-mflux-q4", "flux2-klein"),
            ("mflux-community/flux2-klein-9b-mflux-q4", "flux2-klein"),
            ("mflux-community/z-image-turbo-mflux-q8", "z-image-turbo"),
        ],
    )
    def test_supported_families(self, name, family):
        assert MLXBackend._image_family(name) == family

    def test_unsupported_family(self):
        with pytest.raises(BackendError):
            MLXBackend._image_family("Qwen/Qwen-Image")


class TestSpecialTokenBlocker:
    def test_blocks_specials_but_not_end_of_turn(self):
        mx = pytest.importorskip("mlx.core")

        class Tokenizer:
            all_special_tokens = ["<eos>", "<image|>", "<turn|>"]
            eos_token_ids = {1, 106}

            def convert_tokens_to_ids(self, token):
                return {"<eos>": 1, "<image|>": 5, "<turn|>": 106}[token]

        processor = MLXBackend._special_token_blocker(Tokenizer())
        logits = processor(None, mx.zeros((1, 200)))

        assert logits[0, 5].item() == float("-inf")
        assert logits[0, 1].item() == 0.0
        assert logits[0, 106].item() == 0.0
        assert logits[0, 7].item() == 0.0
