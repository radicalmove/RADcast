# Glossary Growth Design

## Purpose

RADcast already accepts a caption glossary string and uses it to bias transcription and accessibility checks. That is useful for one-off runs, but it does not scale when the same course, lecturer, or subject repeatedly uses the same terminology.

This design turns glossary handling into a persistent, reviewable feature:

- the app can accumulate glossary terms over time
- users can review and edit those terms in the app
- caption generation can continue to use the current glossary plumbing
- accessibility checks can fail when critical terms remain wrong after repair

The goal is not to invent a new transcription system. The goal is to make the existing caption pipeline more reliable for lecture terminology.

## Problem Statement

Current glossary support is transient and manually entered per run. That causes three problems:

1. Repeated lecture terms have to be retyped.
2. Important corrections are not retained for future runs.
3. Critical term misses can still slip through if the glossary is incomplete or unavailable.

For accessibility-oriented lecture captions, this is a weak workflow. We need glossary terms to become a durable, reviewable part of the app.

## Goals

- Persist glossary terms across runs.
- Let users review, approve, edit, and remove glossary terms in the app.
- Automatically suggest new glossary terms from confirmed corrections and repeated high-confidence matches.
- Feed approved glossary terms into the existing caption prompt and accessibility checks.
- Fail exports when critical terms still come out wrong after repair.

## Non-Goals

- Do not replace the existing caption transcription pipeline.
- Do not auto-approve every machine-suggested term.
- Do not build a generic dictionary product for every possible domain.
- Do not require the user to manage glossary terms outside RADcast.

## Recommended Approach

Use a single glossary system with two levels:

1. **Active glossary terms**
   - Terms currently used to bias transcription and review.
   - These are the terms that matter for runtime behavior.

2. **Suggested glossary terms**
   - Terms the app proposes from confirmed corrections, repeated review fixes, or explicit user input.
   - Suggestions are not active until approved.

This keeps the system safe:

- automatic learning is allowed
- automatic promotion is not
- the user can inspect and correct glossary entries before they affect future runs

## Glossary Rules

Glossary entries are matched by normalized term text.

- Project-scoped active terms override global active terms when both exist for the same normalized term.
- If a project-scoped term is disabled, the global active term remains available.
- Duplicate entries with the same normalized term, scope, and project are merged into one entry.
- Suggested entries never influence a run until they are approved.
- Approved entries become active immediately for later runs in the same scope.

## Accessibility Verdict Rules

The final export should be evaluated against explicit, testable rules.

`passed`
- No hard accessibility defects remain after export repair.
- No unresolved truncation, orphan cue, duplicated boundary word, hallucinated cue, or critical glossary miss remains.

`passed with warnings`
- The export is readable and complete.
- The only remaining flags are one or more of:
  - `probable low confidence`
  - `minor punctuation repair`
  - `minor casing repair`
- Export repair has already removed any `probable truncation`, `probable duplication`, or `probable critical term miss` flags.
- If a cue boundary had to be repaired, that repair must have removed the defect entirely; otherwise the export is `failed`.

`failed`
- Any hard accessibility defect remains after export repair.
- Hard defects include:
  - unresolved truncation that changes or breaks meaning
  - orphan cues or standalone fragments that should have been merged
  - duplicated boundary words that distort speech
  - hallucinated or stray captions
  - unresolved critical glossary misses
  - broken continuity that leaves the lecture meaning unclear

This means a cleaned export with only minor warnings can pass, but any remaining hard defect must fail.

## Glossary Source Priority

When sources disagree, use this order:

1. **Manual active entries**
2. **User-approved confirmed corrections**
3. **Project active entries**
4. **Global active entries**
5. **Suggested entries**

Rules:

- Disabled entries never participate in runtime prompting.
- Project active entries shadow global active entries with the same normalized text.
- Suggested entries never shadow active entries.
- If the same normalized term appears more than once at the same priority level, dedupe it.
- The winning entry is the only runtime source for that normalized term.
- Non-winning duplicates are retained as historical rows, marked `disabled` or `superseded`, and their provenance can be copied into the winner's notes.

## User Experience

Add a glossary view in RADcast that supports:

- searching terms
- filtering by project or scope
- adding a new term manually
- editing an existing term
- enabling/disabling a term
- approving or rejecting suggestions
- optionally marking a term as global or project-specific

