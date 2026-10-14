"""Story themes, romance tropes and prompt templates, loaded from themes.toml.

A theme is a key (what --theme takes), a display name, a description, the
system prompt that rewrites the story, a motif map (how Thompson Motif-Index
chapters are rendered in the setting), and the visual keywords that keep image
prompts on-theme. Adult themes set `adult = true`.

[defaults] holds the prompt templates every theme shares; a theme table can
override any of them. [tropes.KEY] tables are romance tropes picked with
--trope. Adult themes and tropes add the [defaults] adult rules to the rewrite:
every character in a romantic or sexual scene is an adult, and is aged up.

"unmodified" is built in (the story isn't rewritten), but a [unmodified] table
can rename it or override templates.
"""

import re
import string
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

# code/ebook_gen/themes.py -> repo root (/workspace in the containers)
THEMES_FILE = Path(__file__).resolve().parents[2] / "themes.toml"

UNMODIFIED = "unmodified"
DEFAULTS = "defaults"
TROPES = "tropes"

_KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")
_THEME_FIELDS = ("name", "description", "story_prompt", "image_keywords", "motif_map")
_UNMODIFIED_FIELDS = ("name", "description")
_TROPE_FIELDS = ("name", "description", "guidance")

# Prompt templates and the {placeholders} each one may use
TEMPLATE_FIELDS: dict[str, set[str]] = {
    "story_request": {"theme", "theme_name", "rating", "story", "motif_map", "adult_rules", "tropes", "direction"},
    "adult_rules": {"rating"},
    "tropes_request": {"tropes"},
    "direction_request": {"direction"},
    "adult_image_keywords": set(),
    "scene_system": {"theme", "theme_name", "theme_visuals", "style", "rating"},
    "scene_request": {"theme", "theme_name", "theme_visuals", "style", "rating", "synopsis", "scene"},
    "cover_system": {"theme", "theme_name", "theme_visuals", "style", "rating"},
    "cover_request": {"theme", "theme_name", "theme_visuals", "style", "rating", "synopsis"},
}


@dataclass(frozen=True)
class ThemeDef:
    """One theme from themes.toml, with its templates merged over [defaults]."""

    key: str
    name: str
    description: str
    story_prompt: str
    image_keywords: str
    motif_map: str = ""
    adult: bool = False
    templates: dict[str, str] = field(default_factory=dict)

    def render(self, template: str, **values: str) -> str:
        """Fill in one of this theme's prompt templates."""
        return self.templates[template].format(**values)


@dataclass(frozen=True)
class TropeDef:
    """One romance trope from [tropes.KEY] in themes.toml."""

    key: str
    name: str
    description: str
    guidance: str


@dataclass(frozen=True)
class Catalog:
    themes: dict[str, ThemeDef]
    tropes: dict[str, TropeDef]


def _check_template(path: Path, where: str, name: str, text) -> None:
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{path}: {where}.{name} must be a non-empty string")
    allowed = TEMPLATE_FIELDS[name]
    try:
        used = {f for _, f, _, _ in string.Formatter().parse(text) if f is not None}
    except ValueError as e:
        raise ValueError(f"{path}: {where}.{name}: {e} (write literal braces as {{{{ }}}})") from e
    unknown = used - allowed
    if unknown:
        allowed_text = ", ".join("{" + f + "}" for f in sorted(allowed)) or "none"
        raise ValueError(
            f"{path}: {where}.{name} uses {', '.join('{' + f + '}' for f in sorted(unknown))}; "
            f"allowed: {allowed_text}"
        )


def _check_key(path: Path, kind: str, key: str) -> None:
    if not _KEY_PATTERN.match(key):
        raise ValueError(
            f"{path}: {kind} key '{key}' must be lowercase letters, digits and underscores"
        )


