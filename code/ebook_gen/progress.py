"""Progress tracking for the ebook generation pipeline.

Also provides the StateAdapter abstraction for Phase 0 microservices seam.
Set STATE_BACKEND=postgres to route pipeline state through PostgreSQL instead
of local CSV files (requires POSTGRES_* env vars).  Default: csv.
"""

import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import PipelineStep, StepStatus, PIPELINE_STEPS
from .utils.csv_io import read_pipeline_steps, write_pipeline_steps
from .utils.file_io import ensure_directory


class ProgressTracker:
    """Manages the pipeline_state.csv file for a single story.

    All mutations are atomic -- the CSV is rewritten entirely on each update
    to prevent corruption.
    """

    def __init__(self, progress_dir: Path):
        """Initialize progress tracker.

        Args:
            progress_dir: Directory for this story's progress tracking
                         (e.g., progress/three-billy-goats-gruff/)
        """
        self._dir = progress_dir
        self._csv_path = progress_dir / "pipeline_state.csv"
        self._steps: List[PipelineStep] = []

    def initialize(self) -> None:
        """Create a fresh pipeline_state.csv with all 8 steps in 'pending' status.

        Called at the start of a new run.

        Raises:
            FileExistsError: If state already exists (use load instead)
        """
        if self._csv_path.exists():
            raise FileExistsError(
                f"Pipeline state already exists: {self._csv_path}. "
                f"Use load() to read existing state or delete the file to start fresh."
            )

        # Create directory
        ensure_directory(self._dir)

        # Initialize steps
        self._steps = [
            PipelineStep(step=step_num, name=step_name)
            for step_num, step_name in PIPELINE_STEPS
        ]

        # Write to disk
        write_pipeline_steps(self._csv_path, self._steps)

    def load(self) -> List[PipelineStep]:
        """Load existing pipeline state from CSV.

        Returns:
            List of pipeline steps

        Raises:
            FileNotFoundError: If no state exists (use initialize instead)
        """
        self._steps = read_pipeline_steps(self._csv_path)
        return self._steps

    def get_steps(self) -> List[PipelineStep]:
        """Get the current list of steps.

        Returns:
            List of pipeline steps (may be empty if not initialized/loaded)
        """
        return self._steps

    def get_step(self, step_number: int) -> PipelineStep:
        """Get a specific step's state.

        Args:
            step_number: Step number (1-8)

        Returns:
            PipelineStep object

        Raises:
            ValueError: If step number is invalid
        """
        if not 1 <= step_number <= 8:
            raise ValueError(f"Invalid step number: {step_number}. Must be 1-8.")

        for step in self._steps:
            if step.step == step_number:
                return step

        raise ValueError(f"Step {step_number} not found in loaded state.")

    def update_step(
        self,
        step_number: int,
        status: StepStatus,
        error_message: str = "",
        output_artifact: str = "",
    ) -> None:
        """Update a step's status and rewrite the CSV atomically.

        Args:
            step_number: Step number (1-8)
            status: New status
            error_message: Error message if failed
            output_artifact: Path(s) to output files (comma-separated)

        Raises:
            ValueError: If step number is invalid
        """
        step = self.get_step(step_number)

        # Update status
        old_status = step.status
        step.status = status
        step.error_message = error_message
        step.output_artifact = output_artifact

        # Update timestamps
        if status == StepStatus.IN_PROGRESS and old_status == StepStatus.PENDING:
            step.started_at = datetime.utcnow()
            step.attempts += 1
        elif status in (StepStatus.COMPLETED, StepStatus.FAILED):
            step.completed_at = datetime.utcnow()
        elif status == StepStatus.IN_PROGRESS and old_status == StepStatus.FAILED:
            # Retry - increment attempts
            step.attempts += 1
            step.started_at = datetime.utcnow()
            step.completed_at = None
            step.error_message = ""

        # Write atomically
        write_pipeline_steps(self._csv_path, self._steps)

    def mark_step_in_progress(self, step_number: int) -> None:
        """Mark a step as in progress.

        Args:
            step_number: Step number (1-8)
        """
        self.update_step(step_number, StepStatus.IN_PROGRESS)

    def mark_step_completed(
        self, step_number: int, output_artifact: str = ""
    ) -> None:
        """Mark a step as completed.

        Args:
            step_number: Step number (1-8)
            output_artifact: Path(s) to output files (comma-separated)
        """
        self.update_step(
            step_number, StepStatus.COMPLETED, output_artifact=output_artifact
        )

    def mark_step_failed(self, step_number: int, error_message: str) -> None:
        """Mark a step as failed.

        Args:
            step_number: Step number (1-8)
            error_message: Error description
        """
        self.update_step(step_number, StepStatus.FAILED, error_message=error_message)

    def get_resume_step(self) -> Optional[int]:
        """Return the step number to resume from, or None if all complete.

        The resume step is the first step with status != 'completed'.

        Returns:
            Step number (1-8) or None if all steps are completed
        """
        for step in self._steps:
            if step.status != StepStatus.COMPLETED:
                return step.step
        return None

    def is_step_completed(self, step_number: int) -> bool:
        """Check if a step is completed.

        Args:
            step_number: Step number (1-8)

        Returns:
            True if step is completed, False otherwise
        """
        step = self.get_step(step_number)
        return step.status == StepStatus.COMPLETED

    def is_pipeline_complete(self) -> bool:
        """Check if the entire pipeline is complete.

        Returns:
            True if all steps are completed, False otherwise
        """
        return all(step.status == StepStatus.COMPLETED for step in self._steps)

    def get_failed_steps(self) -> List[int]:
        """Get a list of failed step numbers.

        Returns:
            List of step numbers (1-8) that have failed status
        """
        return [step.step for step in self._steps if step.status == StepStatus.FAILED]

    def reset_step(self, step_number: int) -> None:
        """Reset a step to pending status.

        Useful for retrying after manual fixes.

        Args:
            step_number: Step number (1-8)
        """
        step = self.get_step(step_number)
        step.status = StepStatus.PENDING
        step.error_message = ""
        step.completed_at = None
        # Keep started_at and attempts for history

        write_pipeline_steps(self._csv_path, self._steps)


