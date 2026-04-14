# Sparse Span Rerun Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve transcription accuracy for long, sparse caption stretches by rerunning only the weak spans with stronger review coverage and better acceptance rules, without slowing every job.

**Architecture:** Keep the current fast first pass and the existing selective rerun pipeline. Tighten the sparse-span heuristics so the review sweep catches long stretches that have too few words, then widen the review snippet and acceptance criteria for those spans so the reread can recover missing words instead of re-emitting another fragmentary caption run. Preserve glossary behaviour and the human-review workflow unchanged.

**Tech Stack:** Existing RADcast Python services, current caption review scoring in `caption_review.py`, speech transcription orchestration in `speech_cleanup.py`, pytest, and the existing light-weight Node/Python regression coverage pattern already used elsewhere in the branch.

---

### Task 1: Lock down sparse-span detection and acceptance rules

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/services/caption_review.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py`

- [ ] **Step 1: Write the failing test**

Add a focused test that builds a high-confidence but word-sparse caption run and asserts it is flagged as `probable sparse caption run`, then add a second assertion that a materially denser reread candidate is accepted even if the probability change is small. The key behaviour to lock in is that sparse runs are judged by coverage and recovered wording, not just probability.

```python
def test_sparse_run_requires_materially_better_word_coverage_for_acceptance():
    # build a long run with too few words
    # build a reread candidate with more recovered wording but similar confidence
    # assert the sparse flag is present
    # assert sparse acceptance prefers the denser candidate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py -k sparse -q`

Expected: FAIL because the sparse-span acceptance path still treats these candidates too much like generic low-confidence reruns.

- [ ] **Step 3: Write minimal implementation**

Adjust the sparse-span selection/acceptance helpers so sparse runs are:
- recognised reliably when a long span contains too few words
- prioritised as a rerun target
- accepted when the reread is materially denser than the original span, even if the model confidence delta is modest

Keep the existing critical-term, truncation, and duplication handling intact.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py -k sparse -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/services/caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py
git commit -m "feat: tighten sparse caption rerun selection"
```

### Task 2: Make sparse reruns capture more surrounding speech and keep better candidates

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/services/speech_cleanup.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py`

- [ ] **Step 1: Write the failing test**

Add a regression test for the light-bulb-style failure mode where the current transcript is too sparse across a long span. Stub the review reread so the stronger model returns a fuller phrase, and assert the sparse span is replayed with enough surrounding context to recover the missing words.

```python
def test_sparse_rerun_recovers_missing_words_from_long_sparse_span():
    # stub sparse first-pass segments
    # stub review reread returning a denser replacement
    # assert the replacement is accepted
    # assert the resulting transcript is no longer broken into single-word fragments
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -k sparse -q`

Expected: FAIL because the current sparse rerun path does not yet widen context or use a sparse-specific acceptance rule strongly enough.

- [ ] **Step 3: Write minimal implementation**

Update the speech cleanup review sweep so sparse windows can:
- use a slightly wider snippet context than ordinary low-confidence lines
- prefer rereads that recover a materially larger amount of spoken text
- avoid replacing the original span unless the candidate is clearly better for word coverage, not just slightly higher in confidence

Keep the first-pass runtime unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest /Users/rcs58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -k sparse -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add /Users/rcs58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/services/speech_cleanup.py /Users/rcs58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py
git commit -m "feat: recover sparse caption spans with wider review context"
```

### Task 3: Verify the light-bulb regression end to end

**Files:**
- Modify: none new
- Test: `/Users/rcs58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py`
- Test: `/Users/rcs58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py`

- [ ] **Step 1: Run the focused regression suites**

Run:
```bash
python3 -m pytest /Users/rcs58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py /Users/rcs58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q
```

Expected: PASS.

- [ ] **Step 2: Manually validate a sparse lecture clip**

Run the light-bulb sample through RADcast dev and confirm the middle stretch is captioned as a normal phrase-level transcript instead of collapsing into one-word fragments or dropping words.

- [ ] **Step 3: Commit any final polish**

If the manual validation suggests a small threshold tweak is still needed, make only the minimal follow-up change and commit it separately with a focused message.
