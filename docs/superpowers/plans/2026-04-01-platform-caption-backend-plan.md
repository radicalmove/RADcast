# Platform-Specific Caption Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split RADcast local caption transcription by platform so macOS local helpers use a quality-first Apple-Silicon-native backend while Windows local helpers continue using faster-whisper.

**Architecture:** Keep `SpeechCleanupService` as the orchestration layer for quality modes, review flow, glossary handling, progress, and output writing. Introduce a narrow caption backend abstraction beneath it, then provide two concrete implementations: `faster-whisper` for Windows/current compatibility and `whisper.cpp` for macOS local helpers.

**Tech Stack:** Python 3.11, FastAPI, faster-whisper, CTranslate2, whisper.cpp, Metal (macOS), pytest

---

## File Map

**Create:**
- `src/radcast/services/caption_backends.py`
- `src/radcast/services/caption_backend_selection.py`
- `tests/test_caption_backends.py`
- `tests/test_caption_backend_selection.py`
- `scripts/bench_caption_backends.py`

**Modify:**
- `src/radcast/services/speech_cleanup.py`
- `src/radcast/worker_client.py`
- `src/radcast/worker_setup.py`
- `src/radcast/models.py` (only if a new enum/config surface becomes necessary)
- `tests/test_speech_cleanup.py`
- `tests/test_worker_queue.py`
- `tests/test_worker_setup.py`
- `README.md`
- `docs/radcast_optimized.md` only if helper setup or runtime docs reference caption backend assumptions

**Do not modify in the first pass unless forced:**
- UI templates / JS
- enhancement model code paths
- server routing behavior

---

### Task 1: Define the caption backend interface

**Files:**
- Create: `src/radcast/services/caption_backends.py`
- Test: `tests/test_caption_backends.py`

- [ ] **Step 1: Write the failing interface tests**

Add tests for a narrow backend contract:
- backend exposes an `id`
- backend exposes `capability_status()`
- backend can transcribe a single chunk and return normalized segment/word output
- normalized output contains only fields the rest of `SpeechCleanupService` actually uses

Suggested test shape:

```python
from radcast.services.caption_backends import CaptionTranscriptionResult


def test_transcription_result_normalizes_segments():
    result = CaptionTranscriptionResult(
        text="hello world",
        segments=[{"start": 0.0, "end": 1.0, "text": "hello world", "avg_logprob": -0.1}],
        words=[],
        model_id="demo",
    )
    assert result.text == "hello world"
    assert result.model_id == "demo"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest /Users/rcd58/RADcast/tests/test_caption_backends.py -q
```

Expected: import/module failure

- [ ] **Step 3: Implement the interface and normalized result types**

Create `caption_backends.py` with:
- `CaptionTranscriptionResult` dataclass
- `CaptionBackend` protocol / ABC
- minimal typed shapes for segment/word metadata used by `speech_cleanup.py`

Keep this file focused. No backend selection logic here.

- [ ] **Step 4: Re-run the tests**

Run:

```bash
pytest /Users/rcd58/RADcast/tests/test_caption_backends.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/radcast/services/caption_backends.py tests/test_caption_backends.py
git commit -m "refactor: add caption backend interface"
```

---

### Task 2: Wrap the existing faster-whisper path behind the backend interface

**Files:**
- Modify: `src/radcast/services/caption_backends.py`
- Modify: `src/radcast/services/speech_cleanup.py`
- Test: `tests/test_caption_backends.py`
- Test: `tests/test_speech_cleanup.py`

- [ ] **Step 1: Write a failing adapter test**

Add tests that a `FasterWhisperCaptionBackend`:
- reports capability based on `faster_whisper`
- accepts model/device/beam config
- returns normalized transcription output

Use monkeypatching instead of real model loads.

- [ ] **Step 2: Run only the new adapter tests**

```bash
pytest /Users/rcd58/RADcast/tests/test_caption_backends.py -q
```

Expected: FAIL on missing adapter

- [ ] **Step 3: Implement `FasterWhisperCaptionBackend`**

Move the backend-specific chunk transcription logic out of `SpeechCleanupService` into the adapter.

Do not rewrite orchestration. Keep `SpeechCleanupService` responsible for:
- chunk planning
- review flow
- glossary handling
- output writing

- [ ] **Step 4: Update `SpeechCleanupService` to call the adapter instead of directly calling faster-whisper internals**

Refactor only the transcription boundary. Preserve behavior.

- [ ] **Step 5: Run focused regression tests**

```bash
pytest /Users/rcd58/RADcast/tests/test_caption_backends.py /Users/rcd58/RADcast/tests/test_speech_cleanup.py -q
```

Expected: PASS with unchanged reviewed-caption behavior

- [ ] **Step 6: Commit**

```bash
git add src/radcast/services/caption_backends.py src/radcast/services/speech_cleanup.py tests/test_caption_backends.py tests/test_speech_cleanup.py
git commit -m "refactor: route captions through faster-whisper backend"
```

