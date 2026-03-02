# Prompt Enhancement Models

This document details the optional Ollama models that can enhance image prompt generation.

## Overview

Instead of a single-step prompt generation, we can use a **multi-model pipeline** where each model contributes specialized analysis:

```
Input Story Passage
    ↓
┌─────────────────────────────────┐
│  Parallel Analysis Phase        │
├─────────────────────────────────┤
│ • Emotion/Mood Analyzer         │
│ • Scene Summarizer              │
│ • Visual Detail Extractor       │
│ • Character Tracker             │
│ • Style Reference Generator     │
└─────────────────────────────────┘
    ↓
Aggregated Context
    ↓
Prompt Generator (brxce/stable-diffusion-prompt-generator)
    ↓
Quality Validator
    ↓
Final Refined Prompt → prompts.csv
```

## Model Catalog

### 1. Emotion/Mood Analysis Model

**Model:** `llama3.1:8b` (general-purpose LLM)

**Purpose:** Extract emotional tone and atmospheric mood from story passages

**System Prompt:**
```
You are an emotion analyzer. Read the following story passage and identify:
1. Primary emotion (joy, fear, sadness, anger, surprise, disgust, anticipation, trust)
2. Secondary emotions (if any)
3. Atmospheric mood (tense, peaceful, chaotic, mysterious, etc.)
4. Intensity (subtle, moderate, intense)

Output format:
{
  "primary_emotion": "fear",
  "secondary_emotions": ["anticipation"],
  "mood": "tense, foreboding",
  "intensity": "moderate"
}
```

**Example Input:**
```
The smallest goat approached the bridge cautiously. Below, the toxic waters
churned with an oily sheen. Ahead, the megastructure's lights beckoned,
but something in the shadows shifted.
```

**Example Output:**
```json
{
  "primary_emotion": "fear",
  "secondary_emotions": ["anticipation", "hope"],
  "mood": "tense, foreboding, cautious",
  "intensity": "moderate"
}
```

**Usage in Prompts:**
- Add mood descriptors: "tense atmosphere", "foreboding shadows"
- Adjust lighting: fearful → dark, mysterious lighting
- Influence composition: tension → off-center, unbalanced framing

---

### 2. Scene Summarization Model

**Model:** `qwen2.5:7b` (efficient summarization)

**Alternative:** `mistral:7b`

**Purpose:** Create concise, visual-focused scene summaries

**System Prompt:**
```
You are a visual scene summarizer. Read the story passage and create a brief
summary (1-2 sentences) focusing on:
- Who is present in the scene
- What action is happening
- Where it takes place

Be concrete and visual. Avoid abstractions. Output only the summary.
```

**Example Input:**
```
The smallest Gruff needed to cross the Bifrost Bridge, a crumbling overpass
spanning the toxic runoff canal, to reach the rooftop gardens on the other
side where real grass still grew. As his hooves clicked on the rusted metal,
a deep voice rumbled from below: "Who dares cross my bridge?"
```

**Example Output:**
```
A small goat crosses a rusted bridge over a toxic canal while a threatening
voice emerges from beneath.
```

**Usage in Prompts:**
- Provides clear subject and action for image
- Ensures prompt captures the essential scene elements
- Helps maintain narrative continuity across images

---

### 3. Visual Detail Extraction Model

**Model:** `llama3.1:8b` with specialized prompt

**Purpose:** Extract concrete visual details (colors, lighting, setting, composition)

**System Prompt:**
```
You are a visual detail extractor. Analyze this story passage and extract:
1. Lighting (natural/artificial, time of day, quality)
2. Color palette (dominant colors, contrasts)
3. Setting details (environment, props, architecture)
4. Weather/atmosphere

Output as JSON:
{
  "lighting": "...",
  "colors": ["...", "..."],
  "setting": "...",
  "weather": "..."
}
```

**Example Input:**
```
Neon advertisements flickered across the rain-slicked bridge, casting blue
and purple reflections in the oily water below. The megastructure loomed
ahead, its thousand windows glowing amber against the perpetual smog.
```

