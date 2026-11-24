# Local Agent capacity recovery: operations

Operational documentation for the pilot accepted in `agent-recovery-scope.md`. The behavior lives in `scripts/workflow/agent_router.py` (provider routing), `scripts/workflow/loop.py` (runner), `scripts/workflow/prepare_recovery.py` (plan generation) and the suite `scripts/workflow/tests/test_agent_router.py`. This file describes that implementation; the code and tests remain authoritative.

## What the router executes

`agent_router.py <mode> --policy <policy.json> --instructions <instructions.md>` runs one workflow step (`work`, `repair` or `review`) through local provider CLIs, prompted on stdin with the request, specifications and instructions:

- Codex primary: `codex exec --json --ephemeral --color never --sandbox workspace-write -C <repo> --output-schema <schema.json> -o <final.json> -` (`read-only` sandbox in review mode).
- Claude fallback: `claude -p --output-format stream-json --verbose --json-schema <schema> --tools ... --permission-mode dontAsk --no-session-persistence`, with tools `Read,Glob,Grep` for review and `Read,Glob,Grep,Edit,Write` for work/repair.

Both providers must return a structured report echoing the request's `candidate_id` unchanged: work/repair use `decision: completed|blocked` plus `summary`; review uses `decision: pass|rework|human` plus `findings`. The router prints `agent-start`, `capacity-retry` and `capacity-fallback` events to stderr and the final report JSON to stdout.

## Defaults (REC-1)

`prepare_recovery.py` writes `policy.json` outside the repository with `codex_attempts: 2`, `backoff_seconds: 2`, `attempt_timeout: 900`, `total_timeout: 2400` and the explicit `write_paths`. The attempt sequence is therefore Codex, Codex, Claude. Between Codex capacity failures the router waits `backoff_seconds * 2^(n-1)` (2 s after the first failure); the switch to Claude is immediate. Each attempt is capped at `min(attempt_timeout, remaining total budget)`, and a retry that cannot fit in the remaining total budget is refused. The router validates policy bounds before starting: attempts 1..3, backoff 0..30 s, attempt timeout 1..900 s, and attempt ≤ total ≤ 3000 s.

## Exact prepare and run commands

Run everything from the repository root; plan, state and policy must live outside the repository, and `prepare_recovery.py` creates its files exclusively, so use a fresh directory per preparation.

```sh
# normal Codex-first execution
python3 scripts/workflow/prepare_recovery.py /private/tmp/excalidraw-agent-recovery-20261124

# labelled capacity injection used by this pilot (see below)
python3 scripts/workflow/prepare_recovery.py /private/tmp/excalidraw-agent-recovery-20261124 --inject-capacity

python3 scripts/workflow/loop.py init --plan /private/tmp/excalidraw-agent-recovery-20261124/plan.json --state /private/tmp/excalidraw-agent-recovery-20261124/state
python3 scripts/workflow/loop.py run --plan /private/tmp/excalidraw-agent-recovery-20261124/plan.json --state /private/tmp/excalidraw-agent-recovery-20261124/state
python3 scripts/workflow/loop.py gate --plan /private/tmp/excalidraw-agent-recovery-20261124/plan.json --state /private/tmp/excalidraw-agent-recovery-20261124/state
```

Preconditions: a clean tree at the candidate HEAD, one runner per repository (a `flock` in the Git common dir), and spec files tracked in Git. Exit codes: `0` ready (configured checks only), `1` rework, `2` environment-error, `3` awaiting-human. Exit 3 is a handoff, never approval or permission to merge. The generated plan runs: `document-recovery` (work) → `recovery-tests` (the workflow unit suite) and `production-browser` → `publish` → `github-ci` (`github_gate.py` against PR 14 with the required checks recorded in `plan.json`) → `review` → `product` (human). `refresh`, `decide` and `reconcile` handle candidate changes, recorded human decisions and unknown-outcome retries.

## Capacity-only fallback

Capacity is recognized only from provider error envelopes, never from ordinary output:

- JSON events `type: error` or `turn.failed` (their message), and `result` events with `is_error: true` (their `errors`/`result`).
- Codex stderr transport diagnostics that match `WARN codex_core::responses_retry:` and the capacity pattern.

The pattern is `(selected model is at capacity|model.{0,40}(?:overloaded|at capacity)|overloaded_error)`, case-insensitive. Capacity text quoted inside assistant or tool output is deliberately ignored (`test_quoted_capacity_in_agent_content_is_not_service_failure`). Every other outcome is a terminal environment error with no retry or switch: nonzero exit (auth/permission and the like), launch error, attempt timeout (`test_timeout_is_not_assumed_capacity`), protocol error from an overlong line, incomplete output drain, missing provider session, wrong `candidate_id`, invalid report, or a Claude error result. Capacity on the final Claude attempt is terminal: all configured providers exhausted (`test_fallback_capacity_exhaustion_stops`). A successful Codex retry never reaches Claude (`test_second_codex_attempt_succeeds_without_fallback`), and review decisions are results, not failures (`test_review_rework_is_not_capacity_retry`).

