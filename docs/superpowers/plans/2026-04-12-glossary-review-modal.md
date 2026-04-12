# Glossary Review Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-output glossary review modal that lets a user review glossary-related caption failures in context and approve terms into the shared global glossary for future projects.

**Architecture:** The backend will derive glossary candidates from the existing caption VTT and review artifacts, expose them through a new API endpoint, and persist approved entries through the existing shared glossary store. The frontend will render a modal from each completed output card, show surrounding transcript context for each candidate, and submit only explicitly approved terms back to the server. This feature will not change transcription scoring or accessibility verdict rules.

**Tech Stack:** FastAPI, Pydantic models, existing RADcast glossary store, vanilla JS frontend, existing modal/CSS patterns, pytest, node-based UI tests where applicable.

---

### Task 1: Add glossary-candidate extraction helpers and tests

**Files:**
- Modify: `src/radcast/services/glossary_store.py`
- Create: `tests/test_glossary_review_candidates.py`

- [ ] **Step 1: Write the failing test**

```python
def test_extract_glossary_candidates_returns_context_and_deduped_terms():
    # load a real-ish VTT + review pair and assert the helper returns
    # flagged term candidates with previous/current/next cue context
    # and no duplicate normalized terms.
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_glossary_review_candidates.py -q`
Expected: FAIL because the candidate extraction helper does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add a small, focused helper in `glossary_store.py` that can:
- parse a VTT plus matching `.review.txt`
- identify glossary-related failures from the review output
- return a structured candidate list with context cues and normalized term suggestions
- de-duplicate candidates by normalized term and cue span

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_glossary_review_candidates.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/radcast/services/glossary_store.py tests/test_glossary_review_candidates.py
git commit -m "feat: derive glossary review candidates from caption artifacts"
```

### Task 2: Expose API endpoints for glossary review and approval

**Files:**
- Modify: `src/radcast/api.py`
- Modify: `src/radcast/models.py` if new request/response models are needed
- Modify: `src/radcast/services/glossary_store.py` if the save path needs a dedicated helper
- Modify: `tests/test_api_ui.py`

- [ ] **Step 1: Write the failing test**

```python
def test_project_output_glossary_candidates_endpoint_returns_context(monkeypatch):
    # create a project output with review artifacts and assert the endpoint
    # returns candidate rows with context snippets and known-status flags.
    ...


def test_project_output_glossary_candidates_save_promotes_terms_to_global_store(monkeypatch):
    # post approved candidates and assert the global glossary store is updated
    # and duplicates are not created.
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py -q -k 'glossary_candidates'`
Expected: FAIL because the endpoints do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add endpoints that:
- load the completed output metadata and associated review artifacts
- return a JSON candidate payload for the modal
- accept approved glossary terms and save them into the shared global glossary
- reject malformed or duplicate approvals cleanly

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py -q -k 'glossary_candidates'`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/radcast/api.py src/radcast/models.py src/radcast/services/glossary_store.py tests/test_api_ui.py
git commit -m "feat: add glossary review candidate APIs"
```

### Task 3: Add glossary review modal wiring in the completed outputs UI

**Files:**
- Modify: `src/radcast/templates/index.html`
- Modify: `src/radcast/static/ui.js`
- Modify: `src/radcast/static/ui.css`
- Modify: `tests/compute_mode_caption_fallback.test.js` or add a focused UI test file for the completed-output action and modal if the current test harness already covers this area

- [ ] **Step 1: Write the failing test**

```javascript
test("completed output cards show glossary review action when review artifacts exist", async () => {
  // render an output with review metadata and assert a new action button appears
});

test("glossary review modal renders candidate rows and context", async () => {
  // click the action, fetch candidate payload, and assert the modal shows context
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/compute_mode_caption_fallback.test.js`
Expected: FAIL or no coverage until the modal action and bindings exist.

- [ ] **Step 3: Write minimal implementation**

Update the completed output card renderer to show a `Review glossary candidates` button when review artifacts are present. Add a modal using the existing modal styling and focus-management pattern, load candidate data on open, and render approve/edit/skip controls plus save/cancel actions.

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/compute_mode_caption_fallback.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/radcast/templates/index.html src/radcast/static/ui.js src/radcast/static/ui.css tests/compute_mode_caption_fallback.test.js
git commit -m "feat: add glossary review modal to completed outputs"
```

### Task 4: End-to-end verification and regression coverage

**Files:**
- Modify: `tests/test_api_ui.py`
- Modify: `tests/test_glossary_store.py` if any new store behavior needs coverage
- Modify: `tests/test_speech_cleanup.py` only if the new glossary metadata needs to remain compatible with caption generation

- [ ] **Step 1: Write the failing test**

Add one end-to-end test that:
- creates an output with review artifacts
- fetches candidates
- approves a candidate
- asserts the shared global glossary contains the new active term

- [ ] **Step 2: Run the full targeted suite**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_glossary_store.py -q`
Expected: PASS.

- [ ] **Step 3: Run the broader regression slice**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q`
Expected: PASS and no regressions in caption review or accessibility verdicts.

- [ ] **Step 4: Commit**

```bash
git add tests/test_api_ui.py tests/test_glossary_store.py tests/test_caption_review.py tests/test_speech_cleanup.py
git commit -m "test: cover glossary review modal flow end to end"
```

### Task 5: Final verification

**Files:**
- None expected unless a small fix is needed

- [ ] **Step 1: Run the full relevant test set**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_glossary_store.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q`
Expected: PASS.

- [ ] **Step 2: Manual check in RADcast dev**

Open a completed output with review artifacts and verify:
- the new glossary review action appears
- the modal shows candidate context correctly
- approved terms save into the shared glossary
- the output list refreshes afterward

- [ ] **Step 3: Commit any final fixups**

```bash
git add <any-fixed-files>
git commit -m "feat: finalize glossary review modal flow"
```