**Example Output:**
```json
{
  "lighting": "artificial neon lights, nighttime, moody and atmospheric",
  "colors": ["neon blue", "electric purple", "amber", "dark gray"],
  "setting": "cyberpunk bridge over polluted canal, megastructure skyline",
  "weather": "rain, smog, urban haze"
}
```

**Usage in Prompts:**
- Ensures visual consistency across image sequence
- Provides specific color palette for art direction
- Adds environmental atmosphere details

---

### 4. Character Consistency Tracker

**Model:** `llama3.1:8b` with character-focused prompt

**Purpose:** Maintain consistent character appearance across all images

**System Prompt:**
```
You maintain a character database. For each character mentioned in the passage:
1. Physical description (size, color, distinctive features)
2. Clothing/accessories
3. Personality traits that affect appearance (nervous, confident, etc.)

Update the character entry or create new if first appearance.
Output as JSON.
```

**Character Database Structure:**
```json
{
  "smallest_goat": {
    "species": "goat",
    "size": "small, young",
    "fur": "gray with white patches",
    "clothing": "worn blue courier jacket, cargo pants",
    "accessories": "LED collar (blue glow), shoulder bag",
    "distinctive_features": "one bent horn, nervous expression",
    "posture": "cautious, hunched shoulders"
  }
}
```

**Usage in Prompts:**
- Insert consistent character description in every prompt
- Prevents character appearance drift across images
- Maintains visual continuity throughout the story

**Example Prompt Addition:**
```
"small gray goat with white patches wearing worn blue courier jacket
and LED collar, one bent horn, nervous expression"
```

---

### 5. Style Reference Generator

**Model:** `llama3.1:8b` with art direction prompt

**Purpose:** Generate consistent art style descriptors based on theme

**System Prompt:**
```
You are an art director. Based on the theme ({theme}) and this passage,
generate art style keywords that should be used consistently.

Include:
1. Overall aesthetic (e.g., "blade runner cyberpunk", "ghibli pastoral")
2. Rendering style (e.g., "digital painting", "ink wash", "3D render")
3. Composition approach (e.g., "cinematic framing", "manga panels")
4. Technical keywords (e.g., "volumetric lighting", "depth of field")

Output as comma-separated keywords.
```

**Example Output (Cyberpunk Theme):**
```
blade runner aesthetic, moody cyberpunk, neon noir, high contrast shadows,
volumetric fog, cinematic composition, digital painting, ray-traced lighting,
dystopian atmosphere, industrial decay, reflective wet surfaces
```

**Usage in Prompts:**
- Append to every image prompt for consistency
- Guides the image model's artistic interpretation
- Ensures cohesive visual style across all images

---

### 6. Prompt Quality Validator

**Model:** `qwen2.5:3b` (lightweight, fast)

**Purpose:** Validate prompt completeness and quality before generation

**System Prompt:**
```
You validate image generation prompts. Check if the prompt includes:
1. Subject (who/what)
2. Action (what's happening)
3. Setting (where)
4. Mood/atmosphere
5. Lighting
6. Art style
7. Composition hints

Output: PASS or FAIL with missing elements.
```

**Example Input:**
```
A small gray goat crossing a bridge
```

**Example Output:**
```
FAIL - Missing: mood/atmosphere, lighting, art style, setting details
```

**Example Input (Good):**
```
A small gray goat in a worn courier jacket crosses a rusted cyberpunk bridge
at night, neon blue and purple lights reflecting off rain-slicked metal,
toxic canal below, foreboding atmosphere, blade runner aesthetic,
cinematic composition, moody lighting
```

**Example Output:**
```
PASS - Prompt is complete and detailed
```

**Usage:**
- Run before saving to prompts.csv
- Flag incomplete prompts for regeneration
- Ensure minimum quality threshold

---

## Implementation Strategy

### Phase 1: Core Pipeline (Current)
- Single model: `brxce/stable-diffusion-prompt-generator`
- Direct story text → prompt
- Fast, simple

### Phase 2: Enhanced Pipeline (Optional)
- Multi-model analysis
- Context aggregation
- Quality validation

### Configuration

Add to `StoryConfig`:

