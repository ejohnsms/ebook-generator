"""Tests for running one pipeline stage per container (EBOOK_GEN_STAGE)."""

import json

import pytest
from click.testing import CliRunner

from ebook_gen import cli as cli_module
from ebook_gen.config import ProjectConfig
from ebook_gen.models import ImageMode, StoryConfig
from ebook_gen.pipeline import PipelineError, PipelineRunner
from ebook_gen.progress import ProgressTracker


@pytest.fixture
def project(tmp_path):
    return ProjectConfig.from_root(tmp_path)


def make_story(project, image_mode=ImageMode.DRAFT, audio=(), completed=()):
    config = StoryConfig(
        story_id="goats",
        title="Goats",
        source_file="stories/goats.txt",
        image_mode=image_mode,
        audio_languages=list(audio),
    )
    story_dir = project.get_story_dir("goats")
    story_dir.mkdir(parents=True)
    (story_dir / "metadata.json").write_text(json.dumps(config.to_dict()))
    tracker = ProgressTracker(project.get_progress_dir("goats"))
    tracker.initialize()
    for step in completed:
        tracker.mark_step_completed(step)
    return config


class RecordingRunner(PipelineRunner):
    """Runs no real components; records the steps it would execute."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed = []

    def _execute_step(self, step_num, step_name):
        self.executed.append(step_num)
        self._progress.mark_step_completed(step_num)


class TestStageFilter:
    def test_without_stage_runs_every_step(self, project, monkeypatch):
        monkeypatch.delenv("EBOOK_GEN_STAGE", raising=False)
        monkeypatch.setattr("ebook_gen.pipeline.create_backend", lambda cfg: FakeHealthyBackend())
        config = make_story(project, completed=(1, 2, 3, 4, 5))
        runner = RecordingRunner(config, project)
        runner.run(start_from_step=1, end_at_step=7)
        assert runner.executed == [6, 7]

    def test_text_stage_stops_before_images(self, project, monkeypatch):
        monkeypatch.setenv("EBOOK_GEN_STAGE", "text")
        monkeypatch.setattr("ebook_gen.pipeline.create_backend", lambda cfg: FakeHealthyBackend())
        config = make_story(project)
        runner = RecordingRunner(config, project)
        runner.run(start_from_step=1, end_at_step=7)
        assert runner.executed == [1, 2, 3, 4, 5]
        assert not runner.is_finished()

    def test_compile_stage_needs_no_backend(self, project, monkeypatch):
        monkeypatch.setenv("EBOOK_GEN_STAGE", "compile")

        def no_backend(cfg):
            raise AssertionError("compile must not create a model backend")

        monkeypatch.setattr("ebook_gen.pipeline.create_backend", no_backend)
        config = make_story(project, completed=(1, 2, 3, 4, 5, 6))
        runner = RecordingRunner(config, project)
        runner.resume()
        assert runner.executed == [7]
        assert runner.is_finished()

    def test_stage_refuses_to_skip_earlier_steps(self, project, monkeypatch):
        monkeypatch.setenv("EBOOK_GEN_STAGE", "images")
        config = make_story(project, completed=(1, 2, 3, 4))
        runner = RecordingRunner(config, project)
        with pytest.raises(PipelineError, match="Step 5"):
            runner.resume()
        assert runner.executed == []

    def test_unknown_stage(self, project, monkeypatch):
        monkeypatch.setenv("EBOOK_GEN_STAGE", "nope")
        config = make_story(project)
        with pytest.raises(PipelineError, match="Unknown EBOOK_GEN_STAGE"):
            PipelineRunner(config, project)

    @pytest.mark.parametrize(
        "mode, audio, end",
        [(ImageMode.PREVIEW, ("en",), 6), (ImageMode.DRAFT, (), 7), (ImageMode.FINAL, ("en",), 8)],
    )
    def test_planned_end_step(self, project, mode, audio, end):
        config = make_story(project, image_mode=mode, audio=audio)
        assert PipelineRunner(config, project).planned_end_step() == end


class FakeHealthyBackend:
    def health_check(self):
        return True

    def close(self):
        pass


class TestStagesCommand:
    def run(self, project, monkeypatch):
        monkeypatch.delenv("EBOOK_GEN_STAGE", raising=False)
        monkeypatch.setattr(cli_module, "get_project_config", lambda: project)
        result = CliRunner().invoke(cli_module.cli, ["stages", "goats"])
        assert result.exit_code == 0, result.output
        return result.output.split()

    def test_new_preview_story(self, project, monkeypatch):
        make_story(project, image_mode=ImageMode.PREVIEW, audio=("en",))
        assert self.run(project, monkeypatch) == ["text", "images"]

    def test_draft_with_audio_after_text(self, project, monkeypatch):
        make_story(project, audio=("en",), completed=(1, 2, 3, 4, 5))
        assert self.run(project, monkeypatch) == ["images", "compile", "audio"]

    def test_finished_story(self, project, monkeypatch):
        make_story(project, completed=range(1, 8))
        assert self.run(project, monkeypatch) == []


def test_pipeline_imports_without_text_stage_packages():
    """The images/compile/audio images lack markdownify; importing the pipeline must not need it."""
    import subprocess
    import sys

    code = "import sys, ebook_gen.cli, ebook_gen.pipeline; assert 'markdownify' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


class TestPromoteImages:
    def test_resets_images_and_compile_steps(self, project, monkeypatch):
        from ebook_gen.models import ImageRecord, ImageStatus
        from ebook_gen.utils.csv_io import read_image_records, write_image_records

        monkeypatch.delenv("EBOOK_GEN_STAGE", raising=False)
        monkeypatch.setattr(cli_module, "get_project_config", lambda: project)
        make_story(project, image_mode=ImageMode.PREVIEW, completed=range(1, 9))
        prompts_csv = project.get_prompts_dir("goats") / "prompts.csv"
        prompts_csv.parent.mkdir(parents=True)
        write_image_records(prompts_csv, [
            ImageRecord(image_id="img_000", name="cover", description="c", prompt="p",
                        model="m", target_filename="cover.png", status=ImageStatus.COMPLETED,
                        width=256, height=256, seed=1),
        ])

        ran = []
        monkeypatch.setattr(PipelineRunner, "run", lambda self, start_from_step, end_at_step: ran.append((start_from_step, end_at_step)))
        result = CliRunner().invoke(cli_module.cli, ["promote-images", "goats", "--mode", "draft"])
        assert result.exit_code == 0, result.output

        tracker = ProgressTracker(project.get_progress_dir("goats"))
        tracker.load()
        assert not tracker.is_step_completed(6)
        assert not tracker.is_step_completed(7)
        assert tracker.is_step_completed(8)  # narration doesn't depend on the images
        assert ran == [(6, 6)]
        record = read_image_records(prompts_csv)[0]
        assert (record.status, record.width, record.height) == (ImageStatus.PENDING, 512, 512)
