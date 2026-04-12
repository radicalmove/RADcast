# Selective Low-Confidence Rerun Design

## Purpose

RADcast already has a workable caption pipeline for lecture recordings, including first-pass transcription, review candidate selection, export shaping, and accessibility verdicts. The remaining problem is accuracy on weak windows: a single pass can still mishear lecture terms, domain phrases, and short context-dependent utterances, especially on Mac local helpers.

This design improves transcription quality without significantly increasing runtime by rerunning only the windows that the system already considers weak.

## Problem Statement

The current reviewed-caption path is too expensive to rerun end-to-end, but a pure first pass still leaves a small number of obvious errors:

- lecture terminology can still be misheard
- low-confidence windows are not always corrected by one pass
- the review stage is useful, but it currently operates as a broad corrective sweep rather than a precision recovery pass

For accessibility-oriented lecture captions, we want a better tradeoff:

- keep the fast first pass
- spend extra time only where the transcript is weak
- preserve the current export and accessibility machinery

## Goals

1. Improve transcript accuracy on weak windows.
2. Keep runtime close to the current fast first pass for clean audio.
3. Reuse the existing review and export pipeline instead of adding a separate transcription system.
4. Make the stronger model apply only where it can materially improve the transcript.
5. Keep the user-facing progress model understandable.

## Non-Goals

1. Do not switch the entire local helper path to the slower stronger model.
2. Do not add a second independent transcription stack.
3. Do not change glossary learning in this feature.
4. Do not change the current accessibility verdict definitions.
5. Do not add a generic post-processing AI rewrite layer.

## Recommended Approach

Use a two-stage selective rerun pipeline:

1. Run the existing first pass exactly as today.
2. Identify weak windows using the existing review report and structural heuristics.
3. Rerun only those windows with the stronger caption review backend/model already supported by the service.
4. Accept a replacement only when the rerun is clearly better than the original.
5. Merge accepted replacements back into the timeline and continue with cue shaping and accessibility review.

This keeps the current fast pass intact while spending extra computation only on the parts that need it.

## Approaches Considered

### Option 1: Stronger model for the entire transcription

Pros:
- simplest to reason about
- easiest to implement

Cons:
- slower for every run
- penalizes clean audio unnecessarily
- risks making the helper feel sluggish on large files

Assessment:
- useful baseline, but not the preferred solution.

### Option 2: Selective rerun of low-confidence windows

Pros:
- best balance of accuracy and runtime
- reuses the existing review signal
- only spends extra time where confidence is weak

Cons:
- needs careful replacement rules
- slightly more complex than a single-pass model choice

Assessment:
- recommended.

### Option 3: Add a separate correction model that rewrites the whole transcript

Pros:
- could improve readability in some cases

Cons:
- higher risk of hallucinated changes
- harder to preserve timing and accessibility semantics
- more complex than needed right now

Assessment:
- not justified for this iteration.

## Architecture

The current caption pipeline already has the right boundaries:

- first-pass transcription
- review candidate selection
- caption repair / review sweep
- cue shaping
- accessibility verdict generation

This feature adds a selective refinement step between review candidate selection and final export.

### Key principle

Do not treat the rerun as a new transcript source of truth. Treat it as a targeted repair pass for individual windows.

### Core units

#### 1. Weak-window selector

Inputs:
- first-pass segments
- review report
- accessibility flags

Outputs:
- a list of windows or segment ranges to rerun

Selection should use the existing review report first, because that is already the system’s best signal for weak transcript regions.

#### 2. Selective rerun executor

Inputs:
- analysis WAV
- selected ranges
- stronger backend/model settings
- caption prompt/glossary context

Outputs:
- candidate replacement segments for each weak range

This executor should only transcribe the selected windows, not the whole file.

#### 3. Replacement gate

Inputs:
- original segment(s)
- candidate rerun segment(s)
- probability and structural signals

Outputs:
- accept or reject each replacement

The gate should be conservative. If the rerun is not clearly better, keep the original.

#### 4. Merge step

Inputs:
- original transcript timeline
- accepted replacement segments

