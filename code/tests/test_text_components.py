"""Tests for translator and prompt generator output handling."""

from unittest.mock import MagicMock

import pytest

from ebook_gen.components.prompt_generator import PromptGenerator
from ebook_gen.components.translator import Translator
from ebook_gen.models import StoryConfig


@pytest.fixture
def config():
    return StoryConfig(story_id="s", title="S", source_file="s.txt")


class TestTranslator:
    def test_empty_section_is_not_sent_to_model(self, config):
        backend = MagicMock()
        backend.generate_text.side_effect = lambda **kw: "T"
        translator = Translator(backend)

        translator._translate_story("# Title\n\n# Chapter 1\nOnce upon a time.", "en", "es", config)

        sent = [call.kwargs["prompt"] for call in backend.generate_text.call_args_list]
        # Two headings + one body; the title's empty body is skipped
        assert len(sent) == 3
        assert not any(p.rstrip().endswith("Translation:") for p in sent)

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Traducción:\n\nÉrase una vez.", "Érase una vez."),
            ("**Translation:**\nHola", "Hola"),
            ("Érase una vez.", "Érase una vez."),
            ("Epílogo:", "Epílogo:"),  # a one-line heading survives
            ("Dijo el troll: ¿quién anda ahí?\nNadie.", "Dijo el troll: ¿quién anda ahí?\nNadie."),
        ],
    )
    def test_strip_label(self, raw, expected):
        assert Translator._strip_label(raw) == expected


class TestPromptGenerator:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ('Prompt: "A goat on a bridge"', "A goat on a bridge"),
            ("**Image prompt:** A goat\non a bridge", "A goat on a bridge"),
            ("A goat on a bridge", "A goat on a bridge"),
        ],
    )
    def test_clean_prompt(self, raw, expected):
        assert PromptGenerator._clean_prompt(raw) == expected

    def test_prompt_requests_are_capped(self, config):
        backend = MagicMock()
        backend.generate_text.return_value = "A goat on a bridge"
        PromptGenerator(backend)._generate_prompt("goat scene", "Once upon a time", config)

        assert backend.generate_text.call_args.kwargs["max_tokens"] == PromptGenerator._PROMPT_MAX_TOKENS
        assert backend.generate_text.call_args.kwargs["model"] == config.prompt_model


class TestTranslatorHeadings:
    def test_heading_levels_preserved(self, config):
        backend = MagicMock()
        backend.generate_text.side_effect = lambda **kw: kw["prompt"].rsplit("\n", 1)[-1].upper()
        out = Translator(backend)._translate_story(
            "# Title\n\n## Chapter 1\nOnce.\n### Scene\nTwice.", "en", "es", config
        )
        assert "# TITLE" in out
        assert "## CHAPTER 1" in out
        assert "### SCENE" in out
        assert "\n# CHAPTER 1" not in out


class TestContentRater:
    def test_parses_nc17_recommendation(self):
        from ebook_gen.components.content_rater import ContentRater
        from ebook_gen.models import ContentRating

        config = StoryConfig(
            story_id="s", title="S", source_file="s.txt", content_rating=ContentRating.NC17
        )
        response = '{"recommended_rating": "NC-17", "matches_target": true, "justification": "x"}'
        rating, _, _ = ContentRater(MagicMock())._parse_rating_response(response, config)
        assert rating == ContentRating.NC17

    def test_nc17_round_trips_through_metadata(self):
        from ebook_gen.models import ContentRating

        config = StoryConfig(
            story_id="s", title="S", source_file="s.txt", content_rating=ContentRating.NC17
        )
        assert StoryConfig.from_dict(config.to_dict()).content_rating == ContentRating.NC17