```python
@dataclass
class PromptEnhancementConfig:
    enabled: bool = False  # Toggle enhancement pipeline
    extract_emotions: bool = True
    extract_visual_details: bool = True
    track_characters: bool = True
    generate_style_refs: bool = True
    validate_quality: bool = True

    # Model assignments
    emotion_model: str = "llama3.1:8b"
    summary_model: str = "qwen2.5:7b"
    visual_model: str = "llama3.1:8b"
    character_model: str = "llama3.1:8b"
    style_model: str = "llama3.1:8b"
    validator_model: str = "qwen2.5:3b"
```

### CLI Usage

```bash
# Enable prompt enhancement
ebook-gen generate "Story" \
  --theme cyberpunk \
  --enhance-prompts

# Disable for quick preview
ebook-gen generate "Story" \
  --theme cyberpunk \
  --image-mode preview \
  --no-enhance-prompts
```

### Performance Considerations

**Without Enhancement:**
- 1 model call per image
- ~2-5 seconds per prompt
- 10 images = ~30 seconds

**With Full Enhancement:**
- 6 model calls per image (5 analyzers + 1 validator)
- ~10-20 seconds per prompt
- 10 images = ~2-3 minutes

**Recommendation:**
- **PREVIEW mode:** Disable enhancement (speed priority)
- **DRAFT mode:** Enable enhancement (balance quality and speed)
- **FINAL mode:** Enable enhancement (quality priority)

---

## Additional Model Options

### Alternative Models to Consider

**For Emotion Analysis:**
- `phi3:mini` - 3.8B params, very fast
- `gemma2:9b` - Good at nuanced analysis

**For Summarization:**
- `mistral:7b` - Excellent at concise extraction
- `qwen2.5:3b` - Even faster, good enough for summaries

**For Visual Analysis:**
- `llama3.1:70b` - More detailed but slower
- `mixtral:8x7b` - Good quality/speed balance

**For Validation:**
- `tinyllama:1.1b` - Extremely fast for simple checks
- `qwen2.5:3b` - Good balance

---

## Example Enhanced Workflow

**Input Passage:**
```
The smallest billy goat Gruff stepped onto the Bifrost Bridge. Neon signs
flickered overhead, reflecting in the rain. Below, the canal churned with
chemical waste. Somewhere in the darkness, metal scraped against metal.
```

**Step 1 - Emotion Analysis:**
```json
{
  "primary": "fear",
  "mood": "tense, ominous",
  "intensity": "moderate"
}
```

**Step 2 - Scene Summary:**
```
Small goat crosses industrial bridge at night over toxic canal
```

**Step 3 - Visual Details:**
```json
{
  "lighting": "neon signs, nighttime, moody",
  "colors": ["neon blue", "neon pink", "dark gray", "toxic green"],
  "setting": "industrial bridge, toxic canal, urban decay",
  "weather": "rain"
}
```

**Step 4 - Character (from DB):**
```
small gray goat, courier jacket, LED collar, nervous demeanor
```

**Step 5 - Style:**
```
blade runner aesthetic, cyberpunk noir, volumetric lighting, cinematic
```

**Step 6 - Aggregate & Generate:**
```
A small gray goat in a worn courier jacket with glowing blue LED collar
cautiously crosses a rusted industrial bridge at night, neon blue and pink
signs flickering overhead reflecting in rain-slicked metal, toxic green
canal churning below, ominous shadows, tense atmosphere, blade runner
aesthetic, cyberpunk noir, volumetric lighting, moody cinematic composition,
high contrast, digital painting
```

**Step 7 - Validate:**
```
PASS - All required elements present
```

**Result:** High-quality, detailed prompt ready for image generation

---

## Future Enhancements

1. **Vision Model Feedback Loop**
   - Use `llava` or similar vision model to analyze generated images
   - Compare to prompt and story context
   - Suggest prompt refinements

2. **Multi-language Prompt Generation**
   - Generate prompts in multiple languages
   - Test which language produces better results for specific models

3. **Prompt Templates by Layout**
   - Different prompt structures for manga panels vs full scenes
   - Layout-aware composition hints

4. **A/B Testing**
   - Generate multiple prompt variations
   - Preview multiple versions
   - Select best for final generation
