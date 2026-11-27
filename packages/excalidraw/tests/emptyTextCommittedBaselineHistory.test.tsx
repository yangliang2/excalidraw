import {
  CaptureUpdateAction,
  StoreIncrement,
  newElementWith,
  type CaptureUpdateActionType,
} from "@excalidraw/element";

import { actionChangeViewBackgroundColor } from "../actions/actionCanvas";
import { Excalidraw } from "../index";

import { API } from "./helpers/api";
import { Keyboard, Pointer, UI } from "./helpers/ui";
import { getTextEditor, updateTextEditor } from "./queries/dom";
import { act, render } from "./test-utils";

const { h } = window;
const red = "#ff0000";
const blue = "#0000ff";

const setBackground = (
  viewBackgroundColor: string,
  captureUpdate: CaptureUpdateActionType,
) => h.app.updateScene({ appState: { viewBackgroundColor }, captureUpdate });

const reviseElement = (
  id: string,
  captureUpdate: CaptureUpdateActionType,
  fields: {
    x?: number;
    opacity?: number;
    customData?: Record<string, unknown>;
  },
) =>
  act(() => {
    h.app.updateScene({
      elements: h.app.scene
        .getElementsIncludingDeleted()
        .map((el) => (el.id === id ? newElementWith(el, fields, true) : el)),
      captureUpdate,
    });
  });

const openEmptyLabel = async (size = 200) => {
  const originalColor = h.state.viewBackgroundColor;
  const container = UI.createElement("rectangle", {
    x: 200,
    y: 200,
    width: size,
    height: size,
  });
  new Pointer("mouse").doubleClickAt(200 + size / 2, 200 + size / 2);
  const editor = await getTextEditor();
  const expectScene = (
    color: string,
    geometry = { width: size, height: size },
  ) => {
    expect(h.state.viewBackgroundColor).toBe(color);
    const live = h.app.scene.getNonDeletedElement(container.id);
    expect(live).toMatchObject(geometry);
    expect(live?.boundElements ?? []).toEqual([]);
    expect(h.app.scene.getNonDeletedElements().map((el) => el.id)).toEqual([
      container.id,
    ]);
  };
  return { container, editor, expectScene, originalColor };
};

