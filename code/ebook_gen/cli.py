"""Command-line interface for ebook generation."""

import json
import sys
from pathlib import Path

import click

from .config import ProjectConfig
from .models import (
    ContentRating,
    IMAGE_STYLE_VALUES,
    ImageMode,
    ImageStatus,
    StoryConfig,
    Theme,
)
from .progress import ProgressTracker


def get_project_config() -> ProjectConfig:
    """Get the project configuration from current directory."""
    # In Docker, we're in /workspace
    # When running locally, find the project root
    current = Path.cwd()

    # Check if we're in /workspace (Docker) or find project root
    if current.name == "code":
        root = current.parent
    elif (current / "code").exists():
        root = current
    else:
        root = current

    return ProjectConfig.from_root(root)


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug.

    Args:
        text: Text to slugify

    Returns:
        Slugified text (lowercase, hyphens, alphanumeric)
    """
    import re

    # Convert to lowercase
    text = text.lower()
    # Replace spaces and hyphens with underscores
    text = re.sub(r"[\s\-]+", "_", text)
    # Remove non-alphanumeric characters (except underscores)
    text = re.sub(r"[^a-z0-9_]", "", text)
    # Collapse multiple underscores
    text = re.sub(r"_+", "_", text)
    # Strip leading/trailing underscores
    text = text.strip("_")
    return text


def build_story_id(title: str, theme: str, image_style: str) -> str:
    """Build a unique project directory name from title + active modifiers.

    Examples:
        "Three Billy Goats Gruff", "unmodified", "photo-realistic"
            → three_billy_goats_gruff
        "Three Billy Goats Gruff", "cyberpunk", "photo-realistic"
            → three_billy_goats_gruff_cyberpunk
        "Three Billy Goats Gruff", "cyberpunk", "anime, studio ghibli style"
            → three_billy_goats_gruff_cyberpunk_anime
    """
    parts = [slugify(title)]
    if theme and theme != "unmodified":
        # Theme values (e.g. "cyberpunk", "caribbean_village") are already clean
        parts.append(theme)
    if image_style and image_style != "photo-realistic":
        # Take the first segment before a comma, then slugify
        style_short = slugify(image_style.split(",")[0].strip())
        if style_short:
            parts.append(style_short)
    return "_".join(parts)


def _dimensions_for_mode(mode: ImageMode, base_width: int, base_height: int) -> tuple[int, int]:
    """Return (width, height) for the given image mode.

    Args:
        mode: Image generation mode
        base_width: Full-resolution width
        base_height: Full-resolution height

    Returns:
        (width, height) tuple for the target mode
    """
    if mode == ImageMode.PREVIEW:
        return base_width // 4, base_height // 4
    elif mode == ImageMode.DRAFT:
        return base_width // 2, base_height // 2
    else:  # FINAL
        return base_width, base_height


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Ebook Generation Pipeline.

    Generate themed, illustrated ebooks from story sources with AI-powered
    modifications, translations, and image generation.
    """
    pass


