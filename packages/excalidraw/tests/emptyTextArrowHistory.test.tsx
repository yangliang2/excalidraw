import { pointFrom } from "@excalidraw/math";

import { Excalidraw } from "../index";

import { API } from "./helpers/api";
import { Keyboard, Pointer } from "./helpers/ui";
import { getTextEditor } from "./queries/dom";
import { render } from "./test-utils";

const { h } = window;
const mouse = new Pointer("mouse");
it("keeps a connected arrow identical on empty resize submission and repeated redo", async () => {
  const rect = API.createElement({
    type: "rectangle",
    x: 200,
    y: 200,
    width: 30,
    height: 10,
  });
  const arrow = API.createElement({
    type: "arrow",
    x: 215,
    y: 260,
    width: 0,
    height: 52,
    points: [pointFrom(0, 0), pointFrom(0, -52)],
    endBinding: { elementId: rect.id, mode: "inside", fixedPoint: [0.5, 0.8] },
  });
  rect.boundElements = [{ id: arrow.id, type: "arrow" }];
  await render(
    <Excalidraw
      handleKeyboardGlobally={true}
      initialData={{ elements: [rect, arrow] }}
    />,
  );
  const endY = () => {
    const current = h.elements.find((el) => el.id === arrow.id)!;
    if (current.type !== "arrow") {
      throw new Error("missing arrow");
    }
    return current.y + current.points[current.points.length - 1][1];
  };
  const before = endY();
  mouse.doubleClickAt(202, 202);
  Keyboard.exitTextEditor(await getTextEditor());
  const submitted = endY();
  const enlarged = h.elements.find((el) => el.id === rect.id)!;
  const expected = enlarged.y + enlarged.height * 0.8;
  const results = [];
  for (let i = 0; i < 2; i++) {
    Keyboard.undo();
    const undone = endY();
    Keyboard.redo();
    const redone = endY();
    results.push({ undone, redone });
  }
  expect(submitted).toBeCloseTo(expected);
  for (const result of results) {
    expect(result.undone).toBeCloseTo(before);
    expect(result.redone).toBeCloseTo(submitted);
  }
});
