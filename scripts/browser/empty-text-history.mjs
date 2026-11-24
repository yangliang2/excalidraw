import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";

const output = process.env.ARTIFACT_DIR || "test-results/empty-text-history";
let browser;
try {
  await mkdir(output, { recursive: true });
  const { chromium } = await import("playwright");
  browser = await chromium.launch();
} catch (error) {
  console.error("Could not start the Chromium check", error);
  process.exit(2);
}

const failures = [];
let environmentError;
const recordEnvironmentError = (error) => {
  environmentError ??= String(error);
  console.error("Browser check environment error", error);
};

let checks = 0;
try {
  for (const type of ["rectangle", "ellipse", "diamond"]) {
    let context;
    let page;
    let navigating = false;
    try {
      context = await browser.newContext({
        viewport: { width: 1200, height: 800 },
      });
      page = await context.newPage();
      const read = () =>
        page.evaluate(() =>
          JSON.parse(localStorage.getItem("excalidraw") || "[]"),
        );
      navigating = true;
      await page.goto(process.env.BASE_URL || "http://127.0.0.1:5176", {
        waitUntil: "domcontentloaded",
      });
      navigating = false;
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
      ).catch(recordEnvironmentError);
    } catch (error) {
      const previewUnavailable =
        navigating &&
        /net::ERR_(CONNECTION_REFUSED|CONNECTION_RESET|CONNECTION_CLOSED|EMPTY_RESPONSE|TIMED_OUT)\b/.test(
          String(error),
        );
      if (
        !(error instanceof assert.AssertionError) &&
        (!page || !browser.isConnected() || previewUnavailable)
      ) {
        recordEnvironmentError(error);
      } else {
        failures.push({ type, error: String(error) });
        await page
          ?.screenshot({ path: `${output}/${type}-failure.png` })
          .catch(recordEnvironmentError);
      }
    } finally {
      await context?.close().catch(recordEnvironmentError);
    }
    if (environmentError) {
      break;
    }
  }
} finally {
  await browser.close().catch(recordEnvironmentError);
}
const result = { checks, failures, environmentError };
await writeFile(`${output}/result.json`, JSON.stringify(result, null, 2)).catch(
  recordEnvironmentError,
);
console.log(JSON.stringify({ ...result, environmentError }));
process.exitCode = failures.length ? 1 : environmentError ? 2 : 0;
