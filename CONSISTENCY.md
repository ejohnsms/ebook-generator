# Consistency Framework

## Overview

Maintaining consistency across themed transformations and visual generation is critical for quality ebooks. This document outlines the consistency checks and mechanisms.

## 1. Narrative Consistency

### Problem
When transforming "Three Billy Goats Gruff" into steampunk, cyberpunk, etc., we must ensure:
- Core narrative structure is preserved
- Character relationships remain intact
- Key plot points are maintained (just transformed)
- Moral/theme stays true to original

### Solution: Story Fidelity Validator

**Runs after Step 2 (Story Modification)**

#### What It Checks

```python
@dataclass
class NarrativeStructure:
    """Extracted narrative structure."""
    characters: list[str]            # Main characters
    character_count: int
    relationships: list[str]         # e.g., "sibling", "antagonist"
    plot_points: list[str]          # Key events
    moral: str                      # Story's lesson/theme
    beginning: str                  # Setup summary
    middle: str                     # Conflict summary
    end: str                        # Resolution summary
```

#### Validation Process

```
Original Story
    ↓
[Extract Structure] → Original Structure
    ↓
Modified Story
    ↓
[Extract Structure] → Modified Structure
    ↓
[Compare Structures]
    ↓
[Generate Fidelity Report]
```

#### Fidelity Metrics

| Aspect | Threshold | Action if Failed |
|--------|-----------|------------------|
| Character count match | Exact | Warn user, allow override |
| Character roles preserved | 80%+ | Warn user, allow override |
| Plot points present | 90%+ | Warn user, suggest regeneration |
| Narrative arc preserved | Manual review | Show diff to user |

#### Example

**Original "Three Billy Goats Gruff":**
```yaml
characters:
  - Smallest Goat
  - Middle Goat
  - Biggest Goat
  - Troll
relationships:
  - "Three goats are siblings"
  - "Troll is antagonist"
plot_points:
  - "Smallest crosses bridge, troll confronts"
  - "Smallest talks his way past"
  - "Middle crosses, same pattern"
  - "Biggest crosses, defeats troll"
  - "All three graze safely"
moral: "Clever thinking and unity overcome obstacles"
```

**Cyberpunk Version Check:**
```yaml
characters:
  - Smallest Courier (✓ mapped from Smallest Goat)
  - Middle Hacker (✓ mapped from Middle Goat)
  - Biggest Enforcer (✓ mapped from Biggest Goat)
  - Rogue AI (✓ mapped from Troll)
relationships:
  - "Three are part of same crew" (✓ siblings → crew)
  - "AI is antagonist" (✓ preserved)
plot_points:
  - "Smallest crosses data bridge, AI confronts" (✓)
  - "Smallest talks way through" (✓)
  - "Middle crosses, same" (✓)
  - "Biggest crosses, defeats AI" (✓)
  - "All three access megastructure" (✓ graze → access)
moral: "Clever thinking and teamwork overcome obstacles" (✓)
```

**Result:** PASS - All key elements preserved with appropriate transformations

#### Implementation

```python
class StoryFidelityValidator:
    """Validates that themed story preserves original narrative."""

    def __init__(self, ollama_client: OllamaClient):
        self._ollama = ollama_client

    def validate(
        self,
        original_text: str,
        modified_text: str,
        theme: Theme
    ) -> FidelityReport:
        """Compare original and modified stories.

        Returns:
            FidelityReport with pass/fail and recommendations
        """
        # Extract structures using LLM
        original_structure = self._extract_structure(original_text)
        modified_structure = self._extract_structure(modified_text)

        # Compare
        character_match = self._compare_characters(
            original_structure, modified_structure
        )
        plot_match = self._compare_plot_points(
            original_structure, modified_structure
        )
        moral_match = self._compare_moral(
            original_structure, modified_structure
        )

        # Generate report
        return FidelityReport(
            overall_score=(character_match + plot_match + moral_match) / 3,
            character_fidelity=character_match,
            plot_fidelity=plot_match,
            moral_fidelity=moral_match,
            recommendations=self._generate_recommendations(...)
        )
```

---

## 2. Visual Consistency

### Problem
If the "eldest goat" appears in 5 different images, it must look the same in all 5:
- Same size/build
- Same coloring
- Same distinctive features
- Same clothing/accessories (in themed versions)

### Solution: Character Design Registry

**Created during Step 5 (Prompt Generation)**

#### Character Sheet Generation

For each character, generate a detailed "character sheet":

