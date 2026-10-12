"""Pipeline orchestration for ebook generation."""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .components.audio_generator import AudioGenInput, AudioGenerator
from .components.content_rater import ContentRateInput, ContentRater
from .components.ebook_compiler import EbookCompileInput, EbookCompiler
from .components.image_generator import ImageGenInput, ImageGenerator
from .components.prompt_generator import PromptGenInput, PromptGenerator
from .components.story_modifier import StoryModifyInput, StoryModifier
from .components.translator import TranslateInput, Translator
from .backends import GenerationBackend, create_backend
from .config import BackendConfig, BackendKind, ProjectConfig
from .models import MODEL_STEPS, PIPELINE_STAGES, PIPELINE_STEPS, StepStatus, StoryConfig
from .progress import ProgressTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Base exception for pipeline errors."""

    pass


def current_stage() -> Optional[str]:
    """The stage this process runs (EBOOK_GEN_STAGE), or None for all steps.

    Each pipeline container sets it; the ./ebook-gen wrapper runs the other
    stages in their own containers.

    Raises:
        PipelineError: EBOOK_GEN_STAGE names an unknown stage
    """
    stage = os.getenv("EBOOK_GEN_STAGE") or None
    if stage and stage not in PIPELINE_STAGES:
        raise PipelineError(
            f"Unknown EBOOK_GEN_STAGE '{stage}'; expected one of {', '.join(PIPELINE_STAGES)}"
        )
    return stage


class PipelineRunner:
    """Orchestrates the 8-step ebook generation pipeline.

    Manages execution of all pipeline steps with progress tracking,
    error handling, and resume capability.
    """

    def __init__(
        self,
        story_config: StoryConfig,
        project_config: ProjectConfig,
        backend_config: Optional[BackendConfig] = None,
    ):
        """Initialize pipeline runner.

        Args:
            story_config: Configuration for the story
            project_config: Project directory configuration
            backend_config: Model backend selection (optional; default from env)
        """
        self._story_config = story_config
        self._project = project_config
        self._backend_config = backend_config or BackendConfig.from_env()

        # In a pipeline container, only this stage's steps run here
        self._stage = current_stage()

        # Initialize progress tracker
        progress_dir = self._project.get_progress_dir(story_config.story_id)
        self._progress = ProgressTracker(progress_dir)

        # Model backend (created lazily)
        self._backend: Optional[GenerationBackend] = None

    def run(self, start_from_step: int = 1, end_at_step: int = 6) -> None:
        """Execute the pipeline from start_from_step to end_at_step.

        Args:
            start_from_step: First step to execute (1-8)
            end_at_step: Last step to execute (1-8)

        Raises:
            PipelineError: If pipeline execution fails
        """
        logger.info(
            f"Starting pipeline for '{self._story_config.story_id}' "
            f"(steps {start_from_step}-{end_at_step})"
        )

        # Load progress state if not already loaded (e.g. when called directly via run())
        if not self._progress.get_steps():
            self._progress.load()

        try:
            # Execute each step
            for step_num, step_name in PIPELINE_STEPS:
                if step_num < start_from_step or step_num > end_at_step:
                    continue

                # Check if already completed
                if self._progress.is_step_completed(step_num):
                    logger.info(f"Step {step_num} ({step_name}) already completed")
                    continue

                if not self._in_stage(step_num, step_name):
                    break

                # Model steps need the backend; compile and audio don't
                if step_num in MODEL_STEPS and self._backend is None:
                    self._backend = create_backend(self._backend_config)
                    if not self._backend.health_check():
                        raise PipelineError(self._backend_unavailable_message())

                logger.info(f"Executing step {step_num}: {step_name}")
                self._execute_step(step_num, step_name)

            logger.info("Pipeline execution completed successfully")

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            raise PipelineError(f"Pipeline failed: {e}") from e

        finally:
            # Release HTTP connections / loaded models
            if self._backend:
                self._backend.close()
                self._backend = None

    def _in_stage(self, step_num: int, step_name: str) -> bool:
        """Whether this process runs step_num; False once past this stage's steps.

        Raises:
            PipelineError: An earlier stage's step is still incomplete
        """
        if self._stage is None:
            return True
        steps = PIPELINE_STAGES[self._stage]
        if step_num in steps:
            return True
        if step_num < min(steps):
            raise PipelineError(
                f"Step {step_num} ({step_name}) must complete before the "
                f"'{self._stage}' stage can run"
            )
        logger.info(f"Steps after {max(steps)} run outside the '{self._stage}' stage")
        return False

    def planned_end_step(self) -> int:
        """Last step for this story: preview stops after images, audio adds step 8."""
        if self._story_config.image_mode.value == "preview":
            return 6
        if self._story_config.audio_languages:
            return 8
        return 7

    def is_finished(self) -> bool:
        """Whether every step up to planned_end_step() is completed."""
        return all(
            self._progress.is_step_completed(step)
            for step in range(1, self.planned_end_step() + 1)
        )

    def _backend_unavailable_message(self) -> str:
        if self._backend_config.kind == BackendKind.OLLAMA:
            return f"Cannot connect to Ollama at {self._backend_config.ollama.base_url}"
        if self._backend_config.kind == BackendKind.REMOTE:
            return (
                f"Cannot reach the model server at {self._backend_config.model_server.url}. "
                "Start it with './ebook-gen model-server start'."
            )
        return (
            "MLX backend unavailable: it needs macOS on Apple Silicon with mlx installed. "
            "Set EBOOK_GEN_BACKEND=ollama to use Ollama instead."
        )

    def resume(self) -> None:
        """Resume pipeline from the first non-completed step.

        Raises:
            FileNotFoundError: If no progress state exists
            PipelineError: If resume fails
        """
        # Load progress
        self._progress.load()

        resume_step = self._progress.get_resume_step()
        if resume_step is None:
            logger.info("Pipeline is already complete")
            return

        logger.info(f"Resuming from step {resume_step}")
        self.run(start_from_step=resume_step, end_at_step=self.planned_end_step())

    def _execute_step(self, step_num: int, step_name: str) -> None:
        """Execute a single pipeline step.

        Args:
            step_num: Step number (1-7)
            step_name: Step identifier

        Raises:
            PipelineError: If step execution fails
        """
        # Mark step as in progress
        self._progress.mark_step_in_progress(step_num)

        try:
            # Execute the appropriate step
            if step_num == 1:
                output = self._execute_story_fetch()
                artifact = str(output.raw_markdown_path.relative_to(self._project.root_dir))
            elif step_num == 2:
                output = self._execute_story_modification()
                artifact = str(output.story_markdown_path.relative_to(self._project.root_dir))
            elif step_num == 3:
                output = self._execute_content_rating()
                artifact = str(output.metadata_path.relative_to(self._project.root_dir))
            elif step_num == 4:
                output = self._execute_translation()
                # Multiple output files - join paths
                artifact = ",".join([
                    str(p.relative_to(self._project.root_dir))
                    for p in output.translated_paths.values()
                ])
            elif step_num == 5:
                output = self._execute_prompt_generation()
                artifact = str(output.prompts_csv_path.relative_to(self._project.root_dir))
            elif step_num == 6:
                output = self._execute_image_generation()
                artifact = str(output.images_dir.relative_to(self._project.root_dir))
            elif step_num == 7:
                output = self._execute_ebook_compilation()
                artifact = ",".join([
                    str(p.relative_to(self._project.root_dir))
                    for p in output.compiled_files
                ])
            elif step_num == 8:
                output = self._execute_audio_generation()
                artifact = str(output.audio_dir.relative_to(self._project.root_dir))
            else:
                raise ValueError(f"Invalid step number: {step_num}")

            # Mark as completed
            self._progress.mark_step_completed(step_num, output_artifact=artifact)
            logger.info(f"Step {step_num} completed: {artifact}")

        except Exception as e:
            # Mark as failed
            error_msg = str(e)
            self._progress.mark_step_failed(step_num, error_msg)
            logger.error(f"Step {step_num} failed: {error_msg}")
            raise PipelineError(f"Step {step_num} ({step_name}) failed: {error_msg}") from e

    def _execute_story_fetch(self):
        """Execute step 1: read story from a local file.

        Returns:
            WikiFetchOutput
        """
        # Imported here: the fetchers need markdownify, which only the text image has
        from .components.file_fetcher import FileFetcher

        story_dir = self._project.get_story_dir(self._story_config.story_id)
        story_dir.mkdir(parents=True, exist_ok=True)

        source_file = Path(self._story_config.source_file)
        logger.info(f"Reading story file: {source_file}")
        fetcher = FileFetcher()
        return fetcher.execute(
            source_file=source_file,
            title=self._story_config.title,
            output_dir=story_dir,
        )

    def _execute_story_modification(self):
        """Execute step 2: Story modification.

        Returns:
            StoryModifyOutput
        """
        logger.info(f"Applying theme: {self._story_config.theme}...")

        story_dir = self._project.get_story_dir(self._story_config.story_id)
        raw_path = story_dir / "raw.md"

        if not raw_path.exists():
            raise PipelineError(
                f"Raw story not found: {raw_path}. "
                f"Run step 1 (Wikipedia fetch) first."
            )

        modifier = StoryModifier(self._backend)
        input_data = StoryModifyInput(
            raw_markdown_path=raw_path,
            story_config=self._story_config,
            output_dir=story_dir,
        )

        return modifier.execute(input_data)

    def _execute_content_rating(self):
        """Execute step 3: Content rating.

        Returns:
            ContentRateOutput
        """
        logger.info(f"Assigning content rating: {self._story_config.content_rating.value}...")

        story_dir = self._project.get_story_dir(self._story_config.story_id)
        story_path = story_dir / "story.md"

        if not story_path.exists():
            raise PipelineError(
                f"Story not found: {story_path}. "
                f"Run step 2 (Story modification) first."
            )

        rater = ContentRater(self._backend)
        input_data = ContentRateInput(
            story_markdown_path=story_path,
            story_config=self._story_config,
            output_dir=story_dir,
        )

        return rater.execute(input_data)

    def _execute_translation(self):
        """Execute step 4: Translation.

        Returns:
            TranslateOutput
        """
        logger.info(f"Translating to {len(self._story_config.target_languages)} language(s)...")

        story_dir = self._project.get_story_dir(self._story_config.story_id)
        story_path = story_dir / "story.md"

        if not story_path.exists():
            raise PipelineError(
                f"Story not found: {story_path}. "
                f"Run step 3 (Content rating) first."
            )

        translator = Translator(self._backend)
        input_data = TranslateInput(
            story_markdown_path=story_path,
            story_config=self._story_config,
            output_dir=story_dir,
        )

        return translator.execute(input_data)

    def _execute_prompt_generation(self):
        """Execute step 5: Prompt generation.

        Returns:
            PromptGenOutput
        """
        logger.info("Generating image prompts...")

        story_dir = self._project.get_story_dir(self._story_config.story_id)
        prompts_dir = self._project.get_prompts_dir(self._story_config.story_id)

        # Use source language story for prompt generation
        story_path = story_dir / "story.md"

        if not story_path.exists():
            raise PipelineError(
                f"Story not found: {story_path}. "
                f"Run previous steps first."
            )

        generator = PromptGenerator(self._backend)
        input_data = PromptGenInput(
            story_markdown_path=story_path,
            story_config=self._story_config,
            output_dir=prompts_dir,
        )

        return generator.execute(input_data)

    def _execute_image_generation(self):
        """Execute step 6: Image generation.

        Returns:
            ImageGenOutput
        """
        logger.info(
            f"Generating images (mode: {self._story_config.image_mode.value})..."
        )

        prompts_csv = (
            self._project.get_prompts_dir(self._story_config.story_id) / "prompts.csv"
        )
        images_dir = self._project.get_images_dir(self._story_config.story_id)

        if not prompts_csv.exists():
            raise PipelineError(
                f"Prompts CSV not found: {prompts_csv}. "
                f"Run step 5 (prompt generation) first."
            )

        generator = ImageGenerator(self._backend)
        input_data = ImageGenInput(
            prompts_csv_path=prompts_csv,
            story_config=self._story_config,
            output_dir=images_dir,
        )

        return generator.execute(input_data)

    def _execute_ebook_compilation(self):
        """Execute step 7: Ebook compilation.

        Returns:
            EbookCompileOutput
        """
        logger.info("Compiling ebooks...")

        story_dir = self._project.get_story_dir(self._story_config.story_id)
        images_dir = self._project.get_images_dir(self._story_config.story_id)
        prompts_csv = self._project.get_prompts_dir(self._story_config.story_id) / "prompts.csv"
        output_dir = self._project.get_compiled_dir(self._story_config.story_id)

        compiler = EbookCompiler()
        input_data = EbookCompileInput(
            story_config=self._story_config,
            story_dir=story_dir,
            images_dir=images_dir,
            prompts_csv_path=prompts_csv,
            output_dir=output_dir,
        )

        return compiler.execute(input_data)

    def _execute_audio_generation(self):
        """Execute step 8: Audio generation.

        Returns:
            AudioGenOutput
        """
        if not self._story_config.audio_languages:
            raise PipelineError(
                "No audio languages configured. "
                "Set audio_languages in StoryConfig or pass --audio-languages to the CLI."
            )

        logger.info(
            f"Generating audio for {len(self._story_config.audio_languages)} "
            f"language(s): {self._story_config.audio_languages}"
        )

        audio_dir = self._project.get_audio_dir(self._story_config.story_id)
        audio_csv = audio_dir / "audio_tracks.csv"
        story_dir = self._project.get_story_dir(self._story_config.story_id)

        generator = AudioGenerator()
        input_data = AudioGenInput(
            audio_csv_path=audio_csv,
            story_config=self._story_config,
            story_dir=story_dir,
            output_dir=audio_dir,
        )

        return generator.execute(input_data)
