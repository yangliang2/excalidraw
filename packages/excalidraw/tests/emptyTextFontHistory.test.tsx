import { KEYS } from "@excalidraw/common";

import { Excalidraw } from "../index";

import { Keyboard, Pointer, UI } from "./helpers/ui";
import { getTextEditor } from "./queries/dom";
import { fireEvent, render } from "./test-utils";

const { h } = window;
const mouse = new Pointer("mouse");
it.each([KEYS.CHEVRON_LEFT, KEYS.CHEVRON_RIGHT])(
  "keeps empty text cleanup and geometry coherent after font shortcut %s",
  async (key) => {
    await render(<Excalidraw handleKeyboardGlobally={true} />);
    const container = UI.createElement("rectangle", {
      x: 200,
      y: 200,
      width: 10,
      height: 10,
    });
    mouse.doubleClickAt(205, 205);
    const editor = await getTextEditor();
    fireEvent.keyDown(editor, { key, ctrlKey: true, shiftKey: true });
    Keyboard.exitTextEditor(editor);
    const liveContainer = () =>
      h.elements.find((el) => el.id === container.id && !el.isDeleted)!;
    const resized = {
      width: liveContainer().width,
      height: liveContainer().height,
    };
    expect(resized).not.toEqual({ width: 10, height: 10 });
    const expectClean = () => {
      expect(
        h.elements.filter((el) => el.type === "text" && !el.isDeleted),
      ).toHaveLength(0);
      expect(liveContainer().boundElements ?? []).toEqual([]);
    };
    expectClean();
    for (let i = 0; i < 2; i++) {
      Keyboard.undo();
      expect(liveContainer()).toMatchObject({ width: 10, height: 10 });
      expectClean();
      Keyboard.redo();
      expect(liveContainer()).toMatchObject(resized);
      expectClean();
    }
  },
);