@cli.command()
@click.argument("title")
@click.option(
    "--theme",
    type=click.Choice([t.value for t in Theme]),
    default="unmodified",
    help="Story theme for modification",
)
@click.option(
    "--rating",
    type=click.Choice([r.value for r in ContentRating]),
    default="none",
    help="Target content rating",
)
@click.option(
    "--languages",
    multiple=True,
    default=("en",),
    help="Target languages (ISO 639-1 codes). Can be specified multiple times.",
)
@click.option(
    "--text-model",
    default="llama3.1:8b",
    help="Ollama model for text generation",
)
@click.option(
    "--prompt-model",
    default="brxce/stable-diffusion-prompt-generator",
    help="Ollama model for prompt generation",
)
@click.option(
    "--image-mode",
    type=click.Choice([m.value for m in ImageMode]),
    default="preview",
    help="Image generation tier: preview (fast/low-res), draft (medium), final (publication quality)",
)
@click.option(
    "--style",
    "image_style",
    type=click.Choice(IMAGE_STYLE_VALUES),
    default="photo-realistic",
    help="Visual style for all images",
)
@click.option(
    "--file",
    "source_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the source story file (.txt or .md).",
)
@click.option(
    "--audio-languages",
    multiple=True,
    default=(),
    help="Languages to generate audio narration for (ISO 639-1). Can be specified multiple times.",
)
def generate(title, theme, rating, languages, text_model, prompt_model, image_mode, image_style, source_file, audio_languages):
    """Generate an ebook from a local story file.

    Example:

        ebook-gen generate "Three Billy Goats Gruff" \\
            --file stories/three_billy_goats_gruff.md \\
            --theme cyberpunk \\
            --rating PG-13 \\
            --languages en --languages es \\
            --image-mode preview
    """
    project = get_project_config()
    project.ensure_directories()

    # Create story ID (slug) — encodes title + active modifiers
    story_id = build_story_id(title, theme, image_style)

    click.echo(f"Starting ebook generation for: {title}")
    click.echo(f"Story ID: {story_id}")
    click.echo(f"Theme: {theme}")
    click.echo(f"Rating: {rating}")
    click.echo(f"Languages: {', '.join(languages)}")
    click.echo(f"Image mode: {image_mode}")
    click.echo(f"Image style: {image_style}")
    if audio_languages:
        click.echo(f"Audio languages: {', '.join(audio_languages)}")

    # Create story config
    config = StoryConfig(
        story_id=story_id,
        title=title,
        source_file=source_file,
        source_language="en",
        theme=Theme(theme),
        content_rating=ContentRating(rating),
        target_languages=list(languages),
        ollama_text_model=text_model,
        ollama_prompt_model=prompt_model,
        image_mode=ImageMode(image_mode),
        image_style=image_style,
        audio_languages=list(audio_languages),
    )

    # Create project directory (subdirs are created by pipeline components as needed)
    story_dir = project.get_story_dir(story_id)
    story_dir.mkdir(parents=True, exist_ok=True)
    project.get_progress_dir(story_id).mkdir(parents=True, exist_ok=True)

    # Save metadata
    metadata_path = story_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(config.to_dict(), f, indent=2)

    click.echo(f"\nProject directory: {story_dir}")

    # Initialize progress tracker
    tracker = ProgressTracker(project.get_progress_dir(story_id))
    try:
        tracker.initialize()
        click.echo(f"Initialized pipeline state: {project.get_progress_dir(story_id) / 'pipeline_state.csv'}")
    except FileExistsError:
        click.echo(
            f"Pipeline state already exists. Use 'resume {story_id}' to continue."
        )
        return

    # Determine step range based on image mode
    # preview → steps 1-6 (no compilation, no audio)
    # draft   → steps 1-7 (with ebook compilation) + step 8 if audio requested
    # final   → steps 1-7 (with ebook compilation) + step 8 if audio requested
    end_step = 6 if image_mode == "preview" else 7

    # Run pipeline
    click.echo("\n▶️  Starting pipeline execution...")
    click.echo("   Step 1: Reading story file")
    click.echo("   Step 2: Applying theme modifications")
    click.echo("   Step 3: Assigning content rating")
    click.echo("   Step 4: Translating to target languages")
    click.echo("   Step 5: Generating image prompts")
    click.echo("   Step 6: Generating images")
    if image_mode != "preview":
        click.echo("   Step 7: Compiling ebook")
    if audio_languages and image_mode != "preview":
        click.echo("   Step 8: Generating audio narration")
    click.echo("")

    from .pipeline import PipelineRunner

    try:
        runner = PipelineRunner(config, project)
        runner.run(start_from_step=1, end_at_step=end_step)

        # Audio generation (step 8): draft and final modes with audio languages
        if audio_languages and image_mode != "preview":
            runner.run(start_from_step=8, end_at_step=8)

        images_dir_story = project.get_images_dir(story_id)
        click.echo("\n✅ Pipeline execution completed successfully!")
        click.echo(f"\n📄 Story file: {story_dir / 'story.md'}")
        click.echo(f"📊 Metadata: {story_dir / 'metadata.json'}")
        click.echo(f"🖼️  Image prompts: {project.get_prompts_dir(story_id) / 'prompts.csv'}")
        click.echo(f"🖼️  Images: {images_dir_story}/")
        if image_mode != "preview":
            click.echo(f"📚 Compiled: {project.get_compiled_dir(story_id)}/")
        if audio_languages and image_mode != "preview":
            click.echo(f"🔊 Audio: {project.get_audio_dir(story_id)}/")
        if image_mode == "preview":
            click.echo(f"\n💡 Next: Run 'ebook-gen preview-images {story_id}' to review images")
            click.echo(f"   Then: Run 'ebook-gen promote-images {story_id} --mode draft' for layout review")

        _write_obsidian_note(config, project, story_id)

    except Exception as e:
        click.echo(f"\n❌ Pipeline failed: {e}", err=True)
        click.echo(f"\n💡 Use 'ebook-gen resume {story_id}' to retry", err=True)
        sys.exit(1)


