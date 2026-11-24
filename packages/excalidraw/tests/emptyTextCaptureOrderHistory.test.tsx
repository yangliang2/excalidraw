import { CaptureUpdateAction } from "@excalidraw/element";

import { actionChangeViewBackgroundColor } from "../actions/actionCanvas";
import { Excalidraw } from "../index";

import { Keyboard, Pointer, UI } from "./helpers/ui";
import { getTextEditor } from "./queries/dom";
import { act, render } from "./test-utils";

const { h } = window;
const red = "#ff0000";
const blue = "#0000ff";
const green = "#00ff00";

it.each([
  {
    name: "never then immediate",
    updates: [
      ["never", red],
      ["immediate", blue],
    ],
    final: blue,
    undo: red,
  },
  {
    name: "immediate then never",
    updates: [
      ["immediate", red],
      ["never", blue],
    ],
    final: blue,
    undo: blue,
  },
  {
    name: "immediate, never, immediate",
    updates: [
      ["immediate", red],
      ["never", blue],
      ["immediate", green],
    ],
    final: green,
    undo: blue,
  },
  {
    name: "never then two immediate edits",
    updates: [
      ["never", red],
      ["immediate", blue],
      ["immediate", green],
    ],
    final: green,
    undo: red,
  },
  {
    name: "two never boundaries ending in never",
    updates: [
      ["immediate", red],
      ["never", blue],
      ["immediate", red],
      ["never", green],
    ],
    final: green,
    undo: green,
  },
])(
  "preserves same-field history order: $name",
  async ({ updates, final, undo }) => {
    await render(<Excalidraw handleKeyboardGlobally />);
    UI.createElement("rectangle", { x: 200, y: 200, width: 10, height: 10 });
    new Pointer("mouse").doubleClickAt(205, 205);
    const editor = await getTextEditor();
    act(() => {
      for (const [kind, color] of updates) {
        if (kind === "never") {
          h.app.updateScene({
            appState: { viewBackgroundColor: color },
            captureUpdate: CaptureUpdateAction.NEVER,
          });
        } else {
          h.app.actionManager.executeAction(
            actionChangeViewBackgroundColor,
            "api",
            { viewBackgroundColor: color },
          );
        }
      }
    });
    expect(h.state.viewBackgroundColor).toBe(final);
    if (editor.isConnected) {
      Keyboard.exitTextEditor(editor);
    }
    const colors = [h.state.viewBackgroundColor];
    for (let i = 0; i < 3; i++) {
      Keyboard.undo();
      colors.push(h.state.viewBackgroundColor);
    }
    expect(colors.slice(1)).toContain(undo);
    expect(colors.every((color) => color === final || color === undo)).toBe(
      true,
    );
  },
);
