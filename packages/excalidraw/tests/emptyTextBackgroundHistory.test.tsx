import { Excalidraw } from "../index";
import { actionChangeViewBackgroundColor } from "../actions/actionCanvas";

import { Keyboard, Pointer, UI } from "./helpers/ui";
import { getTextEditor, updateTextEditor } from "./queries/dom";
import { act, render } from "./test-utils";
const { h } = window;
const mouse = new Pointer("mouse");
it.each(["", "Order approved"])(
  "background independent history for %j",
  async (input) => {
    await render(<Excalidraw handleKeyboardGlobally={true} />);
    const originalBackground = h.state.viewBackgroundColor;
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
    act(() =>
      h.app.actionManager.executeAction(
        actionChangeViewBackgroundColor,
        "api",
        { viewBackgroundColor: "#ff0000" },
      ),
    );
    expect(h.state.viewBackgroundColor).toBe("#ff0000");
    Keyboard.exitTextEditor(editor);
    const live = () =>
      h.elements.find((el) => el.id === container.id && !el.isDeleted);
    const texts = () =>
      h.elements.filter((el) => el.type === "text" && !el.isDeleted);
    const resized = { width: live()!.width, height: live()!.height };
    Keyboard.undo();
    expect(live()).toMatchObject({ width: 10, height: 10 });
    expect(texts()).toHaveLength(0);
    expect(h.state.viewBackgroundColor).toBe("#ff0000");
    Keyboard.undo();
    expect(h.state.viewBackgroundColor).toBe(originalBackground);
    expect(live()).toMatchObject({ width: 10, height: 10 });
    Keyboard.redo();
    expect(h.state.viewBackgroundColor).toBe("#ff0000");
    expect(live()).toMatchObject({ width: 10, height: 10 });
    expect(texts()).toHaveLength(0);
    Keyboard.redo();
    expect(live()).toMatchObject(resized);
    expect(texts()).toHaveLength(input ? 1 : 0);
    expect(h.state.viewBackgroundColor).toBe("#ff0000");
    if (input) {
      expect(texts()[0]).toMatchObject({
        originalText: input,
        containerId: container.id,
      });
      expect(live()!.boundElements).toContainEqual({
        id: texts()[0].id,
        type: "text",
      });
    } else {
      expect(live()!.boundElements ?? []).toEqual([]);
    }
  },
);

it("keeps background history without an empty-label entry for an unchanged large shape", async () => {
  await render(<Excalidraw handleKeyboardGlobally={true} />);
  const oldBackground = h.state.viewBackgroundColor;
  const container = UI.createElement("rectangle", {
    x: 200,
    y: 200,
    width: 200,
    height: 200,
  });
  mouse.doubleClickAt(300, 300);
  const editor = await getTextEditor();
  act(() =>
    h.app.actionManager.executeAction(actionChangeViewBackgroundColor, "api", {
      viewBackgroundColor: "#ff0000",
    }),
  );
  Keyboard.exitTextEditor(editor);
  const expectClean = () => {
    const live = h.elements.find(
      (el) => el.id === container.id && !el.isDeleted,
    );
    expect(live).toMatchObject({ width: 200, height: 200 });
    expect(live!.boundElements ?? []).toEqual([]);
    expect(
      h.elements.filter((el) => el.type === "text" && !el.isDeleted),
    ).toHaveLength(0);
  };
  expectClean();
  Keyboard.undo();
  expect(h.state.viewBackgroundColor).toBe(oldBackground);
  expectClean();
  Keyboard.redo();
  expect(h.state.viewBackgroundColor).toBe("#ff0000");
  expectClean();
});
