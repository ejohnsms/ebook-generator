"""Translation component for multi-language support."""

from dataclasses import dataclass
from pathlib import Path

from ..models import StoryConfig
from ..ollama.client import OllamaClient
from ..utils.file_io import safe_read_text, safe_write_text
from ..utils.markdown import (
    extract_annotations,
    split_into_sections,
    strip_all_html_comments,
)


@dataclass
class TranslateInput:
    """Input for translator."""

    story_markdown_path: Path  # annotated story.md (source language)
    story_config: StoryConfig  # contains target_languages list
    output_dir: Path


@dataclass
class TranslateOutput:
    """Output from translator."""

    translated_paths: dict[str, Path]  # language_code -> file path
    # e.g. {"en": Path("story.md"), "es": Path("story_es.md")}


class Translator:
    """Translates stories to multiple languages using Ollama.

    For source language: uses original file (no translation).
    For other languages: strips annotations, translates prose,
    re-inserts annotations at corresponding positions.
    """

    def __init__(self, ollama_client: OllamaClient):
        """Initialize translator.

        Args:
            ollama_client: Ollama client for LLM generation
        """
        self._ollama = ollama_client

    def execute(self, input_data: TranslateInput) -> TranslateOutput:
        """Translate story to all target languages.

        Args:
            input_data: Input configuration

        Returns:
            Output with paths to translated files

        Raises:
            FileNotFoundError: If source story doesn't exist
            OllamaError: If translation fails
        """
        # Read source story
        source_text = safe_read_text(input_data.story_markdown_path)
        source_lang = input_data.story_config.source_language

        translated_paths = {}

        for lang_code in input_data.story_config.target_languages:
            if lang_code == source_lang:
                # No translation needed - use original
                translated_paths[lang_code] = input_data.story_markdown_path
            else:
                # Translate to this language
                translated_text = self._translate_story(
                    source_text, source_lang, lang_code, input_data.story_config
                )

                # Save translated version
                output_path = input_data.output_dir / f"story_{lang_code}.md"
                safe_write_text(output_path, translated_text)
                translated_paths[lang_code] = output_path

        return TranslateOutput(translated_paths=translated_paths)

    def _translate_story(
        self,
        source_text: str,
        source_lang: str,
        target_lang: str,
        config: StoryConfig,
    ) -> str:
        """Translate story to target language.

        Args:
            source_text: Source story with annotations
            source_lang: Source language code (e.g., "en")
            target_lang: Target language code (e.g., "es")
            config: Story configuration

        Returns:
            Translated story with annotations re-inserted

        Raises:
            OllamaError: If translation fails
        """
        # Extract all annotations first
        annotations = extract_annotations(source_text)

        # Strip annotations to get clean prose
        clean_text = strip_all_html_comments(source_text)

        # Split into chapters for chunking
        sections = split_into_sections(clean_text)

        if not sections:
            # No chapter structure - translate whole document
            translated_prose = self._translate_text(
                clean_text, source_lang, target_lang, config
            )
        else:
            # Translate chapter by chapter
            translated_sections = []
            for heading, content in sections:
                # Translate heading
                translated_heading = self._translate_text(
                    heading, source_lang, target_lang, config
                )

                # Translate content
                translated_content = self._translate_text(
                    content, source_lang, target_lang, config
                )

                translated_sections.append((translated_heading, translated_content))

            # Reassemble
            translated_prose = self._reassemble_sections(translated_sections)

        # Re-insert annotations (untranslated)
        # For simplicity, append all annotations at the end
        # In a more sophisticated version, we'd match positions
        translated_with_annotations = translated_prose

        for annotation in annotations:
            annotation_text = f"<!-- {annotation.prefix}: {annotation.content} -->"
            translated_with_annotations += f"\n\n{annotation_text}"

        return translated_with_annotations

    def _translate_text(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        config: StoryConfig,
    ) -> str:
        """Translate a text passage.

        Args:
            text: Text to translate
            source_lang: Source language code
            target_lang: Target language code
            config: Story configuration

        Returns:
            Translated text

        Raises:
            OllamaError: If translation fails
        """
        # Build translation prompt
        system_prompt = self._build_translation_system_prompt(
            source_lang, target_lang
        )
        user_prompt = self._build_translation_user_prompt(text, target_lang)

        # Translate with Ollama
        translated = self._ollama.generate_text(
            model=config.ollama_text_model,
            prompt=user_prompt,
            system=system_prompt,
            temperature=0.3,  # Lower temp for translation accuracy
        )

        return translated.strip()

    def _build_translation_system_prompt(
        self, source_lang: str, target_lang: str
    ) -> str:
        """Build system prompt for translation.

        Args:
            source_lang: Source language code
            target_lang: Target language code

        Returns:
            System prompt
        """
        lang_names = {
            "en": "English",
            "es": "Spanish",
            "hi": "Hindi",
            "fr": "French",
            "de": "German",
            "ja": "Japanese",
            "zh": "Chinese",
            "ar": "Arabic",
        }

        source_name = lang_names.get(source_lang, source_lang.upper())
        target_name = lang_names.get(target_lang, target_lang.upper())

        return f"""You are a professional translator specializing in literary translation.

Your task is to translate from {source_name} to {target_name}.

Guidelines:
1. Preserve the meaning, tone, and style of the original
2. Adapt cultural references where appropriate for target audience
3. Maintain narrative flow and readability
4. Keep character names consistent (do not translate proper names)
5. Preserve markdown formatting (headings, emphasis, etc.)
6. Output ONLY the translation, no preamble or explanation

Translate naturally and idiomatically for {target_name} readers."""

    def _build_translation_user_prompt(self, text: str, target_lang: str) -> str:
        """Build user prompt for translation.

        Args:
            text: Text to translate
            target_lang: Target language code

        Returns:
            User prompt
        """
        lang_names = {
            "en": "English",
            "es": "Spanish",
            "hi": "Hindi",
            "fr": "French",
            "de": "German",
            "ja": "Japanese",
            "zh": "Chinese",
            "ar": "Arabic",
        }

        target_name = lang_names.get(target_lang, target_lang.upper())

        return f"""Translate the following text to {target_name}:

{text}

Translation:"""

    def _reassemble_sections(
        self, sections: list[tuple[str, str]]
    ) -> str:
        """Reassemble translated sections into complete markdown.

        Args:
            sections: List of (heading, content) tuples

        Returns:
            Complete markdown text
        """
        parts = []
        for heading, content in sections:
            parts.append(f"# {heading}")
            parts.append(content)

        return "\n\n".join(parts)
