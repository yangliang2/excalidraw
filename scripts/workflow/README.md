# Local workflow runner

Imported from solution-hub workflow-kit material commit 8dc4e8539289293b5166592cf62f0609f4d430af. Standard-library Python CLI; local Codex performs work and separate read-only review; GitHub Actions performs CI. No self-hosted runner or Copilot is required.

Plan and state must live outside the candidate repository. Run `python3 scripts/workflow/loop.py --help`. Candidate changes invalidate prior check/review/human evidence. Exit 3 waits for real product acceptance; it is not approval or permission to merge. This is a single-host cooperative executor, not an identity or security boundary.
