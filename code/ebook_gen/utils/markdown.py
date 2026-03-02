"""Markdown processing utilities for annotation handling."""

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Annotation:
    """Represents a parsed annotation from markdown."""

    prefix: str  # e.g., "DIRECTOR", "THEME", "IMAGE"
    content: str  # The annotation text
    start_pos: int  # Character position in original text
    end_pos: int  # Character position in original text
    line_number: Optional[int] = None  # Line number (if tracked)


def extract_annotations(
    markdown_text: str, prefix: Optional[str] = None
) -> List[Annotation]:
    """Extract HTML comment annotations from markdown text.

    Annotations use the format: <!-- PREFIX: content -->

    Args:
        markdown_text: Markdown content
        prefix: If specified, only extract annotations with this prefix
                (e.g., "IMAGE"). If None, extract all annotations.

    Returns:
        List of Annotation objects

    Examples:
        >>> text = "Text\\n<!-- IMAGE: A scene -->\\nMore text"
        >>> annotations = extract_annotations(text, "IMAGE")
        >>> annotations[0].content
        'A scene'
    """
    annotations = []

    # Pattern to match HTML comments with PREFIX: format
    # Supports multi-line comments
    if prefix:
        # Match specific prefix
        pattern = rf"<!--\s*{re.escape(prefix)}:\s*(.*?)\s*-->"
    else:
        # Match any prefix (word followed by colon)
        pattern = r"<!--\s*([A-Z_]+):\s*(.*?)\s*-->"

    for match in re.finditer(pattern, markdown_text, re.DOTALL | re.IGNORECASE):
        if prefix:
            # When prefix is specified, group 1 is the content
            annotation = Annotation(
                prefix=prefix,
                content=match.group(1).strip(),
                start_pos=match.start(),
                end_pos=match.end(),
            )
        else:
            # When prefix is not specified, group 1 is prefix, group 2 is content
            annotation = Annotation(
                prefix=match.group(1).upper(),
                content=match.group(2).strip(),
                start_pos=match.start(),
                end_pos=match.end(),
            )

        annotations.append(annotation)

    return annotations


def strip_annotations(markdown_text: str, prefix: Optional[str] = None) -> str:
    """Remove HTML comment annotations from markdown text.

    Args:
        markdown_text: Markdown content
        prefix: If specified, only strip annotations with this prefix.
                If None, strip all annotations.

    Returns:
        Markdown text with annotations removed

    Examples:
        >>> text = "Before\\n<!-- IMAGE: scene -->\\nAfter"
        >>> strip_annotations(text)
        'Before\\n\\nAfter'
    """
    if prefix:
        # Remove specific prefix annotations
        pattern = rf"<!--\s*{re.escape(prefix)}:.*?-->"
    else:
        # Remove all annotations with PREFIX: format
        pattern = r"<!--\s*[A-Z_]+:.*?-->"

    # Remove the annotations but preserve line structure
    result = re.sub(pattern, "", markdown_text, flags=re.DOTALL | re.IGNORECASE)

    # Clean up excessive blank lines that may result
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")

    return result


def strip_all_html_comments(markdown_text: str) -> str:
    """Remove all HTML comments from markdown text.

    This is more aggressive than strip_annotations() - it removes
    ALL HTML comments, not just annotated ones.

    Args:
        markdown_text: Markdown content

    Returns:
        Markdown text with all HTML comments removed

    Examples:
        >>> text = "Text<!-- any comment -->More"
        >>> strip_all_html_comments(text)
        'TextMore'
    """
    result = re.sub(r"<!--.*?-->", "", markdown_text, flags=re.DOTALL)

    # Clean up excessive blank lines
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")

    return result


