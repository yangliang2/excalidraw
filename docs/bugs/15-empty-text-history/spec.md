# Empty bound-text editing: reversible container geometry

Source: https://github.com/excalidraw/excalidraw/issues/9006 Fork issue: https://github.com/yangliang2/excalidraw/issues/15 Baseline: 983ee7e23a044c59c9252e8ffe313cc99f3083bd (idea/13-rtl-opacity).

## Reproduced behavior

Draw a 10×10 rectangle, double-click, leave the editor empty and press Escape. The rectangle becomes 20×35. Undo deletes the rectangle instead of restoring its dimensions. The actual React editor integration test reproduces this in under four seconds, with the failing assertion taking approximately 160ms.

## Acceptance

- HIST-1: After empty editing resizes a small rectangle, ellipse or diamond, one undo restores the same live container's original geometry. Redo restores the resized geometry, without a live empty text element or dangling text binding.
- HIST-2: Both double-click and Enter editing entry points obey HIST-1. An unchanged large container must not acquire a meaningless resize history entry.
- HIST-3: Nonempty bound text still commits as one coherent edit: undo restores the original container and removes the new text; redo restores the text, geometry and valid binding. Existing plain-text and arrow-label history must remain green.
- HIST-4: Existing integration tests, type/lint/format checks and matching GitHub CI pass; a fresh read-only Agent reviews the final candidate. Leave product acceptance and merge to a human.

## Execution experiment

The first work step delivers a minimal rectangle-path fix; the independent acceptance command covers the full matrix from the start. Genuine failed assertions or existing regressions must drive the runner's repair step, with the same immutable specification and no weakening of tests. This is explicitly staged implementation, not a claim that staged omissions were surprising discoveries. Do not inject code errors, synthetic failing receipts, service capacity errors or fake reviews. If the first implementation passes everything, record that honestly rather than manufacture a repair.

Agents may modify only the authorized text-editing production modules. The coordinator prepares the harness and workflow but does not supply the product fix. Preserve all actual logs, revisions, failures and coordinator interventions. The new PR targets idea/13-rtl-opacity to isolate this bug from PR14; no merge into either branch.
