# Real GitHub workflow validation scope

Keep Issue #13 acceptance in verification.md unchanged. This run closes verification gaps for PR #14, without merging master.

- AC-RTL: English, Arabic and Hebrew preserve minimum, bubble, fill and keyboard/pointer behavior. Avoid reliance on :dir() where the supported browser range lacks it, using the existing app RTL convention.
- AC-SCENE: Browser checks verify rectangle scene opacity actually changes after slider operations, persists on reload and survives undo/redo; a slider-value assertion alone is insufficient. Exercise a production build, not just Vite development server.
- AC-CI: GitHub runs the strengthened behavior check and includes shipped CSS in size measurement. Retain existing JS budgets; CSS comparison must expose a baseline and explicit small-change tolerance.
- AC-HANDOFF: Run the local workflow against this real repository; retain candidate-bound checks and independent review, push the existing PR branch, verify its actual CI. Product acceptance and developer merge remain human.

Latest Chromium is the automated browser target in this bounded run. Do not claim historical browser, Firefox or Safari runtime coverage. Avoid changing replay PR #12.