# ---------------------------------------------------------------------------
# StateAdapter — Phase 0 microservices seam
# ---------------------------------------------------------------------------


class StateAdapter(ABC):
    """Abstract pipeline state adapter.

    Both the CSV (monolith) and PostgreSQL (microservices) backends implement
    this interface.  The adapter operates on ``story_id`` strings so that
    callers never need to construct file paths or SQL queries directly.

    Concurrent writes from parallel pods use the PostgreSQL backend's
    ``UPDATE … WHERE status = 'pending' RETURNING *`` pattern; the CSV
    backend uses atomic rename for single-process safety.
    """

    @abstractmethod
    def initialize(self, story_id: str) -> None:
        """Create fresh state with all steps in 'pending'."""

    @abstractmethod
    def load(self, story_id: str) -> List[PipelineStep]:
        """Load and return current pipeline steps."""

    @abstractmethod
    def update_step(
        self,
        story_id: str,
        step_number: int,
        status: StepStatus,
        error_message: str = "",
        output_artifact: str = "",
    ) -> None:
        """Atomically update a single step's status."""

    @abstractmethod
    def get_step(self, story_id: str, step_number: int) -> PipelineStep:
        """Return the current state of a single step."""

    @abstractmethod
    def is_step_completed(self, story_id: str, step_number: int) -> bool:
        """Return True if the step has completed successfully."""

    @abstractmethod
    def get_resume_step(self, story_id: str) -> Optional[int]:
        """Return the first non-completed step number, or None if all done."""

    @abstractmethod
    def reset_step(self, story_id: str, step_number: int) -> None:
        """Reset a step to pending so it can be retried."""


