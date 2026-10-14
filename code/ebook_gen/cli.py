"""Command-line interface for ebook generation."""

import hashlib
import json
import os
import sys
from pathlib import Path

import click

from .config import (
    DEFAULT_IMAGE_MODEL_DRAFT,
    DEFAULT_IMAGE_MODEL_FINAL,
    DEFAULT_IMAGE_MODEL_PREVIEW,
    DEFAULT_TEXT_MODEL,
    ProjectConfig,
)
from .models import (
    AUDIO_LANGUAGE_LABELS,
    IMAGE_STYLE_VALUES,
    IMAGE_STYLES,
    PIPELINE_STAGES,
    PIPELINE_STEPS,
    TEXT_LANGUAGE_OPTIONS,
    ContentRating,
    ImageMode,
    ImageStatus,
    StoryConfig,
)
from .progress import ProgressTracker
from .themes import check_combination, get_themes, get_tropes


def get_project_config() -> ProjectConfig:
    """Get the project configuration from current directory."""
    # Containers run from /workspace (the project root); a shell in code/ uses its parent
    current = Path.cwd()

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


def direction_hash(direction: str) -> str:
    """Short, stable hash of a --direction text (whitespace-insensitive), or "" for none."""
    normalized = " ".join(direction.split())
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode()).hexdigest()[:8]


def build_story_id(
    title: str, theme: str, image_style: str, tropes: list[str] = (), direction: str = ""
) -> str:
    """Build a unique project directory name from title + active modifiers.

    Examples:
        "Three Billy Goats Gruff", "unmodified", "photo-realistic"
            → three_billy_goats_gruff
        "Three Billy Goats Gruff", "cyberpunk", "photo-realistic"
            → three_billy_goats_gruff_cyberpunk
        "Three Billy Goats Gruff", "cyberpunk", "anime, studio ghibli style"
            → three_billy_goats_gruff_cyberpunk_anime
        "Little Red Riding Hood", "monster_romance", "photo-realistic", ["enemies_to_lovers"]
            → little_red_riding_hood_monster_romance_enemies_to_lovers
        "Three Billy Goats Gruff", "cyberpunk", "photo-realistic", [], "The troll is the hero."
            → three_billy_goats_gruff_cyberpunk_dir<8 hex chars>
    """
    parts = [slugify(title)]
    if theme and theme != "unmodified":
        # Theme values (e.g. "cyberpunk", "caribbean_village") are already clean
        parts.append(theme)
    # Trope keys are clean too
    parts.extend(tropes)
    if image_style and image_style != "photo-realistic":
        # Take the first segment before a comma, then slugify
        style_short = slugify(image_style.split(",")[0].strip())
        if style_short:
            parts.append(style_short)
    if digest := direction_hash(direction):
        parts.append(f"dir{digest}")
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


@click.group(context_settings={"help_option_names": ["-h", "--help"], "show_default": True})
@click.version_option(version="0.1.0")
def cli():
    """Ebook Generation Pipeline.

    Generate themed, illustrated ebooks from story sources with AI-powered
    modifications, translations, and image generation.

    Run 'ebook-gen help COMMAND' for a command's options and 'ebook-gen help
    PARAM' for the values a parameter takes (theme, trope, rating, style, ...).
    """
    pass


