# Quality-First Lecture Captions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver accessibility-oriented lecture captions for RADcast local Apple Silicon helpers by prioritizing accurate spoken dialogue, stronger review selection, and readable cue shaping over raw speed.

**Architecture:** Keep `SpeechCleanupService` as the orchestration layer, but introduce an explicit lecture-quality caption policy plus focused helper modules for review-candidate selection and cue shaping. Use a stronger macOS local-helper transcript/review profile, restrict review to genuinely suspicious lines, and reshape stabilized transcript spans into readable lecture-caption cues before export.

**Tech Stack:** Python 3.11, FastAPI, whisper.cpp, faster-whisper, FFmpeg, pytest, Node test runner

---

## File Map

**Create:**
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/caption_quality_policy.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/caption_review.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/caption_cue_shaping.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_quality_policy.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_review.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_cue_shaping.py`

**Modify:**
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/speech_cleanup.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/worker_client.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/worker_setup.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/static/ui.js`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_queue.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_setup.py`
- `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/compute_mode_caption_fallback.test.js`

**Leave alone unless a failing test proves otherwise:**
- server-side enhancement code
- non-caption UI flows
- Windows/local-helper caption policy

---

### Task 1: Introduce an explicit lecture-quality caption policy

**Files:**
- Create: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/caption_quality_policy.py`
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/speech_cleanup.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_quality_policy.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py`

- [ ] **Step 1: Write the failing policy tests**

Add tests that define the new internal policy contract:

```python
from radcast.services.caption_quality_policy import resolve_caption_quality_policy


def test_reviewed_mode_uses_quality_local_lecture_on_macos_helper():
    policy = resolve_caption_quality_policy(
        quality_mode="reviewed",
        runtime_context="local_helper",
        platform_name="Darwin",
        backend_id="whispercpp",
    )
    assert policy.policy_id == "quality_local_lecture"
    assert policy.first_pass_backend_id == "whispercpp"
    assert policy.first_pass_model_size == "medium"
    assert policy.review_backend_id == "whispercpp"
```

Add one more test that Windows or server contexts keep the current reviewed path.

- [ ] **Step 2: Run the new policy tests and verify failure**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_quality_policy.py -q
```

Expected: FAIL on missing module/import.

- [ ] **Step 3: Implement the policy module**

Create `caption_quality_policy.py` with:
- `CaptionQualityPolicy` dataclass
- `resolve_caption_quality_policy(...)`
- fixed fields for:
  - first-pass backend/model/beam
  - review backend/model/beam
  - review strategy id
  - cue-shaping strategy id
  - progress label

Keep it data-only. No transcription code here.

Suggested shape:

```python
@dataclass(frozen=True)
class CaptionQualityPolicy:
    policy_id: str
    first_pass_backend_id: str
    first_pass_model_size: str
    first_pass_beam_size: int
    review_backend_id: str
    review_model_size: str
    review_beam_size: int
    review_strategy_id: str
    cue_shaping_strategy_id: str
    progress_label: str
```

- [ ] **Step 4: Wire `SpeechCleanupService` to resolve and expose the policy**

Use the policy inside `generate_caption_file()` and helper methods instead of hardcoding local-helper review choices in multiple places.

- [ ] **Step 5: Run focused regression tests**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_quality_policy.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends add \
  src/radcast/services/caption_quality_policy.py \
  src/radcast/services/speech_cleanup.py \
  tests/test_caption_quality_policy.py \
  tests/test_speech_cleanup.py

git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends commit -m "feat: add lecture caption quality policy"
```

---

### Task 2: Replace blanket review flags with targeted review candidate selection

**Files:**
- Create: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/caption_review.py`
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/speech_cleanup.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_review.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py`

- [ ] **Step 1: Write failing review-selection tests**

Add tests for:
- low-probability segments are flagged
- duplicated text is flagged
- obvious truncation is flagged
- lines with usable confidence and no structural anomaly are not flagged
- review reasons are explicit, not `confidence unknown`

Suggested test snippet:

```python
from radcast.services.caption_review import select_review_candidates
from radcast.services.speech_cleanup import TranscriptSegmentTiming


def test_select_review_candidates_prefers_explicit_reasons():
    segments = [
        TranscriptSegmentTiming(text="Thank you for watching", start=10.0, end=12.0, average_probability=0.92),
        TranscriptSegmentTiming(text="Thank you for watching", start=12.1, end=14.0, average_probability=0.91),
    ]
    report = select_review_candidates(segments)
    assert any(item.reason == "probable duplication" for item in report.flagged_segments)
```

- [ ] **Step 2: Run the new review tests and verify failure**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_review.py -q
```

Expected: FAIL on missing module/import.

