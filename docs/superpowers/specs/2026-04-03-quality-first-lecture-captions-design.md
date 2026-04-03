# Quality-First Lecture Captions Design

Date: 2026-04-03
Branch: `codex/platform-caption-backends`

## Summary

RADcast now has a fast local caption path for Apple Silicon Mac helpers, but the output is not yet suitable for accessibility-grade lecture captions. The current `whisper.cpp (small)` path fixes runtime but still produces transcript errors, poor cue shaping, hallucinated review artifacts, and a review report that is not useful because many lines have `confidence unknown`.

This design introduces a quality-first lecture caption path for macOS local helpers. The path prioritizes accurate spoken dialogue, readable timing and segmentation, and review signals that map to real uncertainty. Speed remains important, but it is explicitly secondary to accessibility-grade output.

## Problem Statement

The current fast macOS local caption path has four practical failures:

1. Transcript fidelity is too weak.
- Hallucinated phrases can appear in the output.
- Content can become truncated, duplicated, or reordered.

2. Cue shaping is not accessibility-grade.
- Caption units can be too short, too long, or semantically awkward.
- Break points do not consistently follow readable lecture-caption conventions.

3. Review signals are low-value.
- Review reports often degrade to `confidence unknown` on most or all lines.
- This prevents effective human spot-checking.

4. The current fast path is optimized for throughput, not lecture accessibility.
- It is a good engineering speed path.
- It is not yet a good end-user caption quality path.

## External Accessibility Standard

The definition of success should be anchored to accessibility best practice, not subjective preference.

Relevant standards and guidance:
- WCAG 2.1 Understanding 1.2.2: captions for prerecorded media must provide the spoken dialogue and audio information needed to understand the content.
- W3C media guidance: captions should be synchronized, accurate, complete, and readable.
- Section 508 synchronized media guidance: captions should be equivalent, synchronized, and usable.
- FCC caption quality standards: accuracy, synchronicity, completeness, and placement/readability are the core quality dimensions.

For lecture recordings in RADcast, that translates to:
- prioritize accurate spoken dialogue;
- synchronize cues reasonably to the speech;
- preserve the full lecture meaning without major omissions;
- present readable caption chunks rather than raw transcript blocks;
- include non-speech or speaker cues only when necessary for understanding.

## Goals

1. Produce accessibility-grade lecture captions for prerecorded spoken-word material.
2. Improve spoken-dialogue accuracy materially over the current fast path.
3. Generate readable VTT/SRT cues with better timing and segmentation.
4. Make the review report useful by flagging genuinely uncertain lines.
5. Keep the workflow local on Apple Silicon Macs.

## Non-Goals

1. Full broadcast-caption compliance for all media genres.
- This design is for lecture recordings first.

2. Rich non-speech sound annotation.
- Only include those cues when needed for comprehension.

3. Maximum throughput.
- This path may be slower than the fast caption profile.

4. A universal single backend for all platforms.
- Platform-specific backend selection remains acceptable.

## Recommended Approach

Implement a separate quality-first caption policy for lecture recordings on Apple Silicon local helpers.

Core strategy:
1. Use a stronger first-pass transcription path than the current fast path.
2. Preserve real timing/confidence data where possible.
3. Review only lines that are genuinely uncertain, instead of degrading the whole output into low-value review noise.
4. Apply lecture-specific cue shaping after transcript stabilization, not before.

Recommendation:
- keep the current fast `whisper.cpp` path as the speed-oriented Mac option;
- add a quality-first local helper profile for lecture captions;
- optimize the quality-first profile for transcript fidelity and accessibility readability, not raw speed.

## Approaches Considered

### Option 1: Keep `whisper.cpp` and just increase model size

Pros:
- stays within the Apple-Silicon-optimized stack;
- smallest architecture change.

Cons:
- may still provide weak confidence or review metadata;
- may not solve hallucination and review-quality issues by itself.

Assessment:
- useful experiment, but not sufficient as the whole design.

### Option 2: Quality-first hybrid path on Mac

Pros:
- best path to accessibility-grade lecture captions;
- allows stronger transcript generation, targeted review, and improved cue shaping;
- keeps the current fast path available separately.

Cons:
- more logic and more tuning work;
- slower than the speed-oriented path.

Assessment:
- recommended.

### Option 3: Dual-backend consensus transcription

Pros:
- could improve transcript confidence through disagreement detection.

Cons:
- much more complexity;
- difficult to justify before the simpler quality-first path is exhausted.

Assessment:
- not justified yet.

## Proposed Architecture

### 1. Caption Quality Policy Layer

Add a quality policy above the caption backend selection.

Policies:
- `fast_local`
- `quality_local_lecture`
- existing server/local behavior remains compatible

Responsibilities:
- choose the transcription model/backend profile;
- choose whether review is enabled;
- choose review aggressiveness;
- choose cue-shaping thresholds;
- expose a stable runtime description for logs and UI.

This separates “what quality level do we want?” from “which backend is physically running?”

### 2. Transcript Generation Phase

For `quality_local_lecture` on Apple Silicon:
- use a stronger first-pass transcription configuration than the current `whisper.cpp (small)` fast profile;
- preserve usable word timings where available;
- preserve usable confidence/probability data when the backend can provide it.