def insert_annotation(
    markdown_text: str,
    prefix: str,
    content: str,
    after_text: Optional[str] = None,
    before_text: Optional[str] = None,
) -> str:
    """Insert an annotation into markdown text.

    Args:
        markdown_text: Markdown content
        prefix: Annotation prefix (e.g., "IMAGE", "THEME")
        content: Annotation content
        after_text: If specified, insert annotation after this text
        before_text: If specified, insert annotation before this text

    Returns:
        Markdown text with annotation inserted

    Note:
        If neither after_text nor before_text is specified,
        annotation is appended to the end.

    Examples:
        >>> text = "Paragraph one\\n\\nParagraph two"
        >>> insert_annotation(text, "IMAGE", "A scene", after_text="one")
        'Paragraph one\\n<!-- IMAGE: A scene -->\\n\\nParagraph two'
    """
    annotation = f"<!-- {prefix}: {content} -->"

    if after_text:
        # Find the text and insert annotation after it
        pos = markdown_text.find(after_text)
        if pos != -1:
            insert_pos = pos + len(after_text)
            return (
                markdown_text[:insert_pos]
                + "\n"
                + annotation
                + "\n"
                + markdown_text[insert_pos:]
            )

    elif before_text:
        # Find the text and insert annotation before it
        pos = markdown_text.find(before_text)
        if pos != -1:
            return (
                markdown_text[:pos]
                + annotation
                + "\n\n"
                + markdown_text[pos:]
            )

    # Default: append to end
    return markdown_text + "\n\n" + annotation


def has_annotation(markdown_text: str, prefix: str) -> bool:
    """Check if markdown text contains an annotation with given prefix.

    Args:
        markdown_text: Markdown content
        prefix: Annotation prefix to check for

    Returns:
        True if at least one annotation with this prefix exists

    Examples:
        >>> text = "<!-- IMAGE: scene -->"
        >>> has_annotation(text, "IMAGE")
        True
        >>> has_annotation(text, "THEME")
        False
    """
    pattern = rf"<!--\s*{re.escape(prefix)}:"
    return bool(re.search(pattern, markdown_text, re.IGNORECASE))


def get_annotation_count(markdown_text: str, prefix: Optional[str] = None) -> int:
    """Count annotations in markdown text.

    Args:
        markdown_text: Markdown content
        prefix: If specified, count only this prefix type.
                If None, count all annotations.

    Returns:
        Number of annotations

    Examples:
        >>> text = "<!-- IMAGE: 1 --><!-- IMAGE: 2 --><!-- THEME: x -->"
        >>> get_annotation_count(text, "IMAGE")
        2
        >>> get_annotation_count(text)
        3
    """
    return len(extract_annotations(markdown_text, prefix))


def extract_image_descriptions(markdown_text: str) -> List[str]:
    """Extract all IMAGE annotation descriptions.

    Convenience function for extracting image descriptions.

    Args:
        markdown_text: Markdown content

    Returns:
        List of image description strings

    Examples:
        >>> text = "<!-- IMAGE: Scene 1 -->\\n<!-- IMAGE: Scene 2 -->"
        >>> extract_image_descriptions(text)
        ['Scene 1', 'Scene 2']
    """
    annotations = extract_annotations(markdown_text, prefix="IMAGE")
    return [ann.content for ann in annotations]


def split_into_sections(markdown_text: str) -> List[tuple[str, str]]:
    """Split markdown into sections based on headings.

    Args:
        markdown_text: Markdown content

    Returns:
        List of (heading, content) tuples

    Examples:
        >>> text = "# Chapter 1\\nContent\\n# Chapter 2\\nMore"
        >>> sections = split_into_sections(text)
        >>> len(sections)
        2
        >>> sections[0][0]
        'Chapter 1'
    """
    sections = []
    current_heading = None
    current_content = []

    for line in markdown_text.split("\n"):
        # Check if line is a heading
        if line.startswith("#"):
            # Save previous section if exists
            if current_heading is not None:
                sections.append((current_heading, "\n".join(current_content)))

            # Start new section
            current_heading = line.lstrip("#").strip()
            current_content = []
        else:
            current_content.append(line)

    # Save last section
    if current_heading is not None:
        sections.append((current_heading, "\n".join(current_content)))

    return sections
