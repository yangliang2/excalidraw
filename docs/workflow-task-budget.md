# Requirement-level repair budget

New plans set a stable `task_id` (for example `owner/repository#123`) plus `budget.assess` and `budget.design` commands. These call `scripts/workflow/agent_router.py assess|design` with a policy and instructions outside the candidate checkout. Both modes are read-only and include the full diff for Codex and Claude. Existing plans without task_id retain legacy max_repairs behavior until migrated.

Policy:

- Five repair rounds per requirement. The Git common-directory ledger persists across plans, state directories and worktrees. Initial implementation may execute once; continuations omit that work step. Explicitly idempotent publishing remains replayable.
- A read-only assessment binds every failed receipt and tracks stable blocker IDs, families, severity and scope. Two consecutive repair rounds in the same family trigger a read-only design review; its implementation/verification plan is supplied to the next repair.
- A single additional block of three repairs is allowed only when the last two complete check/review rounds show a strict subset of blocker IDs, no increased severity, and unchanged scope/specification. Repeating a check without another repair is not progress. Eight is the total automatic ceiling.
- Safe environment checks opt in with `retry_safe: true`; exit2 plus JSON `{"retryable":true}` allows at most three retries for the same task/candidate/check, using2/4/8second backoff. Non-object JSON, unknown errors and potentially effectful work are not blindly retried. Manual retry shares the counter. Provider capacity recovery remains a separate policy.
- `human` or uncertain scope creates a durable task-level hold. New plans/candidates cannot waive it. Actual human resolution is registered via `budget-decide`; it does not replenish repairs or approve the product gate.

```sh
python3 scripts/workflow/loop.py init --plan /outside/plan.json --state /outside/state
python3 scripts/workflow/loop.py run --plan /outside/plan.json --state /outside/state
python3 scripts/workflow/loop.py budget-decide --plan /outside/plan.json --state /outside/state --actor ACTUAL_ACTOR --decision accept --source /outside/actual-decision.json
```

Decision source fields: actor, decision, task_id, hold_run_id, current candidate_id, source_ref, resolution. Record an actual decision; agents do not fabricate approvals. Source bytes are hashed and rechecked. CLI actor fields do not authenticate a person.

For existing tasks, initialize an unused task ledger and run `budget-import --source /outside/import.json`. The source names task_id and old state.json paths in states; optional spec_files selects unchanged confirmed specification anchors. Import counts repair requests, including interrupted attempts, deduplicates run IDs and retains source digests. Ordinary work that was actually an undocumented repair needs explicit historical reconciliation; import cannot infer its intent. Never discard old history to obtain fresh quota.

Each worker receives ARTIFACT_DIR and WORKFLOW_ARTIFACT_DIR pointing to its own runs/<id>/artifacts. Write screenshots, scene JSON and server logs there; receipts bind their hashes. Adapters must honor this directory. Interrupted or unclassified effects remain a reconciliation boundary.

The ledger is single-host cooperative state in the Git common directory, not a security or multi-machine quota service. Fresh clones must migrate the ledger and evidence. Semantic blocker identity and design quality still depend on the evaluating Agent. This workflow does not merge or provide product approval.

The prior editor PR remains a separate blocked product trial. Its17 imported repair reservations are retained; this policy is not a new grant of5attempts to that task.
