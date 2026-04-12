# Glossary Review Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-output glossary review modal that lets a user review glossary-related caption failures in context and approve terms into the shared global glossary for future projects.

**Architecture:** The backend will derive glossary candidates from the existing caption VTT and review artifacts through a dedicated review-candidate service, expose them with a project-output scoped API, and persist approved entries through the existing shared glossary store. The frontend will render a modal from each completed output card, show surrounding transcript context for each candidate, and submit only explicitly approved terms back to the server. This feature will not change transcription scoring or accessibility verdict rules.

**Tech Stack:** FastAPI, Pydantic models, existing RADcast glossary store, vanilla JS frontend, existing modal/CSS patterns, pytest, node-based UI tests.

---

## File Map

- `src/radcast/services/glossary_review.py` - new review-candidate extraction and normalization helpers for VTT + review artifact parsing.
- `src/radcast/services/glossary_store.py` - keep persistence concerns only; add write helpers if the save endpoint needs a small convenience wrapper.
- `src/radcast/api.py` - new glossary-review endpoints and outputs metadata flag.
- `src/radcast/models.py` - new request/response models for glossary candidate payloads if needed.
- `src/radcast/templates/index.html` - modal markup and optional toolbar hook for the completed output card.
- `src/radcast/static/ui.js` - output-card button rendering, modal open/close, fetch/save flow.
- `src/radcast/static/ui.css` - modal layout and candidate-row styling.
- `tests/fixtures/glossary_review/simple.vtt` - tiny deterministic VTT fixture.
- `tests/fixtures/glossary_review/simple.vtt.review.txt` - matching deterministic review fixture.
- `tests/test_glossary_review.py` - service-level extraction tests.
- `tests/test_api_ui.py` - API contract and glossary-save endpoint tests.
- `tests/glossary_review_modal.test.js` - focused UI/modal behavior tests.

---

### Task 1: Add a dedicated glossary-review extraction service and tests

**Files:**
- Create: `src/radcast/services/glossary_review.py`
- Create: `tests/fixtures/glossary_review/simple.vtt`
- Create: `tests/fixtures/glossary_review/simple.vtt.review.txt`
- Create: `tests/test_glossary_review.py`

- [ ] **Step 1: Write the failing test**

```python
def test_extract_glossary_candidates_returns_context_and_deduped_terms():
    # load the tiny fixture VTT/review pair and assert that the helper returns
    # glossary candidates with:
    # - normalized term suggestion
    # - reason text
    # - previous/current/next cue context
    # - deterministic ordering
    # - dedupe by normalized term
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_glossary_review.py -q`
Expected: FAIL because the dedicated glossary-review service does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement a small service that:
- parses the review artifact timestamp ranges and reasons
- keeps only flags whose reason starts with `probable critical term miss:`
- uses the term suffix from that reason as the suggested glossary term
- maps each candidate back to overlapping VTT cues by timestamp
- returns a structured candidate list with `candidate_id`, `term`, `normalized_term`, `reason`, `previous_context`, `flagged_context`, `next_context`, and `already_known`
- dedupes candidates by normalized term and cue span

Normalization rules:
- use the existing glossary term normalization rules for comparison and dedupe
- preserve the term string from the review reason as the default display term
- treat macrons/Unicode variants as the same normalized term for dedupe and already-known checks

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_glossary_review.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/radcast/services/glossary_review.py tests/fixtures/glossary_review/simple.vtt tests/fixtures/glossary_review/simple.vtt.review.txt tests/test_glossary_review.py
git commit -m "feat: derive glossary review candidates from caption artifacts"
```

### Task 2: Expose glossary-review API endpoints and tests

**Files:**
- Modify: `src/radcast/api.py`
- Modify: `src/radcast/models.py` if new request/response models are needed
- Modify: `src/radcast/services/glossary_store.py` only if a small save helper is needed
- Modify: `tests/test_api_ui.py`

**Endpoint contract:**
- GET `/projects/{project_id}/outputs/glossary-review-candidates?path={output_path}`
- POST `/projects/{project_id}/outputs/glossary-review-candidates?path={output_path}`

The `path` query parameter should be the existing `output_path` returned from `/projects/{project_id}/outputs`.

The GET response should include:
- `project_id`
- `output_path`
- `has_candidates`
- `has_review_artifacts`
- `candidates[]` with the fields returned by the extraction service

The POST request should accept:
- `approvals[]` entries containing a `candidate_id` and the approved `term` text

The POST response should include:
- `saved_terms[]`
- `already_known_terms[]`
- `project_id`
- `output_path`

- [ ] **Step 1: Write the failing test**

```python
def test_project_output_glossary_candidates_endpoint_returns_context(monkeypatch):
    # create a project output with review artifacts and assert the endpoint
    # returns candidate rows with context snippets and known-status flags.
    ...


