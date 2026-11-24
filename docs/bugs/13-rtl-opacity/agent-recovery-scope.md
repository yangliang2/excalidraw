# Local Agent capacity recovery: pilot acceptance

User request: make capacity retry and Agent switching part of the workflow, then verify them on this GitHub fork without merging master.

- REC-1: Only explicit provider capacity errors permit bounded retry and fallback. Default Codex attempts: two, with bounded exponential backoff; then one Claude attempt. Auth, permission, malformed output, generic timeout and product/test failures do not trigger capacity recovery.
- REC-2: Preserve each attempt, provider, candidate, process outcome, raw logs and checksums. Stop the previous provider before switching. Cancellation stops downstream work. A reused or interrupted attempt journal cannot silently replay an operation.
- REC-3: In work/repair mode, any observed tool action or Git change before capacity failure blocks automatic retry/switch for reconciliation. Successful work may commit only explicit allowed files; specifications remain immutable. Review remains read-only and never substitutes for product acceptance.
- REC-4: Validate both denial paths and successful retry/fallback in CI. On the real fork, clearly labelled capacity injection must lead to a real installed Claude Agent doing bounded work, a real commit, GitHub checks and a separate independent review; fixture output cannot stand in for actual work or review. Preserve old failure evidence and stop at human product acceptance.

The real work task is to create docs/bugs/13-rtl-opacity/agent-recovery.md from the implemented runtime and its tests, documenting usage, retry boundaries, evidence and limits. It may edit only that file. Existing RTL product acceptance is unchanged. No release, merge or automatic product approval is authorized.
