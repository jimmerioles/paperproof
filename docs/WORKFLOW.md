# Working on Paperproof

The goal is steady progress in short, unpredictable sessions. The system should tell you what to do next without re-reading the whole codebase.

## Pickup ritual

At the start of a session:

```bash
git pull
make check
gh issue list --repo jimmerioles/paperproof --label status:ready --milestone "M1: Pilot-ready"
```

Pick exactly one issue. If two issues depend on each other, pick the one with no blocker.

## Session shape

A 90 minute session:

- **10 min: read.** Read the issue, the acceptance criteria, and the files listed. Do not start coding yet.
- **60 min: build.** Write the smallest change that satisfies the acceptance criteria. Add the test first when the change touches the verifier or extraction.
- **15 min: verify.** Run `make check`. Update the issue and the readiness checklist if a gate moved.
- **5 min: leave a note.** What changed, what is next, what is blocked.

A 20 minute session:

- Add a missing test.
- Add a golden case.
- Improve an error message.
- Refine an issue with acceptance criteria.
- Fix a documentation gap.

Do not start a large issue in a short session. Split it instead.

## Definition of done

A task is done when:

- The acceptance criteria are true.
- `make check` passes.
- New behavior has a test, and extraction or verification changes have an eval case.
- The readiness checklist is updated if a gate moved.
- The PR description says how to verify and how to roll back.
- The issue is closed with a one-line outcome.

## Issue quality bar

Every issue must have:

- **Outcome**: what changes for the user or operator.
- **Scope**: the smallest change that delivers it.
- **Acceptance**: testable statements, including failure behavior.
- **Test plan**: unit, integration, eval, or manual.
- **Out of scope**: what it deliberately does not cover.
- **Size**: S, M, or L. If L, split it before starting.

Use the GitHub task template. If an issue is vague, refine it before writing code.

## Branch and PR

```bash
git switch -c feat/ocr-pipeline
# implement
make check
git add -A
git commit -m "Add OCR pipeline for scanned PDFs"
git push -u origin feat/ocr-pipeline
gh pr create --fill
```

Merge with squash. Keep `main` green. Do not merge a red build to save time; the next session will pay for it.

## Weekly review

15 minutes, once a week:

1. Close or split stale issues.
2. Move one issue into `status:ready`. Keep at most three.
3. Check the active milestone. Is it still the right risk?
4. Update `ROADMAP.md` if the order changed.
5. Pick the next session's issue.
6. If a decision is blocking progress, write an ADR proposal and timebox the spike.

## Decisions

Use `docs/adr/` for choices that are expensive to reverse: OCR engine, deployment target, auth provider, vector store, LLM data policy.

An ADR is one page:

- Context
- Decision
- Consequences
- Alternatives considered

If a decision is not made, label the issue `status:needs-decision` and write the options in the issue. Do not let a spike run without a timebox.

## Keep work small

Split an issue when:

- It touches more than one of authentication, ingestion, extraction, retrieval, or UI.
- It needs more than three sessions.
- It has two independent acceptance criteria that could ship separately.
- It requires a decision that has not been written down.

Small issues are not less ambitious. They are how ambition survives a busy week.

## When stuck

- Re-read the trust invariants in `AGENTS.md`.
- Reproduce with the sample corpus before touching real documents.
- Write the failing test, then ask for help with the test as the artifact.
- If the issue is wrong, change the issue. Do not force the code to match a bad plan.

## What not to do

- Do not start a second issue while the first is red.
- Do not add a feature without an eval or a test.
- Do not bypass `verify_quote`.
- Do not relabel the project as MIT or OSI open source.
- Do not commit customer documents or secrets.
- Do not build Phase 2 or Phase 3 work before the Phase 1 gate.