The UI should make it obvious which terms are:

- active
- suggested
- disabled
- project-scoped
- global

## Data Model

Glossary entries should have at least:

- `term`
- `scope` (`global` or `project`)
- `project_id` if project-scoped
- `status` (`suggested`, `active`, `disabled`)
- `source` (`manual`, `auto_suggested`, `confirmed_correction`)
- `created_at`
- `updated_at`
- optional `notes`

The existing `caption_glossary` field can continue to be the transport layer for active terms at runtime. The glossary store becomes the source of truth for assembling that field.

## Auto-Suggestion Rules

The system may suggest a glossary term when:

- a reviewed caption correction is accepted for the same term in at least two runs within the same project
- a human-edited caption correction clearly identifies a term
- a term appears in a project-specific glossary import
- a high-confidence correction matches a likely critical term in the same project and the correction has already been confirmed once

Suggested terms should not become active automatically unless the source is explicitly trusted and the policy allows it.

Suggested terms should preserve the original evidence:

- source caption text
- corrected caption text
- project or lecture context
- a short reason for suggestion

The decision path should be deterministic:

- manual edits create a suggested entry immediately, or an active entry if the user explicitly approves it
- repeated confirmed corrections create a suggested entry
- repeated high-confidence matches create a suggested entry only when they match an existing course/project glossary term or a previously confirmed correction
- auto-suggested entries never become active without manual approval
- approved terms outrank suggested terms in runtime assembly
- active project terms outrank active global terms with the same normalized text

## Legacy Import Rules

Existing `caption_glossary` values should be imported into the new glossary store using these rules:

- Split on newlines, commas, and semicolons.
- Trim whitespace and discard empty items.
- Preserve quoted phrases as single glossary terms.
- Strip surrounding punctuation from each term, but keep apostrophes and macrons.
- Normalize macrons/case the same way the runtime glossary matcher does.
- Deduplicate identical normalized terms.
- Import as `suggested` entries by default.
- If the source run is project-scoped, import them as project-scoped suggestions.
- If the source run was global, import them as global suggestions.
- Do not auto-promote imported terms to active status.
- If a legacy string cannot be split cleanly, import the cleaned value as one suggested term and add a note that it came from legacy import.

In other words, the app may learn automatically, but it only promotes glossary knowledge after a confirmable signal.

## Runtime Flow

1. The app assembles active glossary terms for the current run.
2. Those terms are passed into the existing caption prompt and review logic.
3. The caption pipeline runs as it does now.
4. If review or post-export repair identifies a likely glossary miss, that miss can generate a suggestion.
5. The output card and review file continue to reflect the final export status.
6. Suggested terms affect only future runs unless a user approves them before the next dispatch.

This design keeps the run path simple. Glossary management happens alongside it, not inside it.

## Accessibility Rules

Glossary misses should matter in the final verdict.

- If a critical glossary term is still wrong after repair, the export should fail.
- If the captions are readable and the glossary issues are minor or already repaired, the export may pass with warnings.
- If the output is clean, it should pass.

This makes glossary quality part of the accessibility standard, not a cosmetic hint.

## Safety and Review

The automatic suggestion path must be conservative.

Reasons:

- a bad auto-added term can poison future runs
- critical term checking should help accessibility, not create false failures
- users need a way to audit why a term was suggested

Suggested entries should always be visible in the app before they affect future runs.

## Testing

Add tests for:

- manual glossary terms being included in runtime caption prompts
- suggested terms staying inactive until approved
- approving a glossary suggestion making it active
- project-scoped terms not leaking into unrelated projects
- project-scoped active terms overriding global terms with the same normalized text
- duplicate glossary entries being merged deterministically
- suggestion deduplication across repeated runs
- reject transitions keeping a term out of the active runtime glossary
- glossary misses causing failed accessibility verdicts
- repaired critical terms no longer triggering failures

## Rollout

Roll out in this order:

1. Persist glossary terms.
2. Backfill existing ad hoc `caption_glossary` values as suggested terms, not active terms.
3. Add glossary management UI.
4. Add suggestion generation.
5. Wire glossary approvals into caption prompting.
6. Enforce critical-term accessibility failures on the final export.

The first implementation should keep the existing `caption_glossary` pipeline intact and layer persistence around it.
