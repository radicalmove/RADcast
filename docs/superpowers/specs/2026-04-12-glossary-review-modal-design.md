# Glossary Review Modal Design

## Purpose

RADcast already flags caption runs that fail accessibility review because of glossary and lecture-term misses. The next step is to turn those failures into a shared learning loop: let a human review the failures in context, approve useful glossary terms, and promote them into the global glossary so future projects benefit automatically.

This feature is intentionally separate from transcription quality changes. It uses the review output to improve terminology coverage across all future runs.

## Problem Statement

Current accessibility review can tell us that a run failed, but it does not yet give the user a direct way to turn those failures into glossary improvements.

That creates two gaps:

- repeated terminology misses can keep happening across projects
- the user has no convenient review surface for approving glossary additions with transcript context

We want a workflow that is human-reviewed, context-aware, and shared across projects.

## Goals

1. Add a per-output workflow for reviewing glossary-related failures.
2. Show surrounding transcript context for each candidate so approval is informed.
3. Let approved terms be saved to the shared global glossary.
4. Keep the current accessibility verdict unchanged.
5. Avoid automatic glossary pollution; require explicit approval.

## Non-Goals

1. Do not create a full transcript editor.
2. Do not change the accessibility scoring rules in this feature.
3. Do not auto-promote glossary terms without human confirmation.
4. Do not add a separate glossary management page unless needed later.
5. Do not redesign the transcription pipeline itself in this feature.

## Recommended Approach

Add a `Review glossary candidates` button to each completed output card. Clicking it opens a modal that loads glossary candidates for that output from the server. The modal shows flagged terms with nearby transcript context, allows the user to approve or edit each term, and saves approved entries into the shared global glossary.

This is the best tradeoff because it:

- keeps the workflow close to the output that produced the failures
- reuses the existing modal pattern in RADcast
- keeps glossary learning human-reviewed
- applies the improvement to all future projects, not just the current one

## Approaches Considered

### Option 1: Inline review controls on each output card

Pros:
- fewer clicks
- simple conceptually

Cons:
- too cramped for surrounding context
- hard to review multiple candidates cleanly
- cluttered output cards

Assessment:
- too limited for the amount of context we need.

### Option 2: Modal-based review from each completed output card

Pros:
- preserves the current page layout
- supports context-rich review
- fits RADcast’s existing modal patterns
- easy to close and reopen without losing place

Cons:
- one more overlay interaction
- requires a small amount of modal state management

Assessment:
- recommended.

### Option 3: Separate glossary inbox page

Pros:
- good for bulk review later
- easier to expand into a glossary management area

Cons:
- more navigation overhead
- less immediate connection to the failing output
- larger implementation for the same outcome

Assessment:
- useful later, but not the best first step.

## User Flow

1. A user opens the completed versions list for a project.
2. A completed output that has caption review data shows a `Review glossary candidates` action.
3. Clicking the action opens a modal.
4. The modal loads glossary candidates derived from the run’s review artifacts.
5. Each candidate shows:
   - suggested term
   - failure reason
   - preceding transcript cue
   - flagged cue
   - following transcript cue
   - current glossary status if the term is already known
6. The user can:
   - approve the term
   - edit the term text before approval
   - skip the term
7. Saving writes approved terms into the shared global glossary.
8. The output list refreshes so the user can see that glossary review completed.

## Backend Design

### Candidate extraction endpoint

Add a server endpoint that accepts a project ID and output identifier, then derives glossary candidates from the existing caption artifacts.

Inputs:
- project/output reference
- completed output metadata
- caption VTT file
- caption review text file
- optional existing glossary lookup

Outputs:
- output metadata
- candidate list
- surrounding transcript context for each candidate
- glossary status for each candidate
- normalized term suggestion

Candidate extraction should be conservative and should rely on the existing review output as the source of truth.

### Save endpoint

Add a server endpoint that accepts approved glossary terms from the modal and writes them into the shared global glossary store.

Inputs:
- project/output reference
- approved term list
- optional user edits to term text

Outputs:
- saved glossary entries
- refreshed glossary status

The save path should dedupe normalized terms before writing so the same term is not added repeatedly.

## Candidate Heuristics

Only suggest terms that are plausibly tied to the review failure. The first pass should prioritize:

- critical term misses
- repeated domain-term substitutions visible in the review file
- phrase-level corrections that are obvious from context

The modal should not auto-suggest unrelated words just because they appear near a failure.

### Context window

For each candidate, show one cue before, the flagged cue, and one cue after when available. If the candidate appears at the beginning or end of the file, show whatever context exists rather than inventing missing cues.

### Safety rules

- Do not add any glossary entry automatically.
- Require explicit approval.
- Normalize approved terms before saving.
- If a candidate is already active globally, show it as already known.
- If no candidates exist, show an empty state rather than a fake suggestion.

## UI Design

### Completed output card

Add a `Review glossary candidates` action to output cards that include caption review data.

The action should only appear when there is a review artifact or accessibility metadata to inspect.

### Modal content

The modal should include:

- title
- short explanation of what is being reviewed
- status line for loading / empty / error states
- a list of candidate rows
- save and cancel actions

Each candidate row should include:

- suggested term field
- reason label
- preceding cue / flagged cue / following cue
- approve checkbox or toggle
- optional editable term input
- known-status indicator when the term already exists in the global glossary

## Data Flow

1. The output list renders metadata from `/projects/{project_id}/outputs`.
2. The user opens the glossary review modal for a completed output.
3. The frontend calls the new candidate endpoint.
4. The backend reads the output’s VTT and review file and builds candidate rows.
5. The frontend displays the candidates with transcript context.
6. The user approves or edits terms.
7. The frontend posts approved terms to the save endpoint.
8. The backend writes those terms to the global glossary store.
9. The frontend refreshes the output list and updates the modal state.

## Error Handling

- If the output has no review file, the action should not appear.
- If the candidate endpoint cannot parse the artifacts, the modal should show a clear error and allow retry.
- If the save endpoint rejects a term, show that row as failed and keep the rest of the modal usable.
- If the glossary store write fails, do not lose the user’s approved terms; show a retriable error.

## Accessibility and UX Notes

- Keep the modal keyboard accessible.
- Preserve focus on open/close.
- Ensure candidate rows are readable in dark and light themes.
- Use clear labels instead of jargon such as “critical miss” without context.
- Treat “already known” as informational, not as a warning.

## Testing

### Server tests

- candidate endpoint returns candidates for a review file with glossary misses
- candidate endpoint returns surrounding transcript context
- candidate endpoint marks already-known glossary terms correctly
- save endpoint writes approved terms to the global glossary store
- duplicate approvals do not create duplicate entries

### UI tests

- completed output cards show the review action when review artifacts exist
- modal opens and closes correctly
- candidate rows render with context and editable term text
- save flow calls the correct endpoint and refreshes the outputs list

### Regression tests

- no candidates means no save action
- existing glossary terms are not duplicated
- approval does not change accessibility verdicts

## Implementation Boundaries

This feature should live in the following areas:

- output card rendering in the frontend
- a new glossary-candidate API surface in the backend
- glossary store writes in the existing shared glossary service
- tests for both UI and API behavior

It should not change:

- transcription model selection
- rerun window logic
- accessibility verdict thresholds
- the global project layout

## Success Criteria

The feature is successful if:

- users can review glossary failures from the completed output card
- the review modal shows enough context to make a safe decision
- approved terms become active globally for future projects
- the workflow does not change transcript scoring or runtime behavior
- repeated glossary misses become less common across future runs