def load_catalog(path: Path = THEMES_FILE) -> Catalog:
    """Read and validate a themes file. Raises ValueError naming the bad entry.

    Themes come back "unmodified" first, then in file order.
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)

    defaults = data.pop(DEFAULTS, None)
    if not isinstance(defaults, dict):
        raise ValueError(f"{path}: missing [{DEFAULTS}] table of prompt templates")
    missing = [name for name in TEMPLATE_FIELDS if name not in defaults]
    unknown = [name for name in defaults if name not in TEMPLATE_FIELDS]
    if missing or unknown:
        raise ValueError(
            f"{path}: [{DEFAULTS}] "
            + "; ".join(filter(None, [
                missing and f"is missing {', '.join(missing)}",
                unknown and f"has unknown {', '.join(unknown)}",
            ]))
        )
    for name, text in defaults.items():
        _check_template(path, DEFAULTS, name, text)

    tropes = {}
    trope_tables = data.pop(TROPES, {})
    if not isinstance(trope_tables, dict):
        raise ValueError(f"{path}: [{TROPES}] must hold [{TROPES}.KEY] tables")
    for key, table in trope_tables.items():
        _check_key(path, "trope", key)
        tropes[key] = _build_trope(path, key, table)

    unmodified = data.pop(UNMODIFIED, {})
    themes = {UNMODIFIED: _build_theme(path, UNMODIFIED, unmodified, defaults, _UNMODIFIED_FIELDS, {
        "name": "Unmodified",
        "description": "The original story, not rewritten.",
        "story_prompt": "",
        "image_keywords": "",
        "motif_map": "",
    })}
    for key, table in data.items():
        _check_key(path, "theme", key)
        themes[key] = _build_theme(path, key, table, defaults, _THEME_FIELDS, {})
    return Catalog(themes=themes, tropes=tropes)


def _build_theme(path, key, table, defaults, fields, fallback) -> ThemeDef:
    if not isinstance(table, dict):
        raise ValueError(f"{path}: '{key}' must be a [{key}] table")
    allows_adult = fields is _THEME_FIELDS
    unknown = [
        name for name in table
        if name not in fields and name not in TEMPLATE_FIELDS and not (allows_adult and name == "adult")
    ]
    if unknown:
        raise ValueError(f"{path}: theme '{key}' has unknown field {', '.join(unknown)}")
    adult = table.get("adult", False)
    if not isinstance(adult, bool):
        raise ValueError(f"{path}: theme '{key}' adult must be true or false")

    values = dict(fallback)
    for name in fields:
        if name in table:
            values[name] = table[name]
    missing = [name for name in _THEME_FIELDS if not isinstance(values.get(name), str)
               or (name in fields and not values[name].strip())]
    if missing:
        raise ValueError(f"{path}: theme '{key}' is missing {', '.join(missing)}")

    templates = dict(defaults)
    for name in TEMPLATE_FIELDS:
        if name in table:
            _check_template(path, key, name, table[name])
            templates[name] = table[name]

    return ThemeDef(
        key=key,
        **{name: values[name].strip() for name in _THEME_FIELDS},
        adult=adult,
        templates=templates,
    )


def _build_trope(path, key, table) -> TropeDef:
    if not isinstance(table, dict):
        raise ValueError(f"{path}: trope '{key}' must be a [{TROPES}.{key}] table")
    unknown = [name for name in table if name not in _TROPE_FIELDS]
    if unknown:
        raise ValueError(f"{path}: trope '{key}' has unknown field {', '.join(unknown)}")
    missing = [name for name in _TROPE_FIELDS
               if not isinstance(table.get(name), str) or not table[name].strip()]
    if missing:
        raise ValueError(f"{path}: trope '{key}' is missing {', '.join(missing)}")
    return TropeDef(key=key, **{name: table[name].strip() for name in _TROPE_FIELDS})


@cache
def get_catalog() -> Catalog:
    return load_catalog()


def get_themes() -> dict[str, ThemeDef]:
    """All themes, "unmodified" first, then themes.toml in file order."""
    return get_catalog().themes


def get_tropes() -> dict[str, TropeDef]:
    """All romance tropes, in file order."""
    return get_catalog().tropes


def get_theme(key: str) -> ThemeDef:
    """Look up a theme by key. Raises ValueError for an unknown key."""
    themes = get_themes()
    if key not in themes:
        raise ValueError(
            f"Unknown theme '{key}'. Themes in {THEMES_FILE.name}: {', '.join(themes)}"
        )
    return themes[key]


def get_trope(key: str) -> TropeDef:
    """Look up a trope by key. Raises ValueError for an unknown key."""
    tropes = get_tropes()
    if key not in tropes:
        raise ValueError(
            f"Unknown trope '{key}'. Tropes in {THEMES_FILE.name}: {', '.join(tropes)}"
        )
    return tropes[key]


def adult_rules_apply(theme: str, tropes: list[str]) -> bool:
    """Adult themes and every romance trope get the adult (aged-up) rules."""
    return get_theme(theme).adult or bool(tropes)


def check_combination(theme: str, tropes: list[str], direction: str = "") -> None:
    """Raise ValueError if the theme/trope/direction combination can't run."""
    get_theme(theme)
    for key in tropes:
        get_trope(key)
    if tropes and theme == UNMODIFIED:
        raise ValueError(
            "Tropes need a theme: 'unmodified' doesn't rewrite the story. Pick a --theme."
        )
    if direction.strip() and theme == UNMODIFIED:
        raise ValueError(
            "--direction needs a theme: 'unmodified' doesn't rewrite the story. Pick a --theme."
        )
