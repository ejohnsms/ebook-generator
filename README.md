# Ebook Generation Pipeline

Generate themed, illustrated, narrated ebooks from story sources with AI-powered modifications, translations, image generation, and text-to-speech audio.

## Features

- **Story Fetching** — Retrieve stories from Wikipedia with clean Markdown conversion
- **Theme Transformation** — Retell stories in 30 themes defined in `themes.toml`: settings (cyberpunk, steampunk, space opera…), the seven ATU folktale divisions (animal fable, tale of magic, formula tale…) and adult romance genres, with optional romance tropes. Rewrites keep the tale's ATU type and core Motif-Index motifs
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

The story ID is the slugified title plus the theme, any tropes, and the image style when they aren't the defaults (`unmodified`, `photo-realistic`), e.g. `three_billy_goats_gruff_cyberpunk` or `little_red_riding_hood_monster_romance_enemies_to_lovers_oil_painting`.

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

### Pick a Style and Translate

```bash
# Watercolor illustrations, translated into Spanish and Japanese
./ebook-gen generate "Three Billy Goats Gruff" \
  --file stories/three_billy_goats_gruff.txt \
  --theme caribbean_village \
  --style "watercolor, soft watercolor" \
  --languages en --languages es --languages ja

./ebook-gen help style        # every style; quote the ones with spaces
./ebook-gen help languages    # common language codes (any ISO 639-1 code works)
```

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
| 1 | `story_fetch` | Read the story file (or fetch it from Wikipedia) |
| 2 | `story_modification` | Apply theme via the text model |
| 3 | `content_rating` | Assign G/PG/PG-13/R/NC-17 rating |
| 4 | `translation` | Translate to target languages |
| 5 | `prompt_generation` | Generate image prompts from annotations |
| 6 | `image_generation` | Generate illustrations (preview/draft/final) |
| 7 | `ebook_compilation` | Assemble ePub + PDF *(in progress)* |
| 8 | `audio_generation` | Narrate story text via Kokoro TTS *(optional)* |

Steps 7 and 8 are independent — audio runs after step 6 without requiring compilation.

## Themes and Tropes

Themes, romance tropes and the prompt wording all live in [`themes.toml`](themes.toml). List them with `./ebook-gen themes`, or `./ebook-gen help theme` and `./ebook-gen help trope`.

| Group | Themes |
|-------|--------|
| Settings | `unmodified` (default, no rewrite), `cyberpunk`, `caribbean_village`, `steampunk`, `fairy_tale_dark`, `space_opera` |
| ATU divisions | `animal_fable` (ATU 1–299), `tale_of_magic` (300–749), `religious_legend` (750–849), `realistic_novella` (850–999), `stupid_ogre` (1000–1199), `jest` (1200–1999), `formula_tale` (2000–2399) |
| Adult romance genres | `contemporary_romance`, `dark_romance`, `erotic_romance`, `fantasy_romance`, `historical_romance`, `mafia_romance`, `medieval_romance`, `monster_romance`, `new_adult_romance`, `omegaverse_romance`, `paranormal_romance`, `regency_romance`, `romantic_suspense`, `scifi_romance`, `urban_fantasy_romance`, `victorian_romance`, `black_romance`, `lgbtq_romance` |

Every rewrite asks the text model to identify the story's Aarne-Thompson-Uther (ATU) tale type and its core motifs (Stith Thompson's Motif-Index), keep them in order, and change only their surface. Each theme's `motif_map` says how the Motif-Index chapters appear in that setting; in `cyberpunk`, for example, D Magic becomes hacks and implants and K Deceptions becomes identity spoofing. `THEME` annotations in the rewritten story name the chapter each passage draws on.

```bash
# Retell a tale in the form of an ATU division
./ebook-gen generate "Three Billy Goats Gruff" \
  --file stories/three_billy_goats_gruff.txt --theme stupid_ogre

./ebook-gen generate "Little Red Riding Hood" \
  --file stories/little_red_riding_hood.txt --theme formula_tale --rating G
```

### Adult themes and romance tropes

