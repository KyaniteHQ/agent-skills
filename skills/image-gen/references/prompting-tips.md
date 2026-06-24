# gpt-image-2 prompting tips

Distilled from the OpenAI cookbook image-generation prompting guide. Focus is on what materially changes
output quality for `gpt-image-2` (the model the `image_generation` tool drives). Notes are short on
purpose; pull only the section relevant to the current task.

## Cheap smoke test

To prove the pipeline works without spending much, drop `--quality low` and `--size 1024x1024` — same
shape, a fraction of the time and cost. Scale up once it works.

## Prompt structure

- **Order matters.** Walk from background → subject → key details → constraints. For complex requests, use
  line breaks or labeled segments rather than one dense paragraph.
- **For photorealism, say "photorealistic" explicitly.** Phrases like "real photograph" or "professional
  photography" help. Camera spec details (lens, ISO, focal length) are interpreted loosely — use them for
  composition and feel, not exact physical simulation.
- **Format is flexible.** Plain sentences, descriptive paragraphs, JSON objects, and tag-based prompts all
  work. Prefer whichever is easiest to maintain in your pipeline.

## What reliably works

- **Specificity + quality cues.** Be concrete about materials, shapes, textures, and medium (photo,
  watercolor, 3D render). Add quality levers sparingly — film grain, textured brushstrokes, macro detail —
  only where they earn the words.
- **Composition control.** Specify framing (close-up, wide, top-down), perspective (eye-level, low-angle),
  and lighting (soft diffuse, golden hour, high-contrast). For moody or wide scenes, add detail about
  scale, atmosphere, and color so the model does not sacrifice mood for surface realism.
- **People and action.** Describe scale, body framing, gaze, and object interactions: "full body visible,
  feet included", "looking down at the open book, not at the camera". Prevents proportion/gaze misalignment.
- **Text in images.** Wrap literal text in **quotes** or **ALL CAPS** and specify typography (font style,
  size, color, placement). For tricky words, spell them letter-by-letter. Use `--quality medium` or `high`
  for small or dense text.

## Editing prompts (`--style-reference`)

- **Preserve vs. change explicitly.** State what to alter AND what must remain unchanged: "change only X",
  "keep everything else the same", "preserve identity / geometry / layout / brand elements". Repeat the
  preserve list every iteration to fight drift.
- **Surgical edits.** Call out what must not move — saturation, contrast, layout, arrows, labels, camera
  angle, surrounding objects.
- **`input_fidelity` does not apply to `gpt-image-2`.** The model is already high-fidelity by default; just
  lean on explicit preserve language.

## Parameter trade-offs

- **`--quality`** — `low`: fast, cheap, ideation/high-volume. `medium`/`high`: small or dense text,
  infographics, detailed close-up portraits, identity-sensitive edits, high-resolution outputs.
- **`--size`** — edges up to 3840px, both multiples of 16, aspect ratio up to 3:1, total pixels between
  655,360 and 8,294,400. Treat results above 2560×1440 ("2K") as experimental; output gets more variable.
- **Output format** — the helper requests PNG from the backend and converts to WebP locally via Pillow;
  pass `--keep-png` to also keep the raw PNG. Generate on an opaque background and remove it downstream if
  you need transparency (transparent backgrounds are unreliable through this path).

## Iteration strategy

- **Avoid overloading.** Long prompts work, but it is easier to debug from a clean base prompt and refine
  with small, single-change follow-ups: "make lighting warmer", "remove the extra tree".
- **Reference prior context cautiously.** "Same style as before" works inside a single edit chain, but
  re-specify any critical detail that has drifted.
- **Text rendering hiccups.** Keep the prompt strict and iterate on wording; demand verbatim rendering with
  no extra characters.

## Use-case shortcuts

- **Infographics / diagrams.** `--quality medium`/`high`, list required components explicitly, state what
  should *not* be included.
- **Product shots.** Opaque background; preserve labels and geometry exactly; light polish, subtle contact
  shadows.
- **UI mockups.** Describe the product as if it already exists — layout, hierarchy, spacing, real interface
  elements. Avoid concept-art language so it looks shipped, not sketched.
- **Logos.** Clean, vector-like shapes; strong silhouette; balanced negative space; simplicity over detail
  so it reads at all sizes. `--n 4` to explore variations.
- **Ad creatives.** Write like a creative brief: brand positioning, audience, scene, exact tagline. Leave
  taste decisions to the model within those guardrails.
- **Character / story continuity.** Lock the character on the first generation, then use `--style-reference`
  (not a fresh generate) for subsequent panels so identity carries through.

## What does not help

- **Camera specs as physical simulation.** They influence look but not exact optics.
- **Stacking redundant quality words.** "ultra-detailed, hyperrealistic, 8k, masterpiece, award-winning…"
  is mostly noise — pick one or two cues, keep the rest about content.
- **Explaining intent.** "I want this to feel inviting" works less well than describing the lighting,
  composition, and color that produce that feel.
