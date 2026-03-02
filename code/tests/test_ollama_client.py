"""Tests for OllamaClient."""

import pytest
import httpx
from unittest.mock import Mock, patch

from ebook_gen.ollama.client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaGenerationError,
    OllamaModelNotFoundError,
)
from ebook_gen.config import OllamaConfig


class TestOllamaClient:
    """Tests for OllamaClient."""

    def test_health_check_success(self):
        """Test successful health check."""
        config = OllamaConfig(base_url="http://localhost:11434")

        with patch("httpx.Client.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            client = OllamaClient(config)
            assert client.health_check() is True
            client.close()

    def test_health_check_failure(self):
        """Test failed health check."""
        config = OllamaConfig(base_url="http://localhost:11434")

        with patch("httpx.Client.get") as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")

            client = OllamaClient(config)
            assert client.health_check() is False
            client.close()

    def test_list_models_success(self):
        """Test listing models."""
        config = OllamaConfig(base_url="http://localhost:11434")

        with patch("httpx.Client.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "models": [
                    {"name": "llama3.1:8b"},
                    {"name": "qwen2.5:7b"},
                ]
            }
            mock_get.return_value = mock_response

            client = OllamaClient(config)
            models = client.list_models()

            assert len(models) == 2
            assert "llama3.1:8b" in models
            assert "qwen2.5:7b" in models
            client.close()

    def test_generate_text_success(self):
        """Test successful text generation."""
        config = OllamaConfig(base_url="http://localhost:11434")

        with patch("httpx.Client.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "response": "Generated text response"
            }
            mock_post.return_value = mock_response

            client = OllamaClient(config)
            result = client.generate_text(
                model="llama3.1:8b",
                prompt="Test prompt",
                system="Test system"
            )

            assert result == "Generated text response"
            client.close()

    def test_generate_text_model_not_found(self):
        """Test generation with missing model."""
        config = OllamaConfig(base_url="http://localhost:11434")

        with patch("httpx.Client.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_post.return_value = mock_response

            client = OllamaClient(config)

            with pytest.raises(OllamaModelNotFoundError):
                client.generate_text(
                    model="nonexistent:model",
                    prompt="Test"
                )

            client.close()

    def test_generate_text_connection_error_retry(self):
        """Test connection error with retry."""
        config = OllamaConfig(base_url="http://localhost:11434")

        with patch("httpx.Client.post") as mock_post:
            # First two attempts fail, third succeeds
            mock_post.side_effect = [
                httpx.ConnectError("Connection failed"),
                httpx.ConnectError("Connection failed"),
                Mock(
                    status_code=200,
                    json=lambda: {"response": "Success after retry"}
                ),
            ]

            with patch("time.sleep"):  # Mock sleep to speed up test
                client = OllamaClient(config)
                result = client.generate_text(
                    model="llama3.1:8b",
                    prompt="Test"
                )

                assert result == "Success after retry"
                assert mock_post.call_count == 3
                client.close()

    def test_generate_text_max_retries_exceeded(self):
        """Test that max retries are respected."""
        config = OllamaConfig(base_url="http://localhost:11434")

        with patch("httpx.Client.post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection failed")

            with patch("time.sleep"):  # Mock sleep
                client = OllamaClient(config)

                with pytest.raises(OllamaConnectionError):
                    client.generate_text(
                        model="llama3.1:8b",
                        prompt="Test"
                    )

                # Should try max_attempts times (default 3)
                assert mock_post.call_count == 3
                client.close()

    def test_context_manager(self):
        """Test using client as context manager."""
        config = OllamaConfig(base_url="http://localhost:11434")

        with OllamaClient(config) as client:
            assert client is not None

        # Client should be closed after context exit
        # (No easy way to test this without implementation details)
