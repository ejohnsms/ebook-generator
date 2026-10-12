"""Prompt generation component for image creation."""

import re
from dataclasses import dataclass
from pathlib import Path

from ..backends import GenerationBackend
from ..models import ImageMode, ImageRecord, ImageStatus, StoryConfig
from ..themes import adult_rules_apply, get_theme
from ..utils.csv_io import write_image_records
from ..utils.file_io import safe_read_text
from ..utils.markdown import Annotation, extract_annotations, split_into_sections


@dataclass
class PromptGenInput:
    """Input for prompt generator."""

    story_markdown_path: Path  # annotated story with IMAGE annotations
    story_config: StoryConfig  # theme and model info
    output_dir: Path  # prompts/<story>/


@dataclass
class PromptGenOutput:
    """Output from prompt generator."""

    prompts_csv_path: Path  # path to prompts.csv
    image_count: int


class PromptGenerator:
    """Generates image prompts from story annotations.

    Extracts <!-- IMAGE: ... --> annotations from story and uses
    the model backend to generate detailed, refined prompts for image generation.
    Creates prompts.csv with all image metadata.
    """

    # Concrete visual vocabulary for each theme.
    # An image prompt is a sentence or two. Capping output also stops models that
    # never emit an end token from running until the HTTP timeout.
    _PROMPT_MAX_TOKENS = 300

    def __init__(self, backend: GenerationBackend):
        self._backend = backend

    def execute(self, input_data: PromptGenInput) -> PromptGenOutput:
        story_text = safe_read_text(input_data.story_markdown_path)

        image_annotations = extract_annotations(story_text, prefix="IMAGE")

        if not image_annotations:
            image_annotations = self._annotations_from_sections(story_text)

        image_records = []

        for i, annotation in enumerate(image_annotations, start=1):
            prompt = self._generate_prompt(
                annotation.content, story_text, input_data.story_config
            )

            record = ImageRecord(
                image_id=f"img_{i:03d}",
                name=f"scene_{i:02d}",
                description=annotation.content,
                prompt=prompt,
                model=self._select_model(input_data.story_config),
                target_filename=f"scene_{i:02d}.png",
                status=ImageStatus.PENDING,
                width=self._get_width(input_data.story_config),
                height=self._get_height(input_data.story_config),
                seed=i,
            )

            image_records.append(record)

        cover_prompt = self._generate_cover_prompt(
            story_text, input_data.story_config
        )

        cover_record = ImageRecord(
            image_id="img_000",
            name="cover",
            description="Cover illustration for the story",
            prompt=cover_prompt,
            model=self._select_model(input_data.story_config),
            target_filename="cover.png",
            status=ImageStatus.PENDING,
            width=1024 if input_data.story_config.image_mode == ImageMode.FINAL else 256,
            height=1024 if input_data.story_config.image_mode == ImageMode.FINAL else 256,
            seed=42,
        )

        image_records.insert(0, cover_record)

        output_dir = input_data.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        csv_path = output_dir / "prompts.csv"
        write_image_records(csv_path, image_records)

        return PromptGenOutput(
            prompts_csv_path=csv_path, image_count=len(image_records)
        )

    # ── prompt generation ────────────────────────────────────────────────────

    def _generate_prompt(
        self, image_description: str, story_context: str, config: StoryConfig
    ) -> str:
        """Generate a refined image prompt for a scene.

        Passes story synopsis and theme visual vocabulary to the LLM so every
        scene prompt is grounded in the same narrative and visual world.
        Then hard-appends theme keywords to guarantee on-theme output even if
        the LLM ignores the instructions.
        """
        synopsis = self._extract_synopsis(story_context)
        system_prompt = self._build_prompt_gen_system_prompt(config)
        user_prompt = self._build_prompt_gen_user_prompt(
            image_description, synopsis, config
        )

        refined_prompt = self._backend.generate_text(
            model=config.prompt_model,
            prompt=user_prompt,
            system=system_prompt,
            temperature=0.7,
            max_tokens=self._PROMPT_MAX_TOKENS,
        )

        # Belt-and-suspenders: always append style + theme keywords so the
        # image generator sees them even if the LLM output was weak.
        parts = [self._clean_prompt(refined_prompt), config.image_style]
        theme_keywords = self._theme_visuals(config)
        if theme_keywords:
            parts.append(theme_keywords)

        return ", ".join(parts)

    def _generate_cover_prompt(self, story_text: str, config: StoryConfig) -> str:
        """Generate the cover image prompt from a story synopsis."""
        synopsis = self._extract_synopsis(story_text, max_chars=600)

        theme = get_theme(config.theme)
        values = self._template_values(config)
        system_prompt = theme.render("cover_system", **values)
        user_prompt = theme.render("cover_request", **values, synopsis=synopsis)

        refined_prompt = self._backend.generate_text(
            model=config.prompt_model,
            prompt=user_prompt,
            system=system_prompt,
            temperature=0.8,
            max_tokens=self._PROMPT_MAX_TOKENS,
        )

        parts = [self._clean_prompt(refined_prompt), config.image_style]
        theme_keywords = self._theme_visuals(config)
        if theme_keywords:
            parts.append(theme_keywords)

        return ", ".join(parts)

    @staticmethod
    def _clean_prompt(text: str) -> str:
        """Strip chat-model wrapping: a "Prompt:" label, markdown, quotes, line breaks."""
        text = text.strip()
        text = re.sub(r"^\W*(?:image\s+)?prompt\W*:\W*", "", text, flags=re.IGNORECASE)
        text = text.replace("**", "")
        text = re.sub(r"\s+", " ", text).strip()
        return text.strip("\"'“”‘’` ")

    # ── prompt building ──────────────────────────────────────────────────────

    @staticmethod
    def _theme_visuals(config: StoryConfig) -> str:
        """The theme's image keywords, plus the adult ones for adult themes and tropes."""
        theme = get_theme(config.theme)
        keywords = [theme.image_keywords]
        if adult_rules_apply(config.theme, config.tropes):
            keywords.append(theme.templates["adult_image_keywords"].strip())
        return ", ".join(k for k in keywords if k)

    @staticmethod
    def _template_values(config: StoryConfig) -> dict[str, str]:
        """Placeholders every themes.toml image template may use."""
        theme = get_theme(config.theme)
        return {
            "theme": config.theme,
            "theme_name": theme.name,
            "theme_visuals": PromptGenerator._theme_visuals(config),
            "style": config.image_style,
            "rating": config.content_rating.value,
        }

    def _build_prompt_gen_system_prompt(self, config: StoryConfig) -> str:
        return get_theme(config.theme).render(
            "scene_system", **self._template_values(config)
        )

    def _build_prompt_gen_user_prompt(
        self, image_description: str, story_synopsis: str, config: StoryConfig
    ) -> str:
        return get_theme(config.theme).render(
            "scene_request",
            **self._template_values(config),
            synopsis=story_synopsis,
            scene=image_description,
        )

    # ── story text helpers ───────────────────────────────────────────────────

    def _extract_synopsis(self, story_text: str, max_chars: int = 400) -> str:
        """Return a clean plain-text synopsis from the first readable lines."""
        # Strip annotations
        text = re.sub(r"<!--.*?-->", "", story_text, flags=re.DOTALL)
        # Strip markdown headings
        text = re.sub(r"^#{1,6}\s+.*$", "", text, flags=re.MULTILINE)
        # Strip markdown links → plain text
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] + ("..." if len(text) > max_chars else "")

    # ── fallback annotation generation ──────────────────────────────────────

    # Section headings that are Wikipedia metadata, not narrative story content
    _NON_NARRATIVE_SECTIONS = {
        "see also", "references", "notes", "external links",
        "bibliography", "further reading", "footnotes", "sources",
        "citations", "explanatory notes",
        "retellings", "adaptations", "media adaptations",
        "audiobooks", "audio books",
        "films", "film", "movies",
        "television", "tv adaptations",
        "music", "music and musicals", "musicals",
        "play productions", "stage productions", "theatre", "theater",
        "games", "video games",
        "in popular culture", "popular culture",
        "legacy", "cultural impact", "influence", "sequels",
        "gallery", "illustrations",
    }

    def _annotations_from_sections(self, story_text: str) -> list[Annotation]:
        """Auto-generate IMAGE annotations from story sections (fallback)."""
        sections = split_into_sections(story_text)
        annotations = []
        for heading, content in sections:
            if len(annotations) >= 6:
                break
            heading = heading.strip()
            if not heading or not content.strip():
                continue
            if heading.lower() in self._NON_NARRATIVE_SECTIONS:
                continue
            clean = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
            clean = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", clean)
            clean = re.sub(r"[\w.#-]+\s*\{[^}]*\}", "", clean, flags=re.DOTALL)
            clean = re.sub(r"@\w+[^{]*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "", clean, flags=re.DOTALL)
            clean = re.sub(r"\.mw-[^\s]+(?:\s+[^\s{]+)*\s*", "", clean)
            clean = re.sub(r"<[^>]+>", "", clean)
            clean = re.sub(r"\s+", " ", clean).strip()
            if not clean:
                continue
            words = clean.split()
            excerpt = " ".join(words[:25])
            description = f"{heading} — {excerpt}{'...' if len(words) > 25 else ''}"
            annotations.append(
                Annotation(prefix="IMAGE", content=description, start_pos=0, end_pos=0)
            )
        return annotations

    # ── model / dimension selection ──────────────────────────────────────────

    def _select_model(self, config: StoryConfig) -> str:
        if config.image_mode == ImageMode.PREVIEW:
            return config.image_model_preview
        elif config.image_mode == ImageMode.DRAFT:
            return config.image_model_draft
        else:
            return config.image_model_final

    def _get_width(self, config: StoryConfig) -> int:
        if config.image_mode == ImageMode.PREVIEW:
            return 1024 // 4
        elif config.image_mode == ImageMode.DRAFT:
            return 1024 // 2
        else:
            return 1024

    def _get_height(self, config: StoryConfig) -> int:
        if config.image_mode == ImageMode.PREVIEW:
            return 768 // 4
        elif config.image_mode == ImageMode.DRAFT:
            return 768 // 2
        else:
            return 768
