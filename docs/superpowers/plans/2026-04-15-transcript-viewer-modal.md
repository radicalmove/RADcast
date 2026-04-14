# Transcript Viewer Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only transcript viewer modal on completed RADcast outputs so users can inspect the generated VTT in the app without downloading it.

**Architecture:** Expose a small transcript-read endpoint that reads an existing caption file and returns timestamped cues in JSON. Add a simple modal in the completed-versions UI that loads those cues on demand and renders them as a scrollable read-only list. Keep the existing download actions unchanged and fail gracefully if the caption file is missing or unreadable.

**Tech Stack:** FastAPI-style JSON endpoint in Python, existing RADcast UI JavaScript modal patterns, current project output storage and file resolution helpers, node-based UI tests and pytest API coverage.

---

### Task 1: Add transcript payload endpoint

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/api.py`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py`

- [ ] **Step 1: Write the failing test**

Add an API test that requests a transcript-view payload for a completed output item and asserts the response includes ordered cues with `start`, `end`, and `text` fields parsed from the existing VTT file.

```python
def test_transcript_view_endpoint_returns_timestamped_cues(client, sample_completed_output):
    response = client.get(f"/projects/{project_id}/outputs/{output_id}/transcript")
    assert response.status_code == 200
    body = response.json()
    assert body["caption_format"] == "vtt"
    assert body["cues"][0]["start"] == 3.7
    assert body["cues"][0]["text"] == "Hi! Replacing the lightbulb is one of the simple"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py -k transcript_view -q`

Expected: FAIL because the endpoint does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement a new authenticated GET endpoint that reuses the existing project-output file resolution, reads the caption file, parses VTT cues into JSON, and returns a small response shape such as:

```python
{
  "caption_format": "vtt",
  "caption_path": "...",
  "cues": [{"index": 1, "start": 3.7, "end": 5.574, "text": "..."}]
}
```

Return a clear 404/400-style error if the caption file is missing or malformed.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py -k transcript_view -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/api.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py
git commit -m "feat: expose transcript viewer payload"
```

### Task 2: Add transcript viewer modal to the completed-version UI

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/static/ui.js`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/transcript_viewer_modal.test.js` (new)

- [ ] **Step 1: Write the failing test**

Add a DOM test that simulates clicking a new `View transcript` action on a completed version card and verifies a modal opens, loads cues, and renders timestamped transcript lines in order.

```javascript
test('completed output cards show a view transcript action and open the transcript modal', async () => {
  // render completed row fixture
  // click View transcript
  // assert modal title, cue list, and timestamps appear
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/transcript_viewer_modal.test.js`

Expected: FAIL because the button/modal do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add a `View transcript` action beside the existing caption actions for completed outputs that have a caption file. Reuse the current modal infrastructure to show a scrollable transcript modal with timestamped cues, plain text, and a close button. Fetch the new transcript endpoint on click and render the returned cues in cue order.

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/transcript_viewer_modal.test.js /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/review_flagged_items_modal.test.js /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/glossary_review_modal.test.js`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/static/ui.js /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/transcript_viewer_modal.test.js
git commit -m "feat: add transcript viewer modal"
```

### Task 3: Make the modal resilient and tidy

**Files:**
- Modify: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/static/ui.js`
- Test: `/Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/transcript_viewer_modal.test.js`

- [ ] **Step 1: Write the failing test**

Add coverage for missing or unreadable transcript payloads so the modal shows a clear inline error instead of failing silently.

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/transcript_viewer_modal.test.js`

Expected: FAIL on the new missing-file scenario.

- [ ] **Step 3: Write minimal implementation**

Render a concise error block inside the modal when the transcript endpoint returns an error, and keep the modal open so the user can dismiss it or try another output.

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/transcript_viewer_modal.test.js`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/src/radcast/static/ui.js /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/transcript_viewer_modal.test.js
git commit -m "feat: improve transcript viewer error handling"
```

### Task 4: Verify end-to-end behavior

**Files:**
- None new

- [ ] **Step 1: Run the focused test suites**

Run:
```bash
python3 -m pytest /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_api_ui.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_caption_review.py /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/test_speech_cleanup.py -q
node --test /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/transcript_viewer_modal.test.js /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/review_flagged_items_modal.test.js /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/glossary_review_modal.test.js /Users/rcd58/RADcast/.worktrees/codex-platform-caption-mlx/tests/help_modal_behavior.test.js
```

Expected: all pass.

- [ ] **Step 2: Manual check in RADcast dev**

Open a completed output row, click `View transcript`, confirm the modal shows timestamped cues in order, and confirm the existing download buttons still work.

- [ ] **Step 3: Commit final cleanup if needed**

If any small polish changes are required after the manual check, commit them separately with a focused message.
