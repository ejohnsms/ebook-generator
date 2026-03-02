"""Ebook compilation component (Step 7).

Assembles translated story text and generated images into ePub and PDF
for each target language. Produces draft-suffixed files for preview/draft
modes and clean filenames for final mode.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models import ImageStatus, StoryConfig
from ..utils.csv_io import read_image_records
from ..utils.markdown import strip_all_html_comments

logger = logging.getLogger(__name__)

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>
    body {{ font-family: Georgia, "Times New Roman", serif;
           max-width: 700px; margin: 0 auto; padding: 2em; line-height: 1.7; }}
    h1 {{ text-align: center; font-size: 2em; margin-bottom: 0.3em; }}
    h2 {{ font-size: 1.4em; margin-top: 2em; border-bottom: 1px solid #ccc; }}
    h3 {{ font-size: 1.15em; margin-top: 1.5em; }}
    .cover {{ text-align: center; margin: 1.5em 0 2.5em; }}
    .cover img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
    figure {{ text-align: center; margin: 1.5em 0; page-break-inside: avoid; }}
    figure img {{ max-width: 100%; height: auto; }}
    figcaption {{ font-style: italic; color: #555; font-size: 0.85em; margin-top: 0.3em; }}
    p {{ margin: 0.8em 0; text-align: justify; }}
  </style>
</head>
<body>
<h1>{title}</h1>
{cover_html}
{body}
</body>
</html>
"""


@dataclass
class EbookCompileInput:
    """Input for ebook compiler."""

    story_config: StoryConfig
    story_dir: Path          # stories/<story>/
    images_dir: Path         # images/<story>/
    prompts_csv_path: Path   # prompts/<story>/prompts.csv
    output_dir: Path         # compiled/<story>/


@dataclass
class EbookCompileOutput:
    """Output from ebook compiler."""

    compiled_files: list[Path] = field(default_factory=list)


class EbookCompiler:
    """Compiles annotated story markdown + images into ePub and PDF.

    For each target language:
      1. Reads the translated story file (story_<lang>.md or story.md).
      2. Strips all pipeline annotations.
      3. Converts Markdown → HTML, inserting scene images after section headings.
      4. Writes an ePub with embedded images via ebooklib.
      5. Writes a PDF via weasyprint.

    File naming:
      - preview/draft modes:  <story>_<lang>_<mode>.epub / .pdf
      - final mode:           <story>_<lang>.epub / .pdf
    """

    def execute(self, input_data: EbookCompileInput) -> EbookCompileOutput:
        """Compile ebooks for all target languages.

        Args:
            input_data: Compilation configuration

        Returns:
            Paths to all generated files
        """
        input_data.output_dir.mkdir(parents=True, exist_ok=True)

        cover_path, scene_paths = self._load_images(input_data)
        compiled_files: list[Path] = []
        mode = input_data.story_config.image_mode.value
        mode_suffix = f"_{mode}" if mode != "final" else ""

        for lang in input_data.story_config.target_languages:
            story_path = self._find_story(input_data.story_dir, lang, input_data.story_config.source_language)
            if story_path is None:
                logger.warning(f"Story file not found for language '{lang}', skipping")
                continue

            story_text = story_path.read_text(encoding="utf-8")
            title = input_data.story_config.title
            html = self._build_html(story_text, title, lang, cover_path, scene_paths)

            stem = f"{input_data.story_config.story_id}_{lang}{mode_suffix}"

            epub_path = input_data.output_dir / f"{stem}.epub"
            pdf_path = input_data.output_dir / f"{stem}.pdf"

            self._write_epub(html, title, lang, cover_path, scene_paths, epub_path)
            compiled_files.append(epub_path)
            logger.info(f"Wrote ePub: {epub_path.name}")

            self._write_pdf(html, input_data.images_dir, pdf_path)
            compiled_files.append(pdf_path)
            logger.info(f"Wrote PDF: {pdf_path.name}")

        return EbookCompileOutput(compiled_files=compiled_files)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _find_story(self, story_dir: Path, lang: str, source_lang: str) -> Path | None:
        """Return the story file path for a given language."""
        if lang == source_lang:
            candidate = story_dir / "story.md"
        else:
            candidate = story_dir / f"story_{lang}.md"
            if not candidate.exists():
                candidate = story_dir / "story.md"  # fall back to source
        return candidate if candidate.exists() else None

    def _load_images(self, input_data: EbookCompileInput) -> tuple[Path | None, list[Path]]:
        """Return (cover_path | None, [scene_path, ...]) from prompts CSV."""
        if not input_data.prompts_csv_path.exists():
            return None, []

        records = read_image_records(input_data.prompts_csv_path)
        cover: Path | None = None
        scenes: list[Path] = []

        for record in records:
            if record.status != ImageStatus.COMPLETED:
                continue
            p = input_data.images_dir / record.target_filename
            if not p.exists():
                continue
            if record.name == "cover":
                cover = p
            else:
                scenes.append(p)

        return cover, scenes

    def _build_html(
        self,
        story_text: str,
        title: str,
        lang: str,
        cover_path: Path | None,
        scene_paths: list[Path],
    ) -> str:
        """Convert story markdown to a full HTML document."""
        from markdown_it import MarkdownIt

        clean = strip_all_html_comments(story_text)
        body_html = MarkdownIt().render(clean)
        body_html = self._interleave_images(body_html, scene_paths)

        cover_html = (
            f'<div class="cover"><img src="{cover_path.name}" alt="Cover" /></div>'
            if cover_path
            else ""
        )

        return _HTML_TEMPLATE.format(
            lang=lang,
            title=title,
            cover_html=cover_html,
            body=body_html,
        )

    def _interleave_images(self, html_body: str, scene_paths: list[Path]) -> str:
        """Insert scene images after each H2/H3 heading in the HTML body."""
        if not scene_paths:
            return html_body

        images = iter(scene_paths)

        def _insert(match: re.Match) -> str:
            try:
                img = next(images)
                return (
                    f"{match.group(0)}\n"
                    f'<figure><img src="{img.name}" alt="" /></figure>\n'
                )
            except StopIteration:
                return match.group(0)

        return re.sub(r"</h[23]>", _insert, html_body)

    def _write_epub(
        self,
        html: str,
        title: str,
        lang: str,
        cover_path: Path | None,
        scene_paths: list[Path],
        output_path: Path,
    ) -> None:
        """Write an ePub file using ebooklib."""
        from ebooklib import epub

        book = epub.EpubBook()
        book.set_identifier(output_path.stem)
        book.set_title(title)
        book.set_language(lang)
        book.add_author("ebook-gen")

        # Embed all images
        all_images = ([cover_path] if cover_path else []) + scene_paths
        for img_path in all_images:
            if img_path and img_path.exists():
                item = epub.EpubImage()
                item.file_name = img_path.name
                item.media_type = "image/png"
                item.content = img_path.read_bytes()
                book.add_item(item)

        chapter = epub.EpubHtml(title=title, file_name="story.xhtml", lang=lang)
        chapter.content = html.encode("utf-8")
        book.add_item(chapter)

        book.toc = (epub.Link("story.xhtml", title, "story"),)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]

        epub.write_epub(str(output_path), book)

    def _write_pdf(self, html: str, images_dir: Path, output_path: Path) -> None:
        """Write a PDF file using weasyprint."""
        from weasyprint import HTML as WeasyprintHTML

        # base_url tells weasyprint where to resolve relative image paths
        WeasyprintHTML(
            string=html,
            base_url=str(images_dir) + "/",
        ).write_pdf(str(output_path))
