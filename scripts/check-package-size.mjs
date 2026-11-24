// Measure shipped ESM assets. Locales load individually; retain their aggregate budget.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

function measure(root) {
  const files = readdirSync(root, { recursive: true }).filter(
    (p) => p.endsWith(".js") || p.endsWith(".css"),
  );
  const groups = [
    ["入口", (p) => p === "index.js", 340000],
    ["语言包", (p) => p.endsWith(".js") && p.startsWith("locales/"), 290000],
    [
      "分块",
      (p) => p.endsWith(".js") && p !== "index.js" && !p.startsWith("locales/"),
      900000,
    ],
    ["样式", (p) => p.endsWith(".css"), null],
  ];
  return groups.map(([name, matches, limit]) => {
    const paths = files.filter(matches);
    if (!paths.length) {
      throw new Error(name + " missing in " + root);
    }
    const bytes = paths.reduce(
      (sum, path) => sum + gzipSync(readFileSync(join(root, path))).byteLength,
      0,
    );
    return { name, bytes, limit };
  });
}
const [base, head] = process.argv.slice(2).map(measure);
for (const [index, group] of head.entries()) {
  const baseline = base[index].bytes;
  console.log(group.name, "gzip bytes", {
    base: baseline,
    head: group.bytes,
    budget: group.limit,
    delta: group.bytes - baseline,
    ...(group.limit === null ? { growthTolerance: 1024 } : {}),
  });
  if (
    group.limit === null
      ? group.bytes > baseline + 1024
      : group.bytes > group.limit && group.bytes > baseline
  ) {
    process.exitCode = 1;
  }
}
