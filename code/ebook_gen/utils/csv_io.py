"""CSV I/O utilities for image records, audio records, and pipeline state."""

import csv
from pathlib import Path
from typing import List

from ..models import AudioRecord, ImageRecord, PipelineStep


def read_image_records(csv_path: Path) -> List[ImageRecord]:
    """Read image records from a CSV file.

    Args:
        csv_path: Path to the prompts CSV file

    Returns:
        List of ImageRecord objects

    Raises:
        FileNotFoundError: If the CSV file doesn't exist
        ValueError: If the CSV has invalid data
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Prompts CSV not found: {csv_path}")

    records = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                records.append(ImageRecord.from_csv_row(row))
            except (KeyError, ValueError) as e:
                raise ValueError(f"Invalid CSV row in {csv_path}: {e}") from e

    return records


def write_image_records(csv_path: Path, records: List[ImageRecord]) -> None:
    """Write image records to a CSV file.

    Uses atomic write pattern (write to temp, then rename).

    Args:
        csv_path: Path to the prompts CSV file
        records: List of ImageRecord objects to write
    """
    from .file_io import atomic_write

    # Convert records to CSV rows
    rows = [record.to_csv_row() for record in records]

    # Generate CSV content
    if rows:
        fieldnames = rows[0].keys()
        lines = []

        # Write header
        lines.append(",".join(fieldnames))

        # Write rows
        for row in rows:
            # Escape fields that contain commas or quotes
            escaped_row = []
            for field in fieldnames:
                value = row[field]
                # Quote if contains comma, newline, or quote
                if "," in value or "\n" in value or '"' in value:
                    value = '"' + value.replace('"', '""') + '"'
                escaped_row.append(value)
            lines.append(",".join(escaped_row))

        content = "\n".join(lines) + "\n"
    else:
        # Empty CSV with just header
        content = (
            "image_id,name,description,prompt,model,target_filename,"
            "status,width,height,seed\n"
        )

    atomic_write(csv_path, content)


def read_audio_records(csv_path: Path) -> List[AudioRecord]:
    """Read audio records from a CSV file.

    Args:
        csv_path: Path to the audio tracks CSV file

    Returns:
        List of AudioRecord objects

    Raises:
        FileNotFoundError: If the CSV file doesn't exist
        ValueError: If the CSV has invalid data
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Audio tracks CSV not found: {csv_path}")

    records = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                records.append(AudioRecord.from_csv_row(row))
            except (KeyError, ValueError) as e:
                raise ValueError(f"Invalid CSV row in {csv_path}: {e}") from e

    return records


def write_audio_records(csv_path: Path, records: List[AudioRecord]) -> None:
    """Write audio records to a CSV file.

    Uses atomic write pattern (write to temp, then rename).

    Args:
        csv_path: Path to the audio tracks CSV file
        records: List of AudioRecord objects to write
    """
    from .file_io import atomic_write

    rows = [record.to_csv_row() for record in records]

    if rows:
        fieldnames = rows[0].keys()
        lines = []

        lines.append(",".join(fieldnames))

        for row in rows:
            escaped_row = []
            for field in fieldnames:
                value = row[field]
                if "," in value or "\n" in value or '"' in value:
                    value = '"' + value.replace('"', '""') + '"'
                escaped_row.append(value)
            lines.append(",".join(escaped_row))

        content = "\n".join(lines) + "\n"
    else:
        content = "audio_id,language,voice,text_length,target_filename,status,duration_seconds\n"

    atomic_write(csv_path, content)


def read_pipeline_steps(csv_path: Path) -> List[PipelineStep]:
    """Read pipeline steps from a CSV file.

    Args:
        csv_path: Path to the pipeline state CSV file

    Returns:
        List of PipelineStep objects sorted by step number

    Raises:
        FileNotFoundError: If the CSV file doesn't exist
        ValueError: If the CSV has invalid data
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Pipeline state CSV not found: {csv_path}")

    steps = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                steps.append(PipelineStep.from_csv_row(row))
            except (KeyError, ValueError) as e:
                raise ValueError(f"Invalid CSV row in {csv_path}: {e}") from e

    # Sort by step number
    steps.sort(key=lambda s: s.step)
    return steps


def write_pipeline_steps(csv_path: Path, steps: List[PipelineStep]) -> None:
    """Write pipeline steps to a CSV file.

    Uses atomic write pattern (write to temp, then rename).

    Args:
        csv_path: Path to the pipeline state CSV file
        steps: List of PipelineStep objects to write
    """
    from .file_io import atomic_write

    # Sort by step number
    steps = sorted(steps, key=lambda s: s.step)

    # Convert steps to CSV rows
    rows = [step.to_csv_row() for step in steps]

    # Generate CSV content
    if rows:
        fieldnames = rows[0].keys()
        lines = []

        # Write header
        lines.append(",".join(fieldnames))

        # Write rows
        for row in rows:
            # Escape fields that contain commas or quotes
            escaped_row = []
            for field in fieldnames:
                value = row[field]
                # Quote if contains comma, newline, or quote
                if "," in value or "\n" in value or '"' in value:
                    value = '"' + value.replace('"', '""') + '"'
                escaped_row.append(value)
            lines.append(",".join(escaped_row))

        content = "\n".join(lines) + "\n"
    else:
        # Empty CSV with just header
        content = (
            "step,name,status,started_at,completed_at,error_message,"
            "attempts,output_artifact\n"
        )

    atomic_write(csv_path, content)
