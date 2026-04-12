# Selective Low-Confidence Rerun Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve lecture transcription accuracy by rerunning only weak caption windows with a stronger model, while keeping the fast first pass and overall runtime close to the current baseline.

**Architecture:** Keep `SpeechCleanupService` as the orchestration layer, but add a selective rerun stage between review candidate selection and final export. Reuse the existing review-report heuristics to identify weak windows, merge adjacent weak ranges into a small rerun set, transcribe only those ranges with the stronger review backend/model already configured in the service, and conservatively replace the original segments only when the rerun is clearly better.

**Tech Stack:** Python 3.11, FastAPI service code in `src/radcast`, FFmpeg, pytest, existing local caption backends (`whisper.cpp`, `faster-whisper`, `mlx-whisper`).

---

## File Map

**Modify:**
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/services/speech_cleanup.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/services/caption_review.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py`

**Leave alone unless a failing test proves otherwise:**
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/api.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/worker_client.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/worker_manager.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/static/ui.js`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/static/ui.css`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/templates/index.html`

---

### Task 1: Define weak-window rerun selection

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/services/caption_review.py`
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/services/speech_cleanup.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py`

- [ ] **Step 1: Write the failing tests**

Add tests that define the new selection contract:
- low-confidence segments are selected for rerun
- truncation and duplication flags are selected for rerun
- critical-term misses are selected for rerun
- adjacent candidate windows are merged into fewer rerun ranges
- clean segments are skipped

Suggested test shape:

```python
from radcast.services.caption_review import build_selective_rerun_plan


def test_build_selective_rerun_plan_flags_weak_segments():
    ...


def test_build_selective_rerun_plan_merges_related_weak_windows():
    ...
```

Add a `SpeechCleanupService` test that proves the rerun stage is not triggered when the review report has no candidates.
Add a `SpeechCleanupService` test that proves critical-term misses are visible to the rerun planner when `caption_glossary` terms are present.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q
```

Expected: FAIL because the selective rerun planner does not exist yet.

- [ ] **Step 3: Implement the weak-window selector**

Extend `caption_review.py` with a small helper that returns rerun windows from the existing `CaptionQualityReport` rather than inventing a separate confidence system.

Implementation constraints:
- reuse existing `CaptionReviewFlag` objects
- prioritize `probable critical term miss`, `probable truncation`, `probable duplication`, then `probable low confidence`
- emit a dedicated rerun-plan object that includes:
  - merged time ranges
  - the underlying flags that produced each range
  - the reason priority that won for each range
- merge overlapping or near-adjacent rerun windows so the rerun stage stays compact
- keep the selector deterministic
- use an initial adjacency tolerance of 0.35 seconds when coalescing ranges
- skip candidate ranges shorter than 1.5 seconds unless they include a critical-term miss or truncation flag

Expose the planner through a small helper that `SpeechCleanupService` can call before rerunning any windows.

The planner, not `SpeechCleanupService`, owns the priority ordering so the first-pass quality report remains reusable for export and UI reporting.

- [ ] **Step 4: Wire the selector into `SpeechCleanupService`**

Add a narrow rerun-planning step in `generate_caption_file()` or the existing review sweep path:
- build the quality report from the first pass
- compute critical terms from the current `caption_glossary` before rerun planning
- pass those critical terms into the first-pass `build_caption_quality_report(...)` call so critical-term misses can be selected
- ask the planner for rerun windows
- skip the rerun stage when no weak windows exist
- keep the first pass and export logic unchanged for clean runs

- [ ] **Step 5: Run focused regression tests**

Run:

```bash
python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx add \
  src/radcast/services/caption_review.py \
  src/radcast/services/speech_cleanup.py \
  tests/test_caption_review.py \
  tests/test_speech_cleanup.py

git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx commit -m "feat: select weak caption windows for reruns"
```

---

### Task 2: Rerun only weak windows with the stronger review backend

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/services/speech_cleanup.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py`

- [ ] **Step 1: Write the failing tests**

Add tests for the selective rerun executor and replacement gate:
- a weak window is retranscribed with the review backend/model
- a clearly better candidate replaces the original segment
- a lower-confidence or lower-quality candidate is rejected
- truncation repairs can be accepted even when the rerun does not simply raise probability
- rerun failure preserves the original first-pass transcript
- a rerun window covering multiple original segments maps replacements back without duplicating or overlapping cues
- the review backend is invoked only for selected weak windows, not for the entire file
- critical-term misses are selectable during rerun planning when `caption_glossary` terms are present

