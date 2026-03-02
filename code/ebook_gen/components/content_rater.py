"""Content rating component."""

import json
from dataclasses import dataclass
from pathlib import Path

from ..models import ContentRating, StoryConfig, Theme
from ..ollama.client import OllamaClient
from ..utils.file_io import safe_read_text, safe_write_text
from ..utils.markdown import insert_annotation


@dataclass
class ContentRateInput:
    """Input for content rater."""

    story_markdown_path: Path
    story_config: StoryConfig  # contains desired rating
    output_dir: Path


@dataclass
class ContentRateOutput:
    """Output from content rater."""

    metadata_path: Path  # updated metadata.json
    rating: ContentRating
    rating_justification: str  # brief explanation


class ContentRater:
    """Assigns and validates content ratings for stories.

    For UNMODIFIED theme: sets rating to NONE, skips LLM analysis.
    For other themes: analyzes story content with LLM and adds RATING
    annotations to justify the rating assignment.
    """

    def __init__(self, ollama_client: OllamaClient):
        """Initialize content rater.

        Args:
            ollama_client: Ollama client for LLM analysis
        """
        self._ollama = ollama_client

    def execute(self, input_data: ContentRateInput) -> ContentRateOutput:
        """Analyze story and assign content rating.

        Args:
            input_data: Input configuration

        Returns:
            Output with rating and metadata path

        Raises:
            FileNotFoundError: If story file doesn't exist
            OllamaError: If LLM analysis fails
        """
        # Read story
        story_text = safe_read_text(input_data.story_markdown_path)

        # Handle UNMODIFIED theme separately
        if input_data.story_config.theme == Theme.UNMODIFIED:
            rating = ContentRating.NONE
            justification = "Unmodified story, no rating assigned"
            # Don't modify the story text for unmodified theme
        else:
            # Analyze with LLM
            rating, justification, passages = self._analyze_rating(
                story_text, input_data.story_config
            )

            # Add RATING annotations to relevant passages
            story_text = self._add_rating_annotations(story_text, passages)

            # Save updated story
            safe_write_text(input_data.story_markdown_path, story_text)

        # Update metadata.json
        metadata = input_data.story_config.to_dict()
        metadata["content_rating"] = rating.value
        metadata["rating_justification"] = justification

        metadata_path = input_data.output_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return ContentRateOutput(
            metadata_path=metadata_path,
            rating=rating,
            rating_justification=justification,
        )

    def _analyze_rating(
        self, story_text: str, config: StoryConfig
    ) -> tuple[ContentRating, str, list[dict]]:
        """Analyze story content and determine appropriate rating.

        Args:
            story_text: Story markdown text
            config: Story configuration with target rating

        Returns:
            Tuple of (rating, justification, passages_to_annotate)
            where passages is a list of dicts with 'text' and 'reason'

        Raises:
            OllamaError: If LLM analysis fails
        """
        system_prompt = self._build_rating_system_prompt()
        user_prompt = self._build_rating_user_prompt(story_text, config)

        # Generate analysis
        response = self._ollama.generate_text(
            model=config.ollama_text_model,
            prompt=user_prompt,
            system=system_prompt,
            temperature=0.3,  # Lower temp for analytical task
        )

        # Parse response
        rating, justification, passages = self._parse_rating_response(
            response, config
        )

        return rating, justification, passages

    def _build_rating_system_prompt(self) -> str:
        """Build system prompt for rating analysis.

        Returns:
            System prompt string
        """
        return """You are a content rating analyst. Your task is to analyze story content and:
1. Identify potentially sensitive content (violence, language, themes, etc.)
2. Assess appropriate content rating (G, PG, PG-13, R)
3. Justify the rating with specific examples
4. Flag specific passages that influenced the rating

Be objective and consistent. Consider:
- Violence (intensity, graphic nature)
- Language (profanity, intensity)
- Themes (mature concepts, fear elements)
- Sexual content
- Drug/alcohol references

Output your analysis as JSON."""

    def _build_rating_user_prompt(
        self, story_text: str, config: StoryConfig
    ) -> str:
        """Build user prompt for rating analysis.

        Args:
            story_text: Story text to analyze
            config: Story configuration

        Returns:
            User prompt string
        """
        return f"""Analyze this story and provide a content rating.

Target Rating: {config.content_rating.value}

Story:
{story_text}

Output JSON format:
{{
  "recommended_rating": "G|PG|PG-13|R",
  "matches_target": true|false,
  "justification": "Brief explanation of rating",
  "sensitive_passages": [
    {{
      "text_snippet": "First 50 chars of passage...",
      "reason": "Why this passage affects rating"
    }}
  ]
}}

Analyze the story and return ONLY the JSON, no other text."""

    def _parse_rating_response(
        self, response: str, config: StoryConfig
    ) -> tuple[ContentRating, str, list[dict]]:
        """Parse LLM rating analysis response.

        Args:
            response: JSON response from LLM
            config: Story configuration

        Returns:
            Tuple of (rating, justification, passages)

        Note:
            If parsing fails, defaults to target rating from config
        """
        try:
            # Try to extract JSON from response
            # Sometimes LLMs add extra text before/after JSON
            import re

            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(response)

            # Extract rating
            recommended = data.get("recommended_rating", "PG")
            rating = ContentRating(recommended)

            # Get justification
            justification = data.get("justification", "Content analyzed and rated")

            # Get passages
            passages = data.get("sensitive_passages", [])

            # If doesn't match target, use target anyway but note in justification
            if not data.get("matches_target", True):
                justification = (
                    f"Target rating {config.content_rating.value} applied "
                    f"(recommended: {recommended}). {justification}"
                )
                rating = config.content_rating

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # Parsing failed - use target rating
            rating = config.content_rating
            justification = f"Rated as {rating.value} (analysis parsing failed)"
            passages = []

        return rating, justification, passages

    def _add_rating_annotations(
        self, story_text: str, passages: list[dict]
    ) -> str:
        """Add RATING annotations to story text.

        Args:
            story_text: Original story text
            passages: List of passage dicts with 'text_snippet' and 'reason'

        Returns:
            Story text with RATING annotations added
        """
        modified_text = story_text

        for passage in passages:
            snippet = passage.get("text_snippet", "")
            reason = passage.get("reason", "")

            if snippet and reason:
                # Try to find the snippet in the text
                # Use first 30 chars to locate
                search_text = snippet[:30]
                annotation = f"RATING: {reason}"

                # Insert annotation after the passage
                modified_text = insert_annotation(
                    modified_text,
                    prefix="RATING",
                    content=reason,
                    after_text=search_text,
                )

        return modified_text
