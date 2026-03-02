"""File fetcher component (Step 1) — reads a local text or Markdown file.

Replaces URL-based fetching with direct file reading so the user can supply
a clean, pre-edited story source without fighting web-page noise.
"""

from datetime import datetime
from pathlib import Path

from .wikipedia_fetcher import WikiFetchOutput


class FileFetcher:
    """Reads a local .txt or .md file and copies it into the story directory.

    Returns WikiFetchOutput for pipeline compatibility.
    """

    SUPPORTED_EXTENSIONS = {".txt", ".md"}

    def execute(self, source_file: Path, title: str, output_dir: Path) -> WikiFetchOutput:
        """Read source_file and save its content as raw.md.

        Args:
            source_file: Path to a .txt or .md file containing the story.
            title: Story title (used for the Markdown header).
            output_dir: Directory to write raw.md into.

        Returns:
            WikiFetchOutput with path to saved file.

        Raises:
            FileNotFoundError: If source_file does not exist.
            ValueError: If the file extension is not supported.
        """
        source_file = Path(source_file)

        if not source_file.exists():
            raise FileNotFoundError(f"Story file not found: {source_file}")

        if source_file.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '{source_file.suffix}'. "
                f"Use one of: {', '.join(sorted(self.SUPPORTED_EXTENSIONS))}"
            )

        content = source_file.read_text(encoding="utf-8")

        header = (
            f"# {title}\n\n"
            f"<!-- Source: {source_file} -->\n"
            f"<!-- Fetched: {datetime.utcnow().isoformat()} -->\n\n"
        )
        raw_content = header + content

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "raw.md"
        output_path.write_text(raw_content, encoding="utf-8")

        return WikiFetchOutput(
            raw_markdown_path=output_path,
            title=title,
            source_url=str(source_file),
            fetch_timestamp=datetime.utcnow(),
        )