@cli.command()
@click.argument("title")
@click.option(
    "--theme",
    type=click.Choice(list(get_themes())),
    default="unmodified",
    metavar="THEME",
    help="Story theme from themes.toml. List them: 'ebook-gen help theme'",
)
@click.option(
    "--trope",
    "tropes",
    multiple=True,
    type=click.Choice(list(get_tropes())),
    metavar="TROPE",
    help="Romance trope; repeat for more. Needs a theme; adds the adult rules. "
    "List them: 'ebook-gen help trope'",
)
@click.option(
    "--direction",
    default="",
    metavar="TEXT",
    help="How the rewrite should change the plot, e.g. \"the troll is the hero\". "
    "Steers step 2 without editing the source file; may override the original "
    "arc, ending and moral. Needs a theme",
)
@click.option(
    "--rating",
    type=click.Choice([r.value for r in ContentRating]),
    default="none",
    help="Target content rating. 'none' lets step 3 pick one",
)
@click.option(
    "--languages",
    multiple=True,
    default=("en",),
    metavar="CODE",
    help="Translation target (ISO 639-1 code); repeat for more, e.g. "
    "--languages en --languages es",
)
@click.option(
    "--text-model",
    default=DEFAULT_TEXT_MODEL,
    help="Text model: a Hugging Face MLX repo id (or an Ollama tag with EBOOK_GEN_BACKEND=ollama)",
)
@click.option(
    "--prompt-model",
    default=None,
    help="Model that writes image prompts (default: same as --text-model)",
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
    metavar="STYLE",
    help="Visual style for all images; quote values with spaces. "
    "List them: 'ebook-gen help style'",
)
@click.option(
    "--file",
    "source_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Source story (.txt or .md). Any host path; files outside the repo are "
    "mounted read-only",
)
@click.option(
    "--audio-languages",
    multiple=True,
    default=(),
    metavar="CODE",
    help="Narrate in this language (draft and final modes); repeat for more. "
    "List them: 'ebook-gen help audio-languages'",
)
def generate(title, theme, tropes, direction, rating, languages, text_model, prompt_model, image_mode, image_style, source_file, audio_languages):
    """Generate an ebook from a local story file.

    TITLE is the story's title; with the theme, tropes and style it makes the
    story ID used by the other commands.

    Examples:

    \b
        ebook-gen generate "Three Billy Goats Gruff" \\
            --file stories/three_billy_goats_gruff.txt \\
            --theme cyberpunk --rating PG-13 \\
            --languages en --languages es

    \b
        ebook-gen generate "Little Red Riding Hood" \\
            --file stories/little_red_riding_hood.txt \\
            --theme monster_romance --trope enemies_to_lovers --rating R \\
            --style "oil painting, painterly"
    """
    try:
        check_combination(theme, list(tropes), direction)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    project = get_project_config()
    project.ensure_directories()

    # Create story ID (slug) — encodes title + active modifiers
    story_id = build_story_id(title, theme, image_style, list(tropes), direction)

    click.echo(f"Starting ebook generation for: {title}")
    click.echo(f"Story ID: {story_id}")
    click.echo(f"Theme: {theme}")
    if tropes:
        click.echo(f"Tropes: {', '.join(tropes)}")
    if direction:
        click.echo(f"Direction: {direction}")
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
        theme=theme,
        tropes=list(tropes),
        direction=direction,
        content_rating=ContentRating(rating),
        target_languages=list(languages),
        text_model=text_model,
        prompt_model=prompt_model or text_model,
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

    # Tell the ./ebook-gen wrapper which story the later stage containers resume
    story_id_file = os.getenv("EBOOK_GEN_STORY_ID_FILE")
    if story_id_file:
        Path(story_id_file).write_text(story_id)

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
        # preview → steps 1-6; draft/final → 1-7, plus step 8 if audio requested
        runner = PipelineRunner(config, project)
        runner.run(start_from_step=1, end_at_step=runner.planned_end_step())
        if not _report_finished(runner):
            return

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

    # Load story config from metadata
    story_dir = project.get_story_dir(story_id)
    metadata_path = story_dir / "metadata.json"

    if not metadata_path.exists():
        click.echo(f"Error: Metadata not found: {metadata_path}", err=True)
        sys.exit(1)

    with open(metadata_path, "r") as f:
        config_dict = json.load(f)

    config = StoryConfig.from_dict(config_dict)

    from .models import PIPELINE_STAGES
    from .pipeline import PipelineRunner, current_stage

    runner = PipelineRunner(config, project)
    resume_step = tracker.get_resume_step()
    if resume_step is None or resume_step > runner.planned_end_step():
        click.echo(f"✓ Pipeline for '{story_id}' is already complete!")
        return

    # A later stage's container picks the story up from here
    stage = current_stage()
    if stage and resume_step > max(PIPELINE_STAGES[stage]):
        return

    click.echo(f"▶️  Resuming pipeline for: {story_id}")
    click.echo(f"   Starting from step {resume_step}")

    try:
        runner.resume()

        if _report_finished(runner):
            click.echo("\n✅ Pipeline resumed successfully!")
            _write_obsidian_note(config, project, story_id)

    except Exception as e:
        click.echo(f"\n❌ Resume failed: {e}", err=True)
        sys.exit(1)


@cli.command(hidden=True)
@click.argument("story_id")
def stages(story_id):
    """Print the pipeline stages with steps left to run, one per line.

    The ./ebook-gen wrapper uses this to start only the containers a story
    still needs (a preview run never reaches compile or audio).
    """
    from .models import PIPELINE_STAGES
    from .pipeline import PipelineRunner

    project = get_project_config()
    with open(project.get_story_dir(story_id) / "metadata.json") as f:
        config = StoryConfig.from_dict(json.load(f))

    runner = PipelineRunner(config, project)
    tracker = ProgressTracker(project.get_progress_dir(story_id))
    tracker.load()
    for stage, steps in PIPELINE_STAGES.items():
        if any(
            step <= runner.planned_end_step() and not tracker.is_step_completed(step)
            for step in steps
        ):
            click.echo(stage)


