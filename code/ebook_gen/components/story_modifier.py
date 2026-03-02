"""Story modification component for theme transformations."""

from dataclasses import dataclass
from pathlib import Path

from ..config import THEME_PROMPTS
from ..models import StoryConfig, Theme
from ..ollama.client import OllamaClient
from ..utils.file_io import safe_read_text, safe_write_text


@dataclass
class StoryModifyInput:
    """Input for story modifier."""

    raw_markdown_path: Path  # from step 1
    story_config: StoryConfig  # contains theme selection
    output_dir: Path


@dataclass
class StoryModifyOutput:
    """Output from story modifier."""

    story_markdown_path: Path  # path to annotated story.md
    chapter_count: int
    word_count: int


class StoryModifier:
    """Applies thematic transformations to stories using LLM.

    For UNMODIFIED theme: copies raw story as-is with minimal metadata.
    For other themes: uses Ollama to rewrite story in the target theme
    and add annotations (DIRECTOR, THEME, IMAGE) for pipeline processing.
    """

    def __init__(self, ollama_client: OllamaClient):
        """Initialize story modifier.

        Args:
            ollama_client: Ollama client for LLM generation
        """
        self._ollama = ollama_client

    def execute(self, input_data: StoryModifyInput) -> StoryModifyOutput:
        """Apply theme modification to story.

        Args:
            input_data: Input configuration

        Returns:
            Output with path to modified story

        Raises:
            FileNotFoundError: If raw markdown file doesn't exist
            OllamaError: If LLM generation fails
        """
        # Read raw story
        raw_text = safe_read_text(input_data.raw_markdown_path)

        # Handle UNMODIFIED theme separately
        if input_data.story_config.theme == Theme.UNMODIFIED:
            modified_text = self._process_unmodified(raw_text, input_data.story_config)
        else:
            # Apply theme transformation via LLM
            modified_text = self._process_with_theme(
                raw_text, input_data.story_config
            )

        # Save to output
        output_path = input_data.output_dir / "story.md"
        safe_write_text(output_path, modified_text)

        # Calculate stats
        chapter_count = self._count_chapters(modified_text)
        word_count = self._count_words(modified_text)

        return StoryModifyOutput(
            story_markdown_path=output_path,
            chapter_count=chapter_count,
            word_count=word_count,
        )

    def _process_unmodified(self, raw_text: str, config: StoryConfig) -> str:
        """Process story with UNMODIFIED theme (no LLM transformation).

        Args:
            raw_text: Raw markdown text
            config: Story configuration

        Returns:
            Story with minimal META annotation added
        """
        # Add minimal metadata annotation
        meta = f"""<!-- META
theme: {config.theme.value}
rating: {config.content_rating.value}
source: wikipedia
-->

"""
        return meta + raw_text

    def _process_with_theme(self, raw_text: str, config: StoryConfig) -> str:
        """Process story with theme transformation using LLM.

        Args:
            raw_text: Raw markdown text
            config: Story configuration

        Returns:
            Transformed story with annotations

        Raises:
            ValueError: If theme prompt not found
            OllamaError: If LLM generation fails
        """
        # Get system prompt for theme
        theme_key = config.theme.value
        if theme_key not in THEME_PROMPTS:
            raise ValueError(f"No system prompt found for theme: {theme_key}")

        system_prompt = THEME_PROMPTS[theme_key]

        # Construct user prompt
        user_prompt = self._build_modification_prompt(raw_text, config)

        # Generate with Ollama
        modified_text = self._ollama.generate_text(
            model=config.ollama_text_model,
            prompt=user_prompt,
            system=system_prompt,
            temperature=0.8,  # Higher temp for creative rewriting
        )

        # Add metadata annotation at the top
        meta = f"""<!-- META
theme: {config.theme.value}
rating: {config.content_rating.value}
source: wikipedia
-->

"""
        return meta + modified_text

    def _build_modification_prompt(self, raw_text: str, config: StoryConfig) -> str:
        """Build the user prompt for story modification.

        Args:
            raw_text: Raw story text
            config: Story configuration

        Returns:
            Formatted prompt for the LLM
        """
        prompt = f"""Please rewrite the following story into a {config.theme.value} setting.

Original Story:
{raw_text}

Requirements:
1. Maintain the original narrative arc and character relationships
2. Transform all elements to fit the {config.theme.value} theme
3. Structure your output with Markdown chapter headings (## Chapter N: Title)
4. Add annotations using HTML comments:
   - <!-- DIRECTOR: staging and mood notes -->
   - <!-- THEME: explain thematic connections -->
   - <!-- IMAGE: describe key visual moments for illustration -->
5. Add 2-3 IMAGE annotations per chapter at visually striking moments
6. Keep the moral and thematic core of the original story
7. Target content rating: {config.content_rating.value}

Output only the rewritten story with annotations. Do not include any preamble or explanation.
"""
        return prompt

    def _count_chapters(self, markdown_text: str) -> int:
        """Count chapters in markdown text.

        Args:
            markdown_text: Markdown content

        Returns:
            Number of chapters (## headings)
        """
        import re

        # Count ## headings (chapters)
        pattern = r"^##\s+.*$"
        matches = re.findall(pattern, markdown_text, re.MULTILINE)
        return len(matches)

    def _count_words(self, markdown_text: str) -> int:
        """Count words in markdown text (excluding annotations).

        Args:
            markdown_text: Markdown content

        Returns:
            Word count
        """
        from ..utils.markdown import strip_all_html_comments

        # Strip annotations and HTML comments
        clean_text = strip_all_html_comments(markdown_text)

        # Remove markdown formatting
        clean_text = clean_text.replace("#", "")
        clean_text = clean_text.replace("*", "")
        clean_text = clean_text.replace("_", "")

        # Count words
        words = clean_text.split()
        return len(words)
