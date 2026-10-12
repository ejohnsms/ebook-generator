"""Tests for `ebook-gen help` and the wrapper's command overview."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from ebook_gen.cli import _PARAM_VALUES, cli

WRAPPER = Path(__file__).resolve().parents[2] / "ebook-gen"


def _help(*args):
    return CliRunner().invoke(cli, ["help", *args])


@pytest.mark.parametrize("topic", sorted(_PARAM_VALUES))
def test_every_param_topic_lists_values(topic):
    result = _help(topic)
    assert result.exit_code == 0, result.output
    assert len(result.output.splitlines()) >= 2


@pytest.mark.parametrize(
    "topic, expected",
    [
        ("theme", "monster_romance"),
        ("themes", "cyberpunk"),
        ("--trope", "enemies_to_lovers"),
        ("rating", "NC-17"),
        ("style", '"watercolor, soft watercolor"'),
        ("step", "image_generation (images container)"),
        ("audio_languages", "en-gb"),
    ],
)
def test_param_values(topic, expected):
    assert expected in _help(topic).output


def test_command_help():
    result = _help("generate")
    assert result.exit_code == 0
    assert "Usage: cli generate [OPTIONS] TITLE" in result.output
    assert "--trope TROPE" in result.output


def test_params_lists_every_parameter():
    output = _help("params").output
    for name in ("--theme *", "--trope *", "--file", "STORY_ID", "--yes"):
        assert name in output


def test_overview_without_topic():
    output = _help().output
    assert "help" in output and "generate" in output


def test_unknown_topic():
    result = _help("nope")
    assert result.exit_code == 2
    assert "No help for 'nope'" in result.output


def test_hidden_command_not_documented():
    assert _help("stages").exit_code == 2


def test_wrapper_usage_lists_every_command():
    usage = WRAPPER.read_text()
    usage = usage[usage.index("usage() {"):usage.index("wrapper_help() {")]
    for name, cmd in cli.commands.items():
        if not cmd.hidden:
            assert f"\n  {name}" in usage, f"{name} missing from ./ebook-gen help"
