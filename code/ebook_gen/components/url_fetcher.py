"""Generic URL fetcher component (Step 1 alternative to WikipediaFetcher).

Fetches any HTML page and converts it to Markdown, for use when the story
source is not a Wikipedia article.
"""

from datetime import datetime
from pathlib import Path

import httpx
from markdownify import markdownify as md

from .wikipedia_fetcher import WikiFetchOutput


class UrlFetcher:
    """Fetches any HTML page and converts it to Markdown.

    Used as the Step 1 fetcher when source_url is not a Wikipedia article.
    Returns WikiFetchOutput for pipeline compatibility.
    """

    def __init__(self, timeout: int = 30):
        self._timeout = timeout

    def execute(self, url: str, title: str, output_dir: Path) -> WikiFetchOutput:
        """Fetch a URL and save its content as raw.md.

        Args:
            url: Full URL to fetch
            title: Story title (used for the Markdown header)
            output_dir: Directory to write raw.md into

        Returns:
            WikiFetchOutput with path to saved file

        Raises:
            httpx.HTTPError: Network or HTTP errors
        """
        headers = {"User-Agent": "ebook-generation/0.1 (educational use)"}
        with httpx.Client(timeout=self._timeout, headers=headers, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text

        markdown = md(
            html,
            heading_style="ATX",
            bullets="-",
            strip=["script", "style", "nav", "footer", "header"],
        )
        markdown = self._clean(markdown)

        header = f"# {title}\n\n<!-- Source: {url} -->\n<!-- Fetched: {datetime.utcnow().isoformat()} -->\n\n"
        content = header + markdown

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "raw.md"
        output_path.write_text(content, encoding="utf-8")

        return WikiFetchOutput(
            raw_markdown_path=output_path,
            title=title,
            source_url=url,
            fetch_timestamp=datetime.utcnow(),
        )

    def _clean(self, markdown: str) -> str:
        """Collapse excessive blank lines."""
        import re
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        return markdown.strip()
