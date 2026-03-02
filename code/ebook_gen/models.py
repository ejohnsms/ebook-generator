"""Data models for the ebook generation pipeline."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


# Available image styles: (display_label, prompt_value)
IMAGE_STYLES = [
    ("Photorealism / Hyperrealism", "photo-realistic"),
    ("Cinematic", "cinematic"),
    ("Anime / Ghibli Style", "anime, studio ghibli style"),
    ("3D Render / Isometric", "3D render, isometric"),
    ("Cyberpunk", "cyberpunk, neon-lit"),
    ("Oil Painting / Classic Art", "oil painting, painterly"),
    ("Minimalist", "minimalist, clean design"),
    ("Pop Art", "pop art, bold colors"),
    ("Papercraft / Papercut", "papercraft, paper cutout"),
    ("Watercolor", "watercolor, soft watercolor"),
]

# Quick lookup: value → label (for display purposes)
IMAGE_STYLE_VALUES = [v for _, v in IMAGE_STYLES]


class Theme(Enum):
    """Available story themes."""

    UNMODIFIED = "unmodified"
    CYBERPUNK = "cyberpunk"
    CARIBBEAN_VILLAGE = "caribbean_village"
    STEAMPUNK = "steampunk"
    FAIRY_TALE_DARK = "fairy_tale_dark"
    SPACE_OPERA = "space_opera"


class ContentRating(Enum):
    """Content rating categories."""

    NONE = "none"  # used for UNMODIFIED theme
    G = "G"
    PG = "PG"
    PG13 = "PG-13"
    R = "R"


class ImageMode(Enum):
    """Image generation mode (three-tier quality progression)."""

    PREVIEW = "preview"  # low-res, fast model (4b), for prompt testing
    DRAFT = "draft"      # medium-res, standard model (4b), for layout review
    FINAL = "final"      # high-res, best model (9b), for publication


class ImageStatus(Enum):
    """Image generation status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AudioStatus(Enum):
    """Audio generation status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepStatus(Enum):
    """Pipeline step status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StoryConfig:
    """Configuration for a story generation run."""

    story_id: str  # slug, e.g. "three-billy-goats-gruff"
    title: str  # human-readable title
    source_file: str  # path to the source .txt or .md file
    source_language: str = "en"
    theme: Theme = Theme.UNMODIFIED
    content_rating: ContentRating = ContentRating.NONE
    target_languages: list[str] = field(default_factory=lambda: ["en"])
    ollama_text_model: str = "llama3.1:8b"
    ollama_prompt_model: str = "brxce/stable-diffusion-prompt-generator"
    ollama_image_model_preview: str = "x/flux2-klein:4b"
    ollama_image_model_draft: str = "x/flux2-klein:4b"
    ollama_image_model_final: str = "x/flux2-klein:9b"
    image_mode: ImageMode = ImageMode.PREVIEW
    layout_style: str = "traditional"  # Layout style: traditional, manga, graphic-novel, webtoon, cinematic
    image_style: str = "photo-realistic"  # Visual style injected into every image prompt
    audio_languages: list[str] = field(default_factory=list)
    voice_preferences: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    modified_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "story_id": self.story_id,
            "title": self.title,
            "source_file": self.source_file,
            "source_language": self.source_language,
            "theme": self.theme.value,
            "content_rating": self.content_rating.value,
            "target_languages": self.target_languages,
            "ollama_text_model": self.ollama_text_model,
            "ollama_prompt_model": self.ollama_prompt_model,
            "ollama_image_model_preview": self.ollama_image_model_preview,
            "ollama_image_model_draft": self.ollama_image_model_draft,
            "ollama_image_model_final": self.ollama_image_model_final,
            "image_mode": self.image_mode.value,
            "layout_style": self.layout_style,
            "image_style": self.image_style,
            "audio_languages": self.audio_languages,
            "voice_preferences": self.voice_preferences,
            "created_at": self.created_at.isoformat(),
            "modified_at": self.modified_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StoryConfig":
        """Create from dictionary (JSON deserialization)."""
        return cls(
            story_id=data["story_id"],
            title=data["title"],
            source_file=data["source_file"],
            source_language=data.get("source_language", "en"),
            theme=Theme(data.get("theme", "unmodified")),
            content_rating=ContentRating(data.get("content_rating", "none")),
            target_languages=data.get("target_languages", ["en"]),
            ollama_text_model=data.get("ollama_text_model", "llama3.1:8b"),
            ollama_prompt_model=data.get(
                "ollama_prompt_model", "brxce/stable-diffusion-prompt-generator"
            ),
            ollama_image_model_preview=data.get("ollama_image_model_preview", "x/flux2-klein:4b"),
            ollama_image_model_draft=data.get("ollama_image_model_draft", "x/flux2-klein:4b"),
            ollama_image_model_final=data.get("ollama_image_model_final", "x/flux2-klein:9b"),
            image_mode=ImageMode(data.get("image_mode", "preview")),
            layout_style=data.get("layout_style", "traditional"),
            image_style=data.get("image_style", "photo-realistic"),
            audio_languages=data.get("audio_languages", []),
            voice_preferences=data.get("voice_preferences", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            modified_at=datetime.fromisoformat(data["modified_at"]),
        )


@dataclass
class ImageRecord:
    """Record for a single image in the prompts CSV."""

    image_id: str
    name: str
    description: str
    prompt: str
    model: str
    target_filename: str
    status: ImageStatus = ImageStatus.PENDING
    width: int = 1024
    height: int = 768
    seed: int = 42

    def to_csv_row(self) -> dict:
        """Convert to CSV row dictionary."""
        return {
            "image_id": self.image_id,
            "name": self.name,
            "description": self.description,
            "prompt": self.prompt,
            "model": self.model,
            "target_filename": self.target_filename,
            "status": self.status.value,
            "width": str(self.width),
            "height": str(self.height),
            "seed": str(self.seed),
        }

    @classmethod
    def from_csv_row(cls, row: dict) -> "ImageRecord":
        """Create from CSV row dictionary."""
        return cls(
            image_id=row["image_id"],
            name=row["name"],
            description=row["description"],
            prompt=row["prompt"],
            model=row["model"],
            target_filename=row["target_filename"],
            status=ImageStatus(row["status"]),
            width=int(row["width"]),
            height=int(row["height"]),
            seed=int(row["seed"]),
        )


@dataclass
class AudioRecord:
    """Record for a single audio track in the audio_tracks.csv."""

    audio_id: str
    language: str
    voice: str
    text_length: int
    target_filename: str
    status: AudioStatus = AudioStatus.PENDING
    duration_seconds: float = 0.0

    def to_csv_row(self) -> dict:
        """Convert to CSV row dictionary."""
        return {
            "audio_id": self.audio_id,
            "language": self.language,
            "voice": self.voice,
            "text_length": str(self.text_length),
            "target_filename": self.target_filename,
            "status": self.status.value,
            "duration_seconds": str(self.duration_seconds),
        }

    @classmethod
    def from_csv_row(cls, row: dict) -> "AudioRecord":
        """Create from CSV row dictionary."""
        return cls(
            audio_id=row["audio_id"],
            language=row["language"],
            voice=row["voice"],
            text_length=int(row["text_length"]),
            target_filename=row["target_filename"],
            status=AudioStatus(row["status"]),
            duration_seconds=float(row["duration_seconds"]),
        )


@dataclass
class PipelineStep:
    """Record for a single pipeline step in the state CSV."""

    step: int
    name: str
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: str = ""
    attempts: int = 0
    output_artifact: str = ""

    def to_csv_row(self) -> dict:
        """Convert to CSV row dictionary."""
        return {
            "step": str(self.step),
            "name": self.name,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else ""
            ),
            "error_message": self.error_message,
            "attempts": str(self.attempts),
            "output_artifact": self.output_artifact,
        }

    @classmethod
    def from_csv_row(cls, row: dict) -> "PipelineStep":
        """Create from CSV row dictionary."""
        return cls(
            step=int(row["step"]),
            name=row["name"],
            status=StepStatus(row["status"]),
            started_at=(
                datetime.fromisoformat(row["started_at"])
                if row["started_at"]
                else None
            ),
            completed_at=(
                datetime.fromisoformat(row["completed_at"])
                if row["completed_at"]
                else None
            ),
            error_message=row["error_message"],
            attempts=int(row["attempts"]),
            output_artifact=row["output_artifact"],
        )


# Pipeline step definitions
PIPELINE_STEPS = [
    (1, "story_fetch"),
    (2, "story_modification"),
    (3, "content_rating"),
    (4, "translation"),
    (5, "prompt_generation"),
    (6, "image_generation"),
    (7, "ebook_compilation"),
    (8, "audio_generation"),
]
