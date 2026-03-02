"""Audio generation component for ebook pipeline (Step 8).

Uses Kokoro-82M (hexgrad/Kokoro-82M) TTS to narrate translated story text
and produce per-language WAV files.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..models import AudioRecord, AudioStatus, StoryConfig
from ..utils.csv_io import read_audio_records, write_audio_records
from ..utils.markdown import strip_all_html_comments

# Optional dependencies - only required when audio generation is actually used.
# Imported at module level so tests can patch them as module attributes.
try:
    import numpy as np
    from kokoro import KPipeline
    import soundfile as sf
    _KOKORO_AVAILABLE = True
except ImportError:
    np = None  # type: ignore[assignment]
    KPipeline = None  # type: ignore[assignment]
    sf = None  # type: ignore[assignment]
    _KOKORO_AVAILABLE = False

logger = logging.getLogger(__name__)

# Maps ISO 639-1 code -> (kokoro lang_code, default voice)
KOKORO_LANG_MAP: dict[str, tuple[str, str]] = {
    "en": ("a", "af_heart"),
    "en-gb": ("b", "bf_alice"),
    "ja": ("j", "jf_alpha"),
    "zh": ("z", "zf_xiaobei"),
    "es": ("e", "ef_dora"),
    "fr": ("f", "ff_siwis"),
    "hi": ("h", "hf_alpha"),
    "it": ("i", "if_sara"),
    "pt": ("p", "pf_dora"),
}

SUPPORTED_LANGUAGES: frozenset[str] = frozenset(KOKORO_LANG_MAP.keys())


@dataclass
class AudioGenInput:
    """Input for audio generator."""

    audio_csv_path: Path       # audio/<story>/audio_tracks.csv
    story_config: StoryConfig  # audio_languages, voice_preferences
    story_dir: Path            # stories/<story>/ for text files
    output_dir: Path           # audio/<story>/


@dataclass
class AudioGenOutput:
    """Output from audio generator."""

    audio_dir: Path
    completed_count: int
    failed_count: int
    skipped_count: int


class AudioGenerator:
    """Generates WAV audio files from story text using Kokoro-82M TTS.

    For each language in story_config.audio_languages:
      1. Look up Kokoro lang_code; skip with warning if unsupported.
      2. Find translated story text (story_<lang>.md or story.md).
      3. Extract plain text (strip annotations + Markdown formatting).
      4. Generate audio via KPipeline and concatenate chunks.
      5. Write WAV to output_dir with soundfile.
      6. Update audio_tracks.csv atomically after each track.
    """

    def execute(self, input_data: AudioGenInput) -> AudioGenOutput:
        """Generate audio for all configured languages.

        Args:
            input_data: Input configuration

        Returns:
            Counts of completed, failed, and skipped tracks
        """
        if not _KOKORO_AVAILABLE:
            raise ImportError(
                "Audio generation requires kokoro and soundfile. "
                "Install them with: pip install kokoro soundfile"
            )

        input_data.output_dir.mkdir(parents=True, exist_ok=True)

        # Load or initialize records
        if input_data.audio_csv_path.exists():
            records = read_audio_records(input_data.audio_csv_path)
        else:
            input_data.audio_csv_path.parent.mkdir(parents=True, exist_ok=True)
            records = self._initialize_records(input_data.story_config)
            write_audio_records(input_data.audio_csv_path, records)

        completed = 0
        failed = 0
        skipped = 0

        # Cache KPipeline instances by lang_code to avoid reloading per track
        pipelines: dict[str, object] = {}

        for record in records:
            if record.status in (AudioStatus.COMPLETED, AudioStatus.SKIPPED):
                skipped += 1
                continue

            lang = record.language

            # Check language support
            if lang not in KOKORO_LANG_MAP:
                logger.warning(
                    f"Language '{lang}' is not supported by Kokoro TTS. Skipping."
                )
                record.status = AudioStatus.SKIPPED
                write_audio_records(input_data.audio_csv_path, records)
                skipped += 1
                continue

            lang_code, _ = KOKORO_LANG_MAP[lang]

            # Get story text
            try:
                raw_markdown = self._get_story_text(
                    lang, input_data.story_dir, input_data.story_config
                )
            except FileNotFoundError as e:
                logger.error(f"Story text not found for language '{lang}': {e}")
                record.status = AudioStatus.FAILED
                write_audio_records(input_data.audio_csv_path, records)
                failed += 1
                continue

            plain_text = self._plain_text(raw_markdown)
            record.text_length = len(plain_text)

            # Mark in-progress
            record.status = AudioStatus.IN_PROGRESS
            write_audio_records(input_data.audio_csv_path, records)

            try:
                # Get or create pipeline for this lang_code
                if lang_code not in pipelines:
                    pipelines[lang_code] = KPipeline(lang_code=lang_code)
                pipeline = pipelines[lang_code]

                # Generate audio chunks and concatenate
                audio_chunks = []
                for _, _, audio_chunk in pipeline(plain_text, voice=record.voice):
                    audio_chunks.append(audio_chunk)

                if audio_chunks:
                    audio_array = np.concatenate(audio_chunks)
                else:
                    audio_array = np.array([], dtype=np.float32)

                output_path = input_data.output_dir / record.target_filename
                sf.write(str(output_path), audio_array, 24000)

                record.duration_seconds = len(audio_array) / 24000.0
                record.status = AudioStatus.COMPLETED
                completed += 1
                logger.info(
                    f"Generated audio: {output_path} "
                    f"({record.duration_seconds:.1f}s)"
                )

            except Exception as e:
                record.status = AudioStatus.FAILED
                failed += 1
                logger.error(f"Failed to generate audio for language '{lang}': {e}")

            write_audio_records(input_data.audio_csv_path, records)

        logger.info(
            f"Audio generation complete: {completed} completed, "
            f"{failed} failed, {skipped} skipped"
        )

        return AudioGenOutput(
            audio_dir=input_data.output_dir,
            completed_count=completed,
            failed_count=failed,
            skipped_count=skipped,
        )

    def _initialize_records(self, story_config: StoryConfig) -> list[AudioRecord]:
        """Build initial AudioRecord list from story_config.audio_languages.

        Args:
            story_config: Story configuration with audio_languages and voice_preferences

        Returns:
            List of AudioRecord objects (one per language)
        """
        records = []
        for i, lang in enumerate(story_config.audio_languages):
            # Determine voice: user override > default for language > empty string
            if lang in story_config.voice_preferences:
                voice = story_config.voice_preferences[lang]
            elif lang in KOKORO_LANG_MAP:
                _, voice = KOKORO_LANG_MAP[lang]
            else:
                voice = ""  # Will be skipped at generation time

            target_filename = f"{story_config.story_id}_{lang}.wav"
            records.append(
                AudioRecord(
                    audio_id=f"audio_{i:03d}",
                    language=lang,
                    voice=voice,
                    text_length=0,
                    target_filename=target_filename,
                    status=AudioStatus.PENDING,
                    duration_seconds=0.0,
                )
            )
        return records

    def _get_story_text(
        self, lang: str, story_dir: Path, story_config: StoryConfig
    ) -> str:
        """Read the story markdown file for a given language.

        Reads story_<lang>.md for target languages, story.md for the source language.

        Args:
            lang: ISO 639-1 language code
            story_dir: stories/<story>/ directory
            story_config: Story configuration

        Returns:
            Markdown text content

        Raises:
            FileNotFoundError: If the story file doesn't exist
        """
        if lang in story_config.target_languages:
            path = story_dir / f"story_{lang}.md"
        elif lang == story_config.source_language:
            path = story_dir / "story.md"
        else:
            raise FileNotFoundError(
                f"No story file for language '{lang}' in {story_dir}. "
                f"Target languages: {story_config.target_languages}, "
                f"source: {story_config.source_language}"
            )

        if not path.exists():
            raise FileNotFoundError(f"Story file not found: {path}")

        return path.read_text(encoding="utf-8")

    def _plain_text(self, markdown: str) -> str:
        """Convert markdown to plain text suitable for TTS.

        Strips HTML comments, headings, bold/italic, inline code, and list markers.

        Args:
            markdown: Markdown content (may contain pipeline annotations)

        Returns:
            Plain text with whitespace normalized
        """
        text = strip_all_html_comments(markdown)

        # Remove ATX headings (# Heading)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

        # Strip bold/italic markers (*** ** * ___ __ _)
        text = re.sub(r"[*_]{1,3}(.*?)[*_]{1,3}", r"\1", text)

        # Strip inline code
        text = re.sub(r"`+.*?`+", "", text, flags=re.DOTALL)

        # Strip list markers (- * + at line start)
        text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)

        # Normalize whitespace: collapse multiple blank lines, strip leading/trailing
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        return text
