# Critical-Term Accessibility Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make lecture caption exports fail accessibility review when critical glossary terms or course-specific terms are still wrong after repair, while keeping the current MLX caption path and cue-shaping work intact.

**Architecture:** Keep transcription, cue shaping, and accessibility verdicts as separate stages. The transcription backend can remain whatever policy selects for macOS local helper runs, but the final accessibility verdict must be driven by the exported captions plus a narrow critical-term check derived from the project glossary and built-in lecture terms. The export should still be repaired before verdicting; if a critical term remains wrong after repair, the output should be `failed`, not `passed with warnings`.

**Tech Stack:** Python, pytest, existing RADcast caption pipeline, existing accessibility verdict enum/status UI.

---

### Task 1: Add failing coverage for critical-term misses

**Files:**
- Modify: `src/radcast/services/caption_review.py`
- Modify: `tests/test_caption_review.py`
- Modify: `tests/test_speech_cleanup.py`

- [ ] **Step 1: Write the failing test**

Add an integration-style test that feeds a final exported caption segment containing an obvious critical-term miss, such as `Aitikanga Māori space`, and asserts that the exported accessibility assessment is `failed`.

Add or extend a reviewer-level test that confirms `build_caption_quality_report(..., critical_terms=[...])` flags a probable critical-term miss for a glossary term like `tikanga`.

- [ ] **Step 2: Run the targeted tests to verify the current behavior**

Run:

```bash
python3 -m pytest \
  /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py \
  /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q
```

Expected: the new tests fail until the critical-term verdict is wired all the way through the export path.

- [ ] **Step 3: Write the minimal implementation**

Keep the critical-term detection narrow:

- use the project glossary when available
- include the built-in Māori lecture terms
- only classify a miss as critical when the final export still visibly gets the term wrong

Do not expand the heuristic into broad phonetic matching beyond the current tuned thresholds.

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run the same pytest command again.

Expected: all targeted caption-quality tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/radcast/services/caption_review.py tests/test_caption_review.py tests/test_speech_cleanup.py
git commit -m "feat: fail accessibility review on critical term misses"
```

### Task 2: Keep final accessibility verdict aligned with repaired exports

**Files:**
- Modify: `src/radcast/services/speech_cleanup.py`
- Modify: `src/radcast/models.py` only if the verdict payload needs a field shape adjustment
- Modify: `tests/test_api_ui.py`

- [ ] **Step 1: Write the failing test**

Add an API/UI test that verifies the completed output card shows:

- `passed` in green when no accessibility defects remain
- `passed with warnings` in amber when only minor warnings remain
- `failed` in red when a critical-term miss survives export repair

If the existing status mapping already exists, make the test assert the critical-term failure case specifically.

- [ ] **Step 2: Run the targeted test to verify the current behavior**

Run:

```bash
python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py -q
```

Expected: any missing verdict wiring fails here before implementation.

- [ ] **Step 3: Write the minimal implementation**

Ensure the final `CaptionExportResult.accessibility_assessment` is derived from the cleaned export report, not the pre-shape review report, and that the UI consumes that status without reinterpreting it.

- [ ] **Step 4: Run the targeted test to verify it passes**

Run the same pytest command again.

Expected: UI/API status tests pass, and the card reflects the final export verdict.

- [ ] **Step 5: Commit**

```bash
git add src/radcast/services/speech_cleanup.py src/radcast/models.py tests/test_api_ui.py
git commit -m "feat: align accessibility verdict with final caption export"
```

### Task 3: Validate against the lecture examples that motivated the change

**Files:**
- Read only: `~/Desktop/m8-02-utu-reciprocity-20260409-044624.vtt`
- Read only: `~/Desktop/quantum-entanglement-in-5-minutes-20260409-025831.vtt`
- Read only: `~/Desktop/quantum-entanglement-in-5-minutes-20260408-022257.vtt`

- [ ] **Step 1: Re-run the focused regression suite**

Run the caption-quality tests again after the code changes:

```bash
python3 -m pytest \
  /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py \
  /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_cue_shaping.py \
  /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py \
  /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_worker_queue.py \
  /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_worker_setup.py -q
```

- [ ] **Step 2: Check the latest lecture outputs**

Confirm the outputs now fail when a critical term is still wrong and pass when the caption export is actually accessibility-grade.

- [ ] **Step 3: Commit the validation notes only if needed**

No code should be added in this step unless a new regression is discovered.