def test_project_output_glossary_candidates_save_promotes_terms_to_global_store(monkeypatch):
    # post approved candidates and assert the global glossary store is updated,
    # deduped, and normalized.
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py -q -k 'glossary_review_candidates'`
Expected: FAIL because the endpoints do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add API handlers that:
- look up the output record by `output_path` within the project
- derive the sidecar VTT and review paths from the output metadata
- call the glossary-review service to build candidates
- expose the candidate payload with `has_review_artifacts` and `has_candidates`
- save approved terms into the global glossary store using normalized dedupe
- accept POST bodies shaped like `{ "approvals": [{ "candidate_id": "...", "term": "edited or original" }] }`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py -q -k 'glossary_review_candidates'`
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
- Create: `tests/glossary_review_modal.test.js`

- [ ] **Step 1: Write the failing test**

```javascript
test("completed output cards show glossary review action when review artifacts exist", async () => {
  // render an output with review metadata and assert a new action button appears.
});

test("glossary review modal renders candidate rows and context", async () => {
  // open the modal, mock the candidate API response, and assert the modal shows
  // the prev/current/next context rows and approve/edit controls.
});

test("approved glossary terms are posted and the output list refreshes", async () => {
  // submit one approved candidate and assert the save endpoint payload and refresh.
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/glossary_review_modal.test.js`
Expected: FAIL because the modal action and bindings do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Update the completed output card renderer to show a `Review glossary candidates` button whenever the outputs payload includes `has_review_artifacts: true`. The backend should set that flag when a caption review file exists for the output.
Add a modal using the existing modal styling and focus-management pattern, load candidate data on open, and render approve/edit/skip controls plus save/cancel actions.

Use the existing modal helpers in `ui.js` (`syncModalOpenState()`, focus return, ESC/close handling) instead of inventing a separate modal state model.

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/glossary_review_modal.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/radcast/templates/index.html src/radcast/static/ui.js src/radcast/static/ui.css tests/glossary_review_modal.test.js
git commit -m "feat: add glossary review modal to completed outputs"
```

### Task 4: End-to-end verification and regression coverage

**Files:**
- Modify: `tests/test_api_ui.py`
- Modify: `tests/test_glossary_store.py`
- Modify: `tests/test_caption_review.py` only if a shared helper needs a new regression assertion

- [ ] **Step 1: Write the failing test**

Add one end-to-end test that:
- creates an output with review artifacts
- fetches glossary candidates
- approves a candidate
- asserts the shared global glossary contains the new active term exactly once and in normalized form

- [ ] **Step 2: Run the full targeted suite**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_glossary_store.py -q`
Expected: PASS.

- [ ] **Step 3: Run the broader regression slice**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q`
Expected: PASS and no regressions in caption review or accessibility verdicts.

- [ ] **Step 4: Commit**

```bash
git add tests/test_api_ui.py tests/test_glossary_store.py tests/test_caption_review.py
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
- the new glossary review action appears only when review data exists
- the modal shows candidate context correctly
- approved terms save into the shared glossary
- the output list refreshes afterward

- [ ] **Step 3: Commit any final fixups**

```bash
git add <any-fixed-files>
git commit -m "feat: finalize glossary review modal flow"
```
