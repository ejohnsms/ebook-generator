"""Tests for file I/O utilities."""

import pytest
from pathlib import Path

from ebook_gen.utils.file_io import (
    atomic_write,
    ensure_directory,
    safe_read_text,
    safe_write_text,
)


class TestAtomicWrite:
    """Tests for atomic_write."""

    def test_write_string(self, tmp_path):
        """Test writing a string."""
        file_path = tmp_path / "test.txt"
        content = "Hello, world!"

        atomic_write(file_path, content)

        assert file_path.exists()
        assert file_path.read_text() == content

    def test_write_bytes(self, tmp_path):
        """Test writing bytes."""
        file_path = tmp_path / "test.bin"
        content = b"\x00\x01\x02\x03"

        atomic_write(file_path, content)

        assert file_path.exists()
        assert file_path.read_bytes() == content

    def test_overwrite_existing(self, tmp_path):
        """Test overwriting an existing file."""
        file_path = tmp_path / "test.txt"
        file_path.write_text("Old content")

        atomic_write(file_path, "New content")

        assert file_path.read_text() == "New content"

    def test_creates_parent_directory(self, tmp_path):
        """Test that parent directories are created."""
        file_path = tmp_path / "subdir" / "nested" / "test.txt"

        atomic_write(file_path, "Content")

        assert file_path.exists()
        assert file_path.read_text() == "Content"

    def test_no_tmp_file_left_behind(self, tmp_path):
        """Test that temporary file is cleaned up."""
        file_path = tmp_path / "test.txt"

        atomic_write(file_path, "Content")

        # Check no .tmp file exists
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


class TestEnsureDirectory:
    """Tests for ensure_directory."""

    def test_create_new_directory(self, tmp_path):
        """Test creating a new directory."""
        new_dir = tmp_path / "new_directory"

        ensure_directory(new_dir)

        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_create_nested_directories(self, tmp_path):
        """Test creating nested directories."""
        nested_dir = tmp_path / "a" / "b" / "c"

        ensure_directory(nested_dir)

        assert nested_dir.exists()
        assert nested_dir.is_dir()

    def test_existing_directory(self, tmp_path):
        """Test that existing directory is not modified."""
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()
        test_file = existing_dir / "test.txt"
        test_file.write_text("Content")

        ensure_directory(existing_dir)

        assert existing_dir.exists()
        assert test_file.exists()


class TestSafeReadText:
    """Tests for safe_read_text."""

    def test_read_existing_file(self, tmp_path):
        """Test reading an existing file."""
        file_path = tmp_path / "test.txt"
        content = "Test content"
        file_path.write_text(content)

        result = safe_read_text(file_path)

        assert result == content

    def test_read_nonexistent_file(self, tmp_path):
        """Test reading a nonexistent file raises error."""
        file_path = tmp_path / "nonexistent.txt"

        with pytest.raises(FileNotFoundError):
            safe_read_text(file_path)

    def test_read_utf8(self, tmp_path):
        """Test reading UTF-8 encoded file."""
        file_path = tmp_path / "utf8.txt"
        content = "Hello 世界 🌍"
        file_path.write_text(content, encoding="utf-8")

        result = safe_read_text(file_path)

        assert result == content


class TestSafeWriteText:
    """Tests for safe_write_text."""

    def test_write_new_file(self, tmp_path):
        """Test writing a new file."""
        file_path = tmp_path / "test.txt"
        content = "Test content"

        safe_write_text(file_path, content)

        assert file_path.exists()
        assert file_path.read_text() == content

    def test_overwrite_file(self, tmp_path):
        """Test overwriting an existing file."""
        file_path = tmp_path / "test.txt"
        file_path.write_text("Old content")

        safe_write_text(file_path, "New content")

        assert file_path.read_text() == "New content"

    def test_write_utf8(self, tmp_path):
        """Test writing UTF-8 content."""
        file_path = tmp_path / "utf8.txt"
        content = "Hello 世界 🌍"

        safe_write_text(file_path, content)

        assert file_path.read_text() == content