describe("label draft transaction boundaries", () => {
  const drawLargeRectangle = () =>
    UI.createElement("rectangle", {
      x: 200,
      y: 200,
      width: 200,
      height: 200,
    });

  const startLabel = () => new Pointer("mouse").doubleClickAt(300, 300);

  it("captures each explicit update across the start of a draft in one batch", async () => {
    const onIncrement = vi.fn<(increment: StoreIncrement) => void>();
    await render(
      <Excalidraw handleKeyboardGlobally onIncrement={onIncrement} />,
    );
    const container = drawLargeRectangle();
    const originalColor = h.state.viewBackgroundColor;
    const undoDepth = h.history.undoStack.length;
    onIncrement.mockClear();

    act(() => {
      setBackground(red, CaptureUpdateAction.IMMEDIATELY);
      startLabel();
      setBackground(blue, CaptureUpdateAction.IMMEDIATELY);
    });
    const colors = onIncrement.mock.calls
      .map(([increment]) => increment)
      .filter(StoreIncrement.isDurable)
      .map(({ change }) => change.appState.viewBackgroundColor);
    expect(colors).toEqual([red, blue]);
    expect(h.store.snapshot.appState.viewBackgroundColor).toBe(blue);
    Keyboard.exitTextEditor(await getTextEditor());
    expect(h.history.undoStack).toHaveLength(undoDepth + 2);

    const expectColor = (color: string) => {
      expect(h.state.viewBackgroundColor).toBe(color);
      expect(h.app.scene.getNonDeletedElement(container.id)).toMatchObject({
        width: 200,
        height: 200,
      });
    };
    Keyboard.undo();
    expectColor(red);
    Keyboard.undo();
    expectColor(originalColor);
    Keyboard.redo();
    expectColor(red);
    Keyboard.redo();
    expectColor(blue);
  });

  it("captures the final scene name with the batch-end canvas action", async () => {
    await render(<Excalidraw handleKeyboardGlobally />);
    const { editor, expectScene, originalColor } = await openEmptyLabel();
    const originalName = h.state.name;
    const undoDepth = h.history.undoStack.length;
    act(() => {
      h.app.actionManager.executeAction(
        actionChangeViewBackgroundColor,
        "api",
        {
          viewBackgroundColor: red,
        },
      );
      h.app.updateScene({
        appState: { name: "Renamed in the same batch" },
        captureUpdate: CaptureUpdateAction.EVENTUALLY,
      });
    });
    expect(h.store.snapshot.appState).toMatchObject({
      viewBackgroundColor: red,
      name: "Renamed in the same batch",
    });
    Keyboard.exitTextEditor(editor);
    expect(h.history.undoStack).toHaveLength(undoDepth + 1);

    Keyboard.undo();
    expectScene(originalColor);
    expect(h.state.name).toBe(originalName);
    Keyboard.redo();
    expectScene(red);
    expect(h.state.name).toBe("Renamed in the same batch");
  });

  it.each(["remove", "soft-delete", "reset"] as const)(
    "restores ordinary scene capture after the host invalidates a draft: %s",
    async (operation) => {
      await render(<Excalidraw handleKeyboardGlobally />);
      drawLargeRectangle();
      startLabel();
      const editor = await getTextEditor();
      const labelId = h.state.editingTextElement!.id;

      act(() => {
        if (operation === "reset") {
          h.app.api.resetScene();
        } else {
          const elements = h.app.scene.getElementsIncludingDeleted();
          h.app.updateScene({
            elements:
              operation === "remove"
                ? elements.filter(({ id }) => id !== labelId)
                : elements.map((element) =>
                    element.id === labelId
                      ? newElementWith(element, { isDeleted: true })
                      : element,
                  ),
            captureUpdate: CaptureUpdateAction.NEVER,
          });
        }
      });
      if (editor.isConnected) {
        Keyboard.exitTextEditor(editor);
      }
      expect(h.state.editingTextElement).toBeNull();
      expect(h.app.scene.getNonDeletedElement(labelId)).toBeNull();

      const committedColor = h.store.snapshot.appState.viewBackgroundColor;
      const undoDepth = h.history.undoStack.length;
      act(() => setBackground(red, CaptureUpdateAction.EVENTUALLY));
      expect(h.state.viewBackgroundColor).toBe(red);
      act(() => setBackground(red, CaptureUpdateAction.IMMEDIATELY));
      expect(h.store.snapshot.appState.viewBackgroundColor).toBe(
        committedColor,
      );
      expect(h.history.undoStack).toHaveLength(undoDepth);
    },
  );

  it("keeps an invalidated draft out of a pending canvas capture", async () => {
    const onIncrement = vi.fn<(increment: StoreIncrement) => void>();
    await render(
      <Excalidraw handleKeyboardGlobally onIncrement={onIncrement} />,
    );
    const { container, originalColor } = await openEmptyLabel(10);
    const labelId = h.state.editingTextElement!.id;
    onIncrement.mockClear();

    act(() => {
      h.app.actionManager.executeAction(
        actionChangeViewBackgroundColor,
        "api",
        {
          viewBackgroundColor: red,
        },
      );
      h.app.updateScene({
        elements: h.app.scene
          .getElementsIncludingDeleted()
          .filter(({ id }) => id !== labelId),
        captureUpdate: CaptureUpdateAction.NEVER,
      });
    });

    const durable = onIncrement.mock.calls
      .map(([increment]) => increment)
      .filter(StoreIncrement.isDurable);
    expect(durable).toHaveLength(1);
    expect(durable[0].change.elements).toEqual({});
    expect(durable[0].change.appState.viewBackgroundColor).toBe(red);
    expect(h.store.snapshot.elements.get(container.id)).toMatchObject({
      width: 10,
      height: 10,
    });
    expect(
      h.app.scene.getNonDeletedElement(container.id)?.boundElements ?? [],
    ).toEqual([]);
    Keyboard.undo();
    expect(h.state.viewBackgroundColor).toBe(originalColor);
    expect(h.app.scene.getNonDeletedElement(container.id)).toMatchObject({
      width: 10,
      height: 10,
    });
  });

  it("captures the label geometry after a background action commits transient opacity", async () => {
    await render(<Excalidraw handleKeyboardGlobally />);
    const { container, editor } = await openEmptyLabel(10);
    const { id } = container;
    const originalGeometry = { x: 200, y: 200, width: 10, height: 10 };
    updateTextEditor(editor, "Order approved");
    const labelId = h.state.editingTextElement!.id;
    const labelBinding = { id: labelId, type: "text" };
    const live = () => h.app.scene.getNonDeletedElement(id);
    reviseElement(id, CaptureUpdateAction.EVENTUALLY, { opacity: 50 });
    act(() =>
      h.app.actionManager.executeAction(
        actionChangeViewBackgroundColor,
        "api",
        { viewBackgroundColor: red },
      ),
    );
    expect(h.store.snapshot.elements.get(id)).toMatchObject({
      ...originalGeometry,
      opacity: 50,
    });
    expect(h.store.snapshot.elements.has(labelId)).toBe(false);
    Keyboard.exitTextEditor(editor);

    const submitted = live()!;
    expect(submitted.height).toBeGreaterThan(originalGeometry.height);
    expect(submitted.boundElements).toContainEqual(labelBinding);
    Keyboard.undo();
    expect(live()).toMatchObject({ ...originalGeometry, opacity: 50 });
    expect(live()?.boundElements ?? []).toEqual([]);
    expect(h.app.scene.getNonDeletedElement(labelId)).toBeNull();
    expect(h.state.viewBackgroundColor).toBe(red);

    Keyboard.redo();
    expect(live()).toMatchObject({
      x: submitted.x,
      y: submitted.y,
      width: submitted.width,
      height: submitted.height,
      opacity: 50,
    });
    expect(live()?.boundElements).toContainEqual(labelBinding);
    expect(h.app.scene.getNonDeletedElement(labelId)).toMatchObject({
      originalText: "Order approved",
      containerId: id,
    });
    expect(h.state.viewBackgroundColor).toBe(red);
  });

  describe.each([CaptureUpdateAction.NEVER, CaptureUpdateAction.IMMEDIATELY])(
    "host label changes captured with %s",
    (captureUpdate) => {
      it.each([
        { operation: "detach", content: "", size: 200 },
        { operation: "rebind", content: "", size: 200 },
        { operation: "detach", content: "Host label", size: 200 },
        { operation: "rebind", content: "Host label", size: 200 },
        { operation: "rebind", content: "Host label", size: 10 },
      ])(
        "handles $operation of a label with content $content on a $size px shape",
        async ({ operation, content, size }) => {
          await render(<Excalidraw handleKeyboardGlobally />);
          const target = UI.createElement("rectangle", {
            x: 450,
            y: 200,
            width: 200,
            height: 200,
          });
          const { container, editor, originalColor } = await openEmptyLabel(
            size,
          );
          if (content) {
            updateTextEditor(editor, content);
          }
          const labelId = h.state.editingTextElement!.id;
          const targetId = operation === "rebind" ? target.id : null;
          const reference = { id: labelId, type: "text" } as const;
          const undoDepth = h.history.undoStack.length;

          act(() =>
            h.app.updateScene({
              elements: h.app.scene.getElementsIncludingDeleted().map((el) => {
                if (el.id === labelId && el.type === "text") {
                  return newElementWith(el, { containerId: targetId });
                }
                if (el.id === container.id) {
                  return newElementWith(el, { boundElements: null });
                }
                if (el.id === targetId) {
                  return newElementWith(el, { boundElements: [reference] });
                }
                return el;
              }),
              captureUpdate,
            }),
          );
          if (editor.isConnected) {
            Keyboard.exitTextEditor(editor);
          }
          expect(h.state.editingTextElement).toBeNull();

          const expectHostScene = () => {
            for (const get of [
              (id: string) => h.app.scene.getNonDeletedElement(id),
              (id: string) => h.store.snapshot.elements.get(id),
            ]) {
              if (content) {
                expect(get(labelId)).toMatchObject({
                  originalText: content,
                  containerId: targetId,
                  isDeleted: false,
                });
              } else {
                expect(get(labelId)?.isDeleted).not.toBe(false);
              }
              expect(get(container.id)).toMatchObject({
                width: size,
                height: size,
              });
              expect(get(container.id)?.boundElements ?? []).toEqual([]);
              expect(get(target.id)?.boundElements ?? []).toEqual(
                content && targetId ? [reference] : [],
              );
            }
          };
          expectHostScene();
          act(() =>
            h.app.actionManager.executeAction(
              actionChangeViewBackgroundColor,
              "api",
              { viewBackgroundColor: red },
            ),
          );
          Keyboard.undo();
          expect(h.state.viewBackgroundColor).toBe(originalColor);
          expectHostScene();

          if (content && captureUpdate === CaptureUpdateAction.IMMEDIATELY) {
            expect(h.history.undoStack).toHaveLength(undoDepth + 1);
            Keyboard.undo();
            expect(h.app.scene.getNonDeletedElement(labelId)).toBeNull();
            expect(
              h.app.scene.getNonDeletedElement(target.id)?.boundElements ?? [],
            ).toEqual([]);
            expect(h.state.viewBackgroundColor).toBe(originalColor);
            Keyboard.redo();
            expectHostScene();
          }
          Keyboard.redo();
          expect(h.state.viewBackgroundColor).toBe(red);
          expectHostScene();
        },
      );
    },
  );

  it.each(["remove", "soft-delete"])(
    "cleans up the empty label when the host invalidates its container: %s",
    async (operation) => {
      await render(<Excalidraw handleKeyboardGlobally />);
      const { container, editor } = await openEmptyLabel(10);
      const containerId = container.id;
      const labelId = h.state.editingTextElement!.id;

      act(() => {
        h.app.updateScene({
          elements: h.app.scene.getElementsIncludingDeleted().flatMap((el) => {
            if (el.id !== containerId) {
              return [el];
            }
            return operation === "remove"
              ? []
              : [newElementWith(el, { isDeleted: true })];
          }),
          captureUpdate: CaptureUpdateAction.NEVER,
        });
      });
      if (editor.isConnected) {
        Keyboard.exitTextEditor(editor);
      }

      expect(h.state.editingTextElement).toBeNull();
      expect(h.app.scene.getNonDeletedElements()).toEqual([]);
      expect(h.store.snapshot.elements.get(labelId)?.isDeleted).not.toBe(false);
    },
  );

  it.each(["remove", "soft-delete"])(
    "keeps a nonempty label after host container %s and background undo",
    async (operation) => {
      await render(<Excalidraw handleKeyboardGlobally />);
      const { container, editor, originalColor } = await openEmptyLabel(10);
      const containerId = container.id;
      const content = "Retained label";
      updateTextEditor(editor, content);
      const labelId = h.state.editingTextElement!.id;
      const undoDepth = h.history.undoStack.length;

      act(() =>
        h.app.updateScene({
          elements: h.app.scene.getElementsIncludingDeleted().flatMap((el) => {
            if (el.id !== containerId) {
              return [el];
            }
            return operation === "remove"
              ? []
              : [newElementWith(el, { isDeleted: true })];
          }),
          captureUpdate: CaptureUpdateAction.NEVER,
        }),
      );
      if (editor.isConnected) {
        Keyboard.exitTextEditor(editor);
      }
      expect(h.state.editingTextElement).toBeNull();
      expect(h.history.undoStack).toHaveLength(undoDepth);

      act(() =>
        h.app.actionManager.executeAction(
          actionChangeViewBackgroundColor,
          "api",
          {
            viewBackgroundColor: red,
          },
        ),
      );
      for (const [move, color] of [
        [Keyboard.undo, originalColor],
        [Keyboard.redo, red],
      ] as const) {
        move();
        expect(h.state.viewBackgroundColor).toBe(color);
        expect(h.app.scene.getNonDeletedElement(containerId)).toBeNull();
        expect(h.app.scene.getNonDeletedElement(labelId)).toMatchObject({
          originalText: content,
          containerId: null,
        });
        expect(h.store.snapshot.elements.get(labelId)).toMatchObject({
          originalText: content,
          containerId: null,
        });
      }
    },
  );

  it.each([CaptureUpdateAction.NEVER, CaptureUpdateAction.IMMEDIATELY])(
    "restores the host's revised draft text when undoing local input after %s",
    async (captureUpdate) => {
      await render(<Excalidraw handleKeyboardGlobally />);
      const { container, editor } = await openEmptyLabel(10);
      updateTextEditor(editor, "Before host revision");
      const labelId = h.state.editingTextElement!.id;
      const revision = "Host revision";
      const localText = "Local edit after host revision";
      const undoDepth = h.history.undoStack.length;

      act(() =>
        h.app.updateScene({
          elements: h.app.scene
            .getElementsIncludingDeleted()
            .map((el) =>
              el.id === labelId && el.type === "text"
                ? newElementWith(el, { originalText: revision, text: revision })
                : el,
            ),
          captureUpdate,
        }),
      );
      expect(editor.isConnected).toBe(true);
      updateTextEditor(editor, localText);
      act(() =>
        h.app.actionManager.executeAction(
          actionChangeViewBackgroundColor,
          "api",
          {
            viewBackgroundColor: red,
          },
        ),
      );
      expect(h.store.snapshot.elements.get(labelId)).toMatchObject({
        originalText: revision,
        containerId: container.id,
      });
      Keyboard.exitTextEditor(editor);

      const expectBoundText = (originalText: string) => {
        expect(h.app.scene.getNonDeletedElement(labelId)).toMatchObject({
          originalText,
          containerId: container.id,
        });
        expect(
          h.app.scene.getNonDeletedElement(container.id)?.boundElements,
        ).toContainEqual({
          id: labelId,
          type: "text",
        });
      };
      expectBoundText(localText);
      Keyboard.undo();
      expectBoundText(revision);
      expect(h.state.viewBackgroundColor).toBe(red);
      expect(h.history.undoStack).toHaveLength(
        undoDepth +
          1 +
          Number(captureUpdate === CaptureUpdateAction.IMMEDIATELY),
      );
      Keyboard.redo();
      expectBoundText(localText);
    },
  );

  it("clears the reverse binding when the host removes its published label", async () => {
    await render(<Excalidraw handleKeyboardGlobally />);
    const { container, editor } = await openEmptyLabel();
    const id = container.id;
    updateTextEditor(editor, "Draft text");
    const labelId = h.state.editingTextElement!.id;
    const hostText = "Host text";
    act(() =>
      h.app.updateScene({
        elements: h.app.scene
          .getElementsIncludingDeleted()
          .map((el) =>
            el.id === labelId && el.type === "text"
              ? newElementWith(el, { originalText: hostText, text: hostText })
              : el,
          ),
        captureUpdate: CaptureUpdateAction.NEVER,
      }),
    );
    expect(h.store.snapshot.elements.get(labelId)?.isDeleted).toBe(false);

    act(() =>
      h.app.updateScene({
        elements: h.app.scene
          .getElementsIncludingDeleted()
          .filter((el) => el.id !== labelId)
          .map((el) =>
            el.id === id ? newElementWith(el, { boundElements: null }) : el,
          ),
        captureUpdate: CaptureUpdateAction.NEVER,
      }),
    );
    expect(editor.isConnected).toBe(false);
    expect(h.store.snapshot.elements.get(labelId)?.isDeleted).toBe(true);
    expect(h.app.scene.getNonDeletedElement(id)?.boundElements ?? []).toEqual(
      [],
    );
    expect(h.store.snapshot.elements.get(id)?.boundElements ?? []).toEqual([]);
  });

  it("keeps a host-detached nonempty label through background undo and redo", async () => {
    await render(<Excalidraw handleKeyboardGlobally />);
    const { container, editor, originalColor } = await openEmptyLabel(10);
    const containerId = container.id;
    updateTextEditor(editor, "Detached text");
    const labelId = h.state.editingTextElement!.id;

    act(() => {
      h.app.updateScene({
        elements: h.app.scene.getElementsIncludingDeleted().map((el) => {
          if (el.id === labelId && el.type === "text") {
            return newElementWith(el, { containerId: null });
          }
          return el.id === containerId
            ? newElementWith(el, { boundElements: null })
            : el;
        }),
        captureUpdate: CaptureUpdateAction.NEVER,
      });
    });
    if (editor.isConnected) {
      Keyboard.exitTextEditor(editor);
    }

    const expected = { containerId: null, originalText: "Detached text" };
    expect(h.app.scene.getNonDeletedElement(labelId)).toMatchObject(expected);
    expect(h.store.snapshot.elements.get(labelId)).toMatchObject(expected);

    act(() =>
      h.app.actionManager.executeAction(
        actionChangeViewBackgroundColor,
        "api",
        {
          viewBackgroundColor: red,
        },
      ),
    );
    for (const [apply, color] of [
      [() => Keyboard.undo(), originalColor],
      [() => Keyboard.redo(), red],
    ] as const) {
      apply();
      expect(h.state.viewBackgroundColor).toBe(color);
      expect(h.app.scene.getNonDeletedElement(labelId)).toMatchObject(expected);
      expect(
        h.app.scene.getNonDeletedElement(containerId)?.boundElements ?? [],
      ).toEqual([]);
    }
  });
});

