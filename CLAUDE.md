# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based ebook generation pipeline that transforms stories (fetched from Wikipedia) into themed, illustrated ebooks in multiple formats (ePub, PDF) and languages.

**Core workflow (7-step pipeline):**
1. Wikipedia Fetch - retrieve story source
2. Story Modification - apply thematic transformations (cyberpunk, caribbean village, etc.)
3. Content Rating - assign G, PG-13, etc. based on modifications
4. Translation - translate (with cultural adaptation) using the text model
5. Prompt Generation - create image prompts using the text model
6. Image Generation - generate illustrations with FLUX.2 Klein or Z-Image Turbo (mflux)
7. Ebook Compilation - assemble story + images into ePub and PDF

## Development Environment

**Stack (native on Apple Silicon; the Docker/NVIDIA setup in README.md is outdated):**
- pixi (environment + tasks), Python 3.12
- MLX backend (default): `mlx-lm` for text, `mflux` for images, models from Hugging Face cached under `HF_HOME`
- Kokoro TTS (PyTorch) for narration; weasyprint + ebooklib for PDF/ePub
- Ollama is optional (`EBOOK_GEN_BACKEND=ollama`), text only: Ollama removed image generation in v0.32.6

**Key commands** (paths passed to `--file` must be absolute: pixi tasks run from `code/`):

```bash
pixi install                                  # create the environment
pixi run ebook-gen generate "Three Billy Goats Gruff" \
  --file "$PWD/stories/three_billy_goats_gruff.txt" \
  --theme cyberpunk --rating PG-13 \
  --languages en --languages es --image-mode preview
pixi run ebook-gen status <story_id>
pixi run ebook-gen resume <story_id>
pixi run ebook-gen promote-images <story_id> --mode draft
pixi run test                                 # tests
pixi run lint                                 # ruff (pre-existing errors remain)
```

## Architecture

### Component-Based Pipeline

Each pipeline step is a `PipelineComponent` subclass with typed input/output dataclasses. All components are stateless - state lives on disk in CSV files and Markdown.

**Pipeline orchestration:** `PipelineRunner` executes steps sequentially, tracking progress in `progress/<story>/pipeline_state.csv` for resume capability.

**Key components:**
- `WikipediaFetcher` - HTTP fetch + HTML-to-Markdown conversion
- `StoryModifier` - LLM-based theme transformation with annotation insertion
- `ContentRater` - Rating assignment via LLM analysis
- `Translator` - Per-language translation with chunking for long stories
- `PromptGenerator` - Extract IMAGE annotations → generate prompts via Ollama
- `ImageGenerator` - Generate images from prompts, track status in CSV
- `EbookCompiler` - Markdown + images → ePub + PDF (using ebooklib + weasyprint)

### Directory Structure

```
root/
├── code/              # Python source (ebook_gen package)
├── compiled/          # Output: PDF and ePub files (per story, per language)
├── images/            # Output: generated images (subdirectory per story)
├── prompts/           # CSV tracking: image prompts and generation status
├── stories/           # Input: annotated story markdown files
└── progress/          # Pipeline state CSVs (for resume capability)
```

### Story File Format

Stories are stored as Markdown with HTML comment annotations:

```markdown
# Story Title

<!-- META theme: cyberpunk, rating: PG-13 -->

<!-- DIRECTOR: Opening scene shows neon-lit bridge over polluted canal -->

Once upon a time...

<!-- IMAGE: Small goat approaching cyberpunk bridge at night -->

<!-- THEME: Bridge represents digital divide between undercity and megacorp -->
```

**Annotation types:**
- `<!-- META -->` - Story-level metadata
- `<!-- DIRECTOR: -->` - Staging guidance for theme modification
- `<!-- THEME: -->` - Thematic connection explanations
- `<!-- RATING: -->` - Content rating justification
- `<!-- IMAGE: -->` - Image placement hints (consumed by prompt generator)
- `<!-- TRANSLATION_NOTE: -->` - Cultural adaptation guidance

All annotations are stripped before ebook compilation.

### Resume Capability

**Pipeline state:** Tracked in `progress/<story>/pipeline_state.csv` with columns:
- step, name, status (pending/in_progress/completed/failed), timestamps, error_message, attempts, output_artifact

**Image state:** Tracked in `prompts/<story>/prompts.csv` with columns:
- image_id, name, description, prompt, model, target_filename, status, width, height, seed

Both CSVs use atomic writes (write-to-temp-then-rename) to prevent corruption on crashes.

### Model Backends

Components depend on `GenerationBackend` (`backends/base.py`): `generate_text(...)` and `generate_image(...)`. `create_backend()` picks the implementation from `EBOOK_GEN_BACKEND` (`mlx` default, or `ollama`).

**MLX defaults** (`config.py`):
- Text, translation, rating and image prompts: `mlx-community/gemma-4-12B-it-qat-4bit`
- Images, preview/draft: `mflux-community/flux2-klein-4b-mflux-q4` (Apache-2.0)
- Images, final: `mflux-community/flux2-klein-9b-mflux-q4` (FLUX **non-commercial** license)
- Alternative: `mflux-community/z-image-turbo-mflux-q8` (Apache-2.0)

`MLXBackend` keeps one model in memory at a time (24 GB machine) and maps legacy Ollama tags stored in old `metadata.json`/`prompts.csv` (e.g. `x/flux2-klein:4b`) to MLX repo ids via `LEGACY_MODEL_ALIASES`.

## Development Workflow

### Three-Tier Quality Progression

