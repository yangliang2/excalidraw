import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

test("CSS assets cannot be omitted or exceed the explicit growth tolerance", () => {
  const root = mkdtempSync(join(tmpdir(), "excalidraw-size-"));
  try {
    for (const tree of ["base", "head"]) {
      mkdirSync(join(root, tree, "locales"), { recursive: true });
      for (const file of [
        "index.js",
        "chunk.js",
        "locales/en.js",
        "index.css",
      ]) {
        writeFileSync(join(root, tree, file), "/* fixture */");
      }
    }
    const run = () =>
      spawnSync(
        process.execPath,
        [
          "scripts/check-package-size.mjs",
          join(root, "base"),
          join(root, "head"),
        ],
        { encoding: "utf8" },
      );
    assert.equal(run().status, 0);
    writeFileSync(
      join(root, "head/index.css"),
      `/* ${randomBytes(4096).toString("hex")} */`,
    );
    assert.equal(
      run().status,
      1,
      "CSS growth beyond 1024 gzip bytes must fail",
    );
    rmSync(join(root, "head/index.css"));
    assert.notEqual(run().status, 0, "missing candidate CSS must fail");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
