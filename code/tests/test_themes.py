"""Tests for the themes.toml loader and how themes and tropes reach the prompts."""

import pytest

from ebook_gen.cli import build_story_id
from ebook_gen.components.prompt_generator import PromptGenerator
from ebook_gen.components.story_modifier import StoryModifier
from ebook_gen.models import ContentRating, StoryConfig
from ebook_gen.themes import (
    TEMPLATE_FIELDS,
    UNMODIFIED,
    adult_rules_apply,
    check_combination,
    get_theme,
    get_themes,
    get_tropes,
    load_catalog,
)


def _write(tmp_path, text):
    path = tmp_path / "themes.toml"
    path.write_text(text)
    return path


DEFAULTS = "[defaults]\n" + "".join(
    f'{name} = "{name}' + (" for {rating}" if "rating" in fields else "") + '"\n'
    for name, fields in TEMPLATE_FIELDS.items()
)

NOIR = '''
[noir]
name = "Noir"
description = "Rain, shadows and moral grey."
story_prompt = """
Rewrite the story as 1940s film noir."""
motif_map = "- K Deceptions: double-crosses"
image_keywords = "black and white, venetian blind shadows"
'''

TROPE = '''
[tropes.slow_burn]
name = "Slow Burn"
description = "The romance takes its time."
guidance = "Delay the first kiss."
'''

VALID = DEFAULTS + NOIR


class TestLoadCatalog:
    def test_loads_fields(self, tmp_path):
        noir = load_catalog(_write(tmp_path, VALID)).themes["noir"]
        assert noir.name == "Noir"
        assert noir.story_prompt == "Rewrite the story as 1940s film noir."
        assert noir.motif_map == "- K Deceptions: double-crosses"
        assert noir.image_keywords == "black and white, venetian blind shadows"
        assert noir.adult is False

    def test_adult_flag(self, tmp_path):
        noir = load_catalog(_write(tmp_path, VALID + "adult = true\n")).themes["noir"]
        assert noir.adult is True

    def test_adult_flag_must_be_bool(self, tmp_path):
        with pytest.raises(ValueError, match="adult must be true or false"):
            load_catalog(_write(tmp_path, VALID + 'adult = "yes"\n'))

    def test_unmodified_built_in(self, tmp_path):
        themes = load_catalog(_write(tmp_path, VALID)).themes
        assert list(themes) == [UNMODIFIED, "noir"]
        assert themes[UNMODIFIED].story_prompt == ""
        assert themes[UNMODIFIED].render("scene_system", rating="G") == "scene_system for G"

    def test_theme_overrides_default_template(self, tmp_path):
        path = _write(tmp_path, VALID + 'cover_system = "Noir cover, {style}"\n')
        noir = load_catalog(path).themes["noir"]
        assert noir.render("cover_system", style="ink") == "Noir cover, ink"
        assert noir.render("scene_system", rating="R") == "scene_system for R"

    def test_unmodified_table_overrides(self, tmp_path):
        path = _write(tmp_path, VALID + '[unmodified]\nname = "Original"\nscene_request = "Draw {scene}"\n')
        unmodified = load_catalog(path).themes[UNMODIFIED]
        assert unmodified.name == "Original"
        assert unmodified.render("scene_request", scene="a goat") == "Draw a goat"

    @pytest.mark.parametrize("field", ["story_prompt", "adult"])
    def test_unmodified_cannot_rewrite(self, tmp_path, field):
        with pytest.raises(ValueError, match=f"unknown field {field}"):
            load_catalog(_write(tmp_path, VALID + f"[unmodified]\n{field} = true\n"))

    def test_missing_field(self, tmp_path):
        path = _write(tmp_path, VALID.replace('motif_map = "- K Deceptions: double-crosses"\n', ""))
        with pytest.raises(ValueError, match="noir.*motif_map"):
            load_catalog(path)

    def test_unknown_field(self, tmp_path):
        with pytest.raises(ValueError, match="unknown field image_keyword$"):
            load_catalog(_write(tmp_path, VALID + 'image_keyword = "typo"\n'))

    def test_bad_key(self, tmp_path):
        with pytest.raises(ValueError, match="Film-Noir"):
            load_catalog(_write(tmp_path, VALID.replace("[noir]", "[Film-Noir]")))

    def test_missing_defaults(self, tmp_path):
        with pytest.raises(ValueError, match=r"missing \[defaults\]"):
            load_catalog(_write(tmp_path, NOIR))

    def test_defaults_missing_template(self, tmp_path):
        path = _write(tmp_path, VALID.replace('cover_request = "cover_request for {rating}"\n', ""))
        with pytest.raises(ValueError, match="missing cover_request"):
            load_catalog(path)

    def test_unknown_placeholder(self, tmp_path):
        path = _write(tmp_path, VALID + 'scene_system = "Draw {scene}"\n')
        with pytest.raises(ValueError, match=r"noir.scene_system uses \{scene\}"):
            load_catalog(path)

    def test_unbalanced_brace(self, tmp_path):
        path = _write(tmp_path, VALID + 'cover_system = "a { b"\n')
        with pytest.raises(ValueError, match="noir.cover_system"):
            load_catalog(path)

    def test_tropes(self, tmp_path):
        tropes = load_catalog(_write(tmp_path, VALID + TROPE)).tropes
        assert list(tropes) == ["slow_burn"]
        assert tropes["slow_burn"].guidance == "Delay the first kiss."

    def test_trope_missing_field(self, tmp_path):
        path = _write(tmp_path, VALID + TROPE.replace('guidance = "Delay the first kiss."\n', ""))
        with pytest.raises(ValueError, match="slow_burn.*guidance"):
            load_catalog(path)


