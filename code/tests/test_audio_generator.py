"""Tests for AudioGenerator component."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ebook_gen.components.audio_generator import (
    KOKORO_LANG_MAP,
    AudioGenInput,
    AudioGenerator,
)
from ebook_gen.models import (
    AudioRecord,
    AudioStatus,
    ContentRating,
    ImageMode,
    StoryConfig,
)
from ebook_gen.utils.csv_io import read_audio_records, write_audio_records


def make_story_config(**kwargs) -> StoryConfig:
    """Create a minimal StoryConfig for tests."""
    defaults = dict(
        story_id="test-story",
        title="Test Story",
        source_file="/tmp/test_story.md",
        source_language="en",
        target_languages=["en"],
        audio_languages=["en"],
        theme="unmodified",
        content_rating=ContentRating.NONE,
        image_mode=ImageMode.PREVIEW,
    )
    defaults.update(kwargs)
    return StoryConfig(**defaults)


def make_audio_input(tmp_path: Path, config: StoryConfig) -> AudioGenInput:
    """Create AudioGenInput pointing at tmp_path."""
    audio_dir = tmp_path / "audio" / config.story_id
    story_dir = tmp_path / "stories" / config.story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    return AudioGenInput(
        audio_csv_path=audio_dir / "audio_tracks.csv",
        story_config=config,
        story_dir=story_dir,
        output_dir=audio_dir,
    )


def write_story_file(story_dir: Path, lang: str, content: str, source: bool = False) -> None:
    """Write a story markdown file."""
    filename = "story.md" if source else f"story_{lang}.md"
    (story_dir / filename).write_text(content, encoding="utf-8")


# Tiny audio as a plain list (avoids numpy dependency in tests).
_TINY_AUDIO = [0.0] * 2400


@pytest.fixture
def audio_mocks():
    """Patch all optional audio deps so tests run without kokoro/soundfile/numpy installed."""
    import ebook_gen.components.audio_generator as mod

    mock_np = MagicMock()
    mock_np.concatenate = MagicMock(return_value=_TINY_AUDIO)
    mock_np.array = MagicMock(return_value=[])

    mock_sf = MagicMock()
    mock_kpipeline_cls = MagicMock()

    with (
        patch.object(mod, "_KOKORO_AVAILABLE", True),
        patch.object(mod, "np", mock_np),
        patch.object(mod, "sf", mock_sf),
        patch.object(mod, "KPipeline", mock_kpipeline_cls),
    ):
        yield {
            "np": mock_np,
            "sf": mock_sf,
            "KPipeline": mock_kpipeline_cls,
        }


def make_pipeline_instance(mocks, audio_to_yield=None):
    """Configure and return a KPipeline mock instance that yields one audio chunk.

    Uses `side_effect` on the mock instance so that calling `pipeline(text, voice=v)`
    triggers the generator function and returns an iterable of (gs, ps, audio) tuples.
    """
    if audio_to_yield is None:
        audio_to_yield = _TINY_AUDIO

    def _generate(text, voice):
        yield None, None, audio_to_yield

    mock_instance = MagicMock()
    # side_effect on the mock instance: mock_instance(args) -> calls _generate(args) -> generator
    mock_instance.side_effect = _generate
    mocks["KPipeline"].return_value = mock_instance
    return mock_instance


class TestAudioGenerator:

    def test_generates_audio_for_supported_languages(self, tmp_path, audio_mocks):
        """AudioGenerator completes WAV for 'en' language."""
        config = make_story_config(audio_languages=["en"], target_languages=["en"])
        inp = make_audio_input(tmp_path, config)
        write_story_file(inp.story_dir, "en", "# Hello\n\nOnce upon a time.")

        make_pipeline_instance(audio_mocks)

        generator = AudioGenerator()
        result = generator.execute(inp)

        assert result.completed_count == 1
        assert result.failed_count == 0
        assert result.skipped_count == 0
        audio_mocks["sf"].write.assert_called_once()
        # Check WAV path has correct name
        write_args = audio_mocks["sf"].write.call_args[0]
        assert "test-story_en.wav" in write_args[0]

    def test_skips_unsupported_language_with_warning(self, tmp_path, audio_mocks, caplog):
        """Unsupported language logs warning, marks SKIPPED, and continues."""
        config = make_story_config(audio_languages=["no"])  # Norwegian - unsupported
        inp = make_audio_input(tmp_path, config)

        make_pipeline_instance(audio_mocks)

        with caplog.at_level(logging.WARNING, logger="ebook_gen.components.audio_generator"):
            generator = AudioGenerator()
            result = generator.execute(inp)

        assert result.completed_count == 0
        assert result.skipped_count == 1
        assert result.failed_count == 0
        assert "no" in caplog.text
        assert "not supported" in caplog.text

        # CSV should show SKIPPED
        records = read_audio_records(inp.audio_csv_path)
        assert records[0].status == AudioStatus.SKIPPED

    def test_skips_already_completed_tracks(self, tmp_path, audio_mocks):
        """Resume: already-completed tracks are counted as skipped."""
        config = make_story_config(audio_languages=["en"], target_languages=["en"])
        inp = make_audio_input(tmp_path, config)
        inp.output_dir.mkdir(parents=True, exist_ok=True)
        write_story_file(inp.story_dir, "en", "Hello world.")

        # Pre-seed CSV with completed record
        records = [
            AudioRecord(
                audio_id="audio_000",
                language="en",
                voice="af_heart",
                text_length=11,
                target_filename="test-story_en.wav",
                status=AudioStatus.COMPLETED,
                duration_seconds=1.5,
            )
        ]
        inp.audio_csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_audio_records(inp.audio_csv_path, records)

        generator = AudioGenerator()
        result = generator.execute(inp)

        assert result.completed_count == 0
        assert result.skipped_count == 1
        audio_mocks["KPipeline"].assert_not_called()

    def test_handles_generation_failure_per_track(self, tmp_path, audio_mocks):
        """One language fails; others succeed."""
        config = make_story_config(
            audio_languages=["en", "es"],
            target_languages=["en", "es"],
        )
        inp = make_audio_input(tmp_path, config)
        write_story_file(inp.story_dir, "en", "Hello.")
        write_story_file(inp.story_dir, "es", "Hola.")

        call_count = [0]

        def pipeline_side_effect(text, voice):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("TTS engine error")
            yield None, None, _TINY_AUDIO

        mock_instance = MagicMock()
        mock_instance.side_effect = pipeline_side_effect
        audio_mocks["KPipeline"].return_value = mock_instance

        generator = AudioGenerator()
        result = generator.execute(inp)

        assert result.completed_count == 1
        assert result.failed_count == 1

        records = read_audio_records(inp.audio_csv_path)
        statuses = {r.language: r.status for r in records}
        assert statuses["en"] == AudioStatus.FAILED
        assert statuses["es"] == AudioStatus.COMPLETED

    def test_csv_updated_after_each_track(self, tmp_path, audio_mocks):
        """CSV is written atomically after each track."""
        config = make_story_config(audio_languages=["en", "es"], target_languages=["en", "es"])
        inp = make_audio_input(tmp_path, config)
        write_story_file(inp.story_dir, "en", "Hello.")
        write_story_file(inp.story_dir, "es", "Hola.")

        make_pipeline_instance(audio_mocks)

        write_calls = []
        original_write = write_audio_records

        def tracking_write(path, records):
            write_calls.append([r.status for r in records])
            original_write(path, records)

        import ebook_gen.components.audio_generator as mod
        with patch.object(mod, "write_audio_records", side_effect=tracking_write):
            generator = AudioGenerator()
            generator.execute(inp)

        # Initialize (1) + in_progress + completed for each track = 1 + 2*2 = 5
        assert len(write_calls) >= 4

    def test_creates_output_directory(self, tmp_path, audio_mocks):
        """Output directory is created if it doesn't exist."""
        config = make_story_config(audio_languages=["en"], target_languages=["en"])
        inp = make_audio_input(tmp_path, config)
        write_story_file(inp.story_dir, "en", "Hello.")

        assert not inp.output_dir.exists()

        make_pipeline_instance(audio_mocks)

        generator = AudioGenerator()
        generator.execute(inp)

        assert inp.output_dir.exists()

    def test_uses_voice_preference_override(self, tmp_path, audio_mocks):
        """voice_preferences in StoryConfig overrides the default voice."""
        config = make_story_config(
            audio_languages=["en"],
            target_languages=["en"],
            voice_preferences={"en": "af_nicole"},
        )
        inp = make_audio_input(tmp_path, config)
        write_story_file(inp.story_dir, "en", "Hello.")

        captured_voice = []

        def pipeline_side_effect(text, voice):
            captured_voice.append(voice)
            yield None, None, _TINY_AUDIO

        mock_instance = MagicMock()
        mock_instance.side_effect = pipeline_side_effect
        audio_mocks["KPipeline"].return_value = mock_instance

        generator = AudioGenerator()
        generator.execute(inp)

        assert captured_voice == ["af_nicole"]

    def test_uses_translated_file_for_target_language(self, tmp_path, audio_mocks):
        """Uses story_hi.md when Hindi is a target language."""
        config = make_story_config(
            audio_languages=["hi"],
            target_languages=["hi"],
            source_language="en",
        )
        inp = make_audio_input(tmp_path, config)
        (inp.story_dir / "story_hi.md").write_text("एक बार की बात है।", encoding="utf-8")

        make_pipeline_instance(audio_mocks)

        read_texts = []
        original_plain_text = AudioGenerator._plain_text

        def capture_plain_text(self, markdown):
            read_texts.append(markdown)
            return original_plain_text(self, markdown)

        with patch.object(AudioGenerator, "_plain_text", capture_plain_text):
            generator = AudioGenerator()
            generator.execute(inp)

        assert any("एक बार की बात है" in t for t in read_texts)

    def test_uses_source_story_for_source_language(self, tmp_path, audio_mocks):
        """Uses story.md when language matches source_language but is not a target language."""
        config = make_story_config(
            audio_languages=["en"],
            source_language="en",
            target_languages=["es"],  # en is NOT in target_languages
        )
        inp = make_audio_input(tmp_path, config)
        (inp.story_dir / "story.md").write_text(
            "# Source story\n\nOnce upon a time.", encoding="utf-8"
        )

        make_pipeline_instance(audio_mocks)

        read_texts = []
        original_plain_text = AudioGenerator._plain_text

        def capture_plain_text(self, markdown):
            read_texts.append(markdown)
            return original_plain_text(self, markdown)

        with patch.object(AudioGenerator, "_plain_text", capture_plain_text):
            generator = AudioGenerator()
            generator.execute(inp)

        assert any("Once upon a time" in t for t in read_texts)

    def test_plain_text_strips_annotations_and_markdown(self):
        """_plain_text() strips HTML comments, headings, bold/italic, and list markers."""
        generator = AudioGenerator()

        markdown = """# Chapter One

<!-- IMAGE: A bridge at night -->
<!-- DIRECTOR: Open with rain -->

Once upon a **time**, there was a *goat*.

- Item one
- Item two

```code block```

Some `inline code` here."""

        result = generator._plain_text(markdown)

        assert "Chapter One" in result
        assert "IMAGE:" not in result
        assert "DIRECTOR:" not in result
        assert "<!--" not in result
        assert "-->" not in result
        assert "**" not in result
        assert "*goat*" not in result
        assert "goat" in result
        assert "time" in result
        assert "- Item" not in result
        assert "Item one" in result
        assert "```" not in result
        assert "`inline code`" not in result
