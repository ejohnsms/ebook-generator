"""Pytest configuration and shared fixtures."""

import pytest
from pathlib import Path


@pytest.fixture
def fixture_dir() -> Path:
    """Return the path to the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace with standard directory structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "stories").mkdir()
    (workspace / "prompts").mkdir()
    (workspace / "images").mkdir()
    (workspace / "compiled").mkdir()
    (workspace / "progress").mkdir()
    return workspace
