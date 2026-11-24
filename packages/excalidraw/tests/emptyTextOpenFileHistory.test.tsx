import { MIME_TYPES } from "@excalidraw/common";

import { serializeAsJSON } from "../data/json";
import { Excalidraw } from "../index";

import { API } from "./helpers/api";
import { Keyboard, Pointer, UI } from "./helpers/ui";
import { getTextEditor } from "./queries/dom";
import { fireEvent, render, waitFor } from "./test-utils";

const { h } = window;

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
it("review probe: undo Open File while an empty label is active", async () => {
  const filesystem = await import("../data/filesystem");
  const spy = vi.spyOn(filesystem, "fileOpen");
  await render(<Excalidraw handleKeyboardGlobally />);
  const container = UI.createElement("rectangle", {
    x: 200,
    y: 200,
    width: 10,
    height: 10,
  });
  mouse.doubleClickAt(205, 205);
  const editor = await getTextEditor();
  // The editor installs its capture listener on the next animation frame.
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  spy.mockResolvedValueOnce(sceneFile());
  const button = h.app.ownerDocument.querySelector<HTMLButtonElement>(
    "button.properties-trigger",
  )!;
  expect(button).toBeTruthy();
  fireEvent.pointerDown(button);
  button.focus();
  fireEvent.pointerUp(button);
  expect(editor.isConnected).toBe(true);
  fireEvent.keyDown(button, { key: "o", ctrlKey: true, metaKey: true });
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(
      h.app.scene.getNonDeletedElements().some((el) => el.type === "ellipse"),
    ).toBe(true),
  );
  Keyboard.undo();
  expect(
    h.app.scene.getNonDeletedElements().some((el) => el.id === container.id),
  ).toBe(true);
  expect(
    h.app.scene.getNonDeletedElements().some((el) => el.type === "ellipse"),
  ).toBe(false);
  spy.mockRestore();
});