@cli.command()
def themes():
    """List the story themes and romance tropes defined in themes.toml."""
    _echo_values("theme")
    click.echo()
    _echo_values("trope")


# ── help ────────────────────────────────────────────────────────────────────

# Descriptions for positional arguments (click options carry their own help)
_ARGUMENT_HELP = {
    "title": "Story title; with the theme, tropes and style it makes the story ID",
    "story_id": "Story ID that generate printed (a directory under projects/)",
    "topic": "A command, a parameter, or 'params'",
}

# Plural or alternative names people type for parameters
_PARAM_ALIASES = {
    "themes": "theme",
    "tropes": "trope",
    "ratings": "rating",
    "styles": "style",
    "steps": "step",
    "modes": "mode",
    "language": "languages",
    "audio-language": "audio-languages",
    "model": "text-model",
}


def _theme_values():
    rows = []
    for key, theme in get_themes().items():
        adult = " [adult]" if theme.adult else ""
        rows.append((key, f"{theme.name}{adult}: {theme.description}"))
    return rows


def _trope_values():
    return [(key, f"{t.name}: {t.description}") for key, t in get_tropes().items()]


def _rating_values():
    return [
        ("none", "No target: step 3 rates the story and keeps its recommendation. "
                 "Always used for unmodified"),
        ("G", "General audiences"),
        ("PG", "Parental guidance suggested"),
        ("PG-13", "Some material unsuitable under 13"),
        ("R", "Restricted: under 17 needs a parent or guardian"),
        ("NC-17", "Adults only"),
    ]


def _image_mode_values():
    return [
        ("preview", f"256x192 scenes, {DEFAULT_IMAGE_MODEL_PREVIEW}. Seconds per image, "
                    "for checking prompts; no ebook or audio"),
        ("draft", f"512x384 scenes, {DEFAULT_IMAGE_MODEL_DRAFT}. Compiles a draft ebook "
                  "(and audio) for layout review"),
        ("final", f"1024x768 scenes, {DEFAULT_IMAGE_MODEL_FINAL} (FLUX non-commercial "
                  "license). Compiles the publication ebook"),
    ]


def _mode_values():
    return [row for row in _image_mode_values() if row[0] != "preview"]


def _style_values():
    return [(f'"{value}"' if " " in value else value, label) for label, value in IMAGE_STYLES]


def _language_values():
    return [(code, label) for label, code in TEXT_LANGUAGE_OPTIONS]


def _audio_language_values():
    return list(AUDIO_LANGUAGE_LABELS.items())


def _step_values():
    stage_of = {step: stage for stage, steps in PIPELINE_STAGES.items() for step in steps}
    return [(str(num), f"{name} ({stage_of.get(num, '?')} container)") for num, name in PIPELINE_STEPS]


def _model_values():
    return [(DEFAULT_TEXT_MODEL, "Default. Any Hugging Face MLX repo id works, or an "
                                 "Ollama tag with EBOOK_GEN_BACKEND=ollama")]


# Parameters whose values `help PARAM` lists: (heading, values, note)
_PARAM_VALUES = {
    "theme": ("Themes (--theme), from themes.toml", _theme_values,
              "Adult themes and any --trope add the adult rules: every character in a "
              "romantic or sexual scene is an adult, and child characters are aged up."),
    "trope": ("Romance tropes (--trope, repeat for more; needs a theme)", _trope_values,
              "Tropes always add the adult rules."),
    "rating": ("Content ratings (--rating)", _rating_values,
               "With a target, step 3 keeps it even if the model recommends another, "
               "and notes the recommendation."),
    "image-mode": ("Image modes (generate --image-mode)", _image_mode_values,
                   "Move a story up a tier later with promote-images."),
    "mode": ("Promotion targets (promote-images --mode)", _mode_values, None),
    "style": ("Image styles (--style)", _style_values, "Quote values that contain spaces."),
    "languages": ("Translation languages (--languages, repeat for more)", _language_values,
                  "Common choices; any ISO 639-1 code works, since the text model translates."),
    "audio-languages": ("Narration languages (--audio-languages, repeat for more)",
                        _audio_language_values,
                        "Kokoro TTS voices; narration runs in draft and final modes only."),
    "step": ("Pipeline steps (retry --step)", _step_values, None),
    "text-model": ("Text models (--text-model, --prompt-model)", _model_values, None),
    "prompt-model": ("Text models (--text-model, --prompt-model)", _model_values, None),
}


