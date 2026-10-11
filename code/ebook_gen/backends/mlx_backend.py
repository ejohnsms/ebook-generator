"""In-process MLX backend: mlx-lm for text, mflux for images (Apple Silicon only)."""

import gc
import io
import logging
import platform
import sys
from typing import Any

from ..config import LEGACY_MODEL_ALIASES
from .base import BackendError

logger = logging.getLogger(__name__)

# Denoising steps per image model family (both are distilled few-step models).
_IMAGE_STEPS = {"flux2-klein": 4, "z-image-turbo": 9}


def resolve_model_name(model: str) -> str:
    """Map legacy Ollama tags to MLX repo ids; pass anything else through."""
    resolved = LEGACY_MODEL_ALIASES.get(model, model)
    if resolved != model:
        logger.info(f"Using MLX model '{resolved}' for legacy Ollama model '{model}'")
    return resolved


class MLXBackend:
    """Runs text and image models in-process with MLX.

    Holds at most one model in memory: text and image models are swapped as
    the pipeline moves between steps, since a 12B text model and a 9B image
    model don't fit in unified memory together on a 24 GB machine.
    """

    def __init__(self) -> None:
        self._loaded_name: str | None = None
        self._loaded: Any = None  # (model, tokenizer) for text, mflux model for images

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self) -> None:
        self._unload()

    def health_check(self) -> bool:
        """MLX needs macOS on Apple Silicon and the mlx package."""
        if sys.platform != "darwin" or platform.machine() != "arm64":
            return False
        try:
            import mlx.core  # noqa: F401
        except ImportError:
            return False
        return True

    # ── text ─────────────────────────────────────────────────────────────────

    def generate_text(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> str:
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        name = resolve_model_name(model)
        lm, tokenizer, block_specials = self._load(name, self._load_text_model)

        try:
            chat_prompt = self._build_chat_prompt(tokenizer, prompt, system)
            return generate(
                lm,
                tokenizer,
                chat_prompt,
                max_tokens=max_tokens,
                sampler=make_sampler(temp=temperature),
                logits_processors=[block_specials],
            ).strip()
        except Exception as e:
            raise BackendError(f"Text generation failed with '{name}': {e}") from e

    @staticmethod
    def _load_text_model(name: str) -> Any:
        from mlx_lm import load

        lm, tokenizer = load(name)
        return lm, tokenizer, MLXBackend._special_token_blocker(tokenizer)

    @staticmethod
    def _special_token_blocker(tokenizer: Any):
        """Logits processor that forbids special tokens other than end-of-turn.

        Multimodal models (Gemma 4) otherwise sample placeholders such as
        <image|> and <audio|> into story text.
        """
        import mlx.core as mx

        ids = {tokenizer.convert_tokens_to_ids(t) for t in tokenizer.all_special_tokens}
        blocked = sorted(ids - set(tokenizer.eos_token_ids) - {None})
        mask = None

        def processor(tokens: Any, logits: Any) -> Any:
            nonlocal mask
            if mask is None:
                mask = mx.zeros(logits.shape[-1])
                mask[mx.array(blocked)] = -mx.inf
            return logits + mask

        return processor

    @staticmethod
    def _build_chat_prompt(tokenizer: Any, prompt: str, system: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        # enable_thinking=False skips the reasoning preamble on thinking models
        # (Gemma 4); templates that don't use it ignore the extra variable.
        try:
            return tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, enable_thinking=False
            )
        except Exception:
            if not system:
                raise
            # Some templates reject a system role; fold it into the user turn.
            merged = [{"role": "user", "content": f"{system}\n\n{prompt}"}]
            return tokenizer.apply_chat_template(
                merged, add_generation_prompt=True, enable_thinking=False
            )

    # ── images ───────────────────────────────────────────────────────────────

    def generate_image(
        self,
        model: str,
        prompt: str,
        width: int = 1024,
        height: int = 768,
        seed: int = 42,
    ) -> bytes:
        name = resolve_model_name(model)
        family = self._image_family(name)
        image_model = self._load(name, lambda n: self._load_image_model(n, family))

        try:
            result = image_model.generate_image(
                seed=seed,
                prompt=prompt,
                num_inference_steps=_IMAGE_STEPS[family],
                width=width,
                height=height,
            )
            buffer = io.BytesIO()
            result.image.save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception as e:
            raise BackendError(f"Image generation failed with '{name}': {e}") from e

    @staticmethod
    def _image_family(name: str) -> str:
        """Ask mflux which registry model a name or repo id belongs to."""
        from mflux.models.common.resolution.config_resolution import ConfigResolution

        try:
            key = ConfigResolution.resolve_key(name) or ""
        except Exception as e:
            raise BackendError(f"mflux does not recognise image model '{name}': {e}") from e

        for family in _IMAGE_STEPS:
            if key.startswith(family) and "edit" not in key and "controlnet" not in key:
                return family
        raise BackendError(
            f"Image model '{name}' resolves to '{key}'; supported families: "
            f"{', '.join(_IMAGE_STEPS)}"
        )

    @staticmethod
    def _load_image_model(name: str, family: str) -> Any:
        from mflux.models.common.config import ModelConfig

        model_config = ModelConfig.from_name(model_name=name)
        if family == "flux2-klein":
            from mflux.models.flux2.variants import Flux2Klein

            return Flux2Klein(model_config=model_config, model_path=name)

        from mflux.models.z_image.variants import ZImageTurbo

        return ZImageTurbo(model_config=model_config, model_path=name)

    # ── model cache (one at a time) ──────────────────────────────────────────

    def _load(self, name: str, loader) -> Any:
        if self._loaded_name == name:
            return self._loaded

        self._unload()
        logger.info(f"Loading MLX model '{name}'")
        try:
            self._loaded = loader(name)
        except BackendError:
            raise
        except Exception as e:
            raise BackendError(f"Cannot load MLX model '{name}': {e}") from e
        self._loaded_name = name
        return self._loaded

    def _unload(self) -> None:
        if self._loaded is None:
            return
        logger.info(f"Unloading MLX model '{self._loaded_name}'")
        self._loaded = None
        self._loaded_name = None
        gc.collect()
        try:
            import mlx.core as mx

            mx.clear_cache()
        except ImportError:
            pass
