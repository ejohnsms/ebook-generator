"""Textual TUI for interactive ebook generation pipeline testing."""

import json
import logging
from datetime import datetime
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.timer import Timer
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    SelectionList,
    Static,
)

from .cli import build_story_id, get_project_config, slugify
from .components.audio_generator import KOKORO_LANG_MAP
from .config import BackendConfig
from .models import (
    AUDIO_LANGUAGE_LABELS,
    IMAGE_STYLES,
    PIPELINE_STEPS,
    TEXT_LANGUAGE_OPTIONS,
    ContentRating,
    ImageMode,
    PipelineStep,
    StepStatus,
    StoryConfig,
)
from .progress import ProgressTracker
from .themes import check_combination, get_themes, get_tropes



THEME_OPTIONS = [(t.name, key) for key, t in get_themes().items()]
MODE_OPTIONS = [(m.value, m.value) for m in ImageMode]
STYLE_OPTIONS = [(label, val) for label, val in IMAGE_STYLES]

AUDIO_LANGUAGE_OPTIONS = [
    (AUDIO_LANGUAGE_LABELS.get(code, code), code)
    for code in KOKORO_LANG_MAP
]


class LogMessage(Message):
    """Thread-safe log message delivery from worker to UI."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class TuiLogHandler(logging.Handler):
    """Logging handler that forwards records to the TUI log panel."""

    def __init__(self, app: "EbookGeneratorApp") -> None:
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        text = self.format(record)
        try:
            self.app.call_from_thread(self.app.post_message, LogMessage(text))
        except Exception:
            pass  # Don't let logging errors crash the worker


class StepRow(Static):
    """Displays one pipeline step: icon + number + name + elapsed time."""

    ICONS = {
        StepStatus.PENDING: "⏸",
        StepStatus.IN_PROGRESS: "▶",
        StepStatus.COMPLETED: "✓",
        StepStatus.FAILED: "✗",
        StepStatus.SKIPPED: "⊘",
    }

    STATUS_COLORS = {
        StepStatus.PENDING: "grey50",
        StepStatus.IN_PROGRESS: "yellow",
        StepStatus.COMPLETED: "green",
        StepStatus.FAILED: "red",
        StepStatus.SKIPPED: "grey50",
    }

    def __init__(self, step_num: int, step_name: str, **kwargs) -> None:
        initial = f"[grey50]⏸ Step {step_num}  {step_name:<25}[/]"
        super().__init__(initial, **kwargs)
        self._step_num = step_num
        self._step_name = step_name

    def update_step(self, step: PipelineStep) -> None:
        """Refresh this row from a PipelineStep record."""
        icon = self.ICONS.get(step.status, "?")
        color = self.STATUS_COLORS.get(step.status, "white")

        elapsed = ""
        if step.started_at:
            end = step.completed_at or datetime.utcnow()
            delta = end - step.started_at
            total = int(delta.total_seconds())
            mm, ss = divmod(total, 60)
            suffix = "..." if step.status == StepStatus.IN_PROGRESS else ""
            elapsed = f"  {mm:02d}:{ss:02d}{suffix}"

        content = f"[{color}]{icon} Step {step.step}  {step.name:<25}{elapsed}[/]"
        self.update(content)

    def reset(self) -> None:
        """Reset to pending display."""
        self.update(f"[grey50]⏸ Step {self._step_num}  {self._step_name:<25}[/]")


class EbookGeneratorApp(App):
    """Textual TUI for interactive ebook generation."""

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }

    #config-panel {
        height: auto;
        border: heavy $accent;
        margin: 1 1 0 1;
        padding: 1 2;
    }

    #config-panel Label.panel-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .field-row {
        layout: horizontal;
        height: 3;
        margin-bottom: 0;
        align: left middle;
    }

    .field-label {
        width: 16;
        height: 3;
        content-align: right middle;
        padding-right: 1;
        color: $text-muted;
    }

    #file-input, #title-input {
        width: 1fr;
    }

    #generate-btn {
        margin-top: 1;
        margin-left: 16;
    }

    #progress-panel {
        height: auto;
        border: heavy $accent;
        margin: 1 1 0 1;
        padding: 1 2;
    }

    #progress-panel Label.panel-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .step-row {
        height: 1;
    }

    #log-panel {
        height: 1fr;
        border: heavy $accent;
        margin: 1 1 1 1;
        padding: 0;
    }

    #log-panel Label.panel-title {
        text-style: bold;
        padding: 0 1;
    }

    #log {
        height: 1fr;
    }

    Select {
        width: 24;
        margin-right: 2;
    }

    #style-select, #theme-select {
        width: 36;
    }

    .selection-row {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
        align: left top;
    }

    .selection-label {
        width: 16;
        content-align: right top;
        padding-right: 1;
        color: $text-muted;
        padding-top: 1;
    }

    .lang-list {
        width: 1fr;
        height: 5;
        margin-right: 2;
    }

    .audio-list {
        width: 1fr;
        height: 5;
    }

    .trope-list {
        width: 1fr;
        height: 5;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self._poll_timer: Timer | None = None
        self._story_id: str | None = None
        self._project = None
        self._config: StoryConfig | None = None
        self._pipeline_succeeded: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="config-panel"):
            yield Label("Configuration", classes="panel-title")
            with Horizontal(classes="field-row"):
                yield Label("Story File:", classes="field-label")
                yield Input(
                    placeholder="/path/to/story.md  or  story.txt",
                    id="file-input",
                )
            with Horizontal(classes="field-row"):
                yield Label("Title:", classes="field-label")
                yield Input(
                    placeholder="Story title (auto-filled from filename)",
                    id="title-input",
                )
            with Horizontal(classes="field-row"):
                yield Label("Direction:", classes="field-label")
                yield Input(
                    placeholder="Optional plot changes for the rewrite, e.g. the troll is the hero",
                    id="direction-input",
                )
            with Horizontal(classes="field-row"):
                yield Label("Theme:", classes="field-label")
                yield Select(THEME_OPTIONS, value="unmodified", id="theme-select")
                yield Label("Mode:", classes="field-label")
                yield Select(MODE_OPTIONS, value="preview", id="mode-select")
            with Horizontal(classes="field-row"):
                yield Label("Style:", classes="field-label")
                yield Select(STYLE_OPTIONS, value="photo-realistic", id="style-select")
            with Horizontal(classes="selection-row"):
                yield Label("Languages:", classes="selection-label")
                yield SelectionList(
                    *[(label, val, val == "en") for label, val in TEXT_LANGUAGE_OPTIONS],
                    id="languages-list",
                    classes="lang-list",
                )
                yield Label("Audio langs:", classes="selection-label")
                yield SelectionList(
                    *[(label, val) for label, val in AUDIO_LANGUAGE_OPTIONS],
                    id="audio-list",
                    classes="audio-list",
                )
            with Horizontal(classes="selection-row"):
                yield Label("Tropes:", classes="selection-label")
                yield SelectionList(
                    *[(t.name, key) for key, t in get_tropes().items()],
                    id="trope-list",
                    classes="trope-list",
                )
            yield Button("Generate", id="generate-btn", variant="success")

        with Vertical(id="progress-panel"):
            yield Label("Pipeline Progress", classes="panel-title")
            for num, name in PIPELINE_STEPS:
                yield StepRow(num, name, id=f"step-{num}", classes="step-row")

        with Vertical(id="log-panel"):
            yield Label("Log", classes="panel-title")
            yield RichLog(id="log", markup=True, highlight=True, wrap=True)

        yield Footer()

    @on(Input.Changed, "#file-input")
    def on_file_changed(self, event: Input.Changed) -> None:
        """Auto-fill title from the filename when a file path is entered."""
        path = event.value.strip()
        if path:
            stem = Path(path).expanduser().stem
            title = stem.replace("_", " ").replace("-", " ").title()
            self.query_one("#title-input", Input).value = title

    @on(Button.Pressed, "#generate-btn")
    def on_generate(self) -> None:
        file_path = self.query_one("#file-input", Input).value.strip()
        title = self.query_one("#title-input", Input).value.strip()

        if not file_path:
            self._log("[red][ERROR] Please enter a story file path[/]")
            return
        if not title:
            self._log("[red][ERROR] Please enter a story title[/]")
            return

        source_file = Path(file_path).expanduser().resolve()
        if not source_file.exists():
            self._log(f"[red][ERROR] File not found: {source_file}[/]")
            return
        if source_file.suffix.lower() not in {".txt", ".md"}:
            self._log("[red][ERROR] File must be a .txt or .md file[/]")
            return

        try:
            self._start_pipeline(source_file, title)
        except Exception as e:
            self._log(f"[red][ERROR] {e}[/]")

    def _start_pipeline(self, source_file: Path, title: str) -> None:
        """Validate settings, initialise project state, and kick off the pipeline."""
        theme_select = self.query_one("#theme-select", Select)
        mode_select = self.query_one("#mode-select", Select)
        style_select = self.query_one("#style-select", Select)

        if theme_select.value is Select.BLANK or mode_select.value is Select.BLANK:
            self._log("[red][ERROR] Please select a theme and image mode[/]")
            return

        theme_val = str(theme_select.value)
        mode_val = str(mode_select.value)
        style_val = str(style_select.value) if style_select.value is not Select.BLANK else "photo-realistic"

        languages = list(self.query_one("#languages-list", SelectionList).selected) or ["en"]
        audio_langs = list(self.query_one("#audio-list", SelectionList).selected)
        tropes = list(self.query_one("#trope-list", SelectionList).selected)
        direction = self.query_one("#direction-input", Input).value.strip()
        try:
            check_combination(theme_val, tropes, direction)
        except ValueError as e:
            self._log(f"[red][ERROR] {e}[/]")
            return
        story_id = build_story_id(title, theme_val, style_val, tropes, direction)
        self._story_id = story_id

        project = get_project_config()
        project.ensure_directories()
        self._project = project
        self._pipeline_succeeded = False

        config = StoryConfig(
            story_id=story_id,
            title=title,
            source_file=str(source_file),
            source_language="en",
            theme=theme_val,
            tropes=tropes,
            direction=direction,
            content_rating=ContentRating.NONE,
            target_languages=languages,
            image_mode=ImageMode(mode_val),
            image_style=style_val,
            audio_languages=audio_langs,
        )

        # Create project directory (subdirs are created by pipeline components as needed)
        story_dir = project.get_story_dir(story_id)
        story_dir.mkdir(parents=True, exist_ok=True)
        project.get_progress_dir(story_id).mkdir(parents=True, exist_ok=True)

        # Save metadata
        metadata_path = story_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(config.to_dict(), f, indent=2)

        # Initialize progress tracker — raises FileExistsError if already exists
        tracker = ProgressTracker(project.get_progress_dir(story_id))
        try:
            tracker.initialize()
        except FileExistsError:
            self._log(
                f"[red][ERROR] Pipeline state already exists for '{story_id}'. "
                f"Delete projects/{story_id}/progress/ to start fresh.[/]"
            )
            return

        # Reset step display
        for num, _ in PIPELINE_STEPS:
            self.query_one(f"#step-{num}", StepRow).reset()

        # Disable button while running
        self.query_one("#generate-btn", Button).disabled = True

        self._config = config
        self._log(f"[green]Starting pipeline for: {title} (id: {story_id})[/]")
        self._log(f"  File: {source_file}")
        self._log(f"  Theme: {theme_val}  |  Mode: {mode_val}  |  Style: {style_val}  |  Languages: {', '.join(languages)}")
        if audio_langs:
            self._log(f"  Audio languages: {', '.join(audio_langs)}")

        # Start polling timer (0.5s interval)
        self._poll_timer = self.set_interval(0.5, self.poll_progress)

        # Start pipeline in background thread
        self._run_pipeline(config, project)

    @work(thread=True)
    def _run_pipeline(self, config: StoryConfig, project) -> None:
        """Run the pipeline in a background thread."""
        from .pipeline import PipelineRunner  # import here triggers basicConfig

        root_logger = logging.getLogger()

        # Capture and clear existing handlers to keep terminal output clean
        old_handlers = root_logger.handlers[:]
        root_logger.handlers.clear()

        handler = TuiLogHandler(self)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

        succeeded = False
        try:
            backend_config = BackendConfig.from_env()

            runner = PipelineRunner(config, project, backend_config)

            # Mode-aware step range:
            #   preview → steps 1-6 (images only, no compilation, no audio)
            #   draft   → steps 1-7 (images + ebook compilation) + step 8 if audio
            #   final   → steps 1-7 (images + ebook compilation) + step 8 if audio
            end_step = 6 if config.image_mode.value == "preview" else 7
            runner.run(start_from_step=1, end_at_step=end_step)

            # Audio generation: draft and final modes, with audio languages selected
            if config.audio_languages and config.image_mode.value != "preview":
                runner.run(start_from_step=8, end_at_step=8)

            succeeded = True

        except Exception as e:
            self.call_from_thread(
                self.post_message, LogMessage(f"[red][ERROR] {e}[/]")
            )
        finally:
            root_logger.removeHandler(handler)
            for h in old_handlers:
                root_logger.addHandler(h)
            self._pipeline_succeeded = succeeded
            self.call_from_thread(self._on_pipeline_done)

    def on_log_message(self, message: LogMessage) -> None:
        """Handle log messages posted from the worker thread."""
        self.query_one("#log", RichLog).write(message.text)

    def poll_progress(self) -> None:
        """Read pipeline_state.csv and update step widgets. Called every 0.5s."""
        if not self._story_id or not self._project:
            return

        try:
            progress_dir = self._project.get_progress_dir(self._story_id)
            csv_path = progress_dir / "pipeline_state.csv"
            if not csv_path.exists():
                return

            tracker = ProgressTracker(progress_dir)
            steps = tracker.load()

            for step in steps:
                try:
                    row = self.query_one(f"#step-{step.step}", StepRow)
                    row.update_step(step)
                except Exception:
                    pass

        except Exception:
            pass

    def _on_pipeline_done(self) -> None:
        """Called from the worker thread when pipeline finishes (or fails)."""
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None

        # Final progress refresh
        self.poll_progress()

        # Re-enable form
        self.query_one("#generate-btn", Button).disabled = False
        self._log("[bold green]Pipeline finished.[/]")

        if self._pipeline_succeeded and self._config and self._project:
            try:
                from .utils.obsidian import write_story_note
                story_id = self._config.story_id
                note_path = write_story_note(
                    config=self._config,
                    progress_dir=self._project.get_progress_dir(story_id),
                    compiled_dir=self._project.get_compiled_dir(story_id),
                    images_dir=self._project.get_images_dir(story_id),
                    audio_dir=self._project.get_audio_dir(story_id) if self._config.audio_languages else None,
                )
                if note_path:
                    self._log(f"[green]Obsidian note: {note_path}[/]")
            except Exception as e:
                self._log(f"[yellow]Could not write Obsidian note: {e}[/]")

    def _log(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)


if __name__ == "__main__":
    EbookGeneratorApp().run()
