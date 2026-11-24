import { MIME_TYPES } from "@excalidraw/common";

import { actionChangeViewBackgroundColor } from "../actions/actionCanvas";
import { serializeAsJSON } from "../data/json";
import { Excalidraw } from "../index";

import { API } from "./helpers/api";
import { Keyboard, Pointer, UI } from "./helpers/ui";
import { getTextEditor } from "./queries/dom";
import { act, fireEvent, GlobalTestState, render, waitFor } from "./test-utils";

const { h } = window;

// jsdom has no DragEvent constructor. MouseEvent supplies the coordinates and
// modifier keys, and the data store models files being protected until drop.
const drag = (
  target: Element,
  type: string,
  {
    files = [],
    types = ["Files"],
    ...init
  }: MouseEventInit & { files?: File[]; types?: string[] } = {},
) => {
  const event = new target.ownerDocument.defaultView!.MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: 200,
    clientY: 200,
    ...init,
  });
  Object.defineProperty(event, "dataTransfer", {
    value: {
      dropEffect: "none",
      types,
      files: type === "drop" ? files : [],
      items: files.map((file) => ({
        kind: "file",
        type: file.type,
        getAsFile: () => (type === "drop" ? file : null),
      })),
    },
  });
  fireEvent(target, event);
};

const sceneFile = () =>
  new h.app.ownerWindow.File(
    [
      serializeAsJSON(
        [API.createElement({ type: "ellipse", id: "existing" })],
        { ...h.state, viewBackgroundColor: "#ff0000" },
        {},
        "local",
      ),
    ],
    "scene.excalidraw",
    { type: MIME_TYPES.json },
  );

const mouse = new Pointer("mouse");
it("keeps a new empty label out of history when Shift-dropping a scene", async () => {
  await render(<Excalidraw handleKeyboardGlobally />);
  const container = UI.createElement("rectangle", {
    x: 200,
    y: 200,
    width: 10,
    height: 10,
  });
  mouse.doubleClickAt(205, 205);
  const editor = await getTextEditor();
  const labelId = h.state.editingTextElement!.id;
  drag(GlobalTestState.interactiveCanvas, "drop", {
    files: [sceneFile()],
    shiftKey: true,
    clientX: 350,
    clientY: 350,
  });
  await waitFor(() =>
    expect(
      h.app.scene.getNonDeletedElements().some((el) => el.type === "ellipse"),
    ).toBe(true),
  );
  if (editor.isConnected) {
    Keyboard.exitTextEditor(editor);
  }
  const expectClean = () => {
    expect(
      h.app.scene.getNonDeletedElements().some((el) => el.id === labelId),
    ).toBe(false);
    const live = h.elements.find(
      (el) => el.id === container.id && !el.isDeleted,
    );
    expect(live).toBeDefined();
    expect(live!.boundElements ?? []).toEqual([]);
  };
  expectClean();
  Keyboard.undo();
  expectClean();
  expect(
    h.app.scene.getNonDeletedElements().some((el) => el.type === "ellipse"),
  ).toBe(false);
  Keyboard.redo();
  expect(
    h.app.scene.getNonDeletedElements().some((el) => el.type === "ellipse"),
  ).toBe(true);
  expectClean();
});
it("keeps a same-batch background reversal out of label resize history", async () => {
  await render(<Excalidraw handleKeyboardGlobally />);
  const original = h.state.viewBackgroundColor;
  const container = UI.createElement("rectangle", {
    x: 200,
    y: 200,
    width: 10,
    height: 10,
  });
  mouse.doubleClickAt(205, 205);
  const editor = await getTextEditor();
  act(() => {
    h.app.actionManager.executeAction(actionChangeViewBackgroundColor, "api", {
      viewBackgroundColor: "#ff0000",
    });
    h.app.actionManager.executeAction(actionChangeViewBackgroundColor, "api", {
      viewBackgroundColor: original,
    });
  });
  expect(h.state.viewBackgroundColor).toBe(original);
  Keyboard.exitTextEditor(editor);
  const resized = h.elements.find(
    (el) => el.id === container.id && !el.isDeleted,
  )!;
  const geometry = { width: resized.width, height: resized.height };
  const expectClean = () =>
    expect(
      h.elements.filter((el) => el.type === "text" && !el.isDeleted),
    ).toHaveLength(0);
  Keyboard.undo();
  expect(
    h.elements.find((el) => el.id === container.id && !el.isDeleted),
  ).toMatchObject({ width: 10, height: 10 });
  expect(h.state.viewBackgroundColor).toBe(original);
  expectClean();
  Keyboard.redo();
  expect(
    h.elements.find((el) => el.id === container.id && !el.isDeleted),
  ).toMatchObject(geometry);
  expect(h.state.viewBackgroundColor).toBe(original);
  expectClean();
});
