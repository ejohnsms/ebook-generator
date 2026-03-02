"""Tests for CSV I/O utilities."""

import pytest
from pathlib import Path

from ebook_gen.models import ImageRecord, ImageStatus, PipelineStep, StepStatus
from ebook_gen.utils.csv_io import (
    read_image_records,
    read_pipeline_steps,
    write_image_records,
    write_pipeline_steps,
)


class TestImageRecordIO:
    """Tests for ImageRecord CSV I/O."""

    def test_write_and_read_empty(self, tmp_path):
        """Test writing and reading an empty list."""
        csv_path = tmp_path / "empty.csv"
        write_image_records(csv_path, [])

        records = read_image_records(csv_path)
        assert records == []

    def test_write_and_read_single(self, tmp_path):
        """Test writing and reading a single record."""
        csv_path = tmp_path / "single.csv"
        record = ImageRecord(
            image_id="img_001",
            name="test",
            description="Test image",
            prompt="A test prompt",
            model="test-model",
            target_filename="test.png",
        )

        write_image_records(csv_path, [record])
        records = read_image_records(csv_path)

        assert len(records) == 1
        assert records[0].image_id == "img_001"
        assert records[0].name == "test"

    def test_write_and_read_multiple(self, tmp_path):
        """Test writing and reading multiple records."""
        csv_path = tmp_path / "multiple.csv"
        records_in = [
            ImageRecord(
                image_id=f"img_{i:03d}",
                name=f"image_{i}",
                description=f"Image {i}",
                prompt=f"Prompt {i}",
                model="test-model",
                target_filename=f"image_{i}.png",
                status=ImageStatus.PENDING if i % 2 == 0 else ImageStatus.COMPLETED,
            )
            for i in range(5)
        ]

        write_image_records(csv_path, records_in)
        records_out = read_image_records(csv_path)

        assert len(records_out) == 5
        for i, record in enumerate(records_out):
            assert record.image_id == f"img_{i:03d}"
            assert record.name == f"image_{i}"

    def test_read_nonexistent_file(self, tmp_path):
        """Test reading from a nonexistent file."""
        csv_path = tmp_path / "nonexistent.csv"

        with pytest.raises(FileNotFoundError):
            read_image_records(csv_path)

    def test_special_characters_in_fields(self, tmp_path):
        """Test handling of special characters (commas, quotes, newlines)."""
        csv_path = tmp_path / "special.csv"
        record = ImageRecord(
            image_id="img_001",
            name="test, with, commas",
            description='Description with "quotes"',
            prompt="Prompt with\nmultiple\nlines",
            model="test-model",
            target_filename="test.png",
        )

        write_image_records(csv_path, [record])
        records = read_image_records(csv_path)

        assert len(records) == 1
        assert records[0].name == "test, with, commas"
        assert records[0].description == 'Description with "quotes"'

    def test_atomic_write(self, tmp_path):
        """Test that writes are atomic (no .tmp file left behind)."""
        csv_path = tmp_path / "atomic.csv"
        record = ImageRecord(
            image_id="img_001",
            name="test",
            description="Test",
            prompt="Test",
            model="test-model",
            target_filename="test.png",
        )

        write_image_records(csv_path, [record])

        # Check that only the CSV exists, not the .tmp file
        assert csv_path.exists()
        assert not (tmp_path / "atomic.csv.tmp").exists()


class TestPipelineStepIO:
    """Tests for PipelineStep CSV I/O."""

    def test_write_and_read_empty(self, tmp_path):
        """Test writing and reading an empty list."""
        csv_path = tmp_path / "empty.csv"
        write_pipeline_steps(csv_path, [])

        steps = read_pipeline_steps(csv_path)
        assert steps == []

    def test_write_and_read_single(self, tmp_path):
        """Test writing and reading a single step."""
        csv_path = tmp_path / "single.csv"
        step = PipelineStep(step=1, name="test_step", status=StepStatus.PENDING)

        write_pipeline_steps(csv_path, [step])
        steps = read_pipeline_steps(csv_path)

        assert len(steps) == 1
        assert steps[0].step == 1
        assert steps[0].name == "test_step"
        assert steps[0].status == StepStatus.PENDING

    def test_write_and_read_multiple(self, tmp_path):
        """Test writing and reading multiple steps."""
        csv_path = tmp_path / "multiple.csv"
        steps_in = [
            PipelineStep(
                step=i,
                name=f"step_{i}",
                status=StepStatus.PENDING if i % 2 == 0 else StepStatus.COMPLETED,
            )
            for i in range(1, 8)
        ]

        write_pipeline_steps(csv_path, steps_in)
        steps_out = read_pipeline_steps(csv_path)

        assert len(steps_out) == 7
        for i, step in enumerate(steps_out, start=1):
            assert step.step == i
            assert step.name == f"step_{i}"

    def test_sorting_by_step_number(self, tmp_path):
        """Test that steps are sorted by step number."""
        csv_path = tmp_path / "sorted.csv"
        steps_in = [
            PipelineStep(step=3, name="step_3"),
            PipelineStep(step=1, name="step_1"),
            PipelineStep(step=2, name="step_2"),
        ]

        write_pipeline_steps(csv_path, steps_in)
        steps_out = read_pipeline_steps(csv_path)

        assert [s.step for s in steps_out] == [1, 2, 3]

    def test_read_nonexistent_file(self, tmp_path):
        """Test reading from a nonexistent file."""
        csv_path = tmp_path / "nonexistent.csv"

        with pytest.raises(FileNotFoundError):
            read_pipeline_steps(csv_path)

    def test_error_message_with_commas(self, tmp_path):
        """Test handling of error messages with commas."""
        csv_path = tmp_path / "error.csv"
        step = PipelineStep(
            step=1,
            name="test_step",
            status=StepStatus.FAILED,
            error_message="Error: connection failed, timeout occurred",
        )

        write_pipeline_steps(csv_path, [step])
        steps = read_pipeline_steps(csv_path)

        assert len(steps) == 1
        assert steps[0].error_message == "Error: connection failed, timeout occurred"
