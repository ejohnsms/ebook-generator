"""Wikipedia article fetcher component."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from markdownify import markdownify as md


@dataclass
class WikiFetchInput:
    """Input for Wikipedia fetcher."""

    story_title: str  # e.g. "Three Billy Goats Gruff"
    language: str  # e.g. "en"
    output_dir: Path  # e.g. stories/three-billy-goats-gruff/


@dataclass
class WikiFetchOutput:
    """Output from Wikipedia fetcher."""

    raw_markdown_path: Path  # path to saved raw.md
    title: str  # canonical title from Wikipedia
    source_url: str  # full Wikipedia URL
    fetch_timestamp: datetime


class StoryNotFoundError(Exception):
    """Wikipedia article not found."""

    pass


class DisambiguationError(Exception):
    """Wikipedia returned a disambiguation page."""

    def __init__(self, title: str, options: list[str]):
        self.title = title
        self.options = options
        super().__init__(
            f"'{title}' is ambiguous. Did you mean: {', '.join(options[:5])}"
        )


class WikipediaFetcher:
    """Fetches Wikipedia articles and converts to Markdown.

    Uses the Wikipedia REST API to fetch article content in HTML format,
    then converts to clean Markdown suitable for story processing.
    """

    def __init__(self, timeout: int = 30):
        """Initialize Wikipedia fetcher.

        Args:
            timeout: HTTP request timeout in seconds
        """
        self._timeout = timeout

    def execute(self, input_data: WikiFetchInput) -> WikiFetchOutput:
        """Fetch Wikipedia article and convert to Markdown.

        Args:
            input_data: Input configuration

        Returns:
            Output with path to saved Markdown file

        Raises:
            StoryNotFoundError: Article not found (404)
            DisambiguationError: Title is ambiguous
            httpx.HTTPError: Network or HTTP errors
        """
        # Construct Wikipedia URL
        title_for_url = input_data.story_title.replace(" ", "_")
        base_url = f"https://{input_data.language}.wikipedia.org"
        api_url = f"{base_url}/api/rest_v1/page/html/{title_for_url}"
        full_url = f"{base_url}/wiki/{title_for_url}"

        # Fetch HTML content
        # Wikipedia requires a descriptive User-Agent (policy: https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy)
        headers = {"User-Agent": "ebook-generation/0.1 (https://github.com/local/ebook-generation; educational use)"}
        with httpx.Client(timeout=self._timeout, headers=headers) as client:
            try:
                response = client.get(api_url)

                # Handle 404 - article not found
                if response.status_code == 404:
                    raise StoryNotFoundError(
                        f"Wikipedia article not found: {input_data.story_title}"
                    )

                response.raise_for_status()
                html_content = response.text

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise StoryNotFoundError(
                        f"Wikipedia article not found: {input_data.story_title}"
                    ) from e
                raise

        # Check if it's a disambiguation page
        if self._is_disambiguation_page(html_content):
            options = self._extract_disambiguation_options(html_content)
            raise DisambiguationError(input_data.story_title, options)

        # Convert HTML to Markdown
        markdown_content = self._html_to_markdown(html_content)

        # Clean up the markdown
        markdown_content = self._clean_markdown(markdown_content)

        # Add metadata header
        header = f"""# {input_data.story_title}

<!-- Source: {full_url} -->
<!-- Fetched: {datetime.utcnow().isoformat()} -->

"""
        markdown_content = header + markdown_content

        # Save to file
        output_dir = input_data.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "raw.md"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        return WikiFetchOutput(
            raw_markdown_path=output_path,
            title=input_data.story_title,
            source_url=full_url,
            fetch_timestamp=datetime.utcnow(),
        )

    def _html_to_markdown(self, html: str) -> str:
        """Convert HTML to Markdown.

        Args:
            html: HTML content

        Returns:
            Markdown text
        """
        # Use markdownify to convert
        # Strip out script, style, and navigation elements
        markdown = md(
            html,
            heading_style="ATX",  # Use # for headings
            bullets="-",  # Use - for list items
            strip=["script", "style", "nav", "footer"],
        )
        return markdown

    def _clean_markdown(self, markdown: str) -> str:
        """Clean up converted Markdown.

        Removes:
        - Wikipedia-specific elements (edit links, citations)
        - Excessive whitespace
        - Navigation elements

        Args:
            markdown: Raw markdown text

        Returns:
            Cleaned markdown
        """
        lines = markdown.split("\n")
        cleaned_lines = []

        for line in lines:
            # Skip common Wikipedia elements
            if any(
                skip in line.lower()
                for skip in [
                    "[edit]",
                    "citation needed",
                    "references",
                    "external links",
                    "see also",
                    "further reading",
                ]
            ):
                continue

            # Skip lines with only brackets or parentheses
            if line.strip() in ["[]", "()", "[[", "]]"]:
                continue

            cleaned_lines.append(line)

        # Join and remove excessive blank lines
        result = "\n".join(cleaned_lines)
        while "\n\n\n" in result:
            result = result.replace("\n\n\n", "\n\n")

        return result.strip()

    def _is_disambiguation_page(self, html: str) -> bool:
        """Check if the page is a disambiguation page.

        Args:
            html: HTML content

        Returns:
            True if disambiguation page
        """
        # Simple heuristic: check for common disambiguation indicators
        lower_html = html.lower()
        return (
            "disambiguation" in lower_html
            or "may refer to" in lower_html
            or "this article is about" in lower_html
        )

    def _extract_disambiguation_options(self, html: str) -> list[str]:
        """Extract options from a disambiguation page.

        Args:
            html: HTML content of disambiguation page

        Returns:
            List of possible article titles
        """
        # Simple extraction - look for links
        # This is a basic implementation; could be improved with proper HTML parsing
        options = []

        # Extract href="/wiki/..." links
        import re

        pattern = r'href="/wiki/([^"#]+)"'
        matches = re.findall(pattern, html)

        for match in matches[:10]:  # Limit to first 10 options
            # Convert URL format back to title format
            title = match.replace("_", " ")
            if title not in options and not title.startswith("Wikipedia:"):
                options.append(title)

        return options
