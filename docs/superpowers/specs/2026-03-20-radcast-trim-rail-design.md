# RADcast Trim Rail Design

## Goal

Add a simple non-destructive top-and-tail clipper to RADcast so users can trim the start and end of a selected audio clip before processing, while keeping the original saved project audio untouched.

## User Experience

The trim feature lives in the existing whitespace in the RADcast output-settings area. It uses a simple horizontal rail rather than a waveform.

The rail represents the full duration of the currently selected audio clip. Users can:

- drag a start handle to trim from the front
- drag an end handle to trim from the back
- click or drag on the rail to move a playhead for auditioning
- use the existing audio preview player to hear the clip from the chosen point

The trim remains non-destructive. The original selected audio file is never replaced or edited in project storage.

## Interaction Model

The trim rail should:

- be disabled when no audio clip is selected
- appear only when the selected clip duration is known
- allow free handle movement with display rounded to `0.1s`
- clamp automatically so the trimmed clip always keeps a small minimum duration
- show compact time readouts for:
  - trim start
  - trim end
  - resulting output length

Dragging a handle should also move the preview to that handle position so the user can quickly audition the intended cut point.

## Persistence

Trim state is remembered per project and per selected audio clip.

Because RADcast often works from saved project audio, the trim state should be keyed by the selected audio file identity rather than kept as one global project trim. The intended behavior is:

- switch from audio A to audio B: show B's saved trim state
- switch back to audio A: restore A's saved trim state
- upload a new file: treat that new file as the active source and persist trim once it has a saved project audio hash

The trim is stored in project UI settings rather than by mutating the source audio.

## Data Model

Add trim metadata to RADcast project settings and job requests.

Recommended shape:

- per-audio trim settings keyed by saved audio hash
- each entry stores:
  - `clip_start_seconds`
  - `clip_end_seconds`

The stored values are absolute positions in the selected clip, not "seconds removed".

For job execution, the selected trim values should be sent explicitly in the processing request so both helper and server paths apply the same trim behavior.

## Processing Flow

Trim should happen once, before all downstream audio work.

End-to-end flow:

1. User selects saved project audio or uploads a new file.
2. RADcast restores any saved trim state for that audio.
3. User adjusts the trim rail.
4. On process start, RADcast sends the trim values with the job.
5. The pipeline creates a trimmed working copy first.
6. Enhancement, silence cleanup, filler cleanup, and captions all run against the trimmed copy.
7. Final output metadata, captions, and durations all reflect the trimmed clip.

This avoids any need for later caption retiming or special cleanup offsets.

## Backend Approach

Use ffmpeg to create the trimmed working copy.

Rationale:

- RADcast already depends on ffmpeg and ffprobe for audio conversion and duration probing
- trim can be applied consistently before enhancement and post-processing
- helper and server fallback paths can share the same preparation behavior

If the trim is effectively the full clip, skip the trim step entirely and continue with the existing processing flow.

## Validation Rules

The trim system should enforce:

- `clip_start_seconds >= 0`
- `clip_end_seconds <= source duration`
- `clip_end_seconds > clip_start_seconds`
- a minimum remaining clip duration, recommended `0.5s`

If trim preparation fails, the job should fail early with a clear message such as `Could not prepare trimmed audio.`

## UI Layout

The first version should stay intentionally simple:

- no waveform rendering
- no destructive edit/save flow
- no separate trim preset manager
- no additional modal

The trim rail should slot into the current RADcast settings card layout, using the existing whitespace so the feature feels native rather than bolted on.

## Testing Strategy

Add coverage for:

- model and API validation of trim start/end values
- project settings persistence for per-audio trim state
- UI behavior when switching between saved audio files
- processing with trim plus enhancement
- processing with trim and no enhancement
- regression coverage proving captions and cleanup use the trimmed duration rather than the original source duration

## Out of Scope

The first release should not include:

- waveform visualization
- destructive source editing
- multi-region clip editing
- saved named trim presets
- separate caption retiming after processing

## Recommendation

Implement the trim rail as a lightweight non-destructive preprocessing control, remembered per selected audio file and applied once before enhancement/cleanup/captions. This gives the user the top-and-tail control they want without complicating RADcast's streamlined processing flow.