describe.each([false, true])(
  "with an increment subscriber: %s",
  (subscribe) => {
    beforeEach(async () => {
      await render(
        <Excalidraw
          handleKeyboardGlobally
          onIncrement={subscribe ? vi.fn() : undefined}
        />,
      );
    });

    it("undoes an explicit update to the committed color across React batches", async () => {
      const { editor, expectScene, originalColor } = await openEmptyLabel();
      const undoDepth = h.history.undoStack.length;
      act(() => setBackground(red, CaptureUpdateAction.EVENTUALLY));
      expect(h.state.viewBackgroundColor).toBe(red);
      expect(h.store.snapshot.appState.viewBackgroundColor).toBe(originalColor);

      act(() => setBackground(blue, CaptureUpdateAction.IMMEDIATELY));
      Keyboard.exitTextEditor(editor);
      expect(h.history.undoStack).toHaveLength(undoDepth + 1);
      expectScene(blue);
      Keyboard.undo();
      expectScene(originalColor);
      expect(h.history.undoStack).toHaveLength(undoDepth);
      Keyboard.redo();
      expectScene(blue);
    });

    it("captures a canvas action that confirms a transient background color", async () => {
      const { container, editor, expectScene, originalColor } =
        await openEmptyLabel();
      const undoDepth = h.history.undoStack.length;
      act(() => setBackground(red, CaptureUpdateAction.EVENTUALLY));
      expect(h.state.viewBackgroundColor).toBe(red);
      expect(h.store.snapshot.appState.viewBackgroundColor).toBe(originalColor);

      act(() =>
        h.app.actionManager.executeAction(
          actionChangeViewBackgroundColor,
          "api",
          { viewBackgroundColor: red },
        ),
      );
      expect(h.store.snapshot.appState.viewBackgroundColor).toBe(red);
      Keyboard.exitTextEditor(editor);
      expectScene(red);
      expect(h.history.undoStack).toHaveLength(undoDepth + 1);
      Keyboard.undo();
      expectScene(originalColor);
      Keyboard.redo();
      expect(h.state.viewBackgroundColor).toBe(red);
      expect(h.app.scene.getNonDeletedElement(container.id)).toMatchObject({
        width: 200,
        height: 200,
      });
    });

    it.each([CaptureUpdateAction.NEVER, CaptureUpdateAction.IMMEDIATELY])(
      "captures a newer revision that confirms an independent transient move with %s",
      async (captureUpdate) => {
        const remote = UI.createElement("rectangle", {
          x: 450,
          y: 450,
          width: 100,
          height: 100,
        });
        const { editor } = await openEmptyLabel();
        const undoDepth = h.history.undoStack.length;
        const committed = () => h.store.snapshot.elements.get(remote.id);
        const live = () => h.app.scene.getNonDeletedElement(remote.id)!;
        reviseElement(remote.id, CaptureUpdateAction.EVENTUALLY, { x: 470 });
        expect(live().x).toBe(470);
        expect(committed()?.x).toBe(450);

        reviseElement(remote.id, captureUpdate, {});
        expect(committed()).toMatchObject({
          x: 470,
          version: live().version,
          versionNonce: live().versionNonce,
        });
        const durable = captureUpdate === CaptureUpdateAction.IMMEDIATELY;
        expect(h.history.undoStack).toHaveLength(undoDepth + Number(durable));
        Keyboard.exitTextEditor(editor);
        if (durable) {
          Keyboard.undo();
          expect(live().x).toBe(450);
          Keyboard.redo();
          expect(live().x).toBe(470);
        }
      },
    );

    it("keeps a confirmed remote move through label resize undo and redo", async () => {
      const remote = UI.createElement("rectangle", {
        x: 450,
        y: 450,
        width: 100,
        height: 100,
      });
      const { container, editor } = await openEmptyLabel(10);
      reviseElement(remote.id, CaptureUpdateAction.EVENTUALLY, { x: 470 });
      reviseElement(remote.id, CaptureUpdateAction.NEVER, {});
      Keyboard.exitTextEditor(editor);
      const live = (id: string) => h.app.scene.getNonDeletedElement(id);
      const { width, height } = live(container.id)!;
      expect({ width, height }).not.toEqual({ width: 10, height: 10 });

      Keyboard.undo();
      expect(live(container.id)).toMatchObject({ width: 10, height: 10 });
      expect(live(remote.id)?.x).toBe(470);
      Keyboard.redo();
      expect(live(container.id)).toMatchObject({ width, height });
      expect(live(remote.id)?.x).toBe(470);
    });

    it("preserves an explicit capture before a same-batch NEVER and label exit", async () => {
      const { editor, expectScene, originalColor } = await openEmptyLabel();
      const undoDepth = h.history.undoStack.length;
      act(() => {
        setBackground(red, CaptureUpdateAction.IMMEDIATELY);
        setBackground(blue, CaptureUpdateAction.NEVER);
        Keyboard.exitTextEditor(editor);
      });
      expectScene(blue);
      expect(h.store.snapshot.appState.viewBackgroundColor).toBe(blue);
      expect(h.history.undoStack).toHaveLength(undoDepth + 1);
      Keyboard.undo();
      expectScene(originalColor);
      expect(h.history.undoStack).toHaveLength(undoDepth);
      Keyboard.redo();
      expectScene(red);
    });

    it("lets a same-batch NEVER supersede a pending canvas action", async () => {
      const { container, editor, expectScene } = await openEmptyLabel();
      const undoDepth = h.history.undoStack.length;
      act(() => {
        h.app.actionManager.executeAction(
          actionChangeViewBackgroundColor,
          "api",
          {
            viewBackgroundColor: red,
          },
        );
        setBackground(blue, CaptureUpdateAction.NEVER);
      });
      Keyboard.exitTextEditor(editor);
      expectScene(blue);
      expect(h.history.undoStack).toHaveLength(undoDepth);
      Keyboard.undo();
      expect(h.state.viewBackgroundColor).toBe(blue);
      expect(h.app.scene.getNonDeletedElement(container.id)).toBeNull();
      Keyboard.redo();
      expectScene(blue);
    });

    it.each([CaptureUpdateAction.EVENTUALLY, undefined])(
      "redoes the final canvas color after a same-batch API update with capture mode %s",
      async (captureUpdate) => {
        const { editor, expectScene, originalColor } = await openEmptyLabel();
        const undoDepth = h.history.undoStack.length;
        act(() => {
          h.app.actionManager.executeAction(
            actionChangeViewBackgroundColor,
            "api",
            { viewBackgroundColor: red },
          );
          h.app.updateScene({
            appState: { viewBackgroundColor: blue },
            captureUpdate,
          });
        });
        expect(h.state.viewBackgroundColor).toBe(blue);
        expect(h.store.snapshot.appState.viewBackgroundColor).toBe(blue);
        Keyboard.exitTextEditor(editor);
        expect(h.history.undoStack).toHaveLength(undoDepth + 1);
        expectScene(blue);
        Keyboard.undo();
        expectScene(originalColor);
        Keyboard.redo();
        expectScene(blue);
      },
    );

    it("keeps draft geometry out of an explicit mixed scene capture", async () => {
      const { container, editor, expectScene, originalColor } =
        await openEmptyLabel(10);
      const { width, height } = h.app.scene.getNonDeletedElement(container.id)!;
      const undoDepth = h.history.undoStack.length;
      act(() => {
        h.app.updateScene({
          elements: h.app.scene
            .getElementsIncludingDeleted()
            .map((el) =>
              el.id === container.id ? newElementWith(el, { opacity: 50 }) : el,
            ),
          appState: { viewBackgroundColor: blue },
          captureUpdate: CaptureUpdateAction.IMMEDIATELY,
        });
      });
      expect(h.store.snapshot.elements.get(container.id)).toMatchObject({
        width: 10,
        height: 10,
        opacity: 50,
      });
      Keyboard.exitTextEditor(editor);
      expectScene(blue, { width, height });
      expect(h.history.undoStack).toHaveLength(undoDepth + 2);
      Keyboard.undo();
      expectScene(blue);
      expect(h.app.scene.getNonDeletedElement(container.id)?.opacity).toBe(50);
      Keyboard.undo();
      expectScene(originalColor);
      expect(h.app.scene.getNonDeletedElement(container.id)?.opacity).toBe(
        container.opacity,
      );
      Keyboard.redo();
      expectScene(blue);
      expect(h.app.scene.getNonDeletedElement(container.id)?.opacity).toBe(50);
      Keyboard.redo();
      expectScene(blue, { width, height });
    });
  },
);

