"""Configuration management for ebook generation."""

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class StorageBackend(str, Enum):
    """Storage backend selection.

    filesystem: Local disk (default, current behavior).
    minio:      S3-compatible object storage (microservices target).
    """

    FILESYSTEM = "filesystem"
    MINIO = "minio"


class StateBackend(str, Enum):
    """Pipeline state backend selection.

    csv:      Local CSV files (default, current behavior).
    postgres: PostgreSQL (microservices target).
    """

    CSV = "csv"
    POSTGRES = "postgres"


@dataclass
class MinioConfig:
    """Configuration for MinIO (S3-compatible) object storage.

    Activated when STORAGE_BACKEND=minio.
    """

    endpoint: str = "localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket: str = "ebook-gen"
    secure: bool = False

    @classmethod
    def from_env(cls) -> "MinioConfig":
        """Create configuration from environment variables."""
        return cls(
            endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            bucket=os.getenv("MINIO_BUCKET", "ebook-gen"),
            secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
        )


@dataclass
class PostgresConfig:
    """Configuration for PostgreSQL state database.

    Activated when STATE_BACKEND=postgres.
    """

    host: str = "localhost"
    port: int = 5432
    database: str = "ebook_gen"
    user: str = "ebook_gen"
    password: str = ""
    pool_min: int = 1
    pool_max: int = 5

    @classmethod
    def from_env(cls) -> "PostgresConfig":
        """Create configuration from environment variables."""
        return cls(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "ebook_gen"),
            user=os.getenv("POSTGRES_USER", "ebook_gen"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            pool_min=int(os.getenv("POSTGRES_POOL_MIN", "1")),
            pool_max=int(os.getenv("POSTGRES_POOL_MAX", "5")),
        )

    @property
    def dsn(self) -> str:
        """PostgreSQL DSN string."""
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


@dataclass
class RedisConfig:
    """Configuration for Redis cache.

    Used for Ollama health cache, job status hot path, and story text cache.
    """

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""
    # TTL values (seconds)
    ollama_health_ttl: int = 60
    job_status_ttl: int = 5
    story_text_ttl: int = 300

    @classmethod
    def from_env(cls) -> "RedisConfig":
        """Create configuration from environment variables."""
        return cls(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD", ""),
            ollama_health_ttl=int(os.getenv("REDIS_OLLAMA_TTL", "60")),
            job_status_ttl=int(os.getenv("REDIS_JOB_STATUS_TTL", "5")),
            story_text_ttl=int(os.getenv("REDIS_STORY_TEXT_TTL", "300")),
        )


@dataclass
class OllamaConfig:
    """Configuration for Ollama client."""

    base_url: str = "http://localhost:11434"
    timeout_seconds: int = 300  # image generation can be slow
    max_retries: int = 3
    retry_delay_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> "OllamaConfig":
        """Create configuration from environment variables."""
        return cls(
            base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            timeout_seconds=int(os.getenv("OLLAMA_TIMEOUT", "300")),
            max_retries=int(os.getenv("OLLAMA_MAX_RETRIES", "3")),
            retry_delay_seconds=float(os.getenv("OLLAMA_RETRY_DELAY", "2.0")),
        )


# Default models for the MLX backend (Hugging Face repo ids, cached under HF_HOME).
# Image tiers: preview/draft share the fast 4B model; final uses 9B.
# Note: FLUX.2-klein-9B is under the FLUX non-commercial license; 4B and
# Z-Image-Turbo are Apache-2.0.
DEFAULT_TEXT_MODEL = "mlx-community/gemma-4-12B-it-qat-4bit"
DEFAULT_IMAGE_MODEL_PREVIEW = "mflux-community/flux2-klein-4b-mflux-q4"
DEFAULT_IMAGE_MODEL_DRAFT = "mflux-community/flux2-klein-4b-mflux-q4"
DEFAULT_IMAGE_MODEL_FINAL = "mflux-community/flux2-klein-9b-mflux-q4"

# Ollama tags saved in older metadata.json / prompts.csv files, mapped to their
# MLX equivalents so existing projects resume on the MLX backend.
LEGACY_MODEL_ALIASES = {
    "gemma4:12b": DEFAULT_TEXT_MODEL,
    "llama3.1:8b": DEFAULT_TEXT_MODEL,
    "brxce/stable-diffusion-prompt-generator": DEFAULT_TEXT_MODEL,
    "brxce/stable-diffusion-prompt-generator:latest": DEFAULT_TEXT_MODEL,
    "x/flux2-klein": DEFAULT_IMAGE_MODEL_PREVIEW,
    "x/flux2-klein:latest": DEFAULT_IMAGE_MODEL_PREVIEW,
    "x/flux2-klein:4b": DEFAULT_IMAGE_MODEL_PREVIEW,
    "x/flux2-klein:9b": DEFAULT_IMAGE_MODEL_FINAL,
    "x/z-image-turbo": "mflux-community/z-image-turbo-mflux-q8",
    "x/z-image-turbo:latest": "mflux-community/z-image-turbo-mflux-q8",
}


class BackendKind(str, Enum):
    """Which model runner the pipeline uses.

    mlx:    In-process MLX (mlx-lm for text, mflux for images). Apple Silicon only.
    ollama: Ollama HTTP API. Text only: Ollama dropped image generation in v0.32.6.
    """

    MLX = "mlx"
    OLLAMA = "ollama"