---

### Task 3: Add backend selection policy

**Files:**
- Create: `src/radcast/services/caption_backend_selection.py`
- Modify: `src/radcast/services/speech_cleanup.py`
- Test: `tests/test_caption_backend_selection.py`
- Test: `tests/test_speech_cleanup.py`

- [ ] **Step 1: Write failing selection tests**

Add tests for:
- `auto` on macOS local helper -> `whispercpp`
- `auto` on Windows -> `faster_whisper`
- explicit override beats auto
- missing backend capability yields deterministic failure or fallback per policy

- [ ] **Step 2: Run the selection tests**

```bash
pytest /Users/rcd58/RADcast/tests/test_caption_backend_selection.py -q
```

Expected: FAIL on missing module

- [ ] **Step 3: Implement backend resolution**

Create a small policy module that answers:
- requested backend
- available backend
- chosen backend

Inputs should include:
- platform
- explicit env override
- local-helper/server context

- [ ] **Step 4: Wire selection into `SpeechCleanupService` construction**

Avoid scattering backend-choice logic through transcription methods.

- [ ] **Step 5: Run regression tests**

```bash
pytest /Users/rcd58/RADcast/tests/test_caption_backend_selection.py /Users/rcd58/RADcast/tests/test_speech_cleanup.py /Users/rcd58/RADcast/tests/test_worker_queue.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/radcast/services/caption_backend_selection.py src/radcast/services/speech_cleanup.py tests/test_caption_backend_selection.py tests/test_speech_cleanup.py tests/test_worker_queue.py
git commit -m "feat: add platform-aware caption backend selection"
```

---

### Task 4: Add macOS whisper.cpp backend for first-pass transcription

**Files:**
- Modify: `src/radcast/services/caption_backends.py`
- Modify: `src/radcast/worker_setup.py`
- Modify: `src/radcast/worker_client.py`
- Test: `tests/test_caption_backends.py`
- Test: `tests/test_worker_setup.py`
- Test: `tests/test_worker_queue.py`

- [ ] **Step 1: Write failing macOS backend tests**

Cover:
- capability detection for `whisper.cpp`
- command construction / invocation shape
- normalized output parsing from backend output
- macOS local helper default selecting the new backend

Use fixture/mocked process output rather than real whisper.cpp execution.

- [ ] **Step 2: Run the new macOS backend tests**

```bash
pytest /Users/rcd58/RADcast/tests/test_caption_backends.py /Users/rcd58/RADcast/tests/test_worker_setup.py -q
```

Expected: FAIL on missing backend implementation

- [ ] **Step 3: Implement `WhisperCppCaptionBackend`**

Start with first-pass transcription only.

Requirements:
- use `whisper.cpp` invocation appropriate for local helper execution
- preserve `Window X of Y` progress semantics
- normalize segment output into the shared backend shape

Do not couple it to UI or job-record logic.

- [ ] **Step 4: Add macOS local helper setup support**

Update helper setup/runtime so macOS local helpers can resolve the new backend deterministically.

This includes:
- install-time defaults
- runtime override behavior
- capability error message if whisper.cpp is missing

- [ ] **Step 5: Run focused tests**

```bash
pytest /Users/rcd58/RADcast/tests/test_caption_backends.py /Users/rcd58/RADcast/tests/test_worker_setup.py /Users/rcd58/RADcast/tests/test_worker_queue.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/radcast/services/caption_backends.py src/radcast/worker_setup.py src/radcast/worker_client.py tests/test_caption_backends.py tests/test_worker_setup.py tests/test_worker_queue.py
git commit -m "feat: add macos whisper.cpp caption backend"
```

---

### Task 5: Preserve reviewed-caption orchestration across backends

**Files:**
- Modify: `src/radcast/services/speech_cleanup.py`
- Test: `tests/test_speech_cleanup.py`

- [ ] **Step 1: Add failing regression tests around reviewed mode**

Cover:
- reviewed mode still produces review metadata
- glossary flow still works
- output file generation is backend-agnostic
- backend output feeds the same review policy

- [ ] **Step 2: Run the reviewed-mode tests**

```bash
pytest /Users/rcd58/RADcast/tests/test_speech_cleanup.py -q
```

Expected: FAIL on backend integration gaps

- [ ] **Step 3: Refactor orchestration boundaries**

Make `SpeechCleanupService` backend-agnostic by isolating:
- chunk planning
- per-window transcription calls
- reviewed-segment escalation
- output writing

If the macOS path cannot yet run the reviewed sweep entirely through whisper.cpp, isolate that as an explicit compatibility branch instead of hiding it in ad hoc conditionals.

- [ ] **Step 4: Run the regression suite**

```bash
pytest /Users/rcd58/RADcast/tests/test_speech_cleanup.py /Users/rcd58/RADcast/tests/test_worker_queue.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/radcast/services/speech_cleanup.py tests/test_speech_cleanup.py tests/test_worker_queue.py
git commit -m "refactor: keep reviewed captions backend-agnostic"
```

