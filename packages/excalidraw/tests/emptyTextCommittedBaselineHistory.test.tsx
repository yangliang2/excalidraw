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
  fields: { x?: number },
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