@dataclass
class BackendConfig:
    """Selects and configures the model backend."""

    kind: BackendKind = BackendKind.MLX
    ollama: OllamaConfig = field(default_factory=OllamaConfig)

    @classmethod
    def from_env(cls) -> "BackendConfig":
        """Create configuration from environment variables (EBOOK_GEN_BACKEND)."""
        return cls(
            kind=BackendKind(os.getenv("EBOOK_GEN_BACKEND", BackendKind.MLX.value)),
            ollama=OllamaConfig.from_env(),
        )


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0


@dataclass
class ProjectConfig:
    """Project-level configuration."""

    root_dir: Path
    projects_dir: Path  # root/projects/ — one subdirectory per story
    storage_backend: StorageBackend = StorageBackend.FILESYSTEM
    state_backend: StateBackend = StateBackend.CSV

    @classmethod
    def from_root(cls, root_dir: Path) -> "ProjectConfig":
        """Create configuration from project root directory."""
        root_dir = root_dir.resolve()
        return cls(
            root_dir=root_dir,
            projects_dir=root_dir / "projects",
            storage_backend=StorageBackend(
                os.getenv("STORAGE_BACKEND", StorageBackend.FILESYSTEM.value)
            ),
            state_backend=StateBackend(
                os.getenv("STATE_BACKEND", StateBackend.CSV.value)
            ),
        )

    def ensure_directories(self) -> None:
        """Ensure the top-level projects directory exists."""
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def get_story_dir(self, story_id: str) -> Path:
        """Project root for a story — story files (raw.md, story.md, …) live here."""
        return self.projects_dir / story_id

    def get_prompts_dir(self, story_id: str) -> Path:
        return self.projects_dir / story_id / "prompts"

    def get_images_dir(self, story_id: str) -> Path:
        return self.projects_dir / story_id / "images"

    def get_compiled_dir(self, story_id: str) -> Path:
        return self.projects_dir / story_id / "compiled"

    def get_progress_dir(self, story_id: str) -> Path:
        return self.projects_dir / story_id / "progress"

    def get_audio_dir(self, story_id: str) -> Path:
        return self.projects_dir / story_id / "audio"


# Theme-specific system prompts for story modification
THEME_PROMPTS = {
    "cyberpunk": """You are a creative writer who adapts traditional stories into cyberpunk settings.

Your task is to rewrite the given story while:
- Maintaining the original narrative arc and character relationships
- Transplanting all elements into a near-future dystopian megacity
- Replacing magical elements with technology (AI, cybernetics, holograms)
- Adding cyberpunk atmosphere: neon lights, rain, corporate dystopia, digital divide
- Preserving the moral and thematic core of the original story

Add these annotations to guide the pipeline:
- <!-- DIRECTOR: ... --> for staging, mood, and pacing notes
- <!-- THEME: ... --> to explain how this passage connects to cyberpunk themes
- <!-- IMAGE: ... --> at key visual moments (2-3 per chapter)

Structure your output with proper Markdown headings for chapters.""",
    "caribbean_village": """You are a creative writer who adapts traditional stories into Caribbean village settings.

Your task is to rewrite the given story while:
- Maintaining the original narrative arc and character relationships
- Transplanting all elements into a vibrant Caribbean coastal village
- Incorporating Caribbean culture, food, music, and landscape
- Adding cultural authenticity: local dialects, traditions, community values
- Preserving the moral and thematic core of the original story

Add these annotations to guide the pipeline:
- <!-- DIRECTOR: ... --> for staging, mood, and pacing notes
- <!-- THEME: ... --> to explain cultural adaptations and thematic connections
- <!-- IMAGE: ... --> at key visual moments (2-3 per chapter)

Structure your output with proper Markdown headings for chapters.""",
    "steampunk": """You are a creative writer who adapts traditional stories into steampunk settings.

Your task is to rewrite the given story while:
- Maintaining the original narrative arc and character relationships
- Transplanting all elements into a Victorian-era world with advanced steam technology
- Replacing magical elements with mechanical inventions and clockwork
- Adding steampunk atmosphere: airships, brass goggles, coal smoke, gears
- Preserving the moral and thematic core of the original story

Add these annotations to guide the pipeline:
- <!-- DIRECTOR: ... --> for staging, mood, and pacing notes
- <!-- THEME: ... --> to explain how this passage uses steampunk elements
- <!-- IMAGE: ... --> at key visual moments (2-3 per chapter)

Structure your output with proper Markdown headings for chapters.""",
    "fairy_tale_dark": """You are a creative writer who adapts traditional stories into dark fairy tale retellings.

Your task is to rewrite the given story while:
- Maintaining the original narrative arc and character relationships
- Deepening the psychological complexity and moral ambiguity
- Adding gothic atmosphere: dark forests, ancient magic, moral choices
- Exploring darker themes while keeping within the target content rating
- Preserving the archetypal power of the original story

Add these annotations to guide the pipeline:
- <!-- DIRECTOR: ... --> for staging, mood, and pacing notes
- <!-- THEME: ... --> to explain symbolic and thematic depth
- <!-- IMAGE: ... --> at key visual moments (2-3 per chapter)

Structure your output with proper Markdown headings for chapters.""",
    "space_opera": """You are a creative writer who adapts traditional stories into space opera settings.

Your task is to rewrite the given story while:
- Maintaining the original narrative arc and character relationships
- Transplanting all elements into a galactic civilization
- Replacing traditional settings with planets, space stations, and starships
- Adding space opera elements: alien species, FTL travel, planetary politics
- Preserving the moral and thematic core of the original story

Add these annotations to guide the pipeline:
- <!-- DIRECTOR: ... --> for staging, mood, and pacing notes
- <!-- THEME: ... --> to explain how this passage uses space opera conventions
- <!-- IMAGE: ... --> at key visual moments (2-3 per chapter)

Structure your output with proper Markdown headings for chapters.""",
}
