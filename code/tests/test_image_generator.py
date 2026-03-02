"""Integration tests for ImageGenerator component."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from ebook_gen.components.image_generator import ImageGenerator, ImageGenInput, ImageGenOutput
from ebook_gen.models import ImageMode, ImageRecord, ImageStatus, StoryConfig, Theme, ContentRating
from ebook_gen.ollama.client import OllamaClient, OllamaGenerationError, OllamaConnectionError
from ebook_gen.utils.csv_io import read_image_records, write_image_records


# Minimal 1x1 PNG bytes for testing
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def make_story_config(**kwargs) -> StoryConfig:
    """Create a minimal StoryConfig for tests."""
    defaults = dict(
        story_id="test-story",
        title="Test Story",
        source_file="/tmp/test_story.md",
        image_mode=ImageMode.PREVIEW,
    )
    defaults.update(kwargs)
    return StoryConfig(**defaults)


def make_image_records(count: int = 2) -> list[ImageRecord]:
    """Create a list of pending ImageRecords for tests."""
    records = []
    for i in range(count):
        records.append(ImageRecord(
            image_id=f"img_{i:03d}",
            name=f"scene_{i:02d}",
            description=f"Test scene {i}",
            prompt=f"A test prompt for scene {i}",
            model="x/flux2-klein:4b",
            target_filename=f"scene_{i:02d}.png",
            status=ImageStatus.PENDING,
            width=256,
            height=192,
            seed=42,
        ))
    return records


class TestImageGenerator:
    """Tests for ImageGenerator."""

    def test_generates_all_pending_images(self, tmp_path):
        """Test that all pending images are generated and saved."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        images_dir = tmp_path / "images"

        records = make_image_records(3)
        csv_path = prompts_dir / "prompts.csv"
        write_image_records(csv_path, records)

        mock_ollama = Mock(spec=OllamaClient)
        mock_ollama.generate_image.return_value = _TINY_PNG

        generator = ImageGenerator(mock_ollama)
        result = generator.execute(ImageGenInput(
            prompts_csv_path=csv_path,
            story_config=make_story_config(),
            output_dir=images_dir,
        ))

        assert result.completed_count == 3
        assert result.failed_count == 0
        assert result.skipped_count == 0
        assert mock_ollama.generate_image.call_count == 3

        # All PNG files should exist
        for record in records:
            assert (images_dir / record.target_filename).exists()

    def test_skips_completed_images(self, tmp_path):
        """Test that already-completed images are skipped (resume behavior)."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        images_dir = tmp_path / "images"
        images_dir.mkdir()

        records = make_image_records(3)
        # Mark first image as already completed
        records[0].status = ImageStatus.COMPLETED
        (images_dir / records[0].target_filename).write_bytes(_TINY_PNG)

        csv_path = prompts_dir / "prompts.csv"
        write_image_records(csv_path, records)

        mock_ollama = Mock(spec=OllamaClient)
        mock_ollama.generate_image.return_value = _TINY_PNG

        generator = ImageGenerator(mock_ollama)
        result = generator.execute(ImageGenInput(
            prompts_csv_path=csv_path,
            story_config=make_story_config(),
            output_dir=images_dir,
        ))

        assert result.completed_count == 2
        assert result.skipped_count == 1
        assert mock_ollama.generate_image.call_count == 2

    def test_retries_failed_images(self, tmp_path):
        """Test that previously failed images are retried."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        images_dir = tmp_path / "images"

        records = make_image_records(2)
        records[0].status = ImageStatus.FAILED  # Failed on previous run

        csv_path = prompts_dir / "prompts.csv"
        write_image_records(csv_path, records)

        mock_ollama = Mock(spec=OllamaClient)
        mock_ollama.generate_image.return_value = _TINY_PNG

        generator = ImageGenerator(mock_ollama)
        result = generator.execute(ImageGenInput(
            prompts_csv_path=csv_path,
            story_config=make_story_config(),
            output_dir=images_dir,
        ))

        assert result.completed_count == 2
        assert result.failed_count == 0
        assert mock_ollama.generate_image.call_count == 2

    def test_handles_generation_failure_per_image(self, tmp_path):
        """Test that a single image failure doesn't abort remaining images."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        images_dir = tmp_path / "images"

        records = make_image_records(3)
        csv_path = prompts_dir / "prompts.csv"
        write_image_records(csv_path, records)

        mock_ollama = Mock(spec=OllamaClient)
        # Second image fails, others succeed
        mock_ollama.generate_image.side_effect = [
            _TINY_PNG,
            OllamaGenerationError("GPU out of memory"),
            _TINY_PNG,
        ]

        generator = ImageGenerator(mock_ollama)
        result = generator.execute(ImageGenInput(
            prompts_csv_path=csv_path,
            story_config=make_story_config(),
            output_dir=images_dir,
        ))

        assert result.completed_count == 2
        assert result.failed_count == 1
        assert mock_ollama.generate_image.call_count == 3

        # Failed image should have status=failed in CSV
        updated_records = read_image_records(csv_path)
        assert updated_records[0].status == ImageStatus.COMPLETED
        assert updated_records[1].status == ImageStatus.FAILED
        assert updated_records[2].status == ImageStatus.COMPLETED

    def test_csv_updated_after_each_image(self, tmp_path):
        """Test that CSV is written atomically after each image generation."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        images_dir = tmp_path / "images"

        records = make_image_records(2)
        csv_path = prompts_dir / "prompts.csv"
        write_image_records(csv_path, records)

        write_calls = []
        original_write = write_image_records

        def tracking_write(path, recs):
            write_calls.append([r.status for r in recs])
            original_write(path, recs)

        mock_ollama = Mock(spec=OllamaClient)
        mock_ollama.generate_image.return_value = _TINY_PNG

        with patch(
            "ebook_gen.components.image_generator.write_image_records",
            side_effect=tracking_write,
        ):
            generator = ImageGenerator(mock_ollama)
            generator.execute(ImageGenInput(
                prompts_csv_path=csv_path,
                story_config=make_story_config(),
                output_dir=images_dir,
            ))

        # Should have written CSV: in_progress + completed for each image = 4 writes
        assert len(write_calls) == 4

    def test_creates_output_directory(self, tmp_path):
        """Test that output directory is created if it doesn't exist."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        images_dir = tmp_path / "images" / "test-story"  # Nested, doesn't exist yet

        records = make_image_records(1)
        csv_path = prompts_dir / "prompts.csv"
        write_image_records(csv_path, records)

        mock_ollama = Mock(spec=OllamaClient)
        mock_ollama.generate_image.return_value = _TINY_PNG

        generator = ImageGenerator(mock_ollama)
        generator.execute(ImageGenInput(
            prompts_csv_path=csv_path,
            story_config=make_story_config(),
            output_dir=images_dir,
        ))

        assert images_dir.exists()

    def test_passes_correct_params_to_ollama(self, tmp_path):
        """Test that generate_image is called with correct model, prompt, dims, seed."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        images_dir = tmp_path / "images"

        record = ImageRecord(
            image_id="img_001",
            name="scene_01",
            description="A neon-lit bridge",
            prompt="neon bridge cyberpunk night rain cinematic",
            model="x/flux2-klein:4b",
            target_filename="scene_01.png",
            status=ImageStatus.PENDING,
            width=256,
            height=192,
            seed=99,
        )
        csv_path = prompts_dir / "prompts.csv"
        write_image_records(csv_path, [record])

        mock_ollama = Mock(spec=OllamaClient)
        mock_ollama.generate_image.return_value = _TINY_PNG

        generator = ImageGenerator(mock_ollama)
        generator.execute(ImageGenInput(
            prompts_csv_path=csv_path,
            story_config=make_story_config(),
            output_dir=images_dir,
        ))

        mock_ollama.generate_image.assert_called_once_with(
            model="x/flux2-klein:4b",
            prompt="neon bridge cyberpunk night rain cinematic",
            width=256,
            height=192,
            seed=99,
        )

    def test_raises_on_missing_prompts_csv(self, tmp_path):
        """Test that FileNotFoundError is raised when prompts CSV is missing."""
        mock_ollama = Mock(spec=OllamaClient)
        generator = ImageGenerator(mock_ollama)

        with pytest.raises(FileNotFoundError):
            generator.execute(ImageGenInput(
                prompts_csv_path=tmp_path / "nonexistent.csv",
                story_config=make_story_config(),
                output_dir=tmp_path / "images",
            ))

    def test_all_skipped_returns_zero_completed(self, tmp_path):
        """Test with all images already completed returns zero new completions."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        images_dir = tmp_path / "images"
        images_dir.mkdir()

        records = make_image_records(2)
        for r in records:
            r.status = ImageStatus.COMPLETED
            (images_dir / r.target_filename).write_bytes(_TINY_PNG)

        csv_path = prompts_dir / "prompts.csv"
        write_image_records(csv_path, records)

        mock_ollama = Mock(spec=OllamaClient)
        generator = ImageGenerator(mock_ollama)
        result = generator.execute(ImageGenInput(
            prompts_csv_path=csv_path,
            story_config=make_story_config(),
            output_dir=images_dir,
        ))

        assert result.completed_count == 0
        assert result.skipped_count == 2
        mock_ollama.generate_image.assert_not_called()
