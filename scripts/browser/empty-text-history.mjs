import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { get } from "node:http";
import { setTimeout as delay } from "node:timers/promises";

const output =
  process.env.ARTIFACT_DIR ||
  process.env.WORKFLOW_ARTIFACT_DIR ||
  "test-results/empty-text-history";
const baseURL = process.env.BASE_URL || "http://127.0.0.1:5176";

const hasPreviewMarker = (url, token) =>
  new Promise((resolve, reject) => {
    // Connect directly to the loopback address and inspect this response only.
    const request = get(
      url,
      { agent: false, signal: AbortSignal.timeout(1_000) },
      async (response) => {
        try {
          if (response.statusCode !== 200) {
            response.destroy();
            resolve(false);
            return;
          }
          let body = "";
          response.setEncoding("utf8");
          for await (const chunk of response) {
            body += chunk;
            if (body.length > token.length) {
              resolve(false);
              return;
            }
          }
          resolve(body === token);
        } catch (error) {
          reject(error);
        }
      },
    );
    request.on("error", reject);
  });

const waitForOwnedPreview = async () => {
  const pid = Number(process.env.PREVIEW_PID);
  const name = process.env.PREVIEW_MARKER_NAME;
  const token = process.env.PREVIEW_MARKER_TOKEN;
  if (
    !Number.isSafeInteger(pid) ||
    pid <= 0 ||
    !name ||
    !/^[a-z0-9-]+\.txt$/.test(name) ||
    !token ||
    !/^http:\/\/127\.0\.0\.1:\d+$/.test(baseURL)
  ) {
    throw new Error("Missing preview ownership information");
  }

  const markerURL = new URL(name, baseURL);
  const deadline = performance.now() + 30_000;
  while (performance.now() < deadline) {
    process.kill(pid, 0);
    let matches;
    try {
      matches = await hasPreviewMarker(markerURL, token);
    } catch (error) {
      if (error.code !== "ECONNREFUSED") {
        throw error;
      }
      await delay(200);
      continue;
    }
    process.kill(pid, 0);
    if (!matches) {
      throw new Error("Preview did not return this build's readiness marker");
    }
    return;
  }
  throw new Error("Preview did not become ready; inspect server.log");
};

let browser;
try {
  await waitForOwnedPreview();
  await mkdir(output, { recursive: true });
  const { chromium } = await import("playwright");
  browser = await chromium.launch();
} catch (error) {
  console.error("Could not verify the preview or start Chromium", error);
  process.exit(2);
}

const failures = [];
let environmentError;
const recordEnvironmentError = (error) => {
  environmentError ??= String(error);
  console.error("Browser check environment error", error);
};
const saveScreenshot = async (page, filename) => {
  try {
    const image = await page.screenshot();
    await writeFile(`${output}/${filename}`, image);
  } catch (error) {
    recordEnvironmentError(error);
  }
};

let checks = 0;
try {
  for (const type of ["rectangle", "ellipse", "diamond"]) {
    let context;
    let page;
    let navigating = false;
    let pageCrashed = false;
    try {
      context = await browser.newContext({
        viewport: { width: 1200, height: 800 },
      });
      page = await context.newPage();
      page.once("crash", () => {
        pageCrashed = true;
        recordEnvironmentError(new Error("Page crashed"));
      });
      const read = () =>
        page.evaluate(() =>
          JSON.parse(localStorage.getItem("excalidraw") || "[]"),
        );
      navigating = true;
      await page.goto(baseURL, {
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
      await saveScreenshot(page, `${type}-resized.png`);
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
      await saveScreenshot(page, `${type}-undo.png`);
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
      if (pageCrashed && !(error instanceof assert.AssertionError)) {
        break;
      }
      const previewUnavailable =
        navigating &&
        (error?.name === "TimeoutError" ||
          /net::ERR_(CONNECTION_REFUSED|CONNECTION_RESET|CONNECTION_CLOSED|EMPTY_RESPONSE|TIMED_OUT)\b/.test(
            String(error),
          ));
      if (
        !(error instanceof assert.AssertionError) &&
        (!page || !browser.isConnected() || previewUnavailable)
      ) {
        recordEnvironmentError(error);
        break;
      } else {
        failures.push({ type, error: String(error) });
        if (page) {
          await saveScreenshot(page, `${type}-failure.png`);
        }
      }
    } finally {
      await context?.close().catch(recordEnvironmentError);
    }
    if (pageCrashed) {
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
