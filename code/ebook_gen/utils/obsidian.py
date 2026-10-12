"""Obsidian note writer for completed ebook generation runs."""

import os
from datetime import datetime
from pathlib import Path

from ..models import StoryConfig
from ..progress import ProgressTracker

# The ./ebook-gen wrapper mounts the vault into containers and sets OBSIDIAN_VAULT_DIR
VAULT_DIR = Path(
    os.getenv("OBSIDIAN_VAULT_DIR", Path.home() / "Documents" / "Obsidian" / "MyVault")
)
NOTE_SUBDIR = "Ebook Gen"

_STATUS_ICON = {
    "pending": "⏸",
    "in_progress": "▶",
    "completed": "✓",
    "failed": "✗",
    "skipped": "⊘",
}


def write_story_note(
    config: StoryConfig,
    progress_dir: Path,
    compiled_dir: Path,
    images_dir: Path,
    audio_dir: Path | None = None,
) -> Path | None:
    """Write (or overwrite) an Obsidian note for a story.

    Creates VAULT_DIR/Ebook Gen/<story-id>.md with YAML front matter,
    pipeline status table, and links to output files.

    Returns the note path on success, None if the vault directory doesn't exist.
    """
    if not VAULT_DIR.is_dir():
        return None
    note_dir = VAULT_DIR / NOTE_SUBDIR
    note_dir.mkdir(exist_ok=True)

    tracker = ProgressTracker(progress_dir)
    try:
        steps = tracker.load()
    except FileNotFoundError:
        steps = []

    # Pipeline status table
    status_rows = "\n".join(
        f"| {s.step}. {s.name.replace('_', ' ').title()} "
        f"| {_STATUS_ICON.get(s.status.value, '?')} {s.status.value} |"
        for s in steps
    )

    # Output files
    compiled_files = sorted(compiled_dir.glob("*")) if compiled_dir.exists() else []
    file_lines = "\n".join(f"- `{f.name}`" for f in compiled_files) or "_(none yet)_"

    image_files = sorted(images_dir.glob("*.png")) if images_dir.exists() else []
    image_lines = "\n".join(f"- `{f.name}`" for f in image_files) or "_(none yet)_"

    audio_lines = "_(not requested)_"
    if audio_dir and audio_dir.exists():
        audio_files = sorted(audio_dir.glob("*.wav"))
        audio_lines = "\n".join(f"- `{f.name}`" for f in audio_files) or "_(none yet)_"

    languages = ", ".join(config.target_languages)
    audio_langs = ", ".join(config.audio_languages) if config.audio_languages else "none"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    note = f"""\
---
title: "{config.title}"
story_id: {config.story_id}
theme: {config.theme}
tropes: [{', '.join(config.tropes)}]
rating: {config.content_rating.value}
image_mode: {config.image_mode.value}
languages: [{languages}]
audio: [{audio_langs}]
source: "{config.source_file}"
updated: {now}
tags: [ebook-gen, {config.theme}]
---

# {config.title}

## Pipeline Status

| Step | Status |
|------|--------|
{status_rows}

## Output Files

### Ebooks
{file_lines}

### Images
{image_lines}

### Audio
{audio_lines}

## Source

`{config.source_file}`
"""

    note_path = note_dir / f"{config.story_id}.md"
    note_path.write_text(note, encoding="utf-8")
    return note_path
