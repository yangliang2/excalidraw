# Real GitHub pilot: verification and limits

This extends PR #14 on `yangliang2/excalidraw`, without merging master. The original acceptance remains in verification.md; workflow-scope.md records this validation scope.

## Actual local evidence (2026-11-23)

- Original browser script against a production build: 36 passed, 0 failed. It did not assert scene outcome.
- Enhanced production browser check: 54 passed, 60 persisted scene assertions, 0 failed. Six language/layout combinations; each covers original values and pointer/keyboard, editor undo/redo, reload and restored selection properties. Scene assertions bind the original rectangle ID, not only the slider value.
- Existing actionStyles tests: 6 passed.
- CSS gate smoke: accepts unchanged CSS, rejects more than 1024 gzip bytes of growth and missing candidate CSS. Existing JS budgets are retained.
- Browser test development caught two real test-flow errors: selection after reload and compact panel closure after undo. Both were fixed with actual editor interactions; failed logs were retained locally.

## Execute against the real fork

Requires Python 3.9+, installed locked Yarn dependencies, Node 22, Playwright Chromium, authenticated gh and Claude CLI. Commit authorized implementation before starting. The runner refuses dirty candidates.

```sh
python3 scripts/workflow/prepare_rtl.py /absolute/outside-repo/run
python3 scripts/workflow/loop.py init --plan /absolute/outside-repo/run/plan.json --state /absolute/outside-repo/run/state
python3 scripts/workflow/loop.py run --plan /absolute/outside-repo/run/plan.json --state /absolute/outside-repo/run/state
```

The prepared plan builds and checks production behavior, tests the size gate, pushes only the existing RTL branch, waits for matching GitHub CI, performs a fresh read-only Claude review, and stops for real product acceptance. `init` exit 1 means pending work. CI waiting exit 2 with a waiting list can be resumed with `run`; human exit 3 is not acceptance. Check registration has a bounded 60-second grace; missing checks then report an environment problem, not a code repair request. Preserve earlier state when the plan changes.

## Actual takeover and remaining boundaries

The first local Codex implementation call failed twice with model capacity exhaustion and long backoff before executing edits. The coordinator ended that call and retained its environment-error receipt; the desktop Agent implemented the changes. This is an explicit takeover, **not evidence that unattended idea-to-implementation worked**. The continuation plan has no automatic repair command; review/behavior failures require the desktop Agent to correct the candidate and refresh evidence. Claude is a separate read-only review provider, not product approval.

The assertions cover scene data, persistence and restored properties, not pixel-level canvas alpha. Browser execution covers current Chromium, not historical Chrome, Firefox or Safari. Runtime logs and gate receipts are kept outside the candidate to avoid self-changing evidence. GitHub CI and deployed preview must be verified for the eventual pushed SHA; this document alone does not claim they passed. Product dogfooding and developer merge remain pending.
