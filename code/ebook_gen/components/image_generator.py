"""Image generation component for ebook pipeline."""

import logging
from dataclasses import dataclass
from pathlib import Path

from ..backends import BackendError, GenerationBackend
from ..models import ImageRecord, ImageStatus, StoryConfig
from ..utils.csv_io import read_image_records, write_image_records

logger = logging.getLogger(__name__)


@dataclass
class ImageGenInput:
    """Input for image generator."""

    prompts_csv_path: Path  # from step 5 (prompts/<story>/prompts.csv)
    story_config: StoryConfig  # contains image_mode, model names
    output_dir: Path  # images/<story>/


@dataclass
class ImageGenOutput:
    """Output from image generator."""

    images_dir: Path
    completed_count: int
    failed_count: int
    skipped_count: int


class ImageGenerator:
    """Generates images from prompts CSV using the model backend.

    Reads prompts.csv, generates images for each pending or failed record,
    saves them as PNG files, and updates the CSV status after each image.
    This enables resume capability: on restart, only non-completed images
    are generated.
    """

    def __init__(self, backend: GenerationBackend):
        """Initialize image generator.

        Args:
            backend: Model backend for image generation
        """
        self._backend = backend

    def execute(self, input_data: ImageGenInput) -> ImageGenOutput:
        """Generate images from prompts CSV.

        For each ImageRecord where status is not 'completed':
          1. Mark as in_progress and write CSV.
          2. Call the backend image generation API.
          3. Save PNG to output_dir/target_filename.
          4. Update status to 'completed' or 'failed'.
          5. Write CSV atomically after each image.

        Args:
            input_data: Input configuration

        Returns:
            Output with counts of completed, failed, and skipped images

        Raises:
            FileNotFoundError: If prompts CSV doesn't exist
        """
        records = read_image_records(input_data.prompts_csv_path)
        input_data.output_dir.mkdir(parents=True, exist_ok=True)

        total = len(records)
        completed = 0
        failed = 0
        skipped = 0

        for i, record in enumerate(records):
            if record.status == ImageStatus.COMPLETED:
                logger.info(f"Skipping already-completed image: {record.name}")
                skipped += 1
                continue

            if record.status == ImageStatus.SKIPPED:
                skipped += 1
                continue

            logger.info(
                f"Generating image {i + 1}/{total}: {record.name} "
                f"({record.width}x{record.height}) model={record.model}"
            )

            # Mark in-progress and persist before attempting generation
            record.status = ImageStatus.IN_PROGRESS
            write_image_records(input_data.prompts_csv_path, records)

            try:
                image_bytes = self._backend.generate_image(
                    model=record.model,
                    prompt=record.prompt,
                    width=record.width,
                    height=record.height,
                    seed=record.seed,
                )

                output_path = input_data.output_dir / record.target_filename
                output_path.write_bytes(image_bytes)

                record.status = ImageStatus.COMPLETED
                completed += 1
                logger.info(f"Saved image: {output_path}")

            except BackendError as e:
                record.status = ImageStatus.FAILED
                failed += 1
                logger.error(f"Failed to generate image '{record.name}': {e}")

            # Persist status after each image (atomic write for crash safety)
            write_image_records(input_data.prompts_csv_path, records)

        logger.info(
            f"Image generation complete: {completed} completed, "
            f"{failed} failed, {skipped} skipped"
        )

        return ImageGenOutput(
            images_dir=input_data.output_dir,
            completed_count=completed,
            failed_count=failed,
            skipped_count=skipped,
        )