The system supports a three-stage workflow to minimize GPU time while maximizing quality:

**Stage 1: PREVIEW** - Test prompts quickly
- Low resolution (256x192, 1/4 target)
- Fast model (`x/flux2-klein:4b`)
- ~5-10 seconds per image
- Purpose: Validate prompts and image selection

**Stage 2: DRAFT** - Review layout and composition
- Medium resolution (512x384, 1/2 target)
- Same fast model but full inference
- ~30-60 seconds per image
- **Compiles a draft ebook for layout review**
- Purpose: Validate layout, text-image flow, overall composition

**Stage 3: FINAL** - Generate publication quality
- Full resolution (1024x768)
- High-quality model (`x/flux2-klein:9b`)
- ~2-5 minutes per image
- **Compiles final publication ebook**
- Purpose: Publication-ready output

**Example Workflow:**
```bash
# 1. Preview - Quick prompt testing (minutes)
ebook-gen generate "Story" --theme cyberpunk --image-mode preview
ebook-gen preview-images story-id
# Edit prompts if needed: prompts/story-id/prompts.csv
ebook-gen retry story-id --step 6

# 2. Draft - Layout review (tens of minutes)
ebook-gen promote-images story-id --mode draft
# Review: compiled/story-id/story-id_en_draft.pdf
# Adjust layout if needed
ebook-gen configure-layout story-id --style manga

# 3. Final - Publication (hours)
ebook-gen promote-images story-id --mode final
# Publication ready: compiled/story-id/story-id_en.pdf
```

### Layout Styles

Five layout styles are supported:

1. **traditional** - Classic illustrated book (images inline with text)
2. **manga** - Japanese-style panels (right-to-left reading)
3. **graphic-novel** - Western comic book panels (left-to-right)
4. **webtoon** - Vertical scroll for mobile (digital-only)
5. **cinematic** - Widescreen storyboard style

Configure layout:
```bash
ebook-gen generate "Story" --layout manga
ebook-gen configure-layout story-id --style graphic-novel --panels-per-page 6
```

See DESIGN.md Section 12 for detailed layout specifications.

### Error Handling

All file writes use atomic operations (write-to-temp-then-rename). Network operations use exponential backoff retry. Per-component errors are logged in pipeline_state.csv with step name, error message, and attempt count.

**Recovery strategies:**
- Wikipedia fetch: Retry with backoff; handle disambiguation pages
- LLM generation: Retry; validate output structure; save raw output for debugging
- Image generation: Per-image retry; skip failed images with placeholder
- Translation: Per-language retry; continue with other languages if one fails

### Testing

**Test structure:**
- Unit tests: Pure logic, no I/O (markdown parsing, CSV serialization, config validation)
- Integration tests: Real file I/O + mocked Ollama (test each component independently)
- E2E tests: Full pipeline with mocked Ollama

**Run tests:**
```bash
pixi run test          # All tests
pixi run test-cov      # With coverage report
```

## Key Design Decisions

1. **CSV over SQLite** - Human-readable, editable, diffable; tiny data volume
2. **File-system-as-database** - One subdirectory per story (no central DB)
3. **HTML comment annotations** - Valid Markdown, invisible in renderers, simple to strip
4. **Synchronous pipeline** - Each step depends on prior; Ollama is single-threaded anyway
5. **Prompts from source language only** - Images are language-independent; avoids inconsistency
6. **Three-tier quality progression** - Preview → Draft → Final minimizes GPU time waste
7. **Layout-first design** - Different layouts require different image prompts and compositions
8. **Consistency checks** - Story fidelity validation and character design registry ensure quality
   - Narrative structure preserved across theme transformations
   - Character appearance consistent across all images via character sheets

## Important Notes

- **Never commit to main without tests passing** - Run `pixi run test` first
- **Annotations must not break Markdown rendering** - Test story files in a Markdown previewer
- **CSV writes must be atomic** - Use the `atomic_write()` helper in `utils/file_io.py`
- **LLM outputs must be validated** - Check for required structure (chapters, annotations) before accepting
- **Always use preview mode first** - Don't waste GPU time on draft/final until prompts are perfect
- **Draft before final** - Always review layout and composition in draft mode before final generation
- **Layout affects prompts** - Different layouts need different image compositions (panels vs full scenes)

## Prompt Enhancement Pipeline (Optional)

The system can use multiple Ollama models to enhance image prompt quality:

**Enhancement Models:**
1. **Emotion Analyzer** - Extract mood and atmosphere (llama3.1:8b)
2. **Scene Summarizer** - Create visual summaries (qwen2.5:7b)
3. **Visual Detail Extractor** - Extract colors, lighting, setting (llama3.1:8b)
4. **Character Tracker** - Maintain consistent appearance (llama3.1:8b)
5. **Style Generator** - Ensure art style consistency (llama3.1:8b)
6. **Quality Validator** - Check prompt completeness (qwen2.5:3b)

**Trade-off:** 6 model calls per image (~10-20 sec) vs 1 call (~2-5 sec)

**Recommendation:**
- PREVIEW: Disable (speed priority)
- DRAFT/FINAL: Enable (quality priority)

See `PROMPT_ENHANCEMENT.md` for detailed documentation.

## Future Enhancements

Potential areas for extension (not currently implemented):
- YAML-based theme registry (currently hard-coded in Python)
- Batch story processing
- Parallel image generation across multiple Ollama instances
- Custom cover image upload option
- Interactive prompt refinement UI
- Vision model feedback loop (analyze generated images, refine prompts)