Design expectation:
- the first pass should be strong enough that the review stage becomes targeted, not corrective for most of the file.

### 3. Review Phase

The review stage should become selective and evidence-driven.

Rules:
- only review lines with low confidence or structural anomalies;
- never inject review-system text into the transcript;
- review output must be constrained to transcript correction, not freeform generation;
- if confidence data is unavailable, fall back to structural heuristics instead of marking nearly everything uncertain.

Structural heuristics include:
- abrupt truncation;
- duplicated phrases;
- suspiciously short single-fragment cues;
- out-of-order or overlapping text windows;
- end-of-file boilerplate or repeated outro text not supported by adjacent content.

### 4. Cue Shaping Phase

Cue shaping should happen after transcript stabilization.

Requirements:
- split long transcript spans into readable lecture-caption cues;
- preserve temporal order;
- keep cues aligned with likely speech phrasing where possible;
- avoid one-word or semantically broken fragments unless the timing genuinely requires it;
- avoid fixed-length segmentation that ignores content.

Lecture-oriented shaping targets:
- readable two-line maximum output where feasible;
- sensible phrase boundaries;
- avoid line endings that split grammatical units badly;
- maintain a minimum cue duration and avoid implausibly long static cues.

### 5. Review Report Phase

The review report should become a useful QA artifact.

Requirements:
- report only truly flagged lines;
- use explicit reasons such as:
  - low backend confidence,
  - probable duplication,
  - probable truncation,
  - timing anomaly,
  - review correction applied;
- do not report the entire file as `confidence unknown` unless the entire backend genuinely lacks usable confidence data and no better heuristic exists.

## Data Flow

For `quality_local_lecture`:

1. Input audio selected.
2. Quality policy chooses stronger local lecture caption profile.
3. First-pass transcript runs with stronger model/profile.
4. Transcript/timing rows are normalized.
5. Review candidates are selected from confidence + structural heuristics.
6. Targeted review corrects only flagged lines.
7. Stabilized transcript is reshaped into lecture-friendly caption cues.
8. Output VTT/SRT is written.
9. Review report is written from actual flagged lines only.

## Error Handling

Failures in this path should degrade predictably.

Rules:
1. If the stronger quality-first path is unavailable locally, fail clearly or fall back only if the fallback is explicitly acceptable.
2. Never silently fall back from quality-first to a weaker fast path while presenting it as equivalent.
3. If review fails, preserve the first-pass transcript and mark the review report accordingly.
4. If cue shaping fails, preserve stabilized transcript segments rather than emitting corrupted or hallucinated output.

## UX Implications

The UI should continue to show:
- backend and model identity;
- window counts during first pass;
- review item counts during targeted review.

For the quality-first path, progress text should reflect that the run is using a stronger lecture-caption profile.

The user should be able to understand:
- that the run is slower because it is quality-first;
- which stage is happening now;
- whether review is correcting flagged lines or just validating them.

## Success Criteria

This path is successful when it meets the accessibility-oriented quality bar below.

### Accessibility-aligned quality criteria

1. Accuracy
- spoken dialogue is materially correct;
- no obvious hallucinated lines;
- no duplicated outro/system text;
- no major out-of-order transcript drift.

2. Synchronicity
- caption cues appear approximately with the speech;
- cue boundaries remain plausible relative to the spoken phrasing.

3. Completeness
- the lecture’s main spoken content is covered end-to-end;
- no major missing stretches.

4. Readability
- cue lengths and line breaks are suitable for lecture viewing;
- cue chunks are semantically readable rather than raw transcript fragments.

5. Review usefulness
- review report flags a minority of lines that are actually uncertain;
- review reasons are specific and actionable.

### Practical acceptance checks

Compared with the current fast path, the quality-first path should:
- remove hallucinated review/system text;
- reduce duplicated or broken segments materially;
- produce cleaner readable VTT output on the lecture sample set;
- generate a review report that is selective instead of all-unknown.

## Testing Strategy

### Unit tests

Add tests for:
- quality-policy selection for `quality_local_lecture`;
- stronger first-pass profile selection on macOS local helper;
- review candidate selection from structural anomalies;
- prevention of review-text hallucinations in final output;
- cue shaping for lecture-style readability;
- review report selectivity and reason labeling.

### Regression tests

Use the quantum entanglement lecture sample as an explicit regression fixture.

Assertions should cover:
- no known hallucinated strings;
- preserved ordering across key sections;
- no repeated outro mid-transcript;
- cue lengths within lecture-caption thresholds;
- review report line count not equal to total cue count by default.

### Manual verification

Human spot-check should inspect:
- opening section;
- middle technical explanation section;
- ending section;
- a handful of review-flagged cues.

## Rollout Plan

1. Implement `quality_local_lecture` behind the current branch-only dev path.
2. Benchmark output quality on the lecture sample set.
3. Tune transcript/review/shaping thresholds.
4. Compare against accessibility-oriented success criteria.
5. Only then decide whether this should replace the current local default or become a selectable quality mode.

## Recommendation

Proceed with a quality-first Apple Silicon lecture caption path built around:
- stronger first-pass transcription,
- selective targeted review,
- accessibility-oriented cue shaping,
- useful review reporting.

This is the most defensible route to accessibility-grade lecture captions while preserving the fast local path as a separate option when speed matters more than quality.
