# Platform-Specific Local Caption Backend Design

**Goal**

Make RADcast local helper caption generation use the right backend for the host platform while preserving one product experience:
- macOS local helpers should use an Apple-Silicon-native backend optimized for quality-first local transcription.
- Windows local helpers should continue using the existing faster-whisper / CTranslate2 path with platform-appropriate acceleration.

**Status Quo**

RADcast currently routes local caption generation through `SpeechCleanupService`, which uses `faster-whisper` for first-pass transcription and reviewed caption generation. This works acceptably on Windows/CUDA, but it is a poor fit for Apple Silicon because the local macOS path is effectively CPU-bound. Recent fixes made the path viable, but not fast enough for high-quality local reviewed captions on a 5–6 minute file.

The current problem is no longer job correctness. It is architecture mismatch: one backend is being stretched across two hardware families with different acceleration strengths.

---

## Architecture

Introduce a caption backend abstraction beneath `SpeechCleanupService` so RADcast keeps one caption feature while using different local transcription engines by platform.

The orchestration layer remains in `SpeechCleanupService`:
- quality mode selection
- caption review workflow
- glossary application
- progress callbacks
- output formatting (`.vtt` / `.srt`)

A backend layer handles transcription execution:
- `FasterWhisperCaptionBackend` for Windows local helpers and existing server behavior
- `WhisperCppCaptionBackend` for macOS local helpers using Metal-accelerated `whisper.cpp`

This keeps the UI, job types, and product semantics stable while making the execution engine platform-specific.

---

## Backend Selection

### Selection policy

RADcast should select a caption backend at runtime using explicit policy rather than environment-variable sprawl.

Initial policy:
- macOS local helper: `whispercpp_metal`
- Windows local helper: `faster_whisper`
- Linux/server: existing `faster_whisper` path unless explicitly overridden later

### Control surface

Add a single backend selector for captions, with auto mode by default.

Proposed env/config shape:
- `RADCAST_CAPTION_BACKEND=auto|faster_whisper|whispercpp`
- `RADCAST_CAPTION_LOCAL_PROFILE=quality|balanced|fast`

`auto` resolves based on platform and capability detection. The product remains “reviewed captions”; only the engine changes.

---

## Components

### 1. Caption backend interface

Create an internal interface/protocol representing the transcription engine.

Responsibilities:
- transcribe one audio chunk/window
- report progress metadata needed by RADcast
- expose model/runtime identity for diagnostics
- return normalized segment/word structures that the rest of `SpeechCleanupService` already understands

This interface must be narrow. It should not own glossary logic, reviewed-caption policy, or output file formatting.

### 2. FasterWhisper backend

Wrap the existing transcription behavior behind the new interface with minimal change.

Responsibilities:
- preserve the current Windows/helper/server path
- retain current model/beam controls
- serve as the compatibility baseline during rollout

This backend becomes the reference implementation for normalized output shape.

### 3. Whisper.cpp backend

Add a new backend for macOS local helpers.

Responsibilities:
- run local transcription through `whisper.cpp`
- use Metal acceleration where available
- expose per-window progress and timing back to RADcast
- normalize results into the same segment/word schema expected by the review/output pipeline

Initial scope should target first-pass transcription for local reviewed captions. If reviewed sweep parity is good enough, the same backend can also handle the review pass. If not, we keep the reviewed sweep on a narrower compatibility path and benchmark before broadening it.

### 4. Capability detection layer

Add a small decision layer that answers:
- which backend is requested
- which backend is available
- which backend should be chosen for this machine

This keeps platform logic out of the UI and out of transcription internals.

---

## Data Flow

### Current target flow

1. User starts caption-only or cleanup+caption job.
2. Worker determines execution context.
3. `SpeechCleanupService` resolves caption backend.
4. Service runs first-pass windowed transcription through the selected backend.
5. Service applies existing quality/review logic on normalized segments.
6. Service writes reviewed caption file and any review artifact.
7. Worker reports progress and completion back to RADcast.

### macOS local helper flow

1. Detect `darwin` local helper.
2. Select `whisper.cpp` backend.
3. Run first-pass transcription with Metal.
4. Keep `Window X of Y` progress reporting.
5. Feed normalized segments into existing reviewed-caption pipeline.
6. Write `.vtt`/`.srt` as today.

### Windows local helper flow

1. Detect Windows local helper.
2. Select `faster-whisper` backend.
3. Keep current reviewed-caption path.
4. Preserve existing CUDA/CPU behavior.

---

## Error Handling

### Backend selection failures

If the preferred backend is unavailable:
- log why
- fall back to the compatible backend only if explicitly allowed by policy
- otherwise fail early with a precise local-helper error

For macOS local helpers, silent fallback to the old slow path should be avoided once the new backend ships. If `whisper.cpp` is the intended path and is missing, the user should get a clear setup/runtime message.

### Backend runtime failures

If a backend crashes mid-job:
- preserve job ownership semantics
- mark the job as failed locally with a backend-specific error
- do not silently shift to the server for this workflow unless the user explicitly wants that behavior

### Progress integrity

ETA should be backend-aware.
- do not show a precise countdown until enough windows have completed
- keep `Window X of Y` as the primary progress truth source
- backend timing data should be fed into a smoothed estimator rather than the current coarse heuristic

---

## Testing Strategy

### Unit tests

Add tests for:
- backend selection by platform and override
- capability fallback behavior
- normalized output shape from each backend adapter
- progress and ETA rules for multi-window transcription

### Integration tests

Add integration-style tests around `SpeechCleanupService` using fake backend implementations to verify:
- reviewed caption flow remains backend-agnostic
- output files are unchanged in shape/metadata
- progress callbacks remain consistent regardless of backend

### Benchmarks

Add explicit benchmark scripts for:
- Apple Silicon local helper, 5–6 minute lecture sample
- Windows helper, same sample

Measure:
- first window latency
- median window latency
- total first-pass runtime
- review-sweep runtime
- total wall-clock runtime

The Apple Silicon acceptance criterion is not a hard fixed number yet. It is “best quality that is clearly faster than the current slower local-helper path,” with iterative tuning afterward.

---

## Rollout Plan

### Phase 1

Introduce the backend abstraction and move the existing faster-whisper path behind it with no behavior change.

### Phase 2

Add macOS-only `whisper.cpp` backend for first-pass transcription and benchmark quality/runtime.

### Phase 3

Decide whether the reviewed sweep on macOS should:
- also use `whisper.cpp`, or
- remain on a compatibility backend for flagged regions only

### Phase 4

Tune backend-specific ETA/progress reporting so the UI reflects real platform throughput.

---

## Recommendation

Proceed with a platform-specific caption backend split.

This is the right approach because:
- it preserves one RADcast feature model
- it keeps Windows on the backend that already fits its hardware strengths
- it moves macOS to a backend that can actually use Apple Silicon well
- it stops the current pattern of platform-specific performance hacks accumulating inside a single transcription implementation

The first implementation milestone should be:
1. caption backend interface
2. `faster-whisper` adapter
3. backend selection layer
4. `whisper.cpp` macOS adapter for first-pass local transcription