```yaml
character_id: eldest_goat
canonical_name: "Biggest Billy Goat Gruff"
themed_name: "The Enforcer" # cyberpunk version

physical_description:
  species: "anthropomorphic goat"
  size: "large, imposing, muscular build"
  height: "tallest of the three"
  fur_color: "dark gray with black patches"
  distinctive_features:
    - "Large curved horns with metal reinforcement"
    - "Scar across left eye"
    - "Intimidating presence"

cyberpunk_adaptation:
  clothing: "Heavy armored jacket, dark colors"
  accessories:
    - "Cybernetic eye implant (left eye, red glow)"
    - "Reinforced combat boots"
    - "Shoulder-mounted weapon system"
  technology: "Built-in HUD, enhanced strength implants"

art_style_notes:
  - "Strong, confident posture"
  - "Often shown from low angle to emphasize size"
  - "Weathered, battle-hardened appearance"

appearance_consistency_prompt: |
  A large, imposing anthropomorphic goat with dark gray fur and black
  patches, tall muscular build, large curved horns with metal reinforcement,
  scar across left eye, wearing heavy armored jacket in dark colors,
  cybernetic red-glowing eye implant on left eye, reinforced combat boots,
  shoulder-mounted weapon system, strong confident posture, battle-hardened
  weathered appearance
```

#### Usage in Image Prompts

**Every prompt featuring this character includes the consistency prompt:**

```
Scene: The Enforcer confronts the rogue AI on the bridge

Prompt:
A large imposing anthropomorphic goat with dark gray fur and black patches,
muscular build, large curved horns with metal reinforcement, scar across
left eye with red-glowing cybernetic implant, wearing heavy armored jacket,
stands confronting a holographic AI interface on a neon-lit bridge at night,
tense standoff, cyberpunk aesthetic, moody lighting, high contrast...
```

#### Visual Consistency Checker

After images are generated (especially in preview mode):

```python
class VisualConsistencyChecker:
    """Checks visual consistency across character appearances."""

    def check_character_consistency(
        self,
        character_id: str,
        image_paths: list[Path],
        character_sheet: CharacterSheet
    ) -> ConsistencyReport:
        """Use vision model to check if character looks consistent.

        Args:
            character_id: Which character to check
            image_paths: All images featuring this character
            character_sheet: Expected appearance

        Returns:
            Report with consistency scores and issues
        """
        # Use a vision-language model (llava, cogvlm, etc.)
        # to analyze each image and check against character sheet

        issues = []
        for i, img_path in enumerate(image_paths):
            description = self._describe_character_in_image(img_path)

            # Compare to character sheet
            if not self._matches_description(description, character_sheet):
                issues.append({
                    "image": img_path,
                    "expected": character_sheet.physical_description,
                    "actual": description,
                    "suggestion": "Regenerate with stronger character emphasis"
                })

        return ConsistencyReport(
            character_id=character_id,
            images_checked=len(image_paths),
            issues_found=len(issues),
            issues=issues
        )
```

#### Multi-Stage Character Refinement

**Stage 1: PREVIEW Mode**
- Generate first image of each character
- Review character appearance
- User approves or requests modifications
- Lock in character design before proceeding

**Stage 2: Character Sheet Finalization**
- Based on approved preview images
- Extract actual visual characteristics from generated images
- Update character sheets with "as-generated" details
- Use these refined sheets for draft/final generation

**Stage 3: DRAFT/FINAL Modes**
- Use locked character sheets
- Stronger weighting on character consistency in prompts
- Optional: Use first preview image as reference image

---

## 3. Implementation Strategy

### Phase 2.5: Add Consistency Checks

Before moving to Phase 3, add:

#### Task 1: Story Fidelity Validator
```
Location: ebook_gen/components/story_validator.py

Runs after: Step 2 (Story Modification)
Before: Step 3 (Content Rating)

Process:
1. Extract narrative structure from original story
2. Extract narrative structure from modified story
3. Compare structures
4. Generate fidelity report
5. If score < 70%, warn user and offer regeneration
```

#### Task 2: Character Registry
```
Location: ebook_gen/components/character_registry.py

Created during: Step 5 (Prompt Generation)

Data Structure:
- characters.json in stories/<story>/ directory
- One entry per character
- Physical description, theme adaptation, consistency prompt

Usage:
- Injected into every image prompt for that character
- Updated based on preview image feedback
```

#### Task 3: Visual Consistency CLI Commands
```bash
# Review character designs after preview generation
ebook-gen review-characters three-billy-goats-gruff

# Shows preview images for each character
# Allows user to approve or request regeneration
# Option to edit character sheets manually

# Check consistency after image generation
ebook-gen check-consistency three-billy-goats-gruff \
  --character "eldest_goat"

# Generates consistency report using vision model
```

