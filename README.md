# Ebook Generation Pipeline

Generate themed, illustrated, narrated ebooks from story sources with AI-powered modifications, translations, image generation, and text-to-speech audio.

## Features

- **Story Fetching** — Retrieve stories from Wikipedia with clean Markdown conversion
- **Theme Transformation** — Convert stories to cyberpunk, caribbean village, steampunk, dark fairy tale, space opera, or leave unmodified
- **Content Rating** — Assign appropriate ratings (G, PG, PG-13, R) via LLM analysis
- **Multi-language** — Translate to multiple languages using Ollama LLMs
- **Image Generation** — AI-generated illustrations with three-tier quality progression (preview → draft → final)
- **Audio Narration** — Text-to-speech via Kokoro-82M TTS for 9 supported languages, producing per-language WAV files
- **Multiple Formats** — Output to ePub and PDF (compilation in progress)
- **Resume Capability** — Crash-safe pipeline with atomic CSV state tracking

## Quick Start

### Prerequisites

- Docker and Docker Compose
- NVIDIA GPU (for Ollama image generation)

### Setup

```bash
# Clone the repository and enter the directory
cd ebook-generation

# Start services (builds app container, pulls Ollama image)
docker-compose up -d

# Pull required Ollama models
docker-compose exec ollama ollama pull llama3.1:8b
docker-compose exec ollama ollama pull brxce/stable-diffusion-prompt-generator
docker-compose exec ollama ollama pull x/flux2-klein:4b
docker-compose exec ollama ollama pull x/flux2-klein:9b
```

### Generate Your First Ebook

```bash
# Generate with preview images (fast, test prompts)
docker-compose exec app pixi run ebook-gen generate "Three Billy Goats Gruff" \
  --theme cyberpunk \
  --rating PG-13 \
  --languages en es \
  --image-mode preview

# Review preview images
docker-compose exec app pixi run ebook-gen preview-images three-billy-goats-gruff

# Promote to draft (medium quality, layout review)
docker-compose exec app pixi run ebook-gen promote-images three-billy-goats-gruff --mode draft

# Promote to final (publication quality)
docker-compose exec app pixi run ebook-gen promote-images three-billy-goats-gruff --mode final
```

### Generate with Audio Narration

```bash
# Generate ebook + audio narration in English and Hindi
docker-compose exec app pixi run ebook-gen generate "Three Billy Goats Gruff" \
  --theme cyberpunk \
  --languages en hi \
  --audio-languages en --audio-languages hi

# Audio files are written to audio/three-billy-goats-gruff/
#   three-billy-goats-gruff_en.wav
#   three-billy-goats-gruff_hi.wav
```

### Supported Audio Languages

| Language | ISO Code | Default Voice |
|----------|----------|---------------|
| English (US) | `en` | `af_heart` |
| English (UK) | `en-gb` | `bf_alice` |
| Japanese | `ja` | `jf_alpha` |
| Chinese | `zh` | `zf_xiaobei` |
| Spanish | `es` | `ef_dora` |
| French | `fr` | `ff_siwis` |
| Hindi | `hi` | `hf_alpha` |
| Italian | `it` | `if_sara` |
| Portuguese | `pt` | `pf_dora` |

Unsupported languages (Norwegian, German, Russian, etc.) are skipped with a warning — no crash, other languages continue.

### Resume an Interrupted Run

```bash
# Check what happened
docker-compose exec app pixi run ebook-gen status three-billy-goats-gruff

# Resume from the first incomplete step
docker-compose exec app pixi run ebook-gen resume three-billy-goats-gruff

# Retry a specific failed step
docker-compose exec app pixi run ebook-gen retry three-billy-goats-gruff --step 6
```

## Pipeline Steps

