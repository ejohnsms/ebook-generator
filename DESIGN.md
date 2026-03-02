# System Design: Ebook Generation Pipeline

## Table of Contents

1. [Requirements Summary](#1-requirements-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Directory Structure](#3-directory-structure)
4. [Data Models](#4-data-models)
5. [Component Interfaces](#5-component-interfaces)
6. [Pipeline Orchestration](#6-pipeline-orchestration)
7. [Error Handling and Recovery](#7-error-handling-and-recovery)
8. [Testing Strategy](#8-testing-strategy)
9. [Docker and Environment](#9-docker-and-environment)
10. [Implementation Plan](#10-implementation-plan)
11. [Design Decisions](#11-design-decisions)
12. [Open Questions](#12-open-questions)

---

## 1. Requirements Summary

### Functional Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|-------------------|
| FR-1 | Fetch story source material from Wikipedia | Given a story title, retrieve the full article text and metadata |
| FR-2 | Apply thematic modifications to stories | Transform a base story into cyberpunk, caribbean village, or other themed variants; support "unmodified" passthrough |
| FR-3 | Assign content ratings | Tag stories as G, PG-13, etc.; unmodified stories receive no rating |
| FR-4 | Translate stories to target languages | Translate via Ollama LLM; support source-language passthrough |
| FR-5 | Generate image prompts from story text | Use Ollama to produce scene-by-scene image prompts informed by story text and theme |
| FR-6 | Generate images from prompts | Use Ollama multimodal model to produce illustrations |
| FR-7 | Compile story + images into ePub and PDF | Produce publication-ready output files |
| FR-8 | Track image metadata in CSV | Record name, description, prompt, model, target filename |
| FR-9 | Resume interrupted runs | Persist pipeline progress in CSV; restart from last successful step |
| FR-10 | Incremental image testing | Generate low-res sample images before committing to a full high-res run |

### Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Graceful error recovery | No step failure should corrupt prior work; all failures are logged and resumable |
| NFR-2 | Reproducibility | Given the same inputs and model versions, produce deterministic output |
| NFR-3 | Observability | Every pipeline run produces a structured log; progress is visible via CSV state files |
| NFR-4 | Portability | Runs identically on any machine with Docker installed |

---

## 2. Architecture Overview

### High-Level Pipeline

```
                         ebook-generation pipeline
  ===================================================================

  [1. Wikipedia     ] --> [2. Story       ] --> [3. Content  ]
  [   Fetcher       ]     [   Modifier    ]     [   Rater    ]
       |                       |                     |
       v                       v                     v
  raw_story.md           modified_story.md     rated_story.md
                                                     |
                    +--------------------------------+
                    |                                |
                    v                                v
  [4. Translator        ]            [5. Prompt Generator   ]
       |                                     |
       v                                     v
  translated_story.md              prompts.csv (per story)
                                             |
                                             v
                                  [6. Image Generator      ]
                                             |
                                             v
                                  images/<story>/  (PNG files)
                                             |
                    +------------------------+
                    |
                    v
  [7. Ebook Compiler   ] --> compiled/<story>.epub
                         --> compiled/<story>.pdf
```

### Component Architecture

```
code/
  ebook_gen/
    __init__.py
    cli.py                    # CLI entry point (click-based)
    config.py                 # Configuration dataclasses
    pipeline.py               # Pipeline orchestrator
    progress.py               # CSV-based progress tracker
    models.py                 # Shared data models / dataclasses
    components/
      __init__.py
      wikipedia_fetcher.py    # Step 1
      story_modifier.py       # Step 2
      content_rater.py        # Step 3
      translator.py           # Step 4
      prompt_generator.py     # Step 5
      image_generator.py      # Step 6
      ebook_compiler.py       # Step 7
    ollama/
      __init__.py
      client.py               # Thin wrapper around Ollama HTTP API
    utils/
      __init__.py
      markdown.py             # Markdown parsing, annotation stripping
      csv_io.py               # CSV read/write helpers
      file_io.py              # Atomic file writes, directory management
```

### Technology Stack

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Language | Python 3.12+ | Specified requirement; rich ecosystem for text/image processing |
| Package manager | pixi | Specified requirement; conda-based, reproducible environments |
| Containerization | Docker + docker-compose | Specified requirement; Ollama runs as a sibling service |
| CLI framework | click | Well-established, supports subcommands, testable |
| HTTP client | httpx | Async support, timeout handling, better than requests |
| Markdown parsing | markdown-it-py | Extensible, faithful to CommonMark, supports custom tokens |
| ePub generation | ebooklib | Mature Python library for ePub 2/3 |
| PDF generation | weasyprint | HTML/CSS to PDF; reuse the same styled HTML for both formats |
| CSV handling | Python csv module (stdlib) | Simple requirement; no need for pandas overhead |
| Logging | Python logging (stdlib) | Standard, configurable, structured via JSON formatter |
| Testing | pytest | Standard for Python |

---

## 3. Directory Structure

```
ebook-generation/                   # project root
  docker-compose.yml
  Dockerfile
  pixi.toml                        # pixi project definition
  pixi.lock
  DESIGN.md                        # this document

  code/                             # Python source
    ebook_gen/                      # package root
      (see Component Architecture above)
    tests/
      conftest.py
      test_pipeline.py
      test_wikipedia_fetcher.py
      test_story_modifier.py
      test_content_rater.py
      test_translator.py
      test_prompt_generator.py
      test_image_generator.py
      test_ebook_compiler.py
      test_progress.py
      fixtures/                     # test data
        sample_story.md
        sample_prompts.csv

  compiled/                         # output: final ebooks
    three-billy-goats-gruff/
      three-billy-goats-gruff_en.epub
      three-billy-goats-gruff_en.pdf
      three-billy-goats-gruff_es.epub
      three-billy-goats-gruff_es.pdf

  images/                           # output: generated images
    three-billy-goats-gruff/
      cover.png
      scene_01.png
      scene_02.png
      ...

  prompts/                          # image prompt CSVs
    three-billy-goats-gruff/
      prompts.csv

  stories/                          # annotated story markdown
    three-billy-goats-gruff/
      story.md                      # the annotated markdown file
      metadata.json                 # story-level metadata

  progress/                         # pipeline state (NEW -- added)
    three-billy-goats-gruff/
      pipeline_state.csv
```

**Note:** A `progress/` directory is added beyond the original spec. This keeps pipeline state separate from story content, prompts, and output. The progress CSV is the mechanism for resume capability.

---

## 4. Data Models

### 4.1 Story Metadata (`stories/<story>/metadata.json`)

```json
{
  "story_id": "three-billy-goats-gruff",
  "title": "Three Billy Goats Gruff",
  "source_url": "https://en.wikipedia.org/wiki/Three_Billy_Goats_Gruff",
  "source_language": "en",
  "theme": "cyberpunk",
  "content_rating": "PG-13",
  "target_languages": ["en", "es", "hi"],
  "created_at": "2026-02-15T10:30:00Z",
  "modified_at": "2026-02-15T11:45:00Z",
  "ollama_text_model": "llama3.1:8b",
  "ollama_prompt_model": "brxce/stable-diffusion-prompt-generator",
  "ollama_image_model_preview": "x/flux2-klein:4b",
  "ollama_image_model_draft": "x/flux2-klein:4b",
  "ollama_image_model_final": "x/flux2-klein:9b",
  "image_mode": "preview",
  "layout_style": "traditional"
}
```

**Python dataclass:**

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Theme(Enum):
    UNMODIFIED = "unmodified"
    CYBERPUNK = "cyberpunk"
    CARIBBEAN_VILLAGE = "caribbean_village"
    STEAMPUNK = "steampunk"
    FAIRY_TALE_DARK = "fairy_tale_dark"
    SPACE_OPERA = "space_opera"
    # extensible -- add new themes here


class ContentRating(Enum):
    NONE = "none"       # used for UNMODIFIED theme
    G = "G"
    PG = "PG"
    PG13 = "PG-13"
    R = "R"


class ImageMode(Enum):
    PREVIEW = "preview"   # low-res, fast model (fp8), for testing prompts
    DRAFT = "draft"       # medium-res, standard model, for layout review
    FINAL = "final"       # high-res, best model (bf16), for publication


@dataclass
class StoryConfig:
    story_id: str                           # slug, e.g. "three-billy-goats-gruff"
    title: str                              # human-readable title
    source_url: str                         # Wikipedia URL
    source_language: str = "en"
    theme: Theme = Theme.UNMODIFIED
    content_rating: ContentRating = ContentRating.NONE
    target_languages: list[str] = field(default_factory=lambda: ["en"])
    ollama_text_model: str = "llama3.1:8b"
    ollama_prompt_model: str = "brxce/stable-diffusion-prompt-generator"
    ollama_image_model_preview: str = "x/flux2-klein:4b"  # Fast, low-res for prompt testing
    ollama_image_model_draft: str = "x/flux2-klein:4b"    # Medium-res for layout review
    ollama_image_model_final: str = "x/flux2-klein:9b"    # High-quality for publication
    image_mode: ImageMode = ImageMode.PREVIEW
    layout_style: str = "traditional"  # Layout configuration (traditional, manga, graphic-novel, webtoon, cinematic)
    created_at: datetime = field(default_factory=datetime.utcnow)
    modified_at: datetime = field(default_factory=datetime.utcnow)
```

### 4.2 Annotated Story Markdown Format (`stories/<story>/story.md`)

The story file uses standard Markdown with custom annotation blocks that are stripped before compilation. Annotations use HTML comments with structured prefixes so they are invisible in any standard Markdown renderer but parseable by the pipeline.

```markdown
# Three Billy Goats Gruff

<!-- META
theme: cyberpunk
rating: PG-13
source: wikipedia
-->

<!-- DIRECTOR: Opening scene establishes the neon-lit bridge over
     a polluted canal. The youngest goat is a small courier drone
     operator. Emphasize vulnerability and the glow of holographic
     advertisements. -->

## Chapter 1: The Smallest Goat

<!-- THEME: The bridge represents the digital divide -- those who
     cross gain access to the corporate megastructure's resources.
     The troll is a rogue AI gatekeeper. -->

Once upon a time, in the sprawling undercity of Neo-Fjord, there
lived three billy goats known by their street handle: the Gruffs.

<!-- RATING: PG-13 -- The troll's threat is menacing but not
     graphic. No explicit violence in this scene. -->

The smallest Gruff needed to cross the Bifrost Bridge, a crumbling
overpass spanning the toxic runoff canal, to reach the rooftop
gardens on the other side where real grass still grew.

<!-- IMAGE: Scene showing the smallest goat approaching a
     cyberpunk bridge at night, neon lights reflecting off dark
     water below. Mood: tense, atmospheric. -->

...
```

**Annotation types and their prefixes:**

| Prefix | Purpose | Compiled into ebook? |
|--------|---------|---------------------|
| `<!-- META ... -->` | Story-level metadata (redundant with metadata.json, but inline for readability) | No |
| `<!-- DIRECTOR: ... -->` | Director notes -- staging, mood, pacing guidance for the modifier LLM | No |
| `<!-- THEME: ... -->` | Theme reinforcement -- explains how this passage connects to the chosen theme | No |
| `<!-- RATING: ... -->` | Content rating justification for this passage | No |
| `<!-- IMAGE: ... -->` | Image placement hint -- describes what illustration should appear here | No (but consumed by prompt generator) |
| `<!-- TRANSLATION_NOTE: ... -->` | Notes for the translation step (e.g., cultural adaptation guidance) | No |

**Parsing rules:**
- All `<!-- PREFIX: ... -->` blocks are stripped before ebook compilation.
- `<!-- IMAGE: ... -->` blocks are extracted by the prompt generator to seed image prompt creation.
- Regular Markdown content (headings, paragraphs, emphasis, lists) passes through to ebook compilation.
- The parser handles multi-line comments (annotations may span multiple lines).

### 4.3 Image Prompts CSV (`prompts/<story>/prompts.csv`)

```csv
image_id,name,description,prompt,model,target_filename,status,width,height,seed
img_001,cover,"Cover illustration for the story","A dramatic cyberpunk cityscape...",stable-diffusion,cover.png,pending,1024,1024,42
img_002,scene_01,"Smallest goat approaches the bridge","A small anthropomorphic goat...",stable-diffusion,scene_01.png,completed,1024,768,42
img_003,scene_02,"Troll confronts the smallest goat","A menacing rogue AI hologram...",stable-diffusion,scene_02.png,failed,1024,768,42
```

**Column definitions:**

| Column | Type | Description |
|--------|------|-------------|
| `image_id` | string | Unique identifier within the story (e.g., `img_001`) |
| `name` | string | Short human-readable name (e.g., `cover`, `scene_01`) |
| `description` | string | What the image depicts (from `<!-- IMAGE: ... -->` annotations) |
| `prompt` | string | Full prompt sent to the image generation model |
| `model` | string | Ollama model name used for generation |
| `target_filename` | string | Output filename within `images/<story>/` |
| `status` | enum | `pending`, `in_progress`, `completed`, `failed`, `skipped` |
| `width` | int | Image width in pixels |
| `height` | int | Image height in pixels |
| `seed` | int | Random seed for reproducibility |

**Python dataclass:**

```python
from dataclasses import dataclass
from enum import Enum


class ImageStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ImageRecord:
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
```

### 4.4 Pipeline State CSV (`progress/<story>/pipeline_state.csv`)

This CSV tracks the overall pipeline progress per story, enabling resume capability.

```csv
step,name,status,started_at,completed_at,error_message,attempts,output_artifact
1,wikipedia_fetch,completed,2026-02-15T10:30:00Z,2026-02-15T10:30:05Z,,1,stories/three-billy-goats-gruff/raw.md
2,story_modification,completed,2026-02-15T10:30:06Z,2026-02-15T10:31:20Z,,1,stories/three-billy-goats-gruff/story.md
3,content_rating,completed,2026-02-15T10:31:21Z,2026-02-15T10:31:22Z,,1,stories/three-billy-goats-gruff/metadata.json
4,translation,completed,2026-02-15T10:31:23Z,2026-02-15T10:35:00Z,,1,"stories/three-billy-goats-gruff/story_es.md,stories/three-billy-goats-gruff/story_hi.md"
5,prompt_generation,completed,2026-02-15T10:35:01Z,2026-02-15T10:36:00Z,,1,prompts/three-billy-goats-gruff/prompts.csv
6,image_generation,failed,2026-02-15T10:36:01Z,,Ollama connection timeout,3,
7,ebook_compilation,pending,,,,0,
```

**Column definitions:**

| Column | Type | Description |
|--------|------|-------------|
| `step` | int | Step number (1-7) |
| `name` | string | Step identifier |
| `status` | enum | `pending`, `in_progress`, `completed`, `failed`, `skipped` |
| `started_at` | ISO 8601 | When the step began |
| `completed_at` | ISO 8601 | When the step finished (empty if not done) |
| `error_message` | string | Last error message if failed |
| `attempts` | int | Number of attempts (for retry tracking) |
| `output_artifact` | string | Comma-separated relative paths to output files |

**Python dataclass:**

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class StepStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStep:
    step: int
    name: str
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: str = ""
    attempts: int = 0
    output_artifact: str = ""
```

---

## 5. Component Interfaces

Each component follows a consistent interface pattern: it takes typed input, produces typed output, and raises specific exceptions. All components are stateless -- state lives in the CSV files and on disk.

### 5.1 Base Component Protocol

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

T_In = TypeVar("T_In")
T_Out = TypeVar("T_Out")


class PipelineComponent(ABC, Generic[T_In, T_Out]):
    """Base class for all pipeline steps."""

    @abstractmethod
    def execute(self, input_data: T_In) -> T_Out:
        """
        Run this pipeline step.

        Args:
            input_data: Typed input for this step.

        Returns:
            Typed output from this step.

        Raises:
            ComponentError: If the step fails after exhausting retries.
        """
        ...

    @abstractmethod
    def validate_input(self, input_data: T_In) -> None:
        """
        Validate input before execution. Raises ValueError on bad input.
        """
        ...

    @property
    @abstractmethod
    def step_number(self) -> int:
        """The pipeline step number (1-7)."""
        ...

    @property
    @abstractmethod
    def step_name(self) -> str:
        """The pipeline step name."""
        ...
```

### 5.2 Step 1: Wikipedia Fetcher

```python
@dataclass
class WikiFetchInput:
    story_title: str            # e.g. "Three Billy Goats Gruff"
    language: str               # e.g. "en"
    output_dir: Path            # e.g. stories/three-billy-goats-gruff/


@dataclass
class WikiFetchOutput:
    raw_markdown_path: Path     # path to saved raw.md
    title: str                  # canonical title from Wikipedia
    source_url: str             # full Wikipedia URL
    fetch_timestamp: datetime


class WikipediaFetcher(PipelineComponent[WikiFetchInput, WikiFetchOutput]):

    def execute(self, input_data: WikiFetchInput) -> WikiFetchOutput:
        """
        1. Query Wikipedia API for the article by title.
        2. Extract the article text (not infoboxes, references, or see-also).
        3. Convert to Markdown.
        4. Write to output_dir/raw.md.
        5. Return metadata.

        Uses the Wikipedia REST API:
          GET https://{lang}.wikipedia.org/api/rest_v1/page/html/{title}
        Then converts HTML -> Markdown via markdownify or similar.

        Error handling:
          - 404: raise StoryNotFoundError(title)
          - Network error: retry up to 3 times with exponential backoff
          - Disambiguation page: raise DisambiguationError(title, options)
        """
        ...
```

### 5.3 Step 2: Story Modifier

```python
@dataclass
class StoryModifyInput:
    raw_markdown_path: Path     # from step 1
    story_config: StoryConfig   # contains theme selection
    output_dir: Path


@dataclass
class StoryModifyOutput:
    story_markdown_path: Path   # path to annotated story.md
    chapter_count: int
    word_count: int


class StoryModifier(PipelineComponent[StoryModifyInput, StoryModifyOutput]):

    def execute(self, input_data: StoryModifyInput) -> StoryModifyOutput:
        """
        If theme is UNMODIFIED:
          - Copy raw markdown as-is (no LLM call).
          - Add minimal META annotation.

        Otherwise:
          - Send raw text + theme description to Ollama text model.
          - System prompt instructs the model to:
              a) Rewrite the story in the target theme
              b) Preserve the narrative structure (same scenes, characters, arc)
              c) Add DIRECTOR annotations for staging guidance
              d) Add THEME annotations explaining thematic connections
              e) Add IMAGE annotations at key scene boundaries
              f) Structure output as proper Markdown with chapter headings
          - Parse and validate the LLM output.
          - Write to output_dir/story.md.

        Ollama API call:
          POST http://ollama:11434/api/generate
          {
            "model": config.ollama_text_model,
            "prompt": <constructed prompt>,
            "system": <theme-specific system prompt>,
            "stream": false
          }
        """
        ...
```

**Theme system prompt templates** are stored as constants or Jinja2 templates:

```python
THEME_PROMPTS: dict[Theme, str] = {
    Theme.CYBERPUNK: """You are a creative writer who adapts traditional
stories into cyberpunk settings. Maintain the original narrative arc
but transplant all elements into a near-future dystopian megacity.
Replace magical elements with technology. The troll becomes a rogue AI
or corporate enforcer. The bridge becomes a data highway or physical
overpass in the undercity. Add neon, rain, holograms, and corporate
dystopia. ...""",

    Theme.CARIBBEAN_VILLAGE: """You are a creative writer who adapts
traditional stories into Caribbean village settings. Maintain the
original narrative arc but transplant all elements into a vibrant
coastal village. Replace European cultural markers with Caribbean
culture, food, music, and landscape. ...""",

    # ... more themes
}
```

### 5.4 Step 3: Content Rater

```python
@dataclass
class ContentRateInput:
    story_markdown_path: Path
    story_config: StoryConfig   # contains desired rating
    output_dir: Path


@dataclass
class ContentRateOutput:
    metadata_path: Path         # updated metadata.json
    rating: ContentRating
    rating_justification: str   # brief explanation


class ContentRater(PipelineComponent[ContentRateInput, ContentRateOutput]):

    def execute(self, input_data: ContentRateInput) -> ContentRateOutput:
        """
        If theme is UNMODIFIED:
          - Set rating to NONE, skip LLM call.

        Otherwise:
          - Send story text to Ollama with a rating-analysis system prompt.
          - The LLM evaluates the story against the target rating:
              a) If content matches target rating: approve and add RATING
                 annotations.
              b) If content exceeds target rating: flag specific passages
                 and suggest softening edits.
          - Update metadata.json with the final rating.
          - Insert RATING annotations into story.md at relevant passages.

        This step modifies story.md in-place (adds annotations only,
        does not change story text).
        """
        ...
```

### 5.5 Step 4: Translator

```python
@dataclass
class TranslateInput:
    story_markdown_path: Path   # the annotated story.md (source language)
    story_config: StoryConfig   # contains target_languages list
    output_dir: Path


@dataclass
class TranslateOutput:
    translated_paths: dict[str, Path]  # language_code -> file path
    # e.g. {"en": Path("story.md"), "es": Path("story_es.md")}


class Translator(PipelineComponent[TranslateInput, TranslateOutput]):

    def execute(self, input_data: TranslateInput) -> TranslateOutput:
        """
        For each target language:
          - If language == source_language: use original file (no translation).
          - Otherwise:
              a) Strip annotations from story text (translate only prose).
              b) Send to Ollama with translation system prompt.
              c) Re-insert annotations (untranslated) into translated text
                 at corresponding positions.
              d) Add TRANSLATION_NOTE annotations where cultural
                 adaptation occurred.
              e) Write to output_dir/story_{lang_code}.md.

        Chunking strategy for long stories:
          - Split by chapter/heading boundaries.
          - Translate each chapter independently to stay within context window.
          - Maintain character name consistency across chunks by providing
            a glossary in each prompt.

        Error handling:
          - If one language fails, mark it failed but continue with others.
          - Individual language failures do not block the pipeline.
        """
        ...
```

### 5.6 Step 5: Prompt Generator

```python
@dataclass
class PromptGenInput:
    story_markdown_path: Path   # annotated story with IMAGE annotations
    story_config: StoryConfig   # theme and model info
    output_dir: Path            # prompts/<story>/


@dataclass
class PromptGenOutput:
    prompts_csv_path: Path      # path to prompts.csv
    image_count: int


class PromptGenerator(PipelineComponent[PromptGenInput, PromptGenOutput]):

    def execute(self, input_data: PromptGenInput) -> PromptGenOutput:
        """
        1. Parse story.md to extract all <!-- IMAGE: ... --> annotations.
        2. For each IMAGE annotation:
             a) Extract the surrounding story context (the passage before
                and after the annotation).
             b) Send to Ollama prompt model (brxce/stable-diffusion-prompt-generator):
                  ollama run brxce/stable-diffusion-prompt-generator "context text"
             c) The model returns a refined image generation prompt.
             d) Create an ImageRecord with the prompt and status=pending.
        3. Generate one additional prompt for the cover image, using the
           full story synopsis + theme.
        4. Write all ImageRecords to prompts.csv.

        The input to the prompt generator should include:
          - Story context (relevant passage)
          - Theme information
          - Content rating constraints
          - Desired art style (e.g., "cyberpunk digital art", "caribbean village watercolor")

        Dimensions are determined by image role:
          - Cover: 1024x1024 (square)
          - Scene illustrations: 1024x768 (landscape)
          - Chapter headers: 768x256 (wide banner)
        """
        ...
```

### 5.7 Step 6: Image Generator

```python
@dataclass
class ImageGenInput:
    prompts_csv_path: Path      # from step 5
    story_config: StoryConfig   # contains image_mode (sample vs full)
    output_dir: Path            # images/<story>/


@dataclass
class ImageGenOutput:
    images_dir: Path
    completed_count: int
    failed_count: int
    skipped_count: int


class ImageGenerator(PipelineComponent[ImageGenInput, ImageGenOutput]):

    def execute(self, input_data: ImageGenInput) -> ImageGenOutput:
        """
        1. Load prompts.csv.
        2. For each ImageRecord where status != 'completed':
             a) If image_mode is SAMPLE:
                  - Reduce dimensions by 4x (e.g., 1024x768 -> 256x192)
                  - May use faster model (x/z-image-turbo) for preview
             b) Generate image using Ollama:
                  ollama run x/flux2-klein "prompt text"
                  OR
                  ollama run x/z-image-turbo "prompt text"
             c) Save the generated image to output_dir/target_filename.
             d) Update ImageRecord status in prompts.csv:
                  - Success: status = completed
                  - Failure: status = failed, log error
             e) Write CSV after each image (for resume capability).

        Implementation notes:
          - The Ollama CLI interface for image models outputs the image directly
          - Need to capture the binary output and save to PNG file
          - For programmatic access, use Ollama HTTP API:
              POST http://ollama:11434/api/generate with prompt
          - Response format may vary by model; handle accordingly

        Resume behavior:
          - On restart, only images with status != 'completed' are generated.
          - This means a partial run can be resumed efficiently.

        Sample mode workflow:
          1. User runs with image_mode=SAMPLE.
          2. Reviews low-res images in images/<story>/.
          3. If satisfied, changes image_mode=FULL and reruns.
          4. The full run regenerates all images at full resolution.
             (status is reset to pending when mode changes)
        """
        ...
```

### 5.8 Step 7: Ebook Compiler

```python
@dataclass
class CompileInput:
    story_config: StoryConfig
    story_dir: Path             # stories/<story>/
    images_dir: Path            # images/<story>/
    prompts_csv_path: Path      # for image placement metadata
    output_dir: Path            # compiled/<story>/


@dataclass
class CompileOutput:
    epub_paths: dict[str, Path]  # language_code -> epub path
    pdf_paths: dict[str, Path]   # language_code -> pdf path


class EbookCompiler(PipelineComponent[CompileInput, CompileOutput]):

    def execute(self, input_data: CompileInput) -> CompileOutput:
        """
        For each target language:
          1. Load story_{lang}.md (or story.md for source language).
          2. Strip all annotations (<!-- PREFIX: ... -->).
          3. Parse clean Markdown into HTML.
          4. Determine image insertion points from prompts.csv:
               - Each image's description is matched to original IMAGE
                 annotation positions in the story.
               - Insert <img> tags at the corresponding positions.
          5. Apply CSS stylesheet for consistent formatting:
               - Typography: readable serif font for body, sans-serif for
                 headings.
               - Image sizing: full-width for scenes, centered for cover.
               - Page breaks before chapters.
          6. Generate ePub:
               - Use ebooklib to create ePub 3 file.
               - Embed images as ePub resources.
               - Add metadata (title, author, language, rating).
               - Add cover image.
               - Add table of contents from chapter headings.
          7. Generate PDF:
               - Use weasyprint to render the styled HTML to PDF.
               - Configure page size (e.g., 6x9 inches for standard ebook).
               - Add page numbers, headers/footers.
          8. Write to output_dir/.

        File naming convention:
          {story_id}_{language_code}.{format}
          e.g., three-billy-goats-gruff_es.epub
        """
        ...
```

### 5.9 Ollama Client

```python
@dataclass
class OllamaConfig:
    base_url: str = "http://ollama:11434"
    timeout_seconds: int = 300      # image generation can be slow
    max_retries: int = 3
    retry_delay_seconds: float = 2.0


class OllamaClient:
    """Thin wrapper around the Ollama HTTP API."""

    def __init__(self, config: OllamaConfig):
        self._config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )

    def generate_text(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
    ) -> str:
        """
        Generate text completion.

        POST /api/generate
        Returns the full response text (non-streaming).

        Raises:
            OllamaConnectionError: Cannot reach Ollama service.
            OllamaModelNotFoundError: Requested model is not pulled.
            OllamaGenerationError: Model returned an error.
        """
        ...

    def generate_image(
        self,
        model: str,
        prompt: str,
        width: int = 1024,
        height: int = 768,
        seed: int = 42,
        num_inference_steps: int | None = None,
    ) -> bytes:
        """
        Generate an image from a text prompt.

        Returns raw image bytes (PNG).

        Raises:
            OllamaConnectionError: Cannot reach Ollama service.
            OllamaModelNotFoundError: Requested model is not pulled.
            OllamaGenerationError: Model returned an error.
        """
        ...

    def list_models(self) -> list[str]:
        """
        List available models.
        GET /api/tags
        """
        ...

    def health_check(self) -> bool:
        """
        Check if Ollama is reachable and responsive.
        GET /api/tags (lightweight endpoint).
        """
        ...
```

### 5.10 CLI Interface

```python
# cli.py -- click-based CLI

@click.group()
def cli():
    """Ebook Generation Pipeline."""
    pass


@cli.command()
@click.argument("title")
@click.option("--theme", type=click.Choice([t.value for t in Theme]),
              default="unmodified")
@click.option("--rating", type=click.Choice([r.value for r in ContentRating]),
              default="none")
@click.option("--languages", multiple=True, default=("en",),
              help="Target languages (ISO 639-1 codes)")
@click.option("--text-model", default="llama3.1:8b",
              help="Ollama model for text generation")
@click.option("--prompt-model", default="brxce/stable-diffusion-prompt-generator",
              help="Ollama model for prompt generation")
@click.option("--image-model", default="x/flux2-klein",
              help="Ollama model for image generation (x/flux2-klein or x/z-image-turbo)")
@click.option("--image-mode", type=click.Choice(["sample", "full"]),
              default="sample")
@click.option("--output-format", type=click.Choice(["epub", "pdf", "both"]),
              default="both")
def generate(title, theme, rating, languages, text_model, image_model,
             image_mode, output_format):
    """
    Generate an ebook from a story title.

    Example:
      ebook-gen generate "Three Billy Goats Gruff" \
        --theme cyberpunk \
        --rating PG-13 \
        --languages en es \
        --image-mode sample
    """
    ...


@cli.command()
@click.argument("story_id")
def resume(story_id):
    """
    Resume a previously interrupted pipeline run.

    Reads progress/<story_id>/pipeline_state.csv and resumes
    from the first non-completed step.
    """
    ...


@cli.command()
@click.argument("story_id")
def status(story_id):
    """
    Show the current pipeline status for a story.

    Prints a table of all 7 steps with their status, timing,
    and any error messages.
    """
    ...


@cli.command()
@click.argument("story_id")
@click.option("--step", type=int, help="Retry a specific failed step")
def retry(story_id, step):
    """
    Retry failed steps for a story.

    Without --step: retries all failed steps in order.
    With --step N: retries only step N.
    """
    ...


@cli.command()
@click.argument("story_id")
def preview_images(story_id):
    """
    Show a summary of generated images for a story.

    Lists all images with their status, dimensions, and file paths.
    Useful for reviewing sample images before committing to a full run.
    """
    ...


@cli.command()
@click.argument("story_id")
def promote_images(story_id):
    """
    Promote sample images to full-resolution mode.

    Resets all image statuses to 'pending' and updates image_mode
    to 'full' in metadata.json, then runs the image generation step.
    """
    ...
```

---

## 6. Pipeline Orchestration

### 6.1 Pipeline Runner

```python
class PipelineRunner:
    """
    Orchestrates the 7-step pipeline with progress tracking
    and resume capability.
    """

    STEPS: list[tuple[int, str, type[PipelineComponent]]] = [
        (1, "wikipedia_fetch",    WikipediaFetcher),
        (2, "story_modification", StoryModifier),
        (3, "content_rating",     ContentRater),
        (4, "translation",        Translator),
        (5, "prompt_generation",  PromptGenerator),
        (6, "image_generation",   ImageGenerator),
        (7, "ebook_compilation",  EbookCompiler),
    ]

    def __init__(
        self,
        story_config: StoryConfig,
        project_root: Path,
        ollama_client: OllamaClient,
    ):
        self._config = story_config
        self._root = project_root
        self._ollama = ollama_client
        self._progress = ProgressTracker(
            project_root / "progress" / story_config.story_id
        )

    def run(self, start_from_step: int = 1) -> None:
        """
        Execute the pipeline from the given step.

        For each step:
          1. Check if already completed (skip if so, unless forced).
          2. Mark as in_progress in pipeline_state.csv.
          3. Construct input from prior step outputs.
          4. Call component.execute().
          5. Mark as completed (or failed) in pipeline_state.csv.
          6. Log timing and result.

        If a step fails:
          - Log the error.
          - Mark step as failed with error message and attempt count.
          - Stop the pipeline (do not proceed to later steps).
          - The user can resume later with `ebook-gen resume <story_id>`.
        """
        ...

    def resume(self) -> None:
        """
        Resume from the first non-completed step.

        Reads pipeline_state.csv, finds the first step that is
        not 'completed', and calls run(start_from_step=that_step).
        """
        ...

    def retry_step(self, step_number: int) -> None:
        """
        Retry a specific step (must be in 'failed' status).
        Increments the attempt counter.
        """
        ...
```

### 6.2 Progress Tracker

```python
class ProgressTracker:
    """
    Manages the pipeline_state.csv file for a single story.
    All mutations are atomic -- the CSV is rewritten entirely
    on each update to prevent corruption.
    """

    def __init__(self, progress_dir: Path):
        self._dir = progress_dir
        self._csv_path = progress_dir / "pipeline_state.csv"
        self._steps: list[PipelineStep] = []

    def initialize(self) -> None:
        """
        Create a fresh pipeline_state.csv with all 7 steps
        in 'pending' status. Called at the start of a new run.
        Raises FileExistsError if state already exists (use load instead).
        """
        ...

    def load(self) -> list[PipelineStep]:
        """
        Load existing pipeline state from CSV.
        Returns the list of steps.
        Raises FileNotFoundError if no state exists (use initialize instead).
        """
        ...

    def update_step(
        self,
        step_number: int,
        status: StepStatus,
        error_message: str = "",
        output_artifact: str = "",
    ) -> None:
        """
        Update a step's status and rewrite the CSV atomically.

        Atomic write strategy:
          1. Write to pipeline_state.csv.tmp
          2. fsync
          3. Rename to pipeline_state.csv (atomic on POSIX)
        """
        ...

    def get_resume_step(self) -> int | None:
        """
        Return the step number to resume from, or None if all complete.
        The resume step is the first step with status != 'completed'.
        """
        ...

    def get_step(self, step_number: int) -> PipelineStep:
        """Return a specific step's state."""
        ...
```

### 6.3 Data Flow Between Steps

```
Step 1 Output -> Step 2 Input:
  WikiFetchOutput.raw_markdown_path -> StoryModifyInput.raw_markdown_path

Step 2 Output -> Step 3 Input:
  StoryModifyOutput.story_markdown_path -> ContentRateInput.story_markdown_path

Step 3 Output -> Step 4 Input:
  story.md (with RATING annotations added) -> TranslateInput.story_markdown_path

Step 4 Output -> Step 5 Input:
  story.md (source language version) -> PromptGenInput.story_markdown_path
  (Note: prompts are generated from source language story only)

Step 5 Output -> Step 6 Input:
  PromptGenOutput.prompts_csv_path -> ImageGenInput.prompts_csv_path

Steps 4+6 Output -> Step 7 Input:
  All story_{lang}.md files + images/ directory -> CompileInput
```

---

## 7. Error Handling and Recovery

### 7.1 Exception Hierarchy

```python
class EbookGenError(Exception):
    """Base exception for all ebook generation errors."""
    pass


class ComponentError(EbookGenError):
    """A pipeline component failed."""
    def __init__(self, step_name: str, message: str,
                 cause: Exception | None = None):
        self.step_name = step_name
        self.cause = cause
        super().__init__(f"Step '{step_name}' failed: {message}")


class StoryNotFoundError(ComponentError):
    """Wikipedia article not found."""
    pass


class DisambiguationError(ComponentError):
    """Wikipedia returned a disambiguation page."""
    def __init__(self, title: str, options: list[str]):
        self.options = options
        super().__init__(
            "wikipedia_fetch",
            f"'{title}' is ambiguous. Options: {options}"
        )


class OllamaConnectionError(ComponentError):
    """Cannot reach the Ollama service."""
    pass


class OllamaModelNotFoundError(ComponentError):
    """Requested model is not available in Ollama."""
    pass


class OllamaGenerationError(ComponentError):
    """Ollama model returned an error during generation."""
    pass


class ImageGenerationError(ComponentError):
    """One or more images failed to generate."""
    def __init__(self, failed_count: int, total_count: int):
        self.failed_count = failed_count
        self.total_count = total_count
        super().__init__(
            "image_generation",
            f"{failed_count}/{total_count} images failed"
        )


class CompilationError(ComponentError):
    """ePub or PDF compilation failed."""
    pass
```

### 7.2 Retry Strategy

```python
from dataclasses import dataclass


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple[type[Exception], ...] = (
        OllamaConnectionError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
    )


def retry_with_backoff(
    func: Callable,
    config: RetryConfig,
    logger: logging.Logger,
) -> Any:
    """
    Execute func with exponential backoff retry.

    Delay formula: min(base * (exponential_base ^ attempt), max_delay)

    Attempt 1: 2s delay
    Attempt 2: 4s delay
    Attempt 3: 8s delay (then give up)

    Only retries on exceptions listed in config.retryable_exceptions.
    All other exceptions propagate immediately.
    """
    ...
```

### 7.3 Recovery Strategies by Step

| Step | Failure Mode | Recovery Strategy |
|------|-------------|-------------------|
| 1. Wikipedia Fetch | 404 / Network error | Retry with backoff; surface disambiguation options; allow manual URL override |
| 2. Story Modification | LLM timeout / bad output | Retry; validate output structure (has chapters, annotations); save raw LLM output for debugging |
| 3. Content Rating | LLM timeout | Retry; fall back to "unrated" if rating step is non-critical |
| 4. Translation | LLM timeout / partial failure | Per-language retry; continue with other languages; mark failed languages in metadata |
| 5. Prompt Generation | LLM timeout / bad output | Retry; validate CSV structure; ensure at least a cover prompt exists |
| 6. Image Generation | Model error / timeout | Per-image retry; update CSV per image; resume generates only pending/failed images |
| 7. Ebook Compilation | Missing images / rendering error | Skip missing images with placeholder; retry compilation; per-language independent compilation |

### 7.4 Atomic File Operations

All file writes use a write-to-temp-then-rename pattern to prevent corruption:

```python
def atomic_write(target_path: Path, content: str | bytes) -> None:
    """
    Write content to a file atomically.

    1. Write to target_path.tmp in the same directory.
    2. Flush and fsync.
    3. Rename target_path.tmp -> target_path (atomic on POSIX).

    This ensures that target_path is never in a partially-written state.
    If the process crashes during write, only the .tmp file is corrupted
    and the previous version of target_path remains intact.
    """
    tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(tmp_path, mode) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    tmp_path.rename(target_path)
```

---

## 8. Testing Strategy

### 8.1 Test Pyramid

```
                    /  E2E Tests  \          <- Full pipeline, real Ollama
                   / (2-3 tests)   \
                  /------------------\
                 / Integration Tests  \      <- Component + real files, mocked Ollama
                / (5-10 per component) \
               /------------------------\
              /      Unit Tests          \   <- Pure logic, no I/O
             / (10-20 per component)      \
            /------------------------------\
```

### 8.2 Unit Tests (fast, no I/O)

- **Markdown parser**: annotation extraction, stripping, round-trip fidelity
- **CSV I/O**: serialization/deserialization of ImageRecord and PipelineStep
- **StoryConfig validation**: theme+rating compatibility, language code validation
- **Retry logic**: backoff timing, exception filtering
- **File naming**: slug generation, language suffix formatting

### 8.3 Integration Tests (mocked Ollama)

Each component gets integration tests with:
- **Mocked Ollama client** returning pre-recorded responses
- **Real file I/O** against a temporary directory
- **Fixture data** in `tests/fixtures/`

Example:

```python
def test_story_modifier_cyberpunk(tmp_path, mock_ollama):
    """Given a raw fairy tale, modifier produces cyberpunk variant with annotations."""
    # Arrange
    raw_md = tmp_path / "raw.md"
    raw_md.write_text(FIXTURE_RAW_BILLY_GOATS)
    mock_ollama.generate_text.return_value = FIXTURE_CYBERPUNK_BILLY_GOATS

    config = StoryConfig(
        story_id="test",
        title="Test",
        source_url="http://example.com",
        theme=Theme.CYBERPUNK,
    )

    modifier = StoryModifier(ollama_client=mock_ollama)

    # Act
    result = modifier.execute(StoryModifyInput(
        raw_markdown_path=raw_md,
        story_config=config,
        output_dir=tmp_path,
    ))

    # Assert
    story_md = result.story_markdown_path.read_text()
    assert "<!-- DIRECTOR:" in story_md
    assert "<!-- THEME:" in story_md
    assert "<!-- IMAGE:" in story_md
    assert "neon" in story_md.lower() or "cyber" in story_md.lower()
```

### 8.4 Three-Tier Quality Progression Workflow

The `ImageMode` enum supports a three-tier progression from preview to publication:

| Aspect | PREVIEW Mode | DRAFT Mode | FINAL Mode |
|--------|-------------|-----------|-----------|
| Resolution | 1/4 target (256x192) | 1/2 target (512x384) | Full target (1024x768) |
| Model | Fast/low-param (4b) | Standard (4b full) | High-quality (9b) |
| Model example | x/flux2-klein:4b | x/flux2-klein:4b | x/flux2-klein:9b |
| Purpose | Test prompts quickly | Review layout & composition | Publication quality |
| File naming | Same filenames (overwritten on promote) | Same filenames | Same filenames |
| Time estimate | ~5-10 seconds/image | ~30-60 seconds/image | ~2-5 minutes/image |
| Compile ebook? | No | Yes (draft PDF/ePub) | Yes (final PDF/ePub) |

**Three-Stage Workflow:**

```bash
# Stage 1: PREVIEW - Test prompts with fast, low-quality model
ebook-gen generate "Three Billy Goats Gruff" \
  --theme cyberpunk \
  --image-mode preview

# Review preview images
ebook-gen preview-images three-billy-goats-gruff

# If prompts need adjustment, edit CSV and retry
# Edit prompts/three-billy-goats-gruff/prompts.csv
ebook-gen retry three-billy-goats-gruff --step 6

# Stage 2: DRAFT - Generate medium-quality images and compile for layout review
ebook-gen promote-images three-billy-goats-gruff --mode draft

# This:
# - Updates image_mode to 'draft'
# - Uses medium resolution and standard model
# - Regenerates all images
# - Compiles a draft ebook for layout review

# Review the compiled draft
open compiled/three-billy-goats-gruff/three-billy-goats-gruff_en_draft.pdf

# If layout needs adjustment, modify layout settings
ebook-gen configure-layout three-billy-goats-gruff --style manga

# Stage 3: FINAL - Generate high-quality images and compile for publication
ebook-gen promote-images three-billy-goats-gruff --mode final

# This:
# - Updates image_mode to 'final'
# - Uses full resolution and best model (bf16)
# - Regenerates all images
# - Compiles final publication-ready ebook

# Your publication-ready ebooks are here:
# compiled/three-billy-goats-gruff/three-billy-goats-gruff_en.pdf
# compiled/three-billy-goats-gruff/three-billy-goats-gruff_en.epub
```

**Rationale for Three Tiers:**
1. **Preview** - Iterate on prompts without burning GPU time (minutes vs hours)
2. **Draft** - Validate layout, composition, and flow with decent quality
3. **Final** - Commit to expensive high-quality generation only when everything else is perfect

### 8.5 Test Fixtures

```
tests/
  fixtures/
    sample_story_raw.md          # Raw Wikipedia-style text
    sample_story_cyberpunk.md    # Expected cyberpunk modification output
    sample_prompts.csv           # Pre-generated image prompts
    sample_image_256x192.png     # Low-res test image
    ollama_responses/
      generate_text_cyberpunk.json   # Recorded Ollama text response
      generate_text_translate_es.json
      generate_image.json            # Recorded Ollama image response (small)
```

---

## 9. Docker and Environment

### 9.1 docker-compose.yml

```yaml
version: "3.8"

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    volumes:
      - ./code:/workspace/code
      - ./stories:/workspace/stories
      - ./prompts:/workspace/prompts
      - ./images:/workspace/images
      - ./compiled:/workspace/compiled
      - ./progress:/workspace/progress
    depends_on:
      ollama:
        condition: service_healthy
    environment:
      - OLLAMA_HOST=http://ollama:11434
    working_dir: /workspace

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_models:/root/.ollama
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

volumes:
  ollama_models:
    driver: local
```

### 9.2 Dockerfile

```dockerfile
FROM ghcr.io/prefix-dev/pixi:latest

WORKDIR /workspace

# Copy pixi project files
COPY pixi.toml pixi.lock ./

# Install dependencies via pixi
RUN pixi install

# Copy source code
COPY code/ /workspace/code/

# Create output directories
RUN mkdir -p stories prompts images compiled progress

# Default command
ENTRYPOINT ["pixi", "run"]
CMD ["ebook-gen", "--help"]
```

### 9.3 pixi.toml

```toml
[project]
name = "ebook-generation"
version = "0.1.0"
description = "Generate themed, illustrated ebooks from story sources"
channels = ["conda-forge"]
platforms = ["linux-64"]

[dependencies]
python = ">=3.12"
pip = "*"

[pypi-dependencies]
click = ">=8.1"
httpx = ">=0.27"
markdown-it-py = ">=3.0"
ebooklib = ">=0.18"
weasyprint = ">=62"
markdownify = ">=0.13"
pytest = ">=8.0"
pytest-cov = ">=5.0"

[tasks]
ebook-gen = { cmd = "python -m ebook_gen.cli", cwd = "code" }
test = { cmd = "pytest tests/ -v", cwd = "code" }
test-cov = { cmd = "pytest tests/ --cov=ebook_gen --cov-report=term-missing", cwd = "code" }
lint = { cmd = "ruff check ebook_gen/ tests/", cwd = "code" }
format = { cmd = "ruff format ebook_gen/ tests/", cwd = "code" }
```

---

## 10. Implementation Plan

### Phase 1: Foundation (Week 1)

**Goal:** Project skeleton, data models, CLI framework, progress tracker.

| Task | Description | Output |
|------|-------------|--------|
| 1.1 | Set up Docker + docker-compose + pixi | Working container environment |
| 1.2 | Create Python package structure (`ebook_gen/`) | Importable package |
| 1.3 | Implement data models (`models.py`, `config.py`) | Dataclasses for StoryConfig, ImageRecord, PipelineStep |
| 1.4 | Implement CSV I/O utilities (`csv_io.py`) | Read/write for prompts.csv and pipeline_state.csv |
| 1.5 | Implement ProgressTracker (`progress.py`) | Atomic CSV state management with resume detection |
| 1.6 | Implement CLI skeleton (`cli.py`) | `generate`, `resume`, `status`, `retry` commands (stubs) |
| 1.7 | Write unit tests for models and CSV I/O | >90% coverage on foundation code |

**Milestone:** `pixi run ebook-gen generate "Test" --theme cyberpunk` creates directory structure and initializes pipeline_state.csv.

### Phase 2: Content Pipeline (Week 2)

**Goal:** Steps 1-3 working end-to-end.

| Task | Description | Output |
|------|-------------|--------|
| 2.1 | Implement OllamaClient (`ollama/client.py`) | HTTP client with retry, health check |
| 2.2 | Implement WikipediaFetcher (step 1) | Fetches and converts Wikipedia articles |
| 2.3 | Implement Markdown annotation parser (`utils/markdown.py`) | Extract/strip annotation blocks |
| 2.4 | Implement StoryModifier (step 2) | Theme-based story rewriting via Ollama |
| 2.5 | Implement ContentRater (step 3) | Rating assignment and annotation |
| 2.6 | Implement PipelineRunner for steps 1-3 | Orchestrated execution with progress tracking |
| 2.7 | Write integration tests with mocked Ollama | Tests for steps 1-3 |

**Milestone:** `pixi run ebook-gen generate "Three Billy Goats Gruff" --theme cyberpunk --rating PG-13` produces `stories/three-billy-goats-gruff/story.md` with annotations.

### Phase 3: Translation and Image Prompts (Week 3)

**Goal:** Steps 4-5 working.

| Task | Description | Output |
|------|-------------|--------|
| 3.1 | Implement Translator (step 4) | Per-language translation with chunking |
| 3.2 | Implement PromptGenerator (step 5) | IMAGE annotation extraction + LLM prompt refinement |
| 3.3 | Extend PipelineRunner for steps 4-5 | Full orchestration through step 5 |
| 3.4 | Write integration tests | Tests for steps 4-5 |

**Milestone:** `pixi run ebook-gen generate "Three Billy Goats Gruff" --theme cyberpunk --languages en es` produces translated stories and `prompts/three-billy-goats-gruff/prompts.csv`.

### Phase 4: Image Generation (Week 4)

**Goal:** Step 6 working with sample/full modes.

| Task | Description | Output |
|------|-------------|--------|
| 4.1 | Implement ImageGenerator (step 6) | Per-image generation with CSV tracking |
| 4.2 | Implement sample vs full mode logic | Resolution scaling, mode switching |
| 4.3 | Implement `preview-images` and `promote-images` CLI commands | Image review workflow |
| 4.4 | Extend PipelineRunner for step 6 | Full orchestration through step 6 |
| 4.5 | Write integration tests | Tests with mock image generation |

**Milestone:** `pixi run ebook-gen generate "Three Billy Goats Gruff" --theme cyberpunk --image-mode sample` produces low-res images in `images/three-billy-goats-gruff/`.

### Phase 5: Ebook Compilation (Week 5)

**Goal:** Step 7 working, full pipeline operational.

| Task | Description | Output |
|------|-------------|--------|
| 5.1 | Implement ebook HTML template and CSS | Styled HTML for both formats |
| 5.2 | Implement ePub compiler | ePub 3 output with embedded images |
| 5.3 | Implement PDF compiler | PDF output via weasyprint |
| 5.4 | Implement EbookCompiler (step 7) | Combined ePub + PDF generation |
| 5.5 | Complete PipelineRunner for all 7 steps | Full end-to-end orchestration |
| 5.6 | Write integration and E2E tests | Full pipeline test with mocked Ollama |

**Milestone:** `pixi run ebook-gen generate "Three Billy Goats Gruff" --theme cyberpunk --languages en es --image-mode sample` produces complete ePub and PDF files.

### Phase 6: Polish and Hardening (Week 6)

**Goal:** Production readiness.

| Task | Description | Output |
|------|-------------|--------|
| 6.1 | End-to-end testing with real Ollama | Verify against actual LLM responses |
| 6.2 | Error handling review and hardening | Edge cases, timeouts, corrupted state |
| 6.3 | Logging and observability | Structured logs, timing metrics |
| 6.4 | Documentation | README, usage examples, theme authoring guide |
| 6.5 | Performance profiling | Identify bottlenecks, optimize if needed |

---

## 11. Design Decisions

### DD-1: CSV over SQLite for state tracking

**Decision:** Use CSV files for both image tracking and pipeline state.

**Rationale:**
- CSVs are human-readable and editable -- users can manually fix prompts or reset state.
- No additional dependency (sqlite3 is stdlib, but CSV is even simpler).
- The data volume is tiny (7 rows for pipeline state, ~10-30 rows for image prompts).
- CSVs are easily diffable and inspectable with standard tools.

**Trade-off:** No transactional guarantees. Mitigated by atomic write pattern (write-to-temp-then-rename).

### DD-2: One story directory per run, not a database of stories

**Decision:** Each story gets its own subdirectory under `stories/`, `prompts/`, `images/`, `compiled/`, and `progress/`. There is no central database.

**Rationale:**
- File-system-as-database is simple and transparent.
- Easy to archive, delete, or share individual stories.
- No schema migrations.
- Natural mapping to the specified directory structure.

**Trade-off:** No cross-story queries (e.g., "show me all cyberpunk stories"). Acceptable for this use case.

### DD-3: Annotations in HTML comments, not custom Markdown extensions

**Decision:** Use `<!-- PREFIX: content -->` for annotations rather than custom Markdown syntax.

**Rationale:**
- HTML comments are valid Markdown and invisible in any standard renderer.
- No need for a custom Markdown parser -- just regex or string matching.
- The story files can be previewed in any Markdown viewer and the annotations are hidden.
- Simple to strip: a single regex removes all annotations.

**Trade-off:** Multi-line HTML comments require careful handling (nested comments, `-->` inside content). Mitigated by using a non-greedy regex and disallowing `-->` inside annotation content.

### DD-4: Synchronous pipeline, not async

**Decision:** The pipeline runs synchronously, one step at a time.

**Rationale:**
- The pipeline is inherently sequential (each step depends on the prior step's output).
- Within step 6, images are generated sequentially (Ollama processes one request at a time anyway since it is a local model server).
- Async would add complexity without improving throughput given the single Ollama instance.

**Trade-off:** Cannot parallelize image generation across multiple Ollama instances. If needed in the future, step 6 can be refactored to use async/concurrent.futures without changing the overall architecture.

### DD-5: Prompt generation from source language only

**Decision:** Image prompts are generated from the source-language story, not from each translated version.

**Rationale:**
- Images are language-independent (a picture of a cyberpunk bridge is the same regardless of whether the caption is in English or Spanish).
- Generating prompts once avoids inconsistency across languages.
- Reduces Ollama API calls.

**Trade-off:** If a translation introduces culturally-adapted imagery (e.g., different food items), the images will not reflect that adaptation. Acceptable for initial version.

---

## 12. Layout Styles and Composition

### 12.1 Overview

The ebook compiler supports multiple layout styles that control how images and text are arranged on the page. This is particularly important for creating graphic novel-style presentations.

### 12.2 Standard Layout Styles

#### Style: `traditional` (Default for Standard Ebooks)

**Description:** Classic illustrated book layout with images embedded inline with text.

**Characteristics:**
- Images appear after the paragraph containing the `<!-- IMAGE: -->` annotation
- Images are full-width within text column (max ~600px for readability)
- Text flows naturally around chapter breaks
- Good for: Traditional illustrated novels, children's books

**Example Page Structure:**
```
┌─────────────────────────────┐
│ Chapter Title               │
│                             │
│ Paragraph of text lorem     │
│ ipsum dolor sit amet...     │
│                             │
│ ┌───────────────────────┐   │
│ │                       │   │
│ │      Image 1          │   │
│ │                       │   │
│ └───────────────────────┘   │
│                             │
│ More text continuing the    │
│ story after the image...    │
└─────────────────────────────┘
```

#### Style: `manga` (Japanese Right-to-Left)

**Description:** Manga-style layout with panel arrangements and reading flow.

**Characteristics:**
- Right-to-left reading order (can be configured to left-to-right)
- Images as full or partial page panels
- Text appears in speech bubbles or caption boxes (overlaid or adjacent)
- Supports multi-panel layouts on single pages
- Good for: Manga-style adaptations, comic book formats

**Example Page Structure:**
```
┌─────────────────────────────┐
│  ┌──────┐  ┌──────────────┐ │
│  │Panel │  │    Panel 2   │ │
│  │  1   │  │              │ │
│  └──────┘  └──────────────┘ │
│                             │
│  ┌────────────────────────┐ │
│  │                        │ │
│  │      Panel 3 (wide)    │ │
│  │                        │ │
│  └────────────────────────┘ │
│  [Caption: Story text...]   │
└─────────────────────────────┘
```

#### Style: `graphic-novel` (Western Comics)

**Description:** Western graphic novel layout with panel grids.

**Characteristics:**
- Left-to-right reading order
- Structured panel grids (typically 2-3 rows, 2-3 columns per page)
- Text in speech bubbles and captions (rendered separately)
- Supports splash pages (full-page dramatic images)
- Good for: Western-style comics, graphic adaptations

**Example Page Structure:**
```
┌─────────────────────────────┐
│  ┌──────────┐  ┌──────────┐ │
│  │          │  │          │ │
│  │ Panel 1  │  │ Panel 2  │ │
│  │          │  │          │ │
│  └──────────┘  └──────────┘ │
│  ┌──────────┐  ┌──────────┐ │
│  │          │  │          │ │
│  │ Panel 3  │  │ Panel 4  │ │
│  │          │  │          │ │
│  └──────────┘  └──────────┘ │
└─────────────────────────────┘
```

#### Style: `webtoon` (Vertical Scroll)

**Description:** Webtoon-style vertical scrolling layout (for digital-only ePub).

**Characteristics:**
- Optimized for mobile/tablet reading
- Vertical scroll with full-width images
- Text appears between images or as overlay
- No page breaks (continuous scroll)
- Good for: Mobile-first digital publications, webcomics

**Example Page Structure:**
```
┌─────────────────────────────┐
│ ┌───────────────────────┐   │
│ │                       │   │
│ │      Image 1          │   │
│ │                       │   │
│ └───────────────────────┘   │
│ Story text paragraph...     │
│                             │
│ ┌───────────────────────┐   │
│ │                       │   │
│ │      Image 2          │   │
│ │                       │   │
│ └───────────────────────┘   │
│ More story text...          │
│                             │
│ ┌───────────────────────┐   │
│ │                       │   │
│ │      Image 3          │   │
│ │    (wider/taller)     │   │
│ │                       │   │
│ └───────────────────────┘   │
│ Continuing text...          │
└─────────────────────────────┘
```

#### Style: `cinematic` (Film Storyboard)

**Description:** Cinematic storyboard layout with widescreen images.

**Characteristics:**
- Widescreen aspect ratio images (16:9 or 2.35:1)
- Text appears as subtitles below images or as voiceover captions
- Emphasizes visual storytelling
- Page breaks between major scenes
- Good for: Cinematic adaptations, visual-heavy narratives

**Example Page Structure:**
```
┌─────────────────────────────┐
│                             │
│ ┌───────────────────────┐   │
│ │                       │   │
│ │   Widescreen Image    │   │
│ │     (16:9 ratio)      │   │
│ │                       │   │
│ └───────────────────────┘   │
│                             │
│ [Caption: Narrative text or │
│  dialogue appears here]     │
│                             │
└─────────────────────────────┘
```

### 12.3 Layout Configuration

#### Configuration in Story Metadata

Layout settings are stored in `stories/<story>/metadata.json`:

```json
{
  "story_id": "three-billy-goats-gruff",
  "title": "Three Billy Goats Gruff",
  "layout_style": "manga",
  "layout_config": {
    "reading_order": "rtl",
    "panels_per_page": 4,
    "aspect_ratio": "4:3",
    "text_placement": "overlay",
    "page_size": "B5"
  }
}
```

#### Layout-Specific Image Prompts

Different layouts require different image compositions. The prompt generator should adjust prompts based on layout style:

**Traditional:**
- Prompts emphasize standalone scenes
- Wider aspect ratios (16:9 or 4:3)

**Manga/Graphic Novel:**
- Prompts specify panel composition
- Multiple perspectives (close-up, wide shot, action shot)
- Consider panel sequence and flow

**Webtoon:**
- Prompts for vertical/portrait compositions
- Full-scene illustrations that work in continuous scroll

**Cinematic:**
- Widescreen compositions (21:9)
- Emphasis on cinematography and framing

#### Image Annotations with Layout Hints

The `<!-- IMAGE: -->` annotations can include layout hints:

```markdown
<!-- IMAGE: layout=full-page
     Panel showing the smallest goat approaching the bridge,
     cyberpunk setting with neon lights and rain -->

<!-- IMAGE: layout=half-page-top
     Close-up of the troll's menacing face emerging from shadows -->

<!-- IMAGE: layout=panel-sequence panels=3
     1. Goat steps onto bridge
     2. Troll emerges
     3. Goat runs away -->
```

### 12.4 Implementation Approach

#### Phase 1: Traditional Layout Only
- Implement the simplest layout first (traditional inline images)
- Full-width images after relevant paragraphs
- Get the basic pipeline working

#### Phase 2: Add Manga/Graphic Novel Layouts
- Implement panel-based layouts
- Support for multi-image pages
- Text rendering as captions/speech bubbles

#### Phase 3: Advanced Layouts
- Webtoon vertical scroll (ePub only)
- Cinematic widescreen
- Custom layout configurations

### 12.5 Layout Templates

Each layout style has a corresponding HTML/CSS template in the compiler:

```
code/ebook_gen/templates/
  traditional/
    page.html
    styles.css
  manga/
    page.html
    styles.css
    panel_layouts.css
  graphic-novel/
    page.html
    styles.css
  webtoon/
    page.html
    styles.css
  cinematic/
    page.html
    styles.css
```

### 12.6 CLI Configuration

```bash
# Set layout style when generating
ebook-gen generate "Story Title" \
  --theme cyberpunk \
  --layout manga \
  --layout-config reading_order=rtl panels_per_page=4

# Change layout for existing story
ebook-gen configure-layout three-billy-goats-gruff \
  --style graphic-novel \
  --panels-per-page 6

# Preview layout with draft images
ebook-gen compile three-billy-goats-gruff \
  --layout-preview \
  --format pdf
```

### 12.7 Recommended Layout by Theme

| Theme | Recommended Layout | Rationale |
|-------|-------------------|-----------|
| Cyberpunk | manga or cinematic | High contrast, dynamic action works well in panels or widescreen |
| Caribbean Village | traditional or graphic-novel | Emphasizes cultural setting and community scenes |
| Steampunk | graphic-novel or traditional | Victorian-era aesthetic suits classic comic or illustrated book |
| Fairy Tale Dark | traditional or cinematic | Atmospheric, single-scene focus for dark imagery |
| Space Opera | cinematic or graphic-novel | Epic scale benefits from widescreen or multi-panel |

---

## 13. Consistency Framework

See `CONSISTENCY.md` for full documentation.

### 13.1 Narrative Consistency

**Challenge:** Themed transformations must preserve core story structure.

**Solution:** Story Fidelity Validator (runs after Step 2)
- Extracts narrative structure from both original and modified stories
- Compares: characters, relationships, plot points, moral
- Generates fidelity score (target: 70%+)
- Warns user if story has drifted too far

**Example Check:**
```
Original: Three goats, troll antagonist, bridge crossing, defeat
Cyberpunk: Three couriers, rogue AI, data bridge, AI defeated
Result: ✓ 87% fidelity - core narrative preserved
```

### 13.2 Visual Consistency

**Challenge:** Characters must look identical across all images.

**Solution:** Character Design Registry + Visual Consistency Checker

**Character Sheet System:**
- Generated during Step 5 (Prompt Generation)
- One sheet per character with detailed physical description
- Includes theme-specific adaptations (cybernetic enhancements, etc.)
- "Consistency prompt" injected into every image prompt for that character

**Multi-Stage Character Refinement:**
1. **Preview:** Generate first appearance of each character
2. **Review:** User approves or requests modifications
3. **Lock:** Character design locked for draft/final modes
4. **Validate:** Vision model checks consistency across images

**Example Character Sheet (Eldest Goat → Cyberpunk):**
```json
{
  "character_id": "eldest_goat",
  "themed_name": "The Enforcer",
  "consistency_prompt": "Large imposing anthropomorphic goat, dark gray fur,
    metal-reinforced horns, red cybernetic eye implant, armored jacket...",
  "appearance_notes": ["Always tallest in frame", "Battle-hardened look"]
}
```

**CLI Commands:**
```bash
# Review character designs after preview
ebook-gen review-characters story-id

# Check consistency across generated images
ebook-gen check-consistency story-id --character eldest_goat
```

### 13.3 Implementation Timeline

**Phase 2.5** (before Phase 3):
- Story Fidelity Validator
- Character Registry foundation
- CLI commands for character review

**Phase 5** (with image generation):
- Visual consistency checking with vision models
- Character sheet locking workflow
- Automated consistency validation

---

## 14. Open Questions

These items need clarification before or during implementation:

### Q1: Ollama models ✓ RESOLVED

**Core Models:**

**Text generation (story modification, translation):** `llama3.1:8b`
- General-purpose LLM for story rewriting and translation
- Alternative: `llama3.1:70b` (more capable but slower)

**Prompt generation:** `brxce/stable-diffusion-prompt-generator`
- Usage: `ollama run brxce/stable-diffusion-prompt-generator "input text"`
- Outputs refined image generation prompts

**Image generation models:**
- Preview/Draft: `x/flux2-klein:4b` - 4 billion parameter model, faster
- Final: `x/flux2-klein:9b` - 9 billion parameter model, higher quality
- Usage: `ollama run x/flux2-klein:4b "prompt text"`
- Usage: `ollama run x/flux2-klein:9b "prompt text"`

**Optional Enhancement Models:**

These models can be used in the prompt generation pipeline to extract additional context:

**1. Emotion/Mood Analysis:**
- `llama3.1:8b` with specialized system prompt for emotion detection
- Extracts: tension, joy, fear, wonder, sadness, anger
- Use case: Add emotional atmosphere to image prompts
- Example output: "tense, foreboding atmosphere with underlying dread"

**2. Scene Summarization:**
- `qwen2.5:7b` - Fast, efficient summarization
- Alternative: `mistral:7b` - Good at concise extraction
- Use case: Create concise scene descriptions for prompt context
- Example output: "Small goat crosses bridge at night, confronted by lurking threat"

**3. Visual Detail Extraction:**
- `llama3.1:8b` with vision-focused system prompt
- Extracts: lighting, colors, composition, setting details
- Use case: Ensure visual consistency across images
- Example output: "neon blue and purple lighting, rain-slicked streets, towering megastructures in background"

**4. Character Consistency Tracking:**
- `llama3.1:8b` with character-focused system prompt
- Maintains: character appearance, clothing, distinctive features
- Use case: Keep character designs consistent across all images
- Example output: "smallest goat: gray fur, worn courier jacket, blue LED collar, nervous demeanor"

**5. Style Reference Generator:**
- `llama3.1:8b` with art style system prompt
- Generates: art style descriptors based on theme
- Use case: Consistent art direction across all images
- Example output: "blade runner aesthetic, moody cyberpunk, neon noir, high contrast shadows, volumetric fog"

**6. Prompt Quality Checker:**
- `qwen2.5:3b` - Fast, lightweight validation
- Checks: prompt clarity, completeness, style consistency
- Use case: Validate prompts before image generation
- Example output: "PASS: prompt is clear, includes mood, setting, composition" or "FAIL: missing lighting description"

**Enhanced Prompt Generation Workflow:**

```
Story Text Passage
    ↓
[Emotion Analysis] → Mood: "tense, atmospheric"
    ↓
[Scene Summary] → Context: "confrontation on bridge"
    ↓
[Visual Details] → Setting: "cyberpunk cityscape, neon lights"
    ↓
[Character Consistency] → Subject: "small gray goat in courier gear"
    ↓
[Style Reference] → Style: "blade runner aesthetic"
    ↓
[Combine All Inputs]
    ↓
[Prompt Generator] → Final Prompt
    ↓
[Quality Check] → Validate
    ↓
Save to prompts.csv
```

**Model Configuration:**

Add optional enhancement models to StoryConfig:

```python
enable_prompt_enhancement: bool = True  # Enable multi-model pipeline
emotion_model: str = "llama3.1:8b"
summary_model: str = "qwen2.5:7b"
style_model: str = "llama3.1:8b"
quality_check_model: str = "qwen2.5:3b"
```

**Performance Impact:**

Without enhancement: 1 model call per image (~2-5 seconds)
With enhancement: 5-6 model calls per image (~10-20 seconds)

**Recommendation:** Enable for DRAFT and FINAL modes, disable for PREVIEW mode to keep iteration fast.

### Q2: Story structure preservation during modification
When the LLM rewrites a story in a new theme, how strictly should the original structure be preserved? Options:
- **Strict:** Same number of chapters, same scene sequence, same character count.
- **Loose:** Same narrative arc, but the LLM can restructure for the theme.
- **Current assumption:** Loose -- the system prompt requests structure preservation but does not enforce it programmatically.

### Q3: Wikipedia article scope
Some Wikipedia articles for fairy tales include extensive analysis, adaptations, and cultural commentary sections beyond the story itself. Should the fetcher:
- Extract only the "Plot" or "Story" section?
- Use the full article?
- **Current assumption:** Extract only the plot/story section, plus a brief synopsis from the introduction.

### Q4: Theme extensibility
Should new themes be addable via configuration files (e.g., a YAML file with theme name + system prompt), or is it acceptable to add them as Python enum values with hard-coded prompts?
- **Current assumption:** Python enum + dictionary of prompts. A YAML-based theme registry can be added later if needed.

### Q5: Multi-story batch processing
Is there a need to generate multiple stories in a single command (e.g., from a list file)? The current design handles one story per CLI invocation.
- **Current assumption:** One story at a time. Batch processing can be done via shell scripting or added as a future feature.

### Q6: Image placement in compiled ebook ✓ RESOLVED
Layout styles now support multiple placement options:
- **Traditional:** After the paragraph containing the annotation, full-width
- **Manga/Graphic Novel:** Panel-based layouts with configurable grids
- **Webtoon:** Vertical scroll with full-width images
- **Cinematic:** Widescreen images with subtitle-style text

See Section 12 (Layout Styles and Composition) for full details.

### Q7: Cover image source
Should the cover image always be AI-generated, or should there be an option to supply a custom cover image?
- **Current assumption:** AI-generated by default, with a future option to override with a user-supplied image.

---

## Design Phase Checklist

- [x] Requirements are clear and documented
- [x] Architecture addresses all requirements
- [x] Component interfaces are well-defined with type signatures
- [x] Data models are specified (CSV schemas, story format, metadata)
- [x] Error handling strategy covers all failure modes
- [x] Resume capability is designed (CSV-based progress tracking)
- [x] Testing strategy covers unit, integration, and E2E
- [x] Sample vs full image run workflow is defined
- [x] Docker and pixi environment is specified
- [x] Implementation plan has clear phases and milestones
- [x] Design decisions are documented with rationale
- [x] Open questions are captured for discussion
- [ ] Stakeholder review and approval (pending your feedback)

---

*Next step: Review this design, resolve open questions, then begin implementation with Phase 1 (foundation).*