---

## 4. Configuration

Add to `StoryConfig`:

```python
@dataclass
class ConsistencyConfig:
    """Consistency checking configuration."""

    # Narrative fidelity
    check_story_fidelity: bool = True
    min_fidelity_score: float = 0.70  # 70% threshold
    auto_reject_low_fidelity: bool = False  # If False, warn user

    # Visual consistency
    check_visual_consistency: bool = True
    lock_characters_after_preview: bool = True
    use_preview_as_reference: bool = False  # Use preview images as reference

    # Character tracking
    generate_character_sheets: bool = True
    characters_from_model: str = "llama3.1:8b"
    visual_check_model: str = "llava"  # Vision-language model
```

---

## 5. Workflow with Consistency Checks

```bash
# Step 1: Generate with preview mode
ebook-gen generate "Three Billy Goats Gruff" \
  --theme cyberpunk \
  --image-mode preview

# After Step 2: Story Fidelity Check (automatic)
# Output: ✓ Story fidelity: 87% - Core narrative preserved

# After Step 5: Character Sheets Generated
# Output: Generated 4 character sheets in stories/.../characters.json

# After Step 6: Preview Images Generated
# Review characters
ebook-gen review-characters three-billy-goats-gruff

# Shows:
# Character: Smallest Courier
#   Preview: images/.../character_01_preview.png
#   Design: [character sheet details]
#   [Approve] [Regenerate] [Edit Design]

# If approved → character sheet locked for draft/final

# Step 7: Generate draft with locked characters
ebook-gen promote-images three-billy-goats-gruff --mode draft

# After draft generation
ebook-gen check-consistency three-billy-goats-gruff

# Output:
# Consistency Report:
#   Smallest Courier: ✓ 3/3 images consistent
#   Middle Hacker: ⚠ 2/3 images consistent
#     Issue: Image 2 shows different clothing
#   Eldest Enforcer: ✓ 4/4 images consistent
```

---

## 6. Example: Three Billy Goats Gruff → Cyberpunk

### Character Sheet: Eldest Goat

**Original:**
- Large billy goat
- Eldest of three siblings
- Strong and brave
- Defeats the troll

**Cyberpunk Transformation:**
```json
{
  "character_id": "eldest_goat",
  "original_name": "Biggest Billy Goat Gruff",
  "themed_name": "The Enforcer",

  "physical_base": {
    "species": "anthropomorphic goat",
    "role": "eldest sibling, protector",
    "personality": "brave, strong, protective"
  },

  "visual_design": {
    "size": "tallest and most muscular of the three",
    "fur": "dark gray with black patches, weathered",
    "horns": "large curved horns with chrome/metal reinforcement",
    "build": "imposing, muscular, battle-hardened",

    "cyberpunk_elements": {
      "cybernetics": "red-glowing eye implant (left eye), enhanced strength implants",
      "clothing": "heavy armored tactical jacket (black/dark gray), cargo pants, combat boots",
      "weapons": "shoulder-mounted weapon system, built-in HUD",
      "accessories": "tactical harness, ammo pouches, comm unit"
    },

    "distinctive_features": [
      "Scar across left eye (where cybernetic implant is)",
      "Metal-reinforced horns gleaming in neon light",
      "Intimidating presence - commands respect",
      "Often shown from low camera angle to emphasize size"
    ]
  },

  "consistency_prompt": "A large imposing anthropomorphic goat, tallest and most muscular of three siblings, dark gray fur with black patches, weathered battle-hardened appearance, large curved horns with chrome metal reinforcement, red-glowing cybernetic eye implant on left eye with scar, wearing heavy black armored tactical jacket and combat boots, shoulder-mounted weapon system, tactical harness, intimidating protective presence",

  "appearance_notes": [
    "Always the tallest figure in frame when with siblings",
    "Confident, protective body language",
    "Tech-enhanced but still recognizably goat-like",
    "Dark color palette - blacks, grays, metallic accents, red eye glow"
  ]
}
```

This character sheet is then **injected into every prompt** where the Enforcer appears, ensuring visual consistency across all images.

---

## Summary

**Consistency is maintained through:**

1. **Story Fidelity Validator** - Ensures narrative stays true to source
2. **Character Design Registry** - Defines consistent appearance for each character
3. **Visual Consistency Checker** - Validates character appearance across images
4. **Multi-stage Workflow** - Preview → approve → lock → generate final

This framework ensures that whether the story is traditional or heavily themed (steampunk, cyberpunk, etc.), the core narrative and character identities remain consistent and recognizable.