The adult genres and the 18 romance tropes come from [bound2books' guide](https://bound2books.com/smut-guide-genres-tropes/). Add tropes with `--trope`, as many as you like, to any theme except `unmodified`:

```bash
./ebook-gen generate "Little Red Riding Hood" \
  --file stories/little_red_riding_hood.txt \
  --theme monster_romance \
  --trope enemies_to_lovers --trope only_one_bed \
  --rating R --style "oil painting, painterly"

# Tropes work with non-romance themes too
./ebook-gen generate "Three Billy Goats Gruff" \
  --file stories/three_billy_goats_gruff.txt \
  --theme cyberpunk --trope second_chance --rating PG-13
```

Adult themes and every trope add the **adult rules** to the rewrite: everyone in a romantic or sexual scene is an adult, characters who are children in the source are always aged up, and partners are humans or sapient humanlike beings, never ordinary animals. Their image prompts also get `adult_image_keywords` (adults, fully clothed, suggestive rather than explicit) at every rating. Both are in `[defaults]` in `themes.toml`.

### Adding or changing a theme

Add a table to `themes.toml`; there's no need to rebuild an image, since the repository is mounted into the containers. The file is checked when it loads, so a typo or an unknown `{placeholder}` stops the command with an error that names the theme and field.

```toml
[noir]
name = "Film Noir"
description = "A 1940s crime story of rain, shadows and moral grey."
story_prompt = """
You are a crime writer who retells traditional stories as 1940s film noir.
..."""
motif_map = """
- G Ogres: a crooked cop or a crime boss
- K Deceptions: double-crosses and femmes fatales"""
image_keywords = "black and white, venetian blind shadows, rain-slicked streets, fedoras"

# Optional: override any [defaults] template for this theme
cover_system = "Create a 1940s pulp paperback cover prompt for a {theme_name} story in {style} style."
```

A trope is a `[tropes.KEY]` table with `name`, `description` and `guidance`.

## Steering the Image Prompts

From most to least direct:

1. **Edit the prompts.** `projects/<story_id>/prompts/prompts.csv` holds the exact text sent to the image model. Change a row's `prompt` (and `seed` if you like), set its `status` to `pending`, then rerun step 6. Step 6 skips rows still marked `completed`.

   ```bash
   $EDITOR projects/three_billy_goats_gruff_cyberpunk/prompts/prompts.csv   # prompt + status=pending
   ./ebook-gen retry three_billy_goats_gruff_cyberpunk --step 6
   ```

   `promote-images` sets every row back to `pending`, so prompt edits made before promoting are picked up anyway.

2. **Write `<!-- IMAGE: ... -->` annotations.** Each one becomes an illustration. With `--theme unmodified`, the ones in your source file are used as written. Other themes rewrite the story and write their own, so edit `projects/<story_id>/story.md` after step 2. Then regenerate the prompts (step 5) and the images (step 6); `retry` resets only the step you name.

   ```markdown
   The troll leapt onto the bridge, eyes like saucers.

   <!-- IMAGE: A huge moss-covered troll with saucer eyes blocks a narrow wooden bridge; the smallest goat, a white kid, stands frozen at the near end -->
   ```

   ```bash
   ./ebook-gen retry three_billy_goats_gruff_cyberpunk --step 5   # new prompts.csv, all rows pending
   ./ebook-gen retry three_billy_goats_gruff_cyberpunk --step 6   # new images
   ```

3. Pick `--theme`, `--style` and `--rating`; the theme's `image_keywords` and the style are added to every prompt.
4. Edit the wording itself in `themes.toml`: `scene_system`, `scene_request`, `cover_system` and `cover_request` in `[defaults]`, or in one theme's table.

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
# Edit projects/story_id/prompts/prompts.csv if needed: set edited rows to
# status=pending, then: ./ebook-gen retry story_id --step 6

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

`./ebook-gen help` lists every command with its parameters. For more:

```bash
./ebook-gen help generate        # a command's arguments, options and defaults
./ebook-gen help theme           # the values a parameter takes
./ebook-gen help trope
./ebook-gen help rating          # none, G, PG, PG-13, R, NC-17
./ebook-gen help image-mode      # preview, draft, final: sizes and models
./ebook-gen help step            # pipeline steps for retry --step
./ebook-gen help params          # every parameter and the commands that take it
./ebook-gen help build           # also: model-server, test, lint, shell, tui, stage
```

```
ebook-gen generate TITLE --file PATH [OPTIONS]
  --theme THEME              see 'help theme' (default: unmodified)
  --trope TROPE              see 'help trope'; repeat for more; needs a theme
  --rating RATING            none|G|PG|PG-13|R|NC-17 (default: none)
  --style STYLE              see 'help style' (default: photo-realistic)
  --image-mode MODE          preview|draft|final (default: preview)
  --languages CODE           repeat for more (default: en)
  --audio-languages CODE     see 'help audio-languages'; draft and final only
  --text-model REPO          default: mlx-community/gemma-4-12B-it-qat-4bit
  --prompt-model REPO        default: same as --text-model

ebook-gen status STORY_ID
ebook-gen resume STORY_ID
ebook-gen retry STORY_ID [--step N]
ebook-gen preview-images STORY_ID
ebook-gen promote-images STORY_ID [--mode draft|final] [-y]
ebook-gen themes
ebook-gen help [COMMAND | PARAM | params]
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