@cli.command()
@click.argument("story_id")
def resume(story_id):
    """Resume a previously interrupted pipeline run.

    Reads progress/<story_id>/pipeline_state.csv and resumes from the first
    non-completed step.
    """
    project = get_project_config()
    progress_dir = project.get_progress_dir(story_id)

    if not progress_dir.exists():
        click.echo(f"Error: No progress found for story '{story_id}'", err=True)
        click.echo(f"Expected directory: {progress_dir}", err=True)
        sys.exit(1)

    tracker = ProgressTracker(progress_dir)
    try:
        tracker.load()
    except FileNotFoundError:
        click.echo(
            f"Error: Pipeline state file not found in {progress_dir}", err=True
        )
        sys.exit(1)

    resume_step = tracker.get_resume_step()
    if resume_step is None:
        click.echo(f"✓ Pipeline for '{story_id}' is already complete!")
        return

    click.echo(f"▶️  Resuming pipeline for: {story_id}")
    click.echo(f"   Starting from step {resume_step}")

    # Load story config from metadata
    story_dir = project.get_story_dir(story_id)
    metadata_path = story_dir / "metadata.json"

    if not metadata_path.exists():
        click.echo(f"Error: Metadata not found: {metadata_path}", err=True)
        sys.exit(1)

    with open(metadata_path, "r") as f:
        config_dict = json.load(f)

    config = StoryConfig.from_dict(config_dict)

    # Run pipeline
    from .pipeline import PipelineRunner

    try:
        runner = PipelineRunner(config, project)
        runner.resume()

        click.echo("\n✅ Pipeline resumed successfully!")
        _write_obsidian_note(config, project, story_id)

    except Exception as e:
        click.echo(f"\n❌ Resume failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("story_id")
def status(story_id):
    """Show the current pipeline status for a story.

    Prints a table of all 7 steps with their status, timing, and any error
    messages.
    """
    project = get_project_config()
    progress_dir = project.get_progress_dir(story_id)

    if not progress_dir.exists():
        click.echo(f"Error: No progress found for story '{story_id}'", err=True)
        sys.exit(1)

    tracker = ProgressTracker(progress_dir)
    try:
        steps = tracker.load()
    except FileNotFoundError:
        click.echo(
            f"Error: Pipeline state file not found in {progress_dir}", err=True
        )
        sys.exit(1)

    click.echo(f"\nPipeline Status: {story_id}")
    click.echo("=" * 80)

    for step in steps:
        status_icon = {
            "pending": "⏸",
            "in_progress": "▶",
            "completed": "✓",
            "failed": "✗",
            "skipped": "⊘",
        }.get(step.status.value, "?")

        click.echo(
            f"\n{status_icon} Step {step.step}: {step.name} [{step.status.value.upper()}]"
        )

        if step.started_at:
            click.echo(f"   Started: {step.started_at.isoformat()}")
        if step.completed_at:
            click.echo(f"   Completed: {step.completed_at.isoformat()}")
        if step.attempts > 0:
            click.echo(f"   Attempts: {step.attempts}")
        if step.error_message:
            click.echo(f"   Error: {step.error_message}")
        if step.output_artifact:
            click.echo(f"   Output: {step.output_artifact}")

    click.echo("\n" + "=" * 80)

    # Summary
    completed = sum(1 for s in steps if s.status.value == "completed")
    failed = sum(1 for s in steps if s.status.value == "failed")
    click.echo(f"Progress: {completed}/{len(steps)} steps completed, {failed} failed")


@cli.command()
@click.argument("story_id")
@click.option("--step", type=int, help="Retry a specific failed step (1-8)")
def retry(story_id, step):
    """Retry failed steps for a story.

    Without --step: retries all failed steps in order.
    With --step N: retries only step N.
    """
    project = get_project_config()
    progress_dir = project.get_progress_dir(story_id)

    if not progress_dir.exists():
        click.echo(f"Error: No progress found for story '{story_id}'", err=True)
        sys.exit(1)

    tracker = ProgressTracker(progress_dir)
    try:
        tracker.load()
    except FileNotFoundError:
        click.echo(
            f"Error: Pipeline state file not found in {progress_dir}", err=True
        )
        sys.exit(1)

    # Load story config from metadata
    story_dir = project.get_story_dir(story_id)
    metadata_path = story_dir / "metadata.json"

    if not metadata_path.exists():
        click.echo(f"Error: Metadata not found: {metadata_path}", err=True)
        sys.exit(1)

    with open(metadata_path, "r") as f:
        config_dict = json.load(f)

    config = StoryConfig.from_dict(config_dict)

    if step:
        # Retry specific step
        step_obj = tracker.get_step(step)
        if step_obj.status.value != "failed":
            click.echo(
                f"Warning: Step {step} is not in failed state "
                f"(current: {step_obj.status.value})"
            )
            click.echo("Proceeding anyway...")

        click.echo(f"Retrying step {step}: {step_obj.name}")
        tracker.reset_step(step)
    else:
        # Retry all failed steps
        failed_steps = tracker.get_failed_steps()
        if not failed_steps:
            click.echo("No failed steps to retry.")
            return

        click.echo(f"Found {len(failed_steps)} failed step(s): {failed_steps}")
        for step_num in failed_steps:
            tracker.reset_step(step_num)

    from .pipeline import PipelineRunner

    try:
        runner = PipelineRunner(config, project)
        runner.resume()
        click.echo("\n✅ Retry completed successfully!")
        _write_obsidian_note(config, project, story_id)
    except Exception as e:
        click.echo(f"\n❌ Retry failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("story_id")
def preview_images(story_id):
    """Show a summary of generated images for a story.

    Lists all images with their status, dimensions, and file paths. Useful for
    reviewing images before promoting to the next quality tier.
    """
    project = get_project_config()
    prompts_dir = project.get_prompts_dir(story_id)
    prompts_csv = prompts_dir / "prompts.csv"

    if not prompts_csv.exists():
        click.echo(f"Error: No prompts found for story '{story_id}'", err=True)
        click.echo(f"Expected file: {prompts_csv}", err=True)
        sys.exit(1)

    from .utils.csv_io import read_image_records

    records = read_image_records(prompts_csv)

    click.echo(f"\nImage Generation Status: {story_id}")
    click.echo("=" * 80)

    for record in records:
        status_icon = {
            "pending": "⏸",
            "in_progress": "▶",
            "completed": "✓",
            "failed": "✗",
            "skipped": "⊘",
        }.get(record.status.value, "?")

        click.echo(
            f"\n{status_icon} {record.name} [{record.status.value.upper()}] "
            f"({record.width}x{record.height})"
        )
        click.echo(f"   File: {record.target_filename}")
        click.echo(f"   Description: {record.description}")
        if record.status.value == "completed":
            image_path = project.get_images_dir(story_id) / record.target_filename
            click.echo(f"   Path: {image_path}")

    click.echo("\n" + "=" * 80)
    completed = sum(1 for r in records if r.status.value == "completed")
    failed = sum(1 for r in records if r.status.value == "failed")
    click.echo(f"Total: {len(records)} images ({completed} completed, {failed} failed)")


@cli.command()
@click.argument("story_id")
@click.option(
    "--mode",
    type=click.Choice(["draft", "final"]),
    default="draft",
    help="Target quality tier: draft (medium-res, layout review) or final (full-res, publication)",
)
def promote_images(story_id, mode):
    """Promote images to the next quality tier.

    Resets image statuses to 'pending', updates dimensions and model for the
    target mode, then runs image generation.

    Three-tier workflow:
      1. Generate with --image-mode preview to test prompts quickly.
      2. Run: promote-images <story> --mode draft  (layout review)
      3. Run: promote-images <story> --mode final  (publication quality)
    """
    project = get_project_config()
    story_dir = project.get_story_dir(story_id)
    metadata_path = story_dir / "metadata.json"

    if not metadata_path.exists():
        click.echo(f"Error: Metadata not found for story '{story_id}'", err=True)
        sys.exit(1)

    # Load and update config
    with open(metadata_path, "r") as f:
        config_dict = json.load(f)

    config = StoryConfig.from_dict(config_dict)
    target_mode = ImageMode(mode)

    if config.image_mode == target_mode:
        click.echo(f"Images are already in '{mode}' mode.")
        click.confirm("Regenerate anyway?", abort=True)

    # Update mode in config
    config.image_mode = target_mode

    with open(metadata_path, "w") as f:
        json.dump(config.to_dict(), f, indent=2)

    click.echo(f"Updated image mode to: {mode}")

    # Reset all image records to pending with new mode dimensions/model
    prompts_csv = project.get_prompts_dir(story_id) / "prompts.csv"
    if not prompts_csv.exists():
        click.echo(f"Error: No prompts found for story '{story_id}'", err=True)
        sys.exit(1)

    from .utils.csv_io import read_image_records, write_image_records

    records = read_image_records(prompts_csv)

    # Select model for the target mode
    if target_mode == ImageMode.DRAFT:
        new_model = config.ollama_image_model_draft
    else:  # FINAL
        new_model = config.ollama_image_model_final

    for record in records:
        record.status = ImageStatus.PENDING
        record.model = new_model
        # Recalculate dimensions for target mode
        # Cover uses square 1024x1024 base; scene images use 1024x768 base
        if record.name == "cover":
            base_w, base_h = 1024, 1024
        else:
            base_w, base_h = 1024, 768
        record.width, record.height = _dimensions_for_mode(target_mode, base_w, base_h)

    write_image_records(prompts_csv, records)
    click.echo(f"Reset {len(records)} image(s) to pending with {mode} dimensions")

    # Run image generation
    click.echo(f"\n▶️  Running image generation in {mode} mode...")

    from .pipeline import PipelineRunner

    try:
        runner = PipelineRunner(config, project)
        runner.run(start_from_step=6, end_at_step=6)
        click.echo("\n✅ Image generation completed!")
        click.echo(f"📂 Images saved to: {project.get_images_dir(story_id)}/")
        if mode == "draft":
            click.echo(f"\n💡 Next: Run 'ebook-gen promote-images {story_id} --mode final' for publication quality")
    except Exception as e:
        click.echo(f"\n❌ Image generation failed: {e}", err=True)
        click.echo(f"\n💡 Use 'ebook-gen retry {story_id} --step 6' to retry", err=True)
        sys.exit(1)


def _write_obsidian_note(config: StoryConfig, project: ProjectConfig, story_id: str) -> None:
    """Write an Obsidian note for the story; silently skip on any error."""
    from .utils.obsidian import write_story_note

    try:
        note_path = write_story_note(
            config=config,
            progress_dir=project.get_progress_dir(story_id),
            compiled_dir=project.get_compiled_dir(story_id),
            images_dir=project.get_images_dir(story_id),
            audio_dir=project.get_audio_dir(story_id) if config.audio_languages else None,
        )
        if note_path:
            click.echo(f"📝 Obsidian note: {note_path}")
    except Exception as e:
        click.echo(f"⚠️  Could not write Obsidian note: {e}", err=True)


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