## Scope, commits and partial-effect reconciliation (REC-3)

- The router starts only from a clean tree at the candidate HEAD, with policy and instructions outside the repository, and `write_paths` inside the repository, outside `.git` and never covering spec files; work/repair require them.
- Snapshots taken before and after each attempt record HEAD, porcelain status, a binary diff digest and untracked file digests.
- On a capacity outcome, retry or switch happens only when the snapshot is unchanged and, in work/repair, no tool action was observed. Observed actions include `command_execution`, `file_change`, `mcp_tool_call`, `web_search` and `tool_use` items plus `tool_use`/`tool_result` message content. Otherwise the router stops with a reconcile error; partial edits stay on disk and are never discarded (`test_dirty_work_preserved_and_no_fallback`, `test_partial_work_blocks_switch_even_if_git_stays_clean`).
- Streams are drained after provider termination before the replay decision, so a backlogged tool event cannot be missed (`test_capacity_drains_backlogged_tool_event_before_switch`).
- On work/repair success, the report decision must be `completed`, the provider must not have committed (HEAD unchanged) or staged anything, and the union of modified and untracked files must be a subset of `write_paths`. The router then commits exactly those files as `chore: apply authorized Agent workflow step` and records the new HEAD in the report. Out-of-scope edits and staged content block the commit and are preserved (`test_out_of_scope_edits_not_committed_or_discarded`, `test_staged_out_of_scope_change_is_not_committed`).
- Review is read-only: a Codex `read-only` sandbox, Claude restricted to `Read,Glob,Grep`, any mutation or contract violation (including pass with findings) fails, and review never substitutes for the human product step.
- Cancellation (SIGTERM/SIGINT) terminates the provider process group — TERM, a short drain, then KILL, covering descendants the CLI spawned — and never switches providers; effects are left for reconciliation.
- `write_paths` is a commit constraint, not a filesystem sandbox: ignored files and external effects cannot be proven absent from Git alone.

## Journal and receipt binding (REC-2)

Each request gets `runs/<run_id>/agents/journal.json`: schema, `run_id`, `candidate_id`, a fingerprint digest of the policy, instructions and request bytes, the `fault_injection` label, and one entry per attempt with provider, resolved executable path and its sha256, status/reason, returncode, timestamps and stdout/stderr digests. Raw per-attempt material lives in `runs/<run_id>/agents/NN-<provider>/` (`prompt.txt`, `stdout.log`, `stderr.log`, `result.json`). The previous provider is fully stopped before the next starts, so a CLI that exits before its descendants still leaves nothing running. An existing journal refuses to start another operation, so an interrupted or reused journal cannot silently replay provider actions (`test_same_request_cannot_replay_provider_actions`).

The runner's worker writes `runs/<run_id>/result.json` binding the run id, returncode and timeout flag, the stdout/stderr paths with sha256 digests, and a sha256 digest of every file under `agents/`. `finish()`, `verify_evidence()` and `gate` re-hash these receipts; changed or missing evidence fails the gate (`test_provider_attachment_tampering_invalidates_receipt`). A missing `result.json` while a step is running yields awaiting-human and requires `loop.py reconcile` with an explicit retry decision bound to actor and run id after inspecting external state. Adapter scripts outside the repository are hashed into the plan; any later change invalidates the state.

## Injection versus real evidence (REC-4)

`--inject-capacity` replaces the Codex executable with `scripts/workflow/tests/capacity_fixture.py`, which only prints a visibly labelled error object (`fault_injection: capacity-fixture; no model call`) and sleeps. It performs no work and cannot produce a successful report, so success can only come from a real provider CLI. Both the policy and the journal carry the `fault_injection` label, and each attempt records its executable path and sha256, keeping injected attempts distinguishable from real service capacity.

Real evidence in this pilot is: the router's commit on this repository, the runner's separate check steps (workflow unit suite, production browser check, `github_gate.py` on PR 14), the separate review step, and the hashed receipts in `state.json`. Fixture output only exercises the denial and retry wiring; it never stands in for actual work, CI or review. In the run producing this document (`run_id 8b917ded617848d8959a514c304c2b37`), the journal records `01-codex` and `02-codex` against the labelled fixture with no observed actions, and `03-claude` against the installed Claude CLI that wrote this file. Downstream steps had produced no receipts when this file was written; `state.json` is the authoritative record, and no live test result may be claimed without its actual receipt.

## Limits

Single-host cooperative executor; not an identity or security boundary, and never an approval authority: no push, merge, release or product acceptance happens here. Failure evidence is preserved — attempt directories and journals of failed runs remain on disk, state history keeps failures, and refresh archives prior state without resetting the repair budget. Both providers unavailable, or any non-capacity failure, returns environment error without approving anything. Human product acceptance remains the final step.