class CsvStateAdapter(StateAdapter):
    """StateAdapter backed by CSV files on the local filesystem.

    Delegates all operations to :class:`ProgressTracker`, keeping the
    existing behaviour identical.  One :class:`ProgressTracker` instance
    is created per ``story_id`` and cached for the lifetime of this adapter.
    """

    def __init__(self, progress_root: Path):
        """
        Args:
            progress_root: Root directory that contains per-story progress
                           subdirectories (e.g. ``projects/<story>/progress``).
        """
        self._root = progress_root
        self._trackers: dict[str, ProgressTracker] = {}

    def _tracker(self, story_id: str) -> ProgressTracker:
        if story_id not in self._trackers:
            self._trackers[story_id] = ProgressTracker(self._root / story_id)
        return self._trackers[story_id]

    def initialize(self, story_id: str) -> None:
        self._tracker(story_id).initialize()

    def load(self, story_id: str) -> List[PipelineStep]:
        return self._tracker(story_id).load()

    def update_step(
        self,
        story_id: str,
        step_number: int,
        status: StepStatus,
        error_message: str = "",
        output_artifact: str = "",
    ) -> None:
        self._tracker(story_id).update_step(
            step_number, status, error_message, output_artifact
        )

    def get_step(self, story_id: str, step_number: int) -> PipelineStep:
        return self._tracker(story_id).get_step(step_number)

    def is_step_completed(self, story_id: str, step_number: int) -> bool:
        return self._tracker(story_id).is_step_completed(step_number)

    def get_resume_step(self, story_id: str) -> Optional[int]:
        return self._tracker(story_id).get_resume_step()

    def reset_step(self, story_id: str, step_number: int) -> None:
        self._tracker(story_id).reset_step(step_number)


class PostgresStateAdapter(StateAdapter):
    """StateAdapter backed by PostgreSQL.

    Not yet implemented — will be wired up in Phase 1 when the PostgreSQL
    infrastructure is deployed.  Raises ``NotImplementedError`` on every
    call so that accidental use during development fails loudly.

    Required env vars when activated::

        POSTGRES_HOST     (default: localhost)
        POSTGRES_PORT     (default: 5432)
        POSTGRES_DB       (default: ebook_gen)
        POSTGRES_USER     (default: ebook_gen)
        POSTGRES_PASSWORD (default: "")

    Schema (DDL) lives in ``infra/postgres/schema.sql``.
    Concurrent step updates use::

        UPDATE pipeline_steps
           SET status = %s, started_at = NOW()
         WHERE story_id = %s AND step = %s AND status = 'pending'
         RETURNING *;
    """

    def __init__(self, config=None):
        # config is PostgresConfig; accepted here so the constructor signature
        # is consistent, but the connection pool is not created until Phase 1.
        self._config = config

    def _not_implemented(self) -> None:
        raise NotImplementedError(
            "PostgresStateAdapter is a Phase 1 stub. "
            "Deploy PostgreSQL infrastructure and install psycopg2/asyncpg "
            "before enabling STATE_BACKEND=postgres."
        )

    def initialize(self, story_id: str) -> None:
        self._not_implemented()

    def load(self, story_id: str) -> List[PipelineStep]:
        self._not_implemented()

    def update_step(self, story_id, step_number, status, error_message="", output_artifact=""):
        self._not_implemented()

    def get_step(self, story_id: str, step_number: int) -> PipelineStep:
        self._not_implemented()

    def is_step_completed(self, story_id: str, step_number: int) -> bool:
        self._not_implemented()

    def get_resume_step(self, story_id: str) -> Optional[int]:
        self._not_implemented()

    def reset_step(self, story_id: str, step_number: int) -> None:
        self._not_implemented()


def get_state_adapter(progress_root: Path) -> StateAdapter:
    """Factory: return the StateAdapter selected by STATE_BACKEND env var.

    Args:
        progress_root: Root directory for per-story progress subdirectories.

    Returns:
        CsvStateAdapter      when STATE_BACKEND=csv (default).
        PostgresStateAdapter when STATE_BACKEND=postgres.
    """
    backend = os.getenv("STATE_BACKEND", "csv").lower()
    if backend == "postgres":
        from .config import PostgresConfig
        return PostgresStateAdapter(PostgresConfig.from_env())
    return CsvStateAdapter(progress_root)
