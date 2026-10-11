# Ebook Generation Pipeline

Generate themed, illustrated, narrated ebooks from story sources with AI-powered modifications, translations, image generation, and text-to-speech audio.

## Features

- **Story Fetching** — Retrieve stories from Wikipedia with clean Markdown conversion
- **Theme Transformation** — Convert stories to cyberpunk, caribbean village, steampunk, dark fairy tale, space opera, or leave unmodified
- **Content Rating** — Assign appropriate ratings (G, PG, PG-13, R, NC-17) via LLM analysis
- **Multi-language** — Translate to multiple languages, with cultural adaptation, using a local LLM
- **Image Generation** — AI-generated illustrations with three-tier quality progression (preview → draft → final)
- **Audio Narration** — Text-to-speech via Kokoro-82M TTS for 9 supported languages, producing per-language WAV files
- **Multiple Formats** — Output to ePub and PDF (compilation in progress)
- **Resume Capability** — Crash-safe pipeline with atomic CSV state tracking

## Quick Start

### Prerequisites

- Apple Silicon Mac (M1 or later); 24 GB of unified memory is enough
- [Apple container](https://github.com/apple/container): `brew install container`
- [uv](https://docs.astral.sh/uv/) for the host model server: `brew install uv`
- The `container` image builder set not to use Rosetta (it's on by default for x86 builds, and the builder VM won't start without Rosetta installed). Add this to `~/.config/container/config.toml`, then run `container system stop && container system start`:
  ```toml
  [build]
  rosetta = false
  ```
- About 20 GB of disk for the Hugging Face model cache (`HF_HOME`, default `~/.cache/huggingface`)

### How it runs

Each pipeline stage runs in its own container image. pixi installs the packages inside each image, from `pixi.toml` (one environment per stage):

| Image | Steps | Contents |
|-------|-------|----------|
| `ebook-gen-text` | 1–5 | Story, theme, rating, translation, image prompts |
| `ebook-gen-images` | 6 | Illustrations |
| `ebook-gen-compile` | 7 | ePub + PDF (weasyprint, ebooklib) |
| `ebook-gen-audio` | 8 | Narration (Kokoro TTS, CPU) |
| `ebook-gen-dev` | — | Tests, lint, TUI |

Containers are Linux VMs without access to Metal, so the text and image models (MLX) run in a **model server on the macOS host** (`code/ebook_gen/model_server.py`, its environment in `model-server/` managed by uv). The containers reach it at the host's address on the container network (`192.168.64.1`). It listens on all interfaces, because that address only exists while a container is running, and requires a token that `./ebook-gen` generates (`.ebook-gen/model-server.token`). It releases the loaded model after 10 idle minutes.

`./ebook-gen` handles all of this: it starts the container services if they're stopped, builds missing or outdated images, starts the model server when a command needs models, and runs each stage the story still needs.

### Setup

```bash
cd ebook-generator
./ebook-gen build                  # build the five images (first build takes a while)
./ebook-gen model-server start     # optional: commands start it on demand
```

The model server downloads models from Hugging Face on first use, into `HF_HOME` on the host. The containers keep their own cache (Kokoro's weights) in the `ebook-gen-hf` container volume, because bind-mounting a cache on an external drive hangs `container run` (the runtime lacks the macOS permission to read removable volumes). Set `EBOOK_GEN_HF_CACHE=/path` to bind a host directory instead.

### Generate Your First Ebook

```bash
# Generate with preview images (fast, test prompts)
./ebook-gen generate "Three Billy Goats Gruff" \
  --file stories/three_billy_goats_gruff.txt \
  --theme cyberpunk \
  --rating PG-13 \
  --languages en --languages es \
  --image-mode preview

# Review preview images
./ebook-gen preview-images three_billy_goats_gruff_cyberpunk

# Promote to draft (medium quality, layout review)
./ebook-gen promote-images three_billy_goats_gruff_cyberpunk --mode draft

# Promote to final (publication quality)
./ebook-gen promote-images three_billy_goats_gruff_cyberpunk --mode final
```

`--file` takes any path on the host, relative or absolute; a file outside the repository is mounted read-only into the container.

The story ID is the slugified title plus the theme and image style when they aren't the defaults (`unmodified`, `photo-realistic`), e.g. `three_billy_goats_gruff_cyberpunk`.

### Generate with Audio Narration

```bash
# Generate ebook + audio narration in English and Hindi
./ebook-gen generate "Three Billy Goats Gruff" \
  --file stories/three_billy_goats_gruff.txt \
  --theme cyberpunk \
  --languages en --languages hi \
  --audio-languages en --audio-languages hi

# Audio files are written to projects/three_billy_goats_gruff_cyberpunk/audio/
#   three_billy_goats_gruff_cyberpunk_en.wav
#   three_billy_goats_gruff_cyberpunk_hi.wav
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
./ebook-gen status three_billy_goats_gruff_cyberpunk

# Resume from the first incomplete step
./ebook-gen resume three_billy_goats_gruff_cyberpunk

# Retry a specific failed step
./ebook-gen retry three_billy_goats_gruff_cyberpunk --step 6
```

## Pipeline Steps

| Step | Name | Description |
|------|------|-------------|
| 1 | `wikipedia_fetch` | Retrieve story from Wikipedia |
| 2 | `story_modification` | Apply theme via the text model |
| 3 | `content_rating` | Assign G/PG/PG-13/R/NC-17 rating |
| 4 | `translation` | Translate to target languages |
| 5 | `prompt_generation` | Generate image prompts from annotations |
| 6 | `image_generation` | Generate illustrations (preview/draft/final) |
| 7 | `ebook_compilation` | Assemble ePub + PDF *(in progress)* |
| 8 | `audio_generation` | Narrate story text via Kokoro TTS *(optional)* |

Steps 7 and 8 are independent — audio runs after step 6 without requiring compilation.

## Three-Tier Image Quality Workflow

| Tier | Resolution | Model | Time | Purpose |
|------|-----------|-------|------|---------|
| **Preview** | 256×192 | FLUX.2 Klein 4B | ~5s/img | Validate prompts |
| **Draft** | 512×384 | FLUX.2 Klein 4B | ~45s/img | Review layout |
| **Final** | 1024×768 | FLUX.2 Klein 9B | ~3min/img | Publication |

```bash
# 1. Preview — quick prompt validation
./ebook-gen generate "Story" --file stories/story.txt --theme cyberpunk --image-mode preview
./ebook-gen preview-images story_id
# Edit projects/story_id/prompts/prompts.csv if needed

# 2. Draft — layout review
./ebook-gen promote-images story_id --mode draft

# 3. Final — publish
./ebook-gen promote-images story_id --mode final
```

## Models and Backends

The backend is chosen with `EBOOK_GEN_BACKEND`:

| Backend | Text | Images | Where it runs |
|---------|------|--------|---------------|
| `remote` (containers) | host model server | host model server | Containers send requests to `EBOOK_GEN_MODEL_SERVER` |
| `mlx` (model server, code default) | `mlx-lm` | `mflux` | In-process on Apple Silicon |
| `ollama` | Ollama HTTP API (`OLLAMA_HOST`) | not supported | Any Ollama server |

The images set `EBOOK_GEN_BACKEND=remote`; the model server itself uses `mlx`. Ollama removed image generation in v0.32.6, so step 6 always needs the model server. To run the text steps against Ollama on the host (started with `OLLAMA_HOST=0.0.0.0` so containers can reach it), `./ebook-gen` passes these variables through:

```bash
EBOOK_GEN_BACKEND=ollama OLLAMA_HOST=http://192.168.64.1:11434 \
  ./ebook-gen generate "Story" --file stories/story.txt --text-model gemma4:12b
```

Settings for `./ebook-gen`: `EBOOK_GEN_MODEL_SERVER_PORT` (default 8765), `EBOOK_GEN_MODEL_SERVER` (override the URL containers use), `EBOOK_GEN_MODEL_IDLE_SECONDS` (default 600), `EBOOK_GEN_CONTAINER_MEMORY` (default 2G) and `EBOOK_GEN_AUDIO_MEMORY` (default 6G, also used for the dev image), and `OBSIDIAN_VAULT_DIR`, which is mounted into the containers if it exists.

Default MLX models (Hugging Face repo IDs, set in `code/ebook_gen/config.py`):

| Use | Model | License |
|-----|-------|---------|
| Story, rating, translation, image prompts | `mlx-community/gemma-4-12B-it-qat-4bit` | Gemma |
| Images, preview/draft | `mflux-community/flux2-klein-4b-mflux-q4` | Apache-2.0 |
| Images, final | `mflux-community/flux2-klein-9b-mflux-q4` | FLUX non-commercial |
| Images, alternative | `mflux-community/z-image-turbo-mflux-q8` | Apache-2.0 |

Only one model is held in memory at a time. Ollama tags saved by older projects (e.g. `x/flux2-klein:4b`, `llama3.1:8b`) are mapped to these models, so those projects resume on MLX.

## CLI Reference

```
ebook-gen generate TITLE [OPTIONS]
  --theme         cyberpunk|caribbean_village|steampunk|fairy_tale_dark|space_opera|unmodified
  --rating        none|G|PG|PG-13|R|NC-17
  --languages     ISO 639-1 codes (multiple, e.g. --languages en --languages es)
  --file          Source story file, .txt or .md (required)
  --image-mode    preview|draft|final
  --style         Visual style for all images (default: photo-realistic)
  --audio-languages  Languages for TTS narration (multiple, e.g. --audio-languages en)
  --text-model    Hugging Face MLX repo id, or an Ollama tag with EBOOK_GEN_BACKEND=ollama
                  (default: mlx-community/gemma-4-12B-it-qat-4bit)
  --prompt-model  Model that writes image prompts (default: same as --text-model)

ebook-gen status STORY_ID
ebook-gen resume STORY_ID
ebook-gen retry STORY_ID [--step N]
ebook-gen preview-images STORY_ID
ebook-gen promote-images STORY_ID [--mode draft|final]
```

## Output Directory Structure

Each story gets one directory under `projects/`:

```
projects/<story_id>/
├── raw.md                   # Source text
├── story.md                 # Themed + annotated
├── story_es.md              # Translated (per language)
├── metadata.json            # StoryConfig
├── prompts/prompts.csv      # Image prompts + generation status
├── images/                  # Generated PNG illustrations
├── compiled/                # ePub and PDF outputs (<story_id>_<lang>[_draft].pdf/.epub)
├── audio/
│   ├── audio_tracks.csv     # TTS generation status
│   └── <story_id>_en.wav    # Narrated audio (per language)
└── progress/pipeline_state.csv   # Pipeline resume state
```

## Development

```bash
./ebook-gen test                    # Run tests (dev image; pytest args pass through)
./ebook-gen test --cov=ebook_gen    # With coverage
./ebook-gen lint                    # Lint (ruff)
./ebook-gen format                  # Format
./ebook-gen tui                     # Terminal UI (runs every step in the dev image)
./ebook-gen shell [STAGE]           # Shell inside an image
./ebook-gen build [STAGE...]        # Rebuild images after changing pixi.toml or Containerfile
```

The repository is mounted at `/workspace`, so code changes take effect without rebuilding. Images rebuild automatically when `pixi.toml` or `Containerfile` changes. To add a package, add it to the matching feature in `pixi.toml`.

## Architecture

The pipeline uses a **component-based, stateless** design. Each step is a `PipelineComponent` subclass with typed `Input`/`Output` dataclasses. State lives entirely on disk (CSV + Markdown files), enabling crash-safe resume at any step.

Key design decisions:
- **CSV over SQLite** — Human-readable, diffable, directly editable
- **Filesystem as database** — One subdirectory per story, no central DB
- **HTML comment annotations** — Valid Markdown, invisible in renderers, simple to strip
- **Synchronous pipeline** — Each step depends on the prior one; one model is loaded at a time
- **Atomic file writes** — All CSV updates use write-to-temp-then-rename

See [DESIGN.md](DESIGN.md) for full architecture documentation.
See [CONSISTENCY.md](CONSISTENCY.md) for character and narrative consistency design.
See [CLAUDE.md](CLAUDE.md) for development guidance.

## License

MIT