describe("explicit captures during a label draft", () => {
  it.each([false, true])(
    "undoes the batch-end canvas action before the explicit scene capture (mixed state: %s)",
    async (mixedState) => {
      const onIncrement = vi.fn<(increment: StoreIncrement) => void>();
      await render(
        <Excalidraw handleKeyboardGlobally onIncrement={onIncrement} />,
      );
      const remote = UI.createElement("rectangle", {
        x: 450,
        y: 450,
        width: 100,
        height: 100,
      });
      const { container, editor, originalColor } = await openEmptyLabel();
      const originalName = h.state.name;
      const nextName = mixedState ? "Updated scene" : originalName;
      const undoDepth = h.history.undoStack.length;
      onIncrement.mockClear();
      act(() => {
        h.app.actionManager.executeAction(
          actionChangeViewBackgroundColor,
          "api",
          {
            viewBackgroundColor: red,
          },
        );
        h.app.updateScene({
          elements: h.app.scene
            .getElementsIncludingDeleted()
            .map((element) =>
              element.id === remote.id
                ? newElementWith(element, { x: 470 })
                : element,
            ),
          appState: mixedState ? { name: nextName } : undefined,
          captureUpdate: CaptureUpdateAction.IMMEDIATELY,
        });
      });
      const expectFrame = (
        x: number,
        background: string,
        name: typeof originalName,
      ) => {
        expect(h.app.scene.getNonDeletedElement(remote.id)?.x).toBe(x);
        expect(h.app.scene.getNonDeletedElement(container.id)).toMatchObject({
          width: 200,
          height: 200,
        });
        expect(h.state.viewBackgroundColor).toBe(background);
        expect(h.state.name).toBe(name);
      };

      expectFrame(470, red, nextName);
      Keyboard.exitTextEditor(editor);
      Keyboard.undo();
      expectFrame(470, originalColor, nextName);
      Keyboard.undo();
      expectFrame(450, originalColor, originalName);
      Keyboard.redo();
      expectFrame(470, originalColor, nextName);
      Keyboard.redo();
      expectFrame(470, red, nextName);
      expect(h.history.undoStack).toHaveLength(undoDepth + 2);
      const durable = onIncrement.mock.calls
        .map(([increment]) => increment)
        .filter(StoreIncrement.isDurable);
      expect(durable[0].change.elements[remote.id]?.x).toBe(470);
      expect(durable[1].change.appState.viewBackgroundColor).toBe(red);
    },
  );

  it.each([CaptureUpdateAction.NEVER, CaptureUpdateAction.IMMEDIATELY])(
    "confirms already visible container opacity in a newer revision with %s",
    async (captureUpdate) => {
      await render(<Excalidraw handleKeyboardGlobally />);
      const { container, editor } = await openEmptyLabel(10);
      const live = () => h.app.scene.getNonDeletedElement(container.id)!;
      const committed = () => h.store.snapshot.elements.get(container.id)!;
      const undoDepth = h.history.undoStack.length;
      reviseElement(container.id, CaptureUpdateAction.EVENTUALLY, {
        opacity: 50,
      });
      expect(live().opacity).toBe(50);
      expect(committed().opacity).toBe(100);

      reviseElement(container.id, captureUpdate, {});
      expect(committed().opacity).toBe(50);
      expect(h.history.undoStack).toHaveLength(
        undoDepth + Number(captureUpdate === CaptureUpdateAction.IMMEDIATELY),
      );
      Keyboard.exitTextEditor(editor);
    },
  );

  it("keeps confirmed remote opacity through label resize undo and redo", async () => {
    await render(<Excalidraw handleKeyboardGlobally />);
    const { container, editor } = await openEmptyLabel(10);
    const live = () => h.app.scene.getNonDeletedElement(container.id)!;
    reviseElement(container.id, CaptureUpdateAction.EVENTUALLY, {
      opacity: 50,
    });
    reviseElement(container.id, CaptureUpdateAction.NEVER, {});
    Keyboard.exitTextEditor(editor);
    const { width, height } = live();
    expect({ width, height }).not.toEqual({ width: 10, height: 10 });
    Keyboard.undo();
    expect(live()).toMatchObject({ width: 10, height: 10, opacity: 50 });
    Keyboard.redo();
    expect(live()).toMatchObject({ width, height, opacity: 50 });
  });

  it("commits consecutive bigint metadata updates during a label draft", async () => {
    await render(<Excalidraw handleKeyboardGlobally />);
    const { container, editor } = await openEmptyLabel();
    const undoDepth = h.history.undoStack.length;
    for (const id of [9007199254740993n, 9007199254740994n]) {
      reviseElement(container.id, CaptureUpdateAction.NEVER, {
        customData: { id },
      });
      expect(
        h.app.scene.getNonDeletedElement(container.id)?.customData?.id,
      ).toBe(id);
      expect(h.store.snapshot.elements.get(container.id)?.customData?.id).toBe(
        id,
      );
    }
    Keyboard.exitTextEditor(editor);
    expect(h.history.undoStack).toHaveLength(undoDepth);
  });
});