Suggested test shape:

```python
def test_review_rerun_replaces_only_better_segments():
    ...


def test_review_rerun_preserves_original_when_candidate_is_worse():
    ...
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q
```

Expected: FAIL until the selective rerun path exists.

- [ ] **Step 3: Implement the rerun executor**

Extend `SpeechCleanupService` so the current review sweep becomes a targeted rerun stage instead of a blanket correction pass.

Implementation details:
- extract candidate windows from the planner
- transcribe only those windows with the existing stronger review backend/model already configured in the service
- preserve prompt/glossary context for reruns
- retain timing offsets when stitching rerun results back into the main timeline
- refactor the current `_review_caption_flag(...)` flow into a reusable helper that accepts an arbitrary `[start, end]` rerun window and returns normalized segments for that interval
- if a rerun window spans multiple original segments, replace only the overlapping range and re-dedupe the stitched timeline afterward

Do not replace the first pass wholesale. The selective rerun should only operate on candidate ranges.

- [ ] **Step 4: Implement the replacement gate**

Accept a rerun replacement only if it is clearly better than the original.

Minimum gate rules:
- accept if the rerun fixes a truncation or duplication and does not degrade meaning
- accept if the rerun materially improves the duration-weighted segment confidence by at least 0.03, using `average_probability` when it is available on both sides
- if either side lacks usable confidence, rely on the structural/critical-term repair rules instead of the numeric threshold
- accept if the rerun repairs a critical term miss
- reject if the rerun is ambiguous, shorter in a way that loses meaning, or lower confidence without a structural repair

Keep the comparison conservative so a bad rerun cannot poison an otherwise good transcript.

- [ ] **Step 5: Run focused regression tests**

Run:

```bash
python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx add \
  src/radcast/services/speech_cleanup.py \
  tests/test_speech_cleanup.py

git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx commit -m "feat: rerun weak caption windows with stronger model"
```

---

### Task 3: Keep progress and export behavior stable

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/services/speech_cleanup.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py`

- [ ] **Step 1: Write the failing tests**

Add tests that lock down the user-facing behavior:
- first-pass progress remains window-based
- rerun progress is shown as a separate stage
- the ETA does not jump wildly when rerun windows begin
- clean runs still complete without invoking the rerun stage
- the final VTT/review output format stays unchanged
- if the configured rerun backend is unavailable, the job uses the existing policy to decide whether a fallback backend is allowed; otherwise it fails clearly instead of pretending the rerun completed
- the merged post-rerun quality report reflects the final transcript, not stale first-pass flags

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q
```

Expected: FAIL until the progress and rerun-stage reporting are wired correctly.

- [ ] **Step 3: Update stage/progress reporting**

Keep the progress semantics simple:
- first pass: `Transcribing speech for captions`
- rerun stage: `Rechecking low-confidence caption lines`
- export: `Writing VTT captions` / `Writing SRT captions`

If needed, add a small helper that computes ETA separately for rerun windows so the UI can stay stable and honest.

- [ ] **Step 4: Run regression tests**

Run:

```bash
python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx add \
  src/radcast/services/speech_cleanup.py \
  tests/test_speech_cleanup.py

git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx commit -m "feat: stabilize selective rerun progress"
```

---

### Task 4: Full verification on lecture samples

**Files:**
- No new files; verify the full selective rerun flow across the existing caption pipeline.

- [ ] **Step 1: Run the targeted Python test suites**

Run:

```bash
python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the existing JS regression check**

Run:

```bash
node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/compute_mode_caption_fallback.test.js
```

Expected: PASS.

- [ ] **Step 3: Run one real lecture caption sample**

Use a lecture clip with weak terminology and verify:
- the first pass still completes quickly enough
- only weak windows are rerun
- the final transcript improves in the flagged spots
- the accessibility verdict remains accurate
- the runtime does not collapse into a full-file slow path

- [ ] **Step 4: Commit verification notes if needed**

If the sample reveals threshold tuning needs, capture them in a follow-up commit rather than broadening the rerun scope.