---

### Task 6: Add benchmark harness for macOS vs Windows caption backends

**Files:**
- Create: `scripts/bench_caption_backends.py`
- Optionally create/update: `README.md`

- [ ] **Step 1: Write the benchmark script skeleton**

Script inputs:
- audio file path
- backend id
- quality mode
- optional explicit model/backend overrides

Script outputs:
- first window latency
- median window latency
- total first-pass runtime
- review runtime if applicable
- total wall-clock runtime

- [ ] **Step 2: Add a dry-run or fake-backend test if practical**

If not practical, at minimum keep the script self-checking with argument validation.

- [ ] **Step 3: Run the script on a known local sample**

Example:

```bash
python /Users/rcd58/RADcast/scripts/bench_caption_backends.py \
  --audio /absolute/path/to/sample.wav \
  --backend faster_whisper \
  --quality reviewed
```

Expected: structured benchmark output

- [ ] **Step 4: Document how to run benchmarks**

Add concise notes to `README.md` only if needed.

- [ ] **Step 5: Commit**

```bash
git add scripts/bench_caption_backends.py README.md
 git commit -m "tools: add caption backend benchmark harness"
```

---

### Task 7: Fix ETA behavior for backend-aware caption progress

**Files:**
- Modify: `src/radcast/worker_client.py`
- Modify: `src/radcast/services/speech_cleanup.py`
- Test: `tests/test_worker_queue.py`
- Test: `tests/test_speech_cleanup.py`

- [ ] **Step 1: Write failing ETA tests**

Cover:
- no precise ETA until enough windows complete
- `Window X of Y` remains primary detail signal
- numeric ETA only appears after stable throughput exists
- ETA smoothing does not jump wildly every heartbeat

- [ ] **Step 2: Run the ETA tests**

```bash
pytest /Users/rcd58/RADcast/tests/test_worker_queue.py /Users/rcd58/RADcast/tests/test_speech_cleanup.py -q
```

Expected: FAIL on current heuristic behavior

- [ ] **Step 3: Implement backend-aware ETA smoothing**

Use measured window throughput from the active backend instead of early static guesses.

Policy:
- first 1–2 windows: `estimating`
- once stable: smoothed ETA
- do not let heartbeat updates oscillate the display heavily

- [ ] **Step 4: Re-run ETA tests**

```bash
pytest /Users/rcd58/RADcast/tests/test_worker_queue.py /Users/rcd58/RADcast/tests/test_speech_cleanup.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/radcast/worker_client.py src/radcast/services/speech_cleanup.py tests/test_worker_queue.py tests/test_speech_cleanup.py
git commit -m "fix: smooth backend-aware caption eta"
```

---

### Task 8: Full verification pass

**Files:**
- Verify all touched files

- [ ] **Step 1: Run focused test suite**

```bash
pytest /Users/rcd58/RADcast/tests/test_caption_backends.py \
       /Users/rcd58/RADcast/tests/test_caption_backend_selection.py \
       /Users/rcd58/RADcast/tests/test_speech_cleanup.py \
       /Users/rcd58/RADcast/tests/test_worker_queue.py \
       /Users/rcd58/RADcast/tests/test_worker_setup.py -q
```

Expected: PASS

- [ ] **Step 2: Run compile checks**

```bash
python3 -m py_compile \
  /Users/rcd58/RADcast/src/radcast/services/caption_backends.py \
  /Users/rcd58/RADcast/src/radcast/services/caption_backend_selection.py \
  /Users/rcd58/RADcast/src/radcast/services/speech_cleanup.py \
  /Users/rcd58/RADcast/src/radcast/worker_client.py \
  /Users/rcd58/RADcast/src/radcast/worker_setup.py \
  /Users/rcd58/RADcast/tests/test_caption_backends.py \
  /Users/rcd58/RADcast/tests/test_caption_backend_selection.py \
  /Users/rcd58/RADcast/tests/test_speech_cleanup.py \
  /Users/rcd58/RADcast/tests/test_worker_queue.py \
  /Users/rcd58/RADcast/tests/test_worker_setup.py
```

Expected: no output

- [ ] **Step 3: Run one real local-helper benchmark on macOS**

Use the existing `Quantum_Entanglement_in_5_minutes.mp3` sample or equivalent and capture:
- first window latency
- total runtime progression
- whether reviewed mode remains acceptable

- [ ] **Step 4: Commit final verification/documentation adjustments**

```bash
git add .
git commit -m "chore: verify platform caption backend split"
```

---

## Notes for Implementation

- Do not break the existing Windows path while landing macOS support.
- Do not let backend-specific process management leak into the UI.
- Prefer capability detection plus explicit error messaging over silent fallback.
- Preserve current project/job/output metadata shapes unless there is a compelling reason to extend them.
- Keep reviewed-caption quality policy in one place, even if backend execution differs by platform.