class TestRepoThemes:
    def test_repo_file_loads(self):
        themes = get_themes()
        assert next(iter(themes)) == UNMODIFIED
        for theme in list(themes.values())[1:]:
            assert theme.story_prompt and theme.motif_map and theme.image_keywords, theme.key

    def test_atu_divisions_and_adult_genres(self):
        themes = get_themes()
        for key in ("animal_fable", "tale_of_magic", "religious_legend", "realistic_novella",
                    "stupid_ogre", "jest", "formula_tale"):
            assert not themes[key].adult
        for key in ("monster_romance", "dark_romance", "regency_romance"):
            assert themes[key].adult
        assert "young_adult_romance" not in themes
        assert "enemies_to_lovers" in get_tropes()

    def test_unmodified_has_no_prompts(self):
        theme = get_theme(UNMODIFIED)
        assert theme.story_prompt == ""
        assert theme.image_keywords == ""

    def test_unknown_theme(self):
        with pytest.raises(ValueError, match="Unknown theme 'nope'"):
            get_theme("nope")

    def test_tropes_need_a_theme(self):
        with pytest.raises(ValueError, match="Tropes need a theme"):
            check_combination(UNMODIFIED, ["enemies_to_lovers"])
        with pytest.raises(ValueError, match="Unknown trope"):
            check_combination("cyberpunk", ["nope"])
        check_combination("cyberpunk", ["enemies_to_lovers"])

    def test_adult_rules_apply(self):
        assert adult_rules_apply("monster_romance", [])
        assert adult_rules_apply("cyberpunk", ["second_chance"])
        assert not adult_rules_apply("cyberpunk", [])


def _config(theme, tropes=()):
    return StoryConfig(
        story_id="x", title="x", source_file="x", theme=theme, tropes=list(tropes),
        content_rating=ContentRating.R,
    )


class TestPrompts:
    def test_rewrite_has_motif_map_without_adult_rules(self):
        request = StoryModifier(None)._build_modification_prompt("STORY", _config("cyberpunk"))
        assert "as a Cyberpunk retelling" in request
        assert get_theme("cyberpunk").motif_map in request
        assert "Aarne-Thompson-Uther" in request
        assert "Adult rules" not in request
        assert "Romance tropes" not in request

    def test_adult_theme_gets_adult_rules(self):
        request = StoryModifier(None)._build_modification_prompt("STORY", _config("monster_romance"))
        assert "Adult rules" in request
        assert "always aged up" in request

    def test_trope_gets_adult_rules_and_guidance(self):
        config = _config("cyberpunk", ["enemies_to_lovers"])
        request = StoryModifier(None)._build_modification_prompt("STORY", config)
        assert "Adult rules" in request
        assert "- Enemies to Lovers: " in request

    def test_adult_image_keywords(self):
        assert "all characters are adults" in PromptGenerator._theme_visuals(_config("monster_romance"))
        assert "all characters are adults" in PromptGenerator._theme_visuals(
            _config("steampunk", ["second_chance"])
        )
        assert "adults" not in PromptGenerator._theme_visuals(_config("steampunk"))


def test_story_id_includes_tropes():
    assert (
        build_story_id("Little Red Riding Hood", "monster_romance", "photo-realistic", ["enemies_to_lovers"])
        == "little_red_riding_hood_monster_romance_enemies_to_lovers"
    )


def test_story_config_round_trips_tropes():
    config = _config("cyberpunk", ["second_chance"])
    assert StoryConfig.from_dict(config.to_dict()).tropes == ["second_chance"]
    data = config.to_dict()
    del data["tropes"]
    assert StoryConfig.from_dict(data).tropes == []
