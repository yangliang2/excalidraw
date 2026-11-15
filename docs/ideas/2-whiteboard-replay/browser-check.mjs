// Start the app first. CHROME_PATH and REPLAY_ORIGIN are optional.
import assert from "node:assert/strict";
import { chromium } from "playwright";
const origin = process.env.REPLAY_ORIGIN || "http://localhost:5173";
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || undefined,
  args: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
  ],
});
try {
  const author = await browser.newContext({ permissions: ["microphone"] });
  const page = await author.newPage();
  page.on("pageerror", (e) => console.error(e.message));
  await page.goto(origin);
  await page.getByRole("button", { name: "录制选区讲解" }).waitFor();
  await page.keyboard.press("r");
  await page.mouse.move(420, 180);
  await page.mouse.down();
  await page.mouse.move(650, 280);
  await page.mouse.up();
  await page.keyboard.press("v");
  await page.keyboard.press("ControlOrMeta+a");
  await page.getByText("录制选区讲解", { exact: true }).click();
  const stage = page.locator("svg[aria-label='评审定稿']");
  await stage.waitFor();
  await page.getByText("开始录制").click();
  await page.getByText("结束录制").waitFor();
  await page.mouse.move(380, 230);
  await page.waitForTimeout(300);
  await page.mouse.move(620, 260);
  await page.waitForTimeout(1300);
  await page.getByText("结束录制").click();
  let encrypted;
  await page.route("**/api/v2/post/", async (route) => {
    encrypted = route.request().postDataBuffer();
    await route.fulfill({
      json: { id: "testclip" },
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  });
  await page.getByText("生成试用链接").click();
  const link = page.getByLabel("试用链接", { exact: true });
  await link.waitFor();
  const url = await link.inputValue();
  assert.ok(encrypted?.length);
  const reader = await browser.newContext();
  const tab = await reader.newPage();
  await tab.route("**/api/v2/testclip", (route) =>
    route.fulfill({
      body: encrypted,
      headers: { "Access-Control-Allow-Origin": "*" },
    }),
  );
  await tab.goto(url);
  const scene = tab.locator("svg[aria-label='评审定稿']");
  await scene.waitFor();
  const audio = tab.locator("audio");
  await audio.evaluate((el) => el.play());
  await tab.waitForTimeout(400);
  await audio.evaluate((el) => el.pause());
  const before = await scene.getAttribute("viewBox");
  await scene.hover();
  await tab.mouse.wheel(0, -150);
  await tab.waitForFunction(
    (old) =>
      document
        .querySelector("svg[aria-label='评审定稿']")
        .getAttribute("viewBox") !== old,
    before,
  );
  await audio.evaluate((el) => el.play());
  await tab.waitForFunction(
    (old) =>
      document
        .querySelector("svg[aria-label='评审定稿']")
        .getAttribute("viewBox") === old,
    before,
  );
  console.log(
    "PASS: selected snapshot, synthetic microphone, encrypted link round trip in a fresh context, paused zoom, resume recorded viewport",
  );
} finally {
  await browser.close();
}
