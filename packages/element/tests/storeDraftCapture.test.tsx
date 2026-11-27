import { Excalidraw } from "@excalidraw/excalidraw";
import { render } from "@excalidraw/excalidraw/tests/test-utils";

import {
  CaptureUpdateAction,
  Store,
  StoreChange,
  StoreDelta,
} from "../src/store";

import type { StoreIncrement, StoreSnapshot } from "../src/store";

const { h } = window;

it("resolves projected updates in Store FIFO order before the batch capture", async () => {
  await render(<Excalidraw />);
  const store = new Store(h.app);
  store.snapshot = h.store.snapshot;
  const onIncrement = vi.fn<(increment: StoreIncrement) => void>();
  const unsubscribe = store.onStoreIncrementEmitter.on(onIncrement);
  const originalState = store.snapshot.appState;
  const precedingState = { ...originalState, viewBackgroundColor: "#ff0000" };
  const resolveChange = vi.fn((snapshot: StoreSnapshot) =>
    StoreChange.create(
      snapshot,
      snapshot.applyChange({ elements: {}, appState: { name: "Remote name" } }),
    ),
  );

  try {
    store.scheduleMicroAction({
      action: CaptureUpdateAction.IMMEDIATELY,
      elements: undefined,
      appState: precedingState,
    });
    store.scheduleMicroAction({
      action: CaptureUpdateAction.NEVER,
      resolveChange,
    });
    store.scheduleCapture();
    expect(resolveChange).not.toHaveBeenCalled();
    store.commit(undefined, {
      ...precedingState,
      name: "Remote name",
      viewBackgroundColor: "#0000ff",
    });

    expect(resolveChange).toHaveBeenCalledTimes(1);
    expect(resolveChange.mock.calls[0][0].appState).toEqual(precedingState);
    const increments = onIncrement.mock.calls.map(([increment]) => increment);
    expect(
      increments.map(({ type, change }) => [type, change.appState]),
    ).toEqual([
      ["durable", { viewBackgroundColor: "#ff0000" }],
      ["ephemeral", { name: "Remote name" }],
      ["durable", { viewBackgroundColor: "#0000ff" }],
    ]);
    expect(store.snapshot.appState).toMatchObject({
      name: "Remote name",
      viewBackgroundColor: "#0000ff",
    });
  } finally {
    unsubscribe();
  }
});

it("keeps the supplied history delta and drops queued projections on clear", async () => {
  await render(<Excalidraw />);
  const store = new Store(h.app);
  store.snapshot = h.store.snapshot;
  const onIncrement = vi.fn();
  store.onDurableIncrementEmitter.on(onIncrement);
  const initial = store.snapshot;
  const next = initial.applyChange({
    elements: {},
    appState: { name: "Name from history" },
  });
  const change = StoreChange.create(initial, next);
  const delta = StoreDelta.calculate(initial, next);
  store.scheduleMicroAction({
    action: CaptureUpdateAction.IMMEDIATELY,
    change,
    delta,
  });
  store.commit(undefined, undefined);
  expect(onIncrement).toHaveBeenCalledTimes(1);
  expect(onIncrement.mock.calls[0][0].delta).toBe(delta);

  const project = vi.fn(() => change);
  store.scheduleMicroAction({
    action: CaptureUpdateAction.IMMEDIATELY,
    resolveChange: project,
  });
  store.clear();
  store.commit(undefined, undefined);
  expect(project).not.toHaveBeenCalled();
  expect(store.snapshot.isEmpty()).toBe(true);
  expect(onIncrement).toHaveBeenCalledTimes(1);
});
