# Human Caption Review Workflow Design

## Goal
Add a human-review workflow for flagged caption items so users can verify, correct, approve, and reuse decisions across future reruns without conflating glossary maintenance with transcription-quality failures.

## Problem
The current `Review glossary candidates` modal is too narrow and too confusing for the actual task users are performing. It mixes actionable glossary gaps with non-actionable items that are already in the glossary, exposes backend terminology such as `probable critical term miss`, and does not support the practical review actions users need when a caption line is questionable.

The actual user workflow is broader than glossary growth:
- verify the audio for a flagged line
- correct transcript text when it is wrong
- adjust timing when timing is wrong
- approve a line as acceptable when the automated review is too strict
- add missing vocabulary to the shared glossary only when that is the real issue

## Proposed Approach
Introduce a dedicated `Review flagged items` workflow per completed run. This is a human-review layer on top of the existing automated caption review.

The workflow will:
- show flagged items in a clear review queue
- separate `Needs review` from `Already in glossary but still misrecognised`
- support per-item audio playback for the flagged cue with short padding
- support immediate per-item transcript correction
- support immediate per-item timing correction with start/end fields and nudge controls
- support `Approve as correct` when no transcript change is needed
- support `Add to shared glossary` only for genuine glossary gaps
- persist corrections and approvals across future reruns of the same source-audio lineage, including trimmed variants
- mark the run as `passed after human review` once all blocking items have been resolved

## Why This Approach
This keeps glossary growth separate from transcript review while still letting the glossary learn from confirmed human corrections. It also gives the user a practical path from automated failure to a reviewed and accepted output without falsifying the original automated verdict.

## Alternatives Considered

### 1. Keep extending the glossary modal
Pros:
- smallest code change

Cons:
- keeps mixing different tasks into one UI
- still frames transcription-quality failures as glossary work
- does not scale to corrections, timing edits, and approvals cleanly

Rejected.

### 2. Dedicated review modal per run
Pros:
- matches the real workflow
- supports per-item verification and correction
- keeps the review loop fast
- can still expose glossary actions where relevant

Cons:
- more persistence and UI work

Recommended.

### 3. Separate review page
Pros:
- best long-term scalability

Cons:
- too much navigation overhead for now
- more structural change than needed to validate the workflow

Deferred.

## User Experience

### Completed Run Card
For runs with review artefacts, add a primary action:
- `Review flagged items`

Retain glossary-specific actions only if still useful after the review modal exists.

The accessibility status line should distinguish:
- `failed`
- `passed with warnings`
- `passed after human review`

Where relevant, keep the original automated outcome available as secondary detail.

### Review Modal Layout
Header copy:
- `Review each flagged caption item. Fix it, approve it, or add it to the shared glossary.`

Sections:
- `Needs review`
- `Already in glossary but still misrecognised` (collapsed by default)
- `Resolved in this review` (optional, if useful during the session)

Each item includes:
- plain-language reason label
- previous / flagged / next transcript context
- `Play clip`
- editable transcript text field
- start / end timing fields
- timing nudge controls
- actions:
  - `Save correction`
  - `Approve as correct`
  - `Add to shared glossary` when applicable

User-facing reason mapping:
- `probable critical term miss` -> `Term likely misheard`
- `probable truncation` -> `Caption may be cut off`
- `probable duplication` -> `Caption may repeat wording`
- `probable low confidence` -> `Caption may need a manual check`

British English is required throughout.

## Behaviour

### Save Correction
- updates the saved VTT for the current run immediately
- records a reusable correction tied to the source-audio lineage
- applies to future reruns of the same source audio, including trimmed variants

### Approve as Correct
- leaves the current transcript text unchanged
- records a persistent approval decision for that flagged item against the source-audio lineage
- applies to future reruns of the same source audio, including trimmed variants

### Add to Shared Glossary
- available when the item is a genuine glossary gap
- stores the term globally for future projects
- remains separate from per-run review approval

### Play Clip
- plays the flagged audio excerpt with a small lead-in and lead-out
- should be fast and available directly from the modal

### Final Run Status
If all blocking issues for the run are resolved through correction or approval, the run becomes:
- `Accessibility review: passed after human review.`

The system should preserve the original automated review metadata for traceability.

## Persistence Model
Add a human-review decision store keyed to source-audio lineage, not just a single run.

The decision key should survive trimmed outputs derived from the same source audio.

Persisted data types:
- manual approvals
- manual transcript text corrections
- manual timing overrides

These decisions should be consulted on future reruns before final review status is finalised.

## Data Flow
1. Automated review produces flagged caption items.
2. User opens `Review flagged items`.
3. UI loads review items and any saved decisions.
4. User plays, corrects, approves, or adds glossary terms.
5. Corrections update the current run’s saved VTT immediately.
6. Decisions persist to the source-audio lineage store.
7. The completed run status updates to reflect reviewed resolution.
8. Future reruns of the same source audio inherit those corrections and approvals.

## Scope for First Version
Include:
- `Review flagged items` action
- grouped sections for actionable vs already-known items
- per-item audio playback
- immediate text correction
- immediate timing correction with start/end and nudge controls
- per-item approval
- optional glossary promotion for missing terms
- `passed after human review` status when all blocking items are resolved
- British English copy cleanup

Exclude for now:
- waveform editor
- bulk edit or bulk approval tools
- standalone review page
- cross-course suggestion inbox

## Risks
- Matching a corrected or approved item back to source-audio lineage must be stable enough to survive trimmed exports.
- Immediate VTT rewriting must not corrupt cue ordering or timing format.
- Human approval must not erase the original automated review evidence.
- The modal can still become cluttered if too many actions are surfaced at once; sectioning and defaults matter.

## Testing Strategy
API and persistence:
- saving a correction updates the current run VTT immediately
- saving a timing edit updates cue timing correctly
- approving a flagged item clears it for the current run
- reruns of the same source audio reuse corrections and approvals
- trimmed variants of the same source audio inherit those decisions
- run status becomes `passed after human review` only when blocking items are fully resolved

UI:
- `Review flagged items` renders only when review artefacts exist
- modal sections render correctly
- already-known glossary items are non-actionable by default
- `Play clip` requests the correct excerpt
- save/apply actions update UI state immediately
- British English copy remains consistent

Regression:
- existing glossary review behaviour continues to work where still exposed
- automated accessibility verdicts still display correctly when no human review is performed
