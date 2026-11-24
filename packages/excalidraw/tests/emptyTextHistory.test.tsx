import { KEYS } from "@excalidraw/common";

import { Excalidraw } from "../index";

import { Keyboard, Pointer, UI } from "./helpers/ui";
import { getTextEditor, updateTextEditor } from "./queries/dom";
import { render } from "./test-utils";

const { h } = window;
const mouse = new Pointer("mouse");
const shapes = ["rectangle", "ellipse", "diamond"] as const;

const live = (id: string) =>
  h.elements.find((element) => element.id === id && !element.isDeleted);
const geometry = (element: {
  x: number;
  y: number;
  width: number;
  height: number;
}) => ({
  x: element.x,
  y: element.y,
  width: element.width,
  height: element.height,
});

beforeEach(async () => {
  await render(<Excalidraw handleKeyboardGlobally={true} />);
});

describe.each(shapes)("empty text history: %s", (type) => {
  it.each(["double-click", "Enter"])(
    "restores resize using undo/redo after %s",
    async (entry) => {
      const container = UI.createElement(type, {
        x: 200,
        y: 200,
        width: 10,
        height: 10,
      });
      const original = geometry(container);
      if (entry === "Enter") {
        Keyboard.keyPress(KEYS.ENTER);
      } else {
        mouse.doubleClickAt(205, 205);
      }
      const editor = await getTextEditor();
      Keyboard.exitTextEditor(editor);
      const resized = geometry(live(container.id)!);
      expect(resized).not.toEqual(original);
      expect(
        h.elements.filter((el) => !el.isDeleted && el.type === "text"),
      ).toHaveLength(0);
      Keyboard.undo();
      expect(live(container.id)).toMatchObject(original);
      Keyboard.redo();
      expect(live(container.id)).toMatchObject(resized);
      expect(live(container.id)!.boundElements ?? []).toEqual([]);
      expect(
        h.elements.filter((el) => !el.isDeleted && el.type === "text"),
      ).toHaveLength(0);
    },
  );

  it("keeps nonempty bound text and geometry in one undoable edit", async () => {
    const container = UI.createElement(type, {
      x: 200,
      y: 200,
      width: 10,
      height: 10,
    });
    const original = geometry(container);
    mouse.doubleClickAt(205, 205);
    const editor = await getTextEditor();
    updateTextEditor(editor, "Order approved");
    Keyboard.exitTextEditor(editor);
    const text = h.elements.find((el) => !el.isDeleted && el.type === "text")!;
    expect(text).toMatchObject({
      text: "Order approved",
      containerId: container.id,
    });
    const resized = geometry(live(container.id)!);
    Keyboard.undo();
    expect(live(container.id)).toMatchObject(original);
    expect(live(text.id)).toBeUndefined();
    Keyboard.redo();
    expect(live(container.id)).toMatchObject(resized);
    expect(live(text.id)).toMatchObject({
      text: "Order approved",
      containerId: container.id,
    });
    expect(live(container.id)!.boundElements).toContainEqual({
      id: text.id,
      type: "text",
    });
  });
});

it("does not create a resize undo entry for an unchanged large rectangle", async () => {
  const container = UI.createElement("rectangle", {
    x: 200,
    y: 200,
    width: 200,
    height: 200,
  });
  const original = geometry(container);
  mouse.doubleClickAt(300, 300);
  Keyboard.exitTextEditor(await getTextEditor());
  expect(live(container.id)).toMatchObject(original);
  Keyboard.undo();
  expect(live(container.id)).toBeUndefined();
});
