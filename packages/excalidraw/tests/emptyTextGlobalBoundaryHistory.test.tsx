import { MIME_TYPES } from "@excalidraw/common";

import { actionChangeViewBackgroundColor } from "../actions/actionCanvas";
import { serializeAsJSON } from "../data/json";
import { Excalidraw } from "../index";

import { API } from "./helpers/api";
import { Keyboard, Pointer, UI } from "./helpers/ui";
import { getTextEditor } from "./queries/dom";
import { act, fireEvent, GlobalTestState, render, waitFor } from "./test-utils";

import type { ExcalidrawProps } from "../types";

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

it.each([false, true])(
  "review probe: replacing scene retains undo, nonempty=%s",
  async (nonempty) => {
    await render(<Excalidraw handleKeyboardGlobally />);
    const container = UI.createElement("rectangle", {
      x: 200,
      y: 200,
      width: 10,
      height: 10,
    });
    mouse.doubleClickAt(205, 205);
    const editor = await getTextEditor();
    if (nonempty) {
      const { updateTextEditor } = await import("./queries/dom");
      updateTextEditor(editor, "Draft label");
    }
    const labelId = h.state.editingTextElement!.id;
    const originalBackground = h.state.viewBackgroundColor;
    drag(GlobalTestState.interactiveCanvas, "drop", {
      files: [sceneFile()],
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
    Keyboard.undo();
    expect(
      h.app.scene.getNonDeletedElements().find((el) => el.id === container.id),
    ).toMatchObject({ width: 10, height: 10 });
    expect(
      h.app.scene
        .getNonDeletedElements()
        .some((el) => el.type === "ellipse" || el.id === labelId),
    ).toBe(false);
    expect(h.state.viewBackgroundColor).toBe(originalBackground);
    Keyboard.redo();
    expect(h.app.scene.getNonDeletedElements().map((el) => el.type)).toEqual([
      "ellipse",
    ]);
    expect(h.state.viewBackgroundColor).toBe("#ff0000");
  },
);
it.each([
  [false, false],
  [false, true],
  [true, false],
  [true, true],
])(
  "review probe: veto preserves draft empty=%s array=%s",
  async (empty, array) => {
    const veto = vi.fn(() => (array ? [] : (false as const)));
    await render(<Excalidraw handleKeyboardGlobally onDuplicate={veto} />);
    UI.createElement("rectangle", { x: 200, y: 200, width: 10, height: 10 });
    mouse.doubleClickAt(205, 205);
    const editor = await getTextEditor();
    if (!empty) {
      const { updateTextEditor } = await import("./queries/dom");
      updateTextEditor(editor, "Draft label");
    }
    const labelId = h.state.editingTextElement!.id;
    const historyLength = h.history.undoStack.length;
    drag(GlobalTestState.interactiveCanvas, "drop", {
      files: [sceneFile()],
      shiftKey: true,
      clientX: 350,
      clientY: 350,
    });
    await waitFor(() => expect(veto).toHaveBeenCalledTimes(1));
    expect(editor.isConnected).toBe(true);
    expect(h.state.editingTextElement?.id).toBe(labelId);
    expect(editor.value).toBe(empty ? "" : "Draft label");
    expect(h.history.undoStack.length).toBe(historyLength);
    expect(
      h.app.scene.getNonDeletedElements().some((el) => el.type === "ellipse"),
    ).toBe(false);
  },
);

it.each([false, true])(
  "preserves host-added arrow binding with nonempty label %s",
  async (nonempty) => {
    let rectId = "";
    let arrowId = "";
    const onDuplicate: NonNullable<ExcalidrawProps["onDuplicate"]> = (next) => {
      const arrow = next.find((el) => el.type === "arrow")!;
      arrowId = arrow.id;
      const target = next.find((el) => el.id === rectId);
      return next.map((el) =>
        el === arrow
          ? {
              ...el,
              endBinding: {
                elementId: rectId,
                mode: "inside",
                fixedPoint: [0.5, 0.8],
              },
            }
          : el === target
          ? {
              ...el,
              boundElements: [
                ...(el.boundElements ?? []),
                { id: arrowId, type: "arrow" },
              ],
            }
          : el,
      );
    };
    await render(
      <Excalidraw handleKeyboardGlobally onDuplicate={onDuplicate} />,
    );
    const container = UI.createElement("rectangle", {
      x: 200,
      y: 200,
      width: 10,
      height: 10,
    });
    rectId = container.id;
    mouse.doubleClickAt(205, 205);
    const editor = await getTextEditor();
    const { updateTextEditor } = await import("./queries/dom");
    if (nonempty) {
      updateTextEditor(editor, "Draft label");
    }
    const labelId = h.state.editingTextElement!.id;
    const file = new h.app.ownerWindow.File(
      [
        serializeAsJSON(
          [API.createElement({ type: "arrow", x: 350, y: 350 })],
          h.state,
          {},
          "local",
        ),
      ],
      "scene.excalidraw",
      { type: MIME_TYPES.json },
    );
    drag(GlobalTestState.interactiveCanvas, "drop", {
      files: [file],
      shiftKey: true,
      clientX: 350,
      clientY: 350,
    });
    await waitFor(() =>
      expect(
        h.app.scene.getNonDeletedElements().some((el) => el.type === "arrow"),
      ).toBe(true),
    );
    if (editor.isConnected) {
      Keyboard.exitTextEditor(editor);
    }
    const arrow = h.app.scene.getNonDeletedElement(arrowId);
    const rect = h.app.scene.getNonDeletedElement(rectId)!;
    if (!arrow || arrow.type !== "arrow") {
      throw new Error("Inserted arrow missing");
    }
    expect(arrow.endBinding?.elementId).toBe(rectId);
    expect(rect.boundElements?.some((el) => el.id === labelId) ?? false).toBe(
      nonempty,
    );
    expect(rect.boundElements).toContainEqual({ id: arrowId, type: "arrow" });
  },
);

it("review probe: background undo preserves a batched NEVER update", async () => {
  const { CaptureUpdateAction } = await import("@excalidraw/element");
  await render(<Excalidraw handleKeyboardGlobally />);
  const oldBackground = h.state.viewBackgroundColor;
  UI.createElement("rectangle", { x: 200, y: 200, width: 10, height: 10 });
  mouse.doubleClickAt(205, 205);
  const editor = await getTextEditor();
  act(() => {
    h.app.actionManager.executeAction(actionChangeViewBackgroundColor, "api", {
      viewBackgroundColor: "#ff0000",
    });
    h.app.updateScene({
      appState: { name: "Remote rename" },
      captureUpdate: CaptureUpdateAction.NEVER,
    });
  });
  expect(h.state.name).toBe("Remote rename");
  expect(h.state.viewBackgroundColor).toBe("#ff0000");
  if (editor.isConnected) {
    Keyboard.exitTextEditor(editor);
  }
  for (let i = 0; i < 3 && h.state.viewBackgroundColor === "#ff0000"; i++) {
    Keyboard.undo();
  }
  expect(h.state.viewBackgroundColor).toBe(oldBackground);
  expect(h.state.name).toBe("Remote rename");
});
