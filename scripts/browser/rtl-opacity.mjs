import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const output = process.env.ARTIFACT_DIR || "test-results/rtl-opacity";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  ...(process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH }
    : {}),
});
const failures = [];
let checks = 0;
let sceneChecks = 0;
try {
  for (const width of [1200, 800]) {
    for (const lang of ["en", "ar", "he"]) {
      const context = await browser.newContext({
        viewport: { width, height: 800 },
      });
      await context.addInitScript((language) => {
        localStorage.setItem("i18nextLng", language);
      }, lang);
      const page = await context.newPage();
      await page.goto(process.env.BASE_URL || "http://127.0.0.1:5173", {
        waitUntil: "domcontentloaded",
      });
      await page.locator("canvas").first().waitFor({ timeout: 90000 });
      await page.getByTestId("toolbar-rectangle").click();
      await page.mouse.move(width - 260, 250);
      await page.mouse.down();
      await page.mouse.move(width - 80, 400);
      await page.mouse.up();
      if (width < 1181)
        await page
          .locator(".compact-action-button.properties-trigger")
          .first()
          .click();
      let rectangleId;
      const sceneOpacity = async (value) => {
        await page.waitForFunction(
          ({ id, opacity }) => {
            const elements = JSON.parse(
              localStorage.getItem("excalidraw") || "[]",
            );
            const rectangle = elements.find(
              (element) =>
                element.type === "rectangle" &&
                !element.isDeleted &&
                (!id || element.id === id),
            );
            return rectangle && rectangle.opacity === opacity;
          },
          { id: rectangleId, opacity: value },
          { timeout: 10000 },
        );
        if (!rectangleId)
          rectangleId = await page.evaluate(
            () =>
              JSON.parse(localStorage.getItem("excalidraw")).find(
                (element) => element.type === "rectangle" && !element.isDeleted,
              ).id,
          );
        sceneChecks++;
      };
      await sceneOpacity(100);
      const input = page.getByTestId("opacity");
      await input.waitFor();
      const verify = async (value, label) => {
        if (width < 1181 && !(await input.isVisible())) {
          await page
            .locator(".compact-action-button.properties-trigger")
            .first()
            .click();
        }
        const actual = await input.evaluate((element) => {
          const win = element.ownerDocument.defaultView;
          const wrapper = element.parentElement;
          const bubble = wrapper.querySelector(".value-bubble");
          const zero = wrapper.querySelector(".zero-label");
          const track = element.getBoundingClientRect();
          const bubbleRect = bubble.getBoundingClientRect();
          const zeroRect = zero.getBoundingClientRect();
          return {
            value: Number(element.value),
            direction: win.getComputedStyle(element).direction,
            gradient: win.getComputedStyle(element).backgroundImage,
            thumbSize: parseFloat(
              win
                .getComputedStyle(element)
                .getPropertyValue("--slider-thumb-size"),
            ),
            left: track.left,
            right: track.right,
            width: track.width,
            bubbleCenter: bubbleRect.left + bubbleRect.width / 2,
            zeroCenter: zeroRect.left + zeroRect.width / 2,
            bubbleText: bubble.textContent,
          };
        });
        const rtl = lang !== "en";
        const progress = value / 100;
        const expected =
          actual.left +
          actual.thumbSize / 2 +
          (actual.width - actual.thumbSize) * (rtl ? 1 - progress : progress);
        const minimum = rtl
          ? actual.right - actual.thumbSize / 2
          : actual.left + actual.thumbSize / 2;
        try {
          assert.equal(actual.value, value, "keyboard/pointer value");
          assert.equal(actual.direction, rtl ? "rtl" : "ltr");
          assert.ok(
            Math.abs(actual.zeroCenter - minimum) < 3,
            "minimum label must follow minimum thumb position",
          );
          assert.ok(
            actual.gradient.includes(rtl ? "to left" : "to right"),
            "fill must grow from the minimum side",
          );
          if (value > 0) {
            assert.equal(actual.bubbleText, String(value));
            assert.ok(
              Math.abs(actual.bubbleCenter - expected) < 2,
              `value label must align with thumb: actual=${actual.bubbleCenter}, expected=${expected}`,
            );
          } else {
            assert.equal(
              actual.bubbleText,
              "",
              "minimum should not have a duplicate label",
            );
          }
          await sceneOpacity(value);
          checks++;
        } catch (error) {
          failures.push(`${lang}/${width}/${label}: ${error.message}`);
        }
      };
      for (const value of [0, 20, 50, 100]) {
        await input.focus();
        await page.keyboard.press("Home");
        for (let i = 0; i < value / 10; i++)
          await page.keyboard.press("ArrowUp");
        await verify(value, String(value));
        if (value === 20)
          await input
            .locator("xpath=ancestor::label")
            .screenshot({ path: `${output}/${lang}-${width}.png` });
      }
      const box = await input.boundingBox();
      const ratio = lang === "en" ? 0.3 : 0.7;
      await page.mouse.click(
        box.x + 8 + (box.width - 16) * ratio,
        box.y + box.height / 2,
      );
      await verify(30, "pointer");
      await input.focus();
      await page.keyboard.press(lang === "en" ? "ArrowRight" : "ArrowLeft");
      await verify(40, "directional-key");
      // Move focus off the range so native input undo cannot mask editor history.
      await input.evaluate((element) => element.blur());
      await page.getByTestId("button-undo").click();
      await verify(30, "undo");
      await page.getByTestId("button-redo").click();
      await verify(40, "redo");
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.locator("canvas").first().waitFor();
      await page.getByTestId("toolbar-selection").click();
      await page.mouse.click(width - 170, 500);
      await page.keyboard.press("ControlOrMeta+a");
      if (width < 1181)
        await page
          .locator(".compact-action-button.properties-trigger")
          .first()
          .click();
      await input.waitFor();
      await verify(40, "reload");
      await context.close();
    }
  }
} finally {
  await browser.close();
}
await writeFile(
  `${output}/result.json`,
  JSON.stringify(
    {
      checks,
      sceneChecks,
      failures,
      baseURL: process.env.BASE_URL || "http://127.0.0.1:5173",
    },
    null,
    2,
  ),
);
console.log(
  `${checks} passed; ${sceneChecks} persisted scene assertions; ${failures.length} failed`,
);
for (const failure of failures) console.error(failure);
assert.equal(failures.length, 0, "RTL opacity browser regression");