- [ ] **Step 3: Implement `caption_review.py`**

Create a focused module that owns:
- review-candidate selection
- structural heuristics
- review reason labeling
- quality report construction helpers

Move logic out of `speech_cleanup.py` for:
- `_build_caption_quality_report`
- `_caption_review_reason`
- duplication/truncation heuristics that are specific to review triage

Keep transcript correction itself in `SpeechCleanupService` for now.

- [ ] **Step 4: Update `SpeechCleanupService` to review only flagged segments**

Use the new review report as the source of truth for:
- which segments are sent to review
- which review reasons appear in the `.review.txt`

Guardrail: never let review-system text become transcript text.

- [ ] **Step 5: Run regression tests**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends add \
  src/radcast/services/caption_review.py \
  src/radcast/services/speech_cleanup.py \
  tests/test_caption_review.py \
  tests/test_speech_cleanup.py

git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends commit -m "feat: target lecture caption review candidates"
```

---

### Task 3: Add accessibility-oriented lecture cue shaping

**Files:**
- Create: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/caption_cue_shaping.py`
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/speech_cleanup.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_cue_shaping.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py`

- [ ] **Step 1: Write failing cue-shaping tests**

Add tests that enforce lecture-caption readability:
- long transcript spans split into multiple cues
- cue order and time order are preserved
- no one-word fragments unless timing forces it
- cue text remains semantically intact
- fixed-length `13s` block behavior does not reappear

Suggested test shape:

```python
from radcast.services.caption_cue_shaping import shape_lecture_caption_cues
from radcast.services.speech_cleanup import TranscriptSegmentTiming


def test_shape_lecture_caption_cues_splits_long_spans():
    segments = [
        TranscriptSegmentTiming(
            text="Quantum entanglement describes correlated states that remain linked even when separated by great distances.",
            start=0.0,
            end=12.5,
            average_probability=0.95,
        )
    ]
    shaped = shape_lecture_caption_cues(segments)
    assert len(shaped) >= 2
    assert all(segment.end > segment.start for segment in shaped)
```

- [ ] **Step 2: Run the new cue-shaping tests and verify failure**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_cue_shaping.py -q
```

Expected: FAIL on missing module/import.

- [ ] **Step 3: Implement `caption_cue_shaping.py`**

Move cue-shaping helpers out of `speech_cleanup.py` into a dedicated module:
- `shape_lecture_caption_cues(...)`
- token splitting
- line wrapping
- timing redistribution for split cues

Preserve the existing `TranscriptSegmentTiming` type.

- [ ] **Step 4: Wire quality-first lecture exports through the new cue shaper**

Use the lecture shaper after transcript stabilization and before final VTT/SRT document writing.

- [ ] **Step 5: Run regression tests**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_cue_shaping.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends add \
  src/radcast/services/caption_cue_shaping.py \
  src/radcast/services/speech_cleanup.py \
  tests/test_caption_cue_shaping.py \
  tests/test_speech_cleanup.py

git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends commit -m "feat: shape lecture captions for readability"
```

---

### Task 4: Upgrade the macOS local-helper quality profile and helper/runtime reporting

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/speech_cleanup.py`
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/worker_client.py`
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/worker_setup.py`
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/static/ui.js`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_queue.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_setup.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/compute_mode_caption_fallback.test.js`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py`

- [ ] **Step 1: Write failing profile/reporting tests**

Add tests that assert:
- macOS local helper reviewed captions expose the quality-local-lecture progress label
- review stage shows item counts, not vague percentages only
- helper defaults set the stronger lecture-quality model/profile for the quality path
- ETA delay still applies during early windows/review even after the quality-path changes

Example assertions:

```python
def test_local_helper_defaults_quality_review_model(monkeypatch):
    env = build_local_helper_env(platform_name="Darwin")
    assert env["RADCAST_CAPTION_REVIEWED_MODEL"] == "medium"
```

```javascript
test("caption ETA stays estimating during first review item", () => {
  const detail = "Reviewing low-confidence caption lines with whisper.cpp (medium). 1 of 12. On your local helper device.";
  expect(shouldDelayNumericEta("captions", detail)).toBe(true);
});
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_setup.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_queue.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py -q
node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/compute_mode_caption_fallback.test.js
```

Expected: FAIL on one or more missing quality-path assertions.

- [ ] **Step 3: Implement the profile/reporting updates**

Update the helper/runtime path to:
- expose the quality-policy label in detail text
- keep `whisper.cpp` review on macOS local helpers when quality policy requests it
- keep ETA text conservative in early review
- avoid silently dropping back to vague or stale stage descriptions

- [ ] **Step 4: Run regression tests**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_setup.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_queue.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py -q
node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/compute_mode_caption_fallback.test.js
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends add \
  src/radcast/services/speech_cleanup.py \
  src/radcast/worker_client.py \
  src/radcast/worker_setup.py \
  src/radcast/static/ui.js \
  tests/test_worker_setup.py \
  tests/test_worker_queue.py \
  tests/compute_mode_caption_fallback.test.js \
  tests/test_speech_cleanup.py

git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends commit -m "feat: wire quality lecture captions through local helper"
```