describe.each([CaptureUpdateAction.IMMEDIATELY, CaptureUpdateAction.NEVER])(
  "captures an arrow binding during a label draft with %s",
  (captureUpdate) => {
    describe.each([true, false])(
      "with an increment subscriber: %s",
      (subscribe) => {
        it.each([
          { input: "", exitInBatch: false },
          { input: "Draft label", exitInBatch: false },
          { input: "", exitInBatch: true },
          { input: "Draft label", exitInBatch: true },
        ])(
          "restores geometry and bindings for $input with same-batch exit: $exitInBatch",
          async ({ input, exitInBatch }) => {
            const onIncrement = vi.fn<(increment: StoreIncrement) => void>();
            await render(
              <Excalidraw
                handleKeyboardGlobally
                onIncrement={subscribe ? onIncrement : undefined}
              />,
            );
            const { container, editor } = await openEmptyLabel(10);
            if (input) {
              updateTextEditor(editor, input);
            }
            const labelId = h.state.editingTextElement!.id;
            const draftBinding = { type: "text", id: labelId } as const;
            const arrow = API.createElement({
              type: "arrow",
              x: 300,
              y: 300,
              endBinding: {
                elementId: container.id,
                mode: "inside",
                fixedPoint: [0.5, 0.8],
              },
            });
            const arrowBinding = { type: "arrow", id: arrow.id } as const;
            const liveContainer = () =>
              h.app.scene.getNonDeletedElement(container.id)!;
            const committedContainer = () =>
              h.store.snapshot.elements.get(container.id)!;
            const originalGeometry = { width: 10, height: 10 };
            const undoDepth = h.history.undoStack.length;
            expect(liveContainer().boundElements).toContainEqual(draftBinding);
            onIncrement.mockClear();

            act(() => {
              h.app.updateScene({
                elements: [
                  ...h.app.scene.getElementsIncludingDeleted().map((element) =>
                    element.id === container.id
                      ? newElementWith(element, {
                          boundElements: [
                            ...(element.boundElements ?? []),
                            arrowBinding,
                          ],
                        })
                      : element,
                  ),
                  arrow,
                ],
                captureUpdate,
              });
              if (exitInBatch) {
                Keyboard.exitTextEditor(editor);
              }
            });

            const durable = captureUpdate === CaptureUpdateAction.IMMEDIATELY;
            if (subscribe) {
              const [[increment]] = onIncrement.mock.calls;
              expect(StoreIncrement.isDurable(increment)).toBe(durable);
              const { elements } = increment.change;
              expect(elements[container.id]).toMatchObject({
                ...originalGeometry,
                boundElements: [arrowBinding],
              });
              expect(elements[arrow.id]).toMatchObject({
                endBinding: { elementId: container.id },
              });
              expect(elements[labelId]).toBeUndefined();
            }

            if (!exitInBatch) {
              expect(h.history.undoStack).toHaveLength(
                undoDepth + Number(durable),
              );
              expect(committedContainer()).toMatchObject({
                ...originalGeometry,
                boundElements: [arrowBinding],
              });
              expect(liveContainer().boundElements).toEqual([
                draftBinding,
                arrowBinding,
              ]);
              expect(committedContainer().version).toBeLessThan(
                liveContainer().version,
              );
              expect(committedContainer().versionNonce).not.toBe(
                liveContainer().versionNonce,
              );
              Keyboard.exitTextEditor(editor);
            }

            const { width, height } = liveContainer();
            const submittedBindings = input
              ? [draftBinding, arrowBinding]
              : [arrowBinding];
            expect({ width, height }).not.toEqual(originalGeometry);
            expect(liveContainer().boundElements).toEqual(submittedBindings);
            expect(committedContainer().boundElements).toEqual(
              submittedBindings,
            );
            expect(h.history.undoStack).toHaveLength(
              undoDepth + Number(durable) + 1,
            );

            Keyboard.undo();
            expect(liveContainer()).toMatchObject({
              ...originalGeometry,
              boundElements: [arrowBinding],
            });
            expect(h.app.scene.getNonDeletedElement(labelId)).toBeNull();
            expect(h.app.scene.getNonDeletedElement(arrow.id)).toMatchObject({
              endBinding: { elementId: container.id },
            });
            expect(h.history.undoStack).toHaveLength(
              undoDepth + Number(durable),
            );

            Keyboard.redo();
            expect(liveContainer()).toMatchObject({ width, height });
            expect(liveContainer().boundElements).toHaveLength(
              submittedBindings.length,
            );
            expect(liveContainer().boundElements).toEqual(
              expect.arrayContaining(submittedBindings),
            );
            expect(h.app.scene.getNonDeletedElement(arrow.id)).toMatchObject({
              endBinding: { elementId: container.id },
            });
            if (input) {
              expect(h.app.scene.getNonDeletedElement(labelId)).toMatchObject({
                originalText: input,
                containerId: container.id,
              });
            } else {
              expect(h.app.scene.getNonDeletedElement(labelId)).toBeNull();
            }
          },
        );
      },
    );
  },
);
