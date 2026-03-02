"""Tests for ProgressTracker."""

import pytest
from datetime import datetime

from ebook_gen.models import StepStatus
from ebook_gen.progress import ProgressTracker


class TestProgressTracker:
    """Tests for ProgressTracker."""

    def test_initialize(self, tmp_path):
        """Test initializing a new progress tracker."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)

        tracker.initialize()

        assert (progress_dir / "pipeline_state.csv").exists()
        steps = tracker.get_steps()
        assert len(steps) == 8
        assert all(s.status == StepStatus.PENDING for s in steps)

    def test_initialize_twice_raises_error(self, tmp_path):
        """Test that initializing twice raises an error."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)

        tracker.initialize()

        with pytest.raises(FileExistsError):
            tracker.initialize()

    def test_load(self, tmp_path):
        """Test loading existing progress."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)

        tracker.initialize()

        # Create new tracker instance and load
        tracker2 = ProgressTracker(progress_dir)
        steps = tracker2.load()

        assert len(steps) == 8
        assert all(s.status == StepStatus.PENDING for s in steps)

    def test_load_nonexistent_raises_error(self, tmp_path):
        """Test loading from nonexistent file raises error."""
        progress_dir = tmp_path / "nonexistent"
        tracker = ProgressTracker(progress_dir)

        with pytest.raises(FileNotFoundError):
            tracker.load()

    def test_get_step(self, tmp_path):
        """Test getting a specific step."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        step1 = tracker.get_step(1)
        assert step1.step == 1
        assert step1.name == "story_fetch"

        step7 = tracker.get_step(7)
        assert step7.step == 7
        assert step7.name == "ebook_compilation"

        step8 = tracker.get_step(8)
        assert step8.step == 8
        assert step8.name == "audio_generation"

    def test_get_step_invalid_number(self, tmp_path):
        """Test getting a step with invalid number."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        with pytest.raises(ValueError):
            tracker.get_step(0)

        with pytest.raises(ValueError):
            tracker.get_step(9)

    def test_mark_step_in_progress(self, tmp_path):
        """Test marking a step as in progress."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        tracker.mark_step_in_progress(1)

        step = tracker.get_step(1)
        assert step.status == StepStatus.IN_PROGRESS
        assert step.started_at is not None
        assert step.attempts == 1

    def test_mark_step_completed(self, tmp_path):
        """Test marking a step as completed."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        tracker.mark_step_in_progress(1)
        tracker.mark_step_completed(1, output_artifact="path/to/output.txt")

        step = tracker.get_step(1)
        assert step.status == StepStatus.COMPLETED
        assert step.completed_at is not None
        assert step.output_artifact == "path/to/output.txt"

    def test_mark_step_failed(self, tmp_path):
        """Test marking a step as failed."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        tracker.mark_step_in_progress(1)
        tracker.mark_step_failed(1, error_message="Test error")

        step = tracker.get_step(1)
        assert step.status == StepStatus.FAILED
        assert step.error_message == "Test error"
        assert step.completed_at is not None

    def test_get_resume_step_all_pending(self, tmp_path):
        """Test get_resume_step when all steps are pending."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        resume_step = tracker.get_resume_step()
        assert resume_step == 1

    def test_get_resume_step_some_completed(self, tmp_path):
        """Test get_resume_step when some steps are completed."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        tracker.mark_step_in_progress(1)
        tracker.mark_step_completed(1)
        tracker.mark_step_in_progress(2)
        tracker.mark_step_completed(2)

        resume_step = tracker.get_resume_step()
        assert resume_step == 3

    def test_get_resume_step_all_completed(self, tmp_path):
        """Test get_resume_step when all steps are completed."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        for i in range(1, 9):
            tracker.mark_step_in_progress(i)
            tracker.mark_step_completed(i)

        resume_step = tracker.get_resume_step()
        assert resume_step is None

    def test_is_step_completed(self, tmp_path):
        """Test checking if a step is completed."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        assert not tracker.is_step_completed(1)

        tracker.mark_step_in_progress(1)
        assert not tracker.is_step_completed(1)

        tracker.mark_step_completed(1)
        assert tracker.is_step_completed(1)

    def test_is_pipeline_complete(self, tmp_path):
        """Test checking if pipeline is complete."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        assert not tracker.is_pipeline_complete()

        for i in range(1, 9):
            tracker.mark_step_in_progress(i)
            tracker.mark_step_completed(i)

        assert tracker.is_pipeline_complete()

    def test_get_failed_steps(self, tmp_path):
        """Test getting list of failed steps."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        assert tracker.get_failed_steps() == []

        tracker.mark_step_in_progress(1)
        tracker.mark_step_completed(1)
        tracker.mark_step_in_progress(2)
        tracker.mark_step_failed(2, "Error")
        tracker.mark_step_in_progress(3)
        tracker.mark_step_failed(3, "Error")

        failed = tracker.get_failed_steps()
        assert failed == [2, 3]

    def test_reset_step(self, tmp_path):
        """Test resetting a step to pending."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        tracker.mark_step_in_progress(1)
        tracker.mark_step_failed(1, "Test error")

        tracker.reset_step(1)

        step = tracker.get_step(1)
        assert step.status == StepStatus.PENDING
        assert step.error_message == ""
        assert step.completed_at is None
        # started_at and attempts are preserved for history
        assert step.started_at is not None
        assert step.attempts > 0

    def test_retry_increments_attempts(self, tmp_path):
        """Test that retrying a failed step increments attempts."""
        progress_dir = tmp_path / "progress"
        tracker = ProgressTracker(progress_dir)
        tracker.initialize()

        tracker.mark_step_in_progress(1)
        assert tracker.get_step(1).attempts == 1

        tracker.mark_step_failed(1, "Error")
        tracker.reset_step(1)
        tracker.mark_step_in_progress(1)

        assert tracker.get_step(1).attempts == 2

    def test_persistence_across_instances(self, tmp_path):
        """Test that changes persist across tracker instances."""
        progress_dir = tmp_path / "progress"

        # Initialize with first instance
        tracker1 = ProgressTracker(progress_dir)
        tracker1.initialize()
        tracker1.mark_step_in_progress(1)
        tracker1.mark_step_completed(1)

        # Load with second instance
        tracker2 = ProgressTracker(progress_dir)
        tracker2.load()

        step = tracker2.get_step(1)
        assert step.status == StepStatus.COMPLETED

        # Modify with second instance
        tracker2.mark_step_in_progress(2)

        # Verify with third instance
        tracker3 = ProgressTracker(progress_dir)
        tracker3.load()

        step1 = tracker3.get_step(1)
        step2 = tracker3.get_step(2)

        assert step1.status == StepStatus.COMPLETED
        assert step2.status == StepStatus.IN_PROGRESS