---

### Task 5: Add regression tests for the known bad lecture-output failures

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py`
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_review.py`
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_cue_shaping.py`

- [ ] **Step 1: Write failing regression tests from the observed failure modes**

Use synthetic transcript fixtures that mimic the actual problems we saw:
- hallucinated review/system line
- duplicated outro text
- overlong caption blocks
- out-of-order/truncated lecture phrases
- review report returning all `confidence unknown`

Suggested examples:

```python
def test_review_report_does_not_mark_everything_confidence_unknown():
    report = build_quality_report([
        TranscriptSegmentTiming(text="Quantum entanglement is...", start=0.0, end=2.0, average_probability=0.96),
        TranscriptSegmentTiming(text="This is the final result of the review", start=2.0, end=4.0, average_probability=0.12),
    ])
    assert any(item.reason != "confidence unknown" for item in report.flagged_segments)
```

```python
def test_export_segments_do_not_include_review_boilerplate():
    shaped = shape_lecture_caption_cues([...])
    assert all("final result of the review" not in segment.text.lower() for segment in shaped)
```

- [ ] **Step 2: Run only the regression tests and verify failure**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py -k "review or caption" -q
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_cue_shaping.py -q
```

Expected: FAIL on at least one of the new accessibility regression checks.

- [ ] **Step 3: Implement the minimum fixes needed to pass the regressions**

Patch only the logic already introduced in Tasks 2-4. Do not add another subsystem.

Priority order:
1. eliminate review/system hallucination text from exports
2. stop duplicated/outro boilerplate from surviving
3. tighten cue shaping for readable lecture output
4. make review reasons explicit and sparse

- [ ] **Step 4: Run the full caption test suite**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_cue_shaping.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_queue.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_setup.py -q
node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/compute_mode_caption_fallback.test.js
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends add \
  tests/test_speech_cleanup.py \
  tests/test_caption_review.py \
  tests/test_caption_cue_shaping.py \
  src/radcast/services/speech_cleanup.py \
  src/radcast/services/caption_review.py \
  src/radcast/services/caption_cue_shaping.py

git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends commit -m "test: lock in lecture caption accessibility regressions"
```

---

### Task 6: Verify against the live local-helper workflow and document the branch behavior

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/src/radcast/services/speech_cleanup.py` only if verification reveals a branch-only bug
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/docs/superpowers/plans/2026-04-03-quality-first-lecture-captions-plan.md` only to mark progress while executing
- Optional doc note if needed: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/README.md`

- [ ] **Step 1: Run a real local-helper lecture-caption job on the quantum entanglement sample**

Use RADcast dev with:
- `Don't enhance audio`
- `VTT`
- same lecture sample used in earlier comparisons

Expected checks:
- run stays local
- first pass uses stronger quality-local-lecture backend/model
- review stage uses targeted items, not blanket review

- [ ] **Step 2: Inspect the output artifacts**

Review the generated:
- `.vtt`
- `.vtt.review.txt`

Check against the accessibility-quality bar:
- no review boilerplate hallucinations
- no duplicated outro/system text
- improved readability and cue timing
- review report contains explicit reasons

- [ ] **Step 3: Run the final verification commands**

Run:

```bash
pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_quality_policy.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_caption_cue_shaping.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_speech_cleanup.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_queue.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/test_worker_setup.py -q
node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends/tests/compute_mode_caption_fallback.test.js
```

Expected: all PASS.

- [ ] **Step 4: Commit the final verification/doc updates**

```bash
git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends add README.md docs/superpowers/plans/2026-04-03-quality-first-lecture-captions-plan.md || true

git -C /Users/rcd58/RADcast/.worktrees/codex-platform-caption-backends commit -m "docs: record quality-first lecture caption verification" || true
```

---

## Notes for Implementation

- Prefer the new focused modules over adding more logic to `speech_cleanup.py`. That file is already oversized.
- Preserve the fast local path. This plan is for the quality-first path, not a universal downgrade.
- Do not silently treat the fast path as quality-first in the UI or logs.
- Keep lecture output focused on spoken dialogue. Only add non-speech cues if later accessibility validation shows they are required for comprehension.
- Use TDD strictly. Every new behavior should arrive with a failing test first.
