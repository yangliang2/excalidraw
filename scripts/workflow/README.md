# Local workflow runner

Imported from solution-hub workflow-kit material commit 8dc4e8539289293b5166592cf62f0609f4d430af. Standard-library Python CLI; local Codex performs work and separate read-only review; GitHub Actions performs CI. No self-hosted runner or Copilot is required.

Plan and state must live outside the candidate repository. Run `python3 scripts/workflow/loop.py --help`. Candidate changes invalidate prior check/review/human evidence. Exit 3 waits for real product acceptance; it is not approval or permission to merge. This is a single-host cooperative executor, not an identity or security boundary.

## Capacity recovery

New plans use agent_router.py for work, repair and independent review. prepare_rtl.py now routes its review through Codex first, then Claude only after explicit capacity errors. prepare_recovery.py generates a complete real-fork trial with an allowed documentation work step, recovery tests, production browser checks, GitHub publication/checks, independent review and product handoff. `--inject-capacity` is a visibly labelled test option: the primary fixture emits errors only; the installed Claude CLI must actually perform the work/review. Omit it for normal Codex-first execution.

Policy and instructions live outside the candidate and are fingerprinted by the runner. Defaults are two Codex attempts with bounded backoff, then one Claude attempt. Total/attempt deadlines apply. Auth, permissions, generic timeout, invalid reports and code failures do not use capacity fallback. A work/repair tool action or changed Git state before capacity failure stops for reconciliation. Existing changes are never discarded. Work/repair require exact `write_paths`; the router commits only those changes after a successful structured result. This allowlist is a commit constraint, not a filesystem security sandbox; ignored files and external effects cannot be proven absent from Git alone.

Each request has an exclusive attempt journal and raw provider logs under `runs/<run_id>/agents/`; worker receipts hash these attachments and gate checks reject later tampering. Cancellation terminates the provider process group; hard-killing the orchestrator may leave an unknown outcome, so an existing journal is not replayed. Both providers unavailable or a non-capacity failure returns environment error without approving anything.
