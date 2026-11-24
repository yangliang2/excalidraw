import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const output = process.env.ARTIFACT_DIR || "test-results/empty-text-history";
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const failures = [];
let checks = 0;
try {
  for (const type of ["rectangle", "ellipse", "diamond"]) {
    const context = await browser.newContext({
      viewport: { width: 1200, height: 800 },
    });
    const page = await context.newPage();
    const read = () =>
      page.evaluate(() =>
        JSON.parse(localStorage.getItem("excalidraw") || "[]"),
      );
    try {
      await page.goto(process.env.BASE_URL || "http://127.0.0.1:5176", {
        waitUntil: "domcontentloaded",
      });
      await page.locator("canvas").first().waitFor();
      await page.getByTestId(`toolbar-${type}`).click();
      await page.mouse.move(600, 300);
      await page.mouse.down();
      await page.mouse.move(610, 310);
      await page.mouse.up();
      await page.waitForTimeout(700);
      const [original] = await read();
      assert.equal(original.type, type);
      await page.mouse.dblclick(605, 305);
      await page.locator("textarea.excalidraw-wysiwyg").waitFor();
      await page.keyboard.press("Escape");
      await page.waitForTimeout(700);
      const [resized] = await read();
      assert.ok(
        resized.width > original.width || resized.height > original.height,
      );
      await page.screenshot({ path: `${output}/${type}-resized.png` });
      await page.keyboard.press("ControlOrMeta+z");
      await page.waitForTimeout(700);
      const afterUndo = await read();
      const restored = afterUndo.find(
        (el) => el.id === original.id && !el.isDeleted,
      );
      assert.ok(
        restored,
        "undo must restore geometry, not delete the container",
      );
      for (const key of ["x", "y", "width", "height"])
        assert.equal(restored[key], original[key]);
      checks++;
      await page.screenshot({ path: `${output}/${type}-undo.png` });
      await page.keyboard.press("ControlOrMeta+Shift+z");
      await page.waitForTimeout(700);
      const afterRedo = await read();
      const redone = afterRedo.find(
        (el) => el.id === original.id && !el.isDeleted,
      );
      assert.ok(redone);
      for (const key of ["x", "y", "width", "height"])
        assert.equal(redone[key], resized[key]);
      assert.equal(
        afterRedo.filter((el) => el.type === "text" && !el.isDeleted).length,
        0,
      );
      assert.deepEqual(redone.boundElements || [], []);
      checks++;
      await writeFile(
        `${output}/${type}.json`,
        JSON.stringify({ original, resized, afterUndo, afterRedo }, null, 2),
      );
    } catch (error) {
      failures.push({ type, error: String(error) });
      await page.screenshot({ path: `${output}/${type}-failure.png` });
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
}
await writeFile(
  `${output}/result.json`,
  JSON.stringify({ checks, failures }, null, 2),
);
console.log(JSON.stringify({ checks, failures }));
if (failures.length) process.exitCode = 1;
