"""Tests for markdown utilities."""

import pytest

from ebook_gen.utils.markdown import (
    extract_annotations,
    strip_annotations,
    strip_all_html_comments,
    insert_annotation,
    has_annotation,
    get_annotation_count,
    extract_image_descriptions,
    split_into_sections,
)


class TestExtractAnnotations:
    """Tests for extract_annotations."""

    def test_extract_single_annotation(self):
        """Test extracting a single annotation."""
        text = "Some text\n<!-- IMAGE: A beautiful scene -->\nMore text"
        annotations = extract_annotations(text, "IMAGE")

        assert len(annotations) == 1
        assert annotations[0].prefix == "IMAGE"
        assert annotations[0].content == "A beautiful scene"

    def test_extract_multiple_annotations(self):
        """Test extracting multiple annotations."""
        text = """
        <!-- IMAGE: Scene 1 -->
        Text here
        <!-- IMAGE: Scene 2 -->
        """
        annotations = extract_annotations(text, "IMAGE")

        assert len(annotations) == 2
        assert annotations[0].content == "Scene 1"
        assert annotations[1].content == "Scene 2"

    def test_extract_all_annotations(self):
        """Test extracting all annotation types."""
        text = """
        <!-- IMAGE: Scene -->
        <!-- THEME: Cyberpunk -->
        <!-- DIRECTOR: Moody lighting -->
        """
        annotations = extract_annotations(text)

        assert len(annotations) == 3
        prefixes = [a.prefix for a in annotations]
        assert "IMAGE" in prefixes
        assert "THEME" in prefixes
        assert "DIRECTOR" in prefixes

    def test_multiline_annotation(self):
        """Test extracting multi-line annotation."""
        text = """
        <!-- IMAGE: A complex scene
             with multiple lines
             of description -->
        """
        annotations = extract_annotations(text, "IMAGE")

        assert len(annotations) == 1
        assert "complex scene" in annotations[0].content
        assert "multiple lines" in annotations[0].content


class TestStripAnnotations:
    """Tests for strip_annotations."""

    def test_strip_specific_prefix(self):
        """Test stripping specific annotation type."""
        text = """
        Before
        <!-- IMAGE: Scene -->
        <!-- THEME: Cyberpunk -->
        After
        """
        result = strip_annotations(text, "IMAGE")

        assert "<!-- IMAGE:" not in result
        assert "<!-- THEME:" in result
        assert "Before" in result
        assert "After" in result

    def test_strip_all_annotations(self):
        """Test stripping all annotations."""
        text = """
        Before
        <!-- IMAGE: Scene -->
        <!-- THEME: Theme -->
        After
        """
        result = strip_annotations(text)

        assert "<!-- IMAGE:" not in result
        assert "<!-- THEME:" not in result
        assert "Before" in result
        assert "After" in result

    def test_preserves_regular_comments(self):
        """Test that regular HTML comments are preserved."""
        text = """
        <!-- A regular comment -->
        <!-- IMAGE: Scene -->
        """
        result = strip_annotations(text)

        assert "<!-- A regular comment -->" in result
        assert "<!-- IMAGE:" not in result


class TestStripAllHtmlComments:
    """Tests for strip_all_html_comments."""

    def test_strip_all_comments(self):
        """Test stripping all HTML comments."""
        text = """
        Before
        <!-- IMAGE: Scene -->
        <!-- Regular comment -->
        After
        """
        result = strip_all_html_comments(text)

        assert "<!--" not in result
        assert "Before" in result
        assert "After" in result


class TestInsertAnnotation:
    """Tests for insert_annotation."""

    def test_insert_after_text(self):
        """Test inserting annotation after specific text."""
        text = "Paragraph one\n\nParagraph two"
        result = insert_annotation(
            text, "IMAGE", "A scene", after_text="one"
        )

        assert "<!-- IMAGE: A scene -->" in result
        assert result.index("one") < result.index("<!-- IMAGE:")

    def test_insert_before_text(self):
        """Test inserting annotation before specific text."""
        text = "Paragraph one\n\nParagraph two"
        result = insert_annotation(
            text, "IMAGE", "A scene", before_text="two"
        )

        assert "<!-- IMAGE: A scene -->" in result
        assert result.index("<!-- IMAGE:") < result.index("two")

    def test_insert_at_end_if_no_target(self):
        """Test inserting at end if no target text."""
        text = "Some text"
        result = insert_annotation(text, "IMAGE", "A scene")

        assert result.endswith("<!-- IMAGE: A scene -->")


class TestHasAnnotation:
    """Tests for has_annotation."""

    def test_has_annotation_true(self):
        """Test checking for existing annotation."""
        text = "<!-- IMAGE: Scene -->"
        assert has_annotation(text, "IMAGE") is True

    def test_has_annotation_false(self):
        """Test checking for non-existing annotation."""
        text = "<!-- THEME: Theme -->"
        assert has_annotation(text, "IMAGE") is False


class TestGetAnnotationCount:
    """Tests for get_annotation_count."""

    def test_count_specific_prefix(self):
        """Test counting specific annotation type."""
        text = """
        <!-- IMAGE: Scene 1 -->
        <!-- IMAGE: Scene 2 -->
        <!-- THEME: Theme -->
        """
        assert get_annotation_count(text, "IMAGE") == 2

    def test_count_all_annotations(self):
        """Test counting all annotations."""
        text = """
        <!-- IMAGE: Scene -->
        <!-- THEME: Theme -->
        <!-- DIRECTOR: Note -->
        """
        assert get_annotation_count(text) == 3


class TestExtractImageDescriptions:
    """Tests for extract_image_descriptions."""

    def test_extract_image_descriptions(self):
        """Test extracting image descriptions."""
        text = """
        <!-- IMAGE: First scene -->
        Text
        <!-- IMAGE: Second scene -->
        """
        descriptions = extract_image_descriptions(text)

        assert len(descriptions) == 2
        assert "First scene" in descriptions
        assert "Second scene" in descriptions


class TestSplitIntoSections:
    """Tests for split_into_sections."""

    def test_split_by_headings(self):
        """Test splitting markdown by headings."""
        text = """# Chapter 1
Content of chapter 1

# Chapter 2
Content of chapter 2"""

        sections = split_into_sections(text)

        assert len(sections) == 2
        assert sections[0][0] == "Chapter 1"
        assert "Content of chapter 1" in sections[0][1]
        assert sections[1][0] == "Chapter 2"
        assert "Content of chapter 2" in sections[1][1]

    def test_nested_headings(self):
        """Test with nested heading levels."""
        text = """# Chapter 1
## Section 1.1
Content"""

        sections = split_into_sections(text)

        # Should split on all heading levels
        assert len(sections) == 2
        assert sections[0][0] == "Chapter 1"
        assert sections[1][0] == "Section 1.1"
