import { FONT_FAMILY } from "@excalidraw/common";

import {
  actionChangeFontFamily,
  actionChangeOpacity,
  actionChangeStrokeColor,
  actionChangeTextAlign,
  actionChangeVerticalAlign,
} from "../actions/actionProperties";
import { Excalidraw } from "../index";

import { Keyboard, Pointer, UI } from "./helpers/ui";
import { getTextEditor, updateTextEditor } from "./queries/dom";
import { act, render } from "./test-utils";

const { h } = window;
const mouse = new Pointer("mouse");
const cases = [
  {
    name: "font family",
    apply: () =>
      h.app.actionManager.executeAction(actionChangeFontFamily, "api", {
        currentItemFontFamily: FONT_FAMILY.Helvetica,
        currentHoveredFontFamily: null,
      }),
    expected: { fontFamily: FONT_FAMILY.Helvetica },
  },
  {
    name: "horizontal alignment",
    apply: () =>
      h.app.actionManager.executeAction(actionChangeTextAlign, "api", "right"),
    expected: { textAlign: "right" },
  },
  {
    name: "vertical alignment",
    apply: () =>
      h.app.actionManager.executeAction(
        actionChangeVerticalAlign,
        "api",
        "bottom",
      ),
    expected: { verticalAlign: "bottom" },
  },
  {
    name: "text color",
    apply: () =>
      h.app.actionManager.executeAction(actionChangeStrokeColor, "api", {
        color: "#e03131",
      }),
    expected: { strokeColor: "#e03131" },
  },
  {
    name: "opacity",
    apply: () =>
      h.app.actionManager.executeAction(actionChangeOpacity, "api", 50),
    expected: { opacity: 50 },
  },
];

describe.each(cases)(
  "new bound text property history: $name",
  ({ apply, expected }) => {
    it.each(["", "Order approved"])(
      "keeps %j geometry and bindings coherent across undo/redo",
      async (input) => {
        await render(<Excalidraw handleKeyboardGlobally={true} />);
        const container = UI.createElement("rectangle", {
          x: 200,
          y: 200,
          width: 10,
          height: 10,
        });
        mouse.doubleClickAt(205, 205);
        const editor = await getTextEditor();
        if (input) {
          updateTextEditor(editor, input);
        }
        act(() => {
          apply();
        });
        expect(h.state.editingTextElement).not.toBeNull();
        expect(
          h.elements.find((el) => el.type === "text" && !el.isDeleted),
        ).toMatchObject(expected);
        Keyboard.exitTextEditor(editor);
        const liveContainer = () =>
          h.elements.find((el) => el.id === container.id && !el.isDeleted)!;
        const liveTexts = () =>
          h.elements.filter((el) => el.type === "text" && !el.isDeleted);
        const resized = {
          width: liveContainer().width,
          height: liveContainer().height,
        };
        expect(resized).not.toEqual({ width: 10, height: 10 });
        const expectSubmitted = () => {
          expect(liveContainer()).toMatchObject(resized);
          expect(liveTexts()).toHaveLength(input ? 1 : 0);
          if (input) {
            expect(liveTexts()[0]).toMatchObject({
              ...expected,
              originalText: input,
              containerId: container.id,
            });
            expect(liveContainer().boundElements).toContainEqual({
              id: liveTexts()[0].id,
              type: "text",
            });
          } else {
            expect(liveContainer().boundElements ?? []).toEqual([]);
          }
        };
        expectSubmitted();
        for (let i = 0; i < 2; i++) {
          Keyboard.undo();
          if (!input) {
            expect(liveContainer()).toMatchObject({ width: 10, height: 10 });
            expect(liveTexts()).toHaveLength(0);
            expect(liveContainer().boundElements ?? []).toEqual([]);
          } else {
            // Property edits during nonempty input may have their own history entry.
            for (const text of liveTexts()) {
              expect(liveContainer().boundElements).toContainEqual({
                id: text.id,
                type: "text",
              });
            }
          }
          Keyboard.redo();
          expectSubmitted();
        }
      },
    );
  },
);