def _echo_values(name: str) -> None:
    heading, values, note = _PARAM_VALUES[name]
    rows = values()
    width = max(len(value) for value, _ in rows) + 2
    click.echo(f"{heading}:")
    for value, description in rows:
        click.echo(f"  {value:<{width}}{description}")
    if note:
        click.echo()
        click.echo(note)


def _param_name(param: click.Parameter) -> str:
    if isinstance(param, click.Option):
        return max(param.opts, key=len).lstrip("-")
    return param.name


def _params_by_name() -> dict[str, tuple[click.Parameter, list[str]]]:
    """Every visible parameter of every visible command, and the commands taking it."""
    found: dict[str, tuple[click.Parameter, list[str]]] = {}
    for cmd_name, cmd in cli.commands.items():
        if cmd.hidden or cmd_name == "help":
            continue
        for param in cmd.params:
            if getattr(param, "hidden", False) or param.name == "help":
                continue
            name = _param_name(param)
            found.setdefault(name, (param, []))[1].append(cmd_name)
    return found


def _echo_params() -> None:
    click.echo("Parameters ('ebook-gen help PARAM' lists the values of those marked *):\n")
    for name, (param, commands) in sorted(_params_by_name().items()):
        if isinstance(param, click.Option):
            label = f"--{name}"
            description = param.help or ""
        else:
            label = name.upper()
            description = _ARGUMENT_HELP.get(name, "")
        if name in _PARAM_VALUES:
            label += " *"
        click.echo(f"  {label:<22}({', '.join(commands)})")
        if description:
            click.echo(f"      {description}")


@cli.command("help", context_settings={"ignore_unknown_options": True})
@click.argument("topic", required=False)
@click.pass_context
def help_command(ctx, topic):
    """Show help for a command, or the values a parameter takes.

    \b
      ebook-gen help              list the commands
      ebook-gen help COMMAND      a command's arguments and options
      ebook-gen help PARAM        the values a parameter takes, e.g. theme
      ebook-gen help params       every parameter and the commands that take it
    """
    if topic is None:
        click.echo(ctx.parent.get_help())
        return
    name = topic.lstrip("-").replace("_", "-").lower()
    name = _PARAM_ALIASES.get(name, name)
    if name in ("params", "parameters", "options"):
        _echo_params()
    elif name in _PARAM_VALUES:
        _echo_values(name)
    elif name in cli.commands and not cli.commands[name].hidden:
        cmd = cli.commands[name]
        click.echo(cmd.get_help(click.Context(cmd, info_name=name, parent=ctx.parent)))
    else:
        raise click.UsageError(
            f"No help for '{topic}'. Try a command "
            f"({', '.join(sorted(n for n, c in cli.commands.items() if not c.hidden))}), "
            f"a parameter ({', '.join(_PARAM_VALUES)}), or 'params'."
        )


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
@click.option(
    "--step",
    type=click.IntRange(1, len(PIPELINE_STEPS)),
    help="Retry only this step. List them: 'ebook-gen help step'",
)
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
        if _report_finished(runner):
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
@click.option("--yes", "-y", is_flag=True, help="Regenerate without asking if already in this mode")
def promote_images(story_id, mode, yes):
    """Promote images to the next quality tier.

    Resets image statuses to 'pending', updates dimensions and model for the
    target mode, then runs image generation.

    Three-tier workflow:

    \b
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
        if not yes:
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
        new_model = config.image_model_draft
    else:  # FINAL
        new_model = config.image_model_final

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

    # Regenerate the images, and rebuild the books made from the old ones;
    # otherwise the completed step 6 is skipped and the records stay pending.
    tracker = ProgressTracker(project.get_progress_dir(story_id))
    tracker.load()
    tracker.reset_step(6)
    tracker.reset_step(7)

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


def _report_finished(runner) -> bool:
    """True if the story's pipeline is done; otherwise note this stage is done.

    In a pipeline container only one stage runs, and the ./ebook-gen wrapper
    starts the next stage's container afterwards.
    """
    if runner.is_finished():
        return True
    stage = os.getenv("EBOOK_GEN_STAGE")
    if stage:
        click.echo(f"\n✓ '{stage}' stage done")
    return False


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
    cli(prog_name="ebook-gen")


if __name__ == "__main__":
    main()