| Step | Name | Description |
|------|------|-------------|
| 1 | `wikipedia_fetch` | Retrieve story from Wikipedia |
| 2 | `story_modification` | Apply theme via Ollama LLM |
| 3 | `content_rating` | Assign G/PG/PG-13/R rating |
| 4 | `translation` | Translate to target languages |
| 5 | `prompt_generation` | Generate image prompts from annotations |
| 6 | `image_generation` | Generate illustrations (preview/draft/final) |
| 7 | `ebook_compilation` | Assemble ePub + PDF *(in progress)* |
| 8 | `audio_generation` | Narrate story text via Kokoro TTS *(optional)* |

Steps 7 and 8 are independent — audio runs after step 6 without requiring compilation.

## Three-Tier Image Quality Workflow

| Tier | Resolution | Model | Time | Purpose |
|------|-----------|-------|------|---------|
| **Preview** | 256×192 | flux2-klein:4b | ~5s/img | Validate prompts |
| **Draft** | 512×384 | flux2-klein:4b | ~45s/img | Review layout |
| **Final** | 1024×768 | flux2-klein:9b | ~3min/img | Publication |

```bash
# 1. Preview — quick prompt validation
ebook-gen generate "Story" --theme cyberpunk --image-mode preview
ebook-gen preview-images story-id
# Edit prompts/story-id/prompts.csv if needed

# 2. Draft — layout review
ebook-gen promote-images story-id --mode draft

# 3. Final — publish
ebook-gen promote-images story-id --mode final
```

## CLI Reference

```
ebook-gen generate TITLE [OPTIONS]
  --theme         cyberpunk|caribbean_village|steampunk|fairy_tale_dark|space_opera|unmodified
  --rating        none|G|PG|PG-13|R
  --languages     ISO 639-1 codes (multiple, e.g. --languages en --languages es)
  --image-mode    preview|draft|final
  --audio-languages  Languages for TTS narration (multiple, e.g. --audio-languages en)
  --text-model    Ollama model for text (default: llama3.1:8b)
  --prompt-model  Ollama model for prompt gen (default: brxce/stable-diffusion-prompt-generator)

ebook-gen status STORY_ID
ebook-gen resume STORY_ID
ebook-gen retry STORY_ID [--step N]
ebook-gen preview-images STORY_ID
ebook-gen promote-images STORY_ID [--mode draft|final]
```

## Output Directory Structure

```
root/
├── stories/<story>/
│   ├── raw.md               # Wikipedia source
│   ├── story.md             # Themed + annotated
│   ├── story_es.md          # Translated (per language)
│   └── metadata.json        # StoryConfig
├── prompts/<story>/
│   └── prompts.csv          # Image prompts + generation status
├── images/<story>/          # Generated PNG illustrations
├── compiled/<story>/        # ePub and PDF outputs
├── audio/<story>/
│   ├── audio_tracks.csv     # TTS generation status
│   ├── <story>_en.wav       # Narrated audio (per language)
│   └── <story>_hi.wav
└── progress/<story>/
    └── pipeline_state.csv   # Pipeline resume state
```

## Development

```bash
# Run tests
docker-compose exec app pixi run test

# Run with coverage
docker-compose exec app pixi run test-cov

# Lint
docker-compose exec app pixi run lint

# Format
docker-compose exec app pixi run format
```

### Running Tests Locally (without Docker)

```bash
cd code
python -m pytest tests/ -v
```

## Architecture

The pipeline uses a **component-based, stateless** design. Each step is a `PipelineComponent` subclass with typed `Input`/`Output` dataclasses. State lives entirely on disk (CSV + Markdown files), enabling crash-safe resume at any step.

Key design decisions:
- **CSV over SQLite** — Human-readable, diffable, directly editable
- **Filesystem as database** — One subdirectory per story, no central DB
- **HTML comment annotations** — Valid Markdown, invisible in renderers, simple to strip
- **Synchronous pipeline** — Each step depends on prior; Ollama is single-threaded
- **Atomic file writes** — All CSV updates use write-to-temp-then-rename

See [DESIGN.md](DESIGN.md) for full architecture documentation.
See [CONSISTENCY.md](CONSISTENCY.md) for character and narrative consistency design.
See [CLAUDE.md](CLAUDE.md) for development guidance.

## License

MIT