Outputs:
- updated timeline for cue shaping and export

This should preserve chronological order and avoid introducing overlaps or duplicate cues.

## Selection Rules

The rerun should target segments flagged for any of the following:

- probable low confidence
- probable truncation
- probable duplication
- critical term miss

Priority order:

1. critical term misses
2. truncation
3. duplication
4. low confidence

If a segment matches multiple categories, rerun it once and let the stronger backend resolve it.

### Skip rules

Do not rerun a segment when:

- the segment is already high-confidence and structurally clean
- the segment is too short to benefit from a stronger pass
- the rerun window would be effectively identical to a neighboring rerun window and can be merged safely into one larger region

The system should merge adjacent candidate ranges so the second pass does not fragment into tiny jobs.

## Replacement Rules

A rerun replacement should be accepted only if one or more of the following are true:

- the new segment has materially higher probability/confidence
- the original segment showed truncation or duplication and the rerun resolves it
- the rerun fixes a critical term miss
- the rerun preserves the meaning more clearly than the original text

Reject a replacement if:

- the candidate is shorter but loses meaning
- the candidate is lower confidence and not a truncation repair
- the candidate changes correct terminology into a worse spelling
- the candidate appears to hallucinate extra wording

For truncation repairs, allow a slightly different threshold than for normal confidence replacement, because the goal there is to recover missing speech rather than just improve a probability score.

## Model Choice

Use the stronger caption review backend/model already available in the service for the rerun stage.

That means:

- the first pass keeps the current fast profile
- the rerun uses the quality-first review model that already exists in the service configuration

This avoids introducing a third transcription path. It also keeps the selective rerun aligned with the existing `review_backend` and `review_model_size` policy in `SpeechCleanupService`.

## Data Flow

1. Run the current first-pass timeline transcription.
2. Build the existing quality report.
3. Identify weak windows from review flags and structural heuristics.
4. Merge overlapping windows into a small set of rerun ranges.
5. Transcribe only those ranges with the stronger review backend/model.
6. Compare candidate replacements to the original segments.
7. Accept only clear improvements.
8. Deduplicate and normalize the merged timeline.
9. Continue with cue shaping and accessibility verdict generation.

## Progress and ETA

The UI should reflect the new two-stage behavior without making progress feel unstable.

Guidelines:

- first-pass window progress remains the primary progress signal
- rerun progress should be shown as a separate stage, not mixed into the first pass
- ETA should not jump backward aggressively when rerun windows begin
- if the selected rerun set is small, the UI should avoid implying that the whole file is being retranscribed

The stage text should be explicit, for example:

- `Transcribing speech for captions`
- `Rechecking low-confidence caption lines`
- `Writing VTT captions`

## Error Handling

If the rerun stage fails:

- preserve the first-pass transcript
- continue with the existing accessibility verdict and export path if safe
- mark the job failed only if the transcript is no longer valid or the pipeline cannot continue safely

If a rerun candidate is unavailable or empty:

- keep the original segment
- do not fail the whole job

If the stronger backend is unavailable:

- fall back only if the configured policy already allows that backend
- otherwise fail clearly, rather than pretending the rerun happened

## Testing

Add tests for:

- selecting rerun windows from review flags
- merging overlapping weak windows
- accepting a better rerun replacement
- rejecting a worse rerun replacement
- skipping reruns when no weak windows exist
- preserving the original transcript when reruns fail
- keeping review/export output unchanged for clean files

Also add a regression test that ensures the first pass is still the fast path and that the stronger backend is only invoked for flagged windows.

## Rollout

1. Add the selective rerun selection and merge logic behind the existing reviewed caption flow.
2. Reuse the current stronger review backend/model for reruns.
3. Add tests for replacement and skip behavior.
4. Verify on lecture clips that runtime stays close to the current baseline on clean windows.
5. Tune thresholds only if the rerun is too aggressive or too conservative.

## Success Criteria

This feature is successful when:

- weak lecture windows are corrected more often
- clean files do not get slower in a meaningful way
- accessibility failures caused by isolated misrecognitions become less frequent
- the user still sees a simple, understandable review and export flow

