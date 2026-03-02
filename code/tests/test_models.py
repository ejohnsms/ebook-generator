"""Tests for data models."""

import pytest
from datetime import datetime

from ebook_gen.models import (
    ContentRating,
    ImageMode,
    ImageRecord,
    ImageStatus,
    PipelineStep,
    StepStatus,
    StoryConfig,
    Theme,
)


class TestStoryConfig:
    """Tests for StoryConfig model."""

    def test_create_with_defaults(self):
        """Test creating a StoryConfig with default values."""
        config = StoryConfig(
            story_id="test-story",
            title="Test Story",
            source_file="/tmp/test_story.md",
        )

        assert config.story_id == "test-story"
        assert config.title == "Test Story"
        assert config.source_language == "en"
        assert config.theme == Theme.UNMODIFIED
        assert config.content_rating == ContentRating.NONE
        assert config.target_languages == ["en"]
        assert config.image_mode == ImageMode.PREVIEW

    def test_to_dict(self):
        """Test serialization to dictionary."""
        config = StoryConfig(
            story_id="test",
            title="Test",
            source_file="/tmp/test_story.md",
            theme=Theme.CYBERPUNK,
            content_rating=ContentRating.PG13,
        )

        data = config.to_dict()

        assert data["story_id"] == "test"
        assert data["theme"] == "cyberpunk"
        assert data["content_rating"] == "PG-13"
        assert "created_at" in data
        assert "modified_at" in data

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "story_id": "test",
            "title": "Test Story",
            "source_file": "/tmp/test_story.md",
            "theme": "cyberpunk",
            "content_rating": "PG-13",
            "target_languages": ["en", "es"],
            "created_at": "2026-01-01T00:00:00",
            "modified_at": "2026-01-02T00:00:00",
        }

        config = StoryConfig.from_dict(data)

        assert config.story_id == "test"
        assert config.theme == Theme.CYBERPUNK
        assert config.content_rating == ContentRating.PG13
        assert config.target_languages == ["en", "es"]

    def test_round_trip(self):
        """Test that to_dict -> from_dict preserves data."""
        original = StoryConfig(
            story_id="test",
            title="Test",
            source_file="/tmp/test_story.md",
            theme=Theme.SPACE_OPERA,
            target_languages=["en", "es", "hi"],
        )

        data = original.to_dict()
        restored = StoryConfig.from_dict(data)

        assert restored.story_id == original.story_id
        assert restored.theme == original.theme
        assert restored.target_languages == original.target_languages


class TestImageRecord:
    """Tests for ImageRecord model."""

    def test_create(self):
        """Test creating an ImageRecord."""
        record = ImageRecord(
            image_id="img_001",
            name="cover",
            description="Cover image",
            prompt="A dramatic scene",
            model="x/flux2-klein",
            target_filename="cover.png",
        )

        assert record.image_id == "img_001"
        assert record.status == ImageStatus.PENDING
        assert record.width == 1024
        assert record.height == 768
        assert record.seed == 42

    def test_to_csv_row(self):
        """Test serialization to CSV row."""
        record = ImageRecord(
            image_id="img_001",
            name="scene_01",
            description="First scene",
            prompt="A cyberpunk bridge",
            model="x/flux2-klein",
            target_filename="scene_01.png",
            status=ImageStatus.COMPLETED,
            width=2048,
            height=1536,
        )

        row = record.to_csv_row()

        assert row["image_id"] == "img_001"
        assert row["status"] == "completed"
        assert row["width"] == "2048"
        assert row["height"] == "1536"

    def test_from_csv_row(self):
        """Test deserialization from CSV row."""
        row = {
            "image_id": "img_002",
            "name": "scene_02",
            "description": "Second scene",
            "prompt": "A neon-lit alley",
            "model": "x/z-image-turbo",
            "target_filename": "scene_02.png",
            "status": "failed",
            "width": "1024",
            "height": "768",
            "seed": "42",
        }

        record = ImageRecord.from_csv_row(row)

        assert record.image_id == "img_002"
        assert record.status == ImageStatus.FAILED
        assert record.width == 1024
        assert record.height == 768

    def test_round_trip(self):
        """Test that to_csv_row -> from_csv_row preserves data."""
        original = ImageRecord(
            image_id="test",
            name="test_image",
            description="Test",
            prompt="Test prompt",
            model="test-model",
            target_filename="test.png",
            status=ImageStatus.IN_PROGRESS,
        )

        row = original.to_csv_row()
        restored = ImageRecord.from_csv_row(row)

        assert restored.image_id == original.image_id
        assert restored.status == original.status
        assert restored.width == original.width


class TestPipelineStep:
    """Tests for PipelineStep model."""

    def test_create(self):
        """Test creating a PipelineStep."""
        step = PipelineStep(step=1, name="test_step")

        assert step.step == 1
        assert step.name == "test_step"
        assert step.status == StepStatus.PENDING
        assert step.started_at is None
        assert step.attempts == 0

    def test_to_csv_row(self):
        """Test serialization to CSV row."""
        now = datetime.utcnow()
        step = PipelineStep(
            step=2,
            name="test_step",
            status=StepStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            attempts=1,
            output_artifact="path/to/output.txt",
        )

        row = step.to_csv_row()

        assert row["step"] == "2"
        assert row["status"] == "completed"
        assert row["attempts"] == "1"
        assert row["output_artifact"] == "path/to/output.txt"

    def test_from_csv_row(self):
        """Test deserialization from CSV row."""
        row = {
            "step": "3",
            "name": "test_step",
            "status": "failed",
            "started_at": "2026-01-01T10:00:00",
            "completed_at": "",
            "error_message": "Test error",
            "attempts": "2",
            "output_artifact": "",
        }

        step = PipelineStep.from_csv_row(row)

        assert step.step == 3
        assert step.status == StepStatus.FAILED
        assert step.error_message == "Test error"
        assert step.attempts == 2
        assert step.completed_at is None

    def test_round_trip(self):
        """Test that to_csv_row -> from_csv_row preserves data."""
        original = PipelineStep(
            step=5,
            name="prompt_generation",
            status=StepStatus.IN_PROGRESS,
            started_at=datetime.utcnow(),
            attempts=1,
        )

        row = original.to_csv_row()
        restored = PipelineStep.from_csv_row(row)

        assert restored.step == original.step
        assert restored.status == original.status
        assert restored.name == original.name


class TestEnums:
    """Tests for enum values."""

    def test_theme_values(self):
        """Test Theme enum values."""
        assert Theme.CYBERPUNK.value == "cyberpunk"
        assert Theme.UNMODIFIED.value == "unmodified"
        assert Theme.CARIBBEAN_VILLAGE.value == "caribbean_village"

    def test_content_rating_values(self):
        """Test ContentRating enum values."""
        assert ContentRating.G.value == "G"
        assert ContentRating.PG13.value == "PG-13"
        assert ContentRating.NONE.value == "none"

    def test_image_mode_values(self):
        """Test ImageMode enum values."""
        assert ImageMode.PREVIEW.value == "preview"
        assert ImageMode.DRAFT.value == "draft"
        assert ImageMode.FINAL.value == "final"

    def test_status_values(self):
        """Test status enum values."""
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.COMPLETED.value == "completed"
        assert ImageStatus.FAILED.value == "failed"
