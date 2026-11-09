import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CaptureError, parseSpec, repoRoot, resolveOutDir, resolveUrl } from "../src/index.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const base = { baseUrl: "http://localhost:3100" };
const shot = { action: "screenshot", name: "x" };

describe("parseSpec", () => {
  it("accepts every step type", () => {
    const spec = parseSpec({
      ...base,
      steps: [
        { action: "goto", url: "/" },
        { action: "click", selector: "button" },
        { action: "fill", selector: "input", value: "Soering" },
        { action: "press", key: "Enter" },
        { action: "press", key: "Enter", selector: "input" },
        { action: "wait", ms: 100 },
        { action: "waitFor", selector: "main" },
        { action: "waitFor", text: "Results", timeoutMs: 5000 },
        { action: "highlight", selector: "h1", color: "red" },
        { action: "screenshot", name: "C1-a", selector: "main", fullPage: true },
      ],
    });
    expect(spec.steps).toHaveLength(10);
  });

  it("accepts optional outDir / viewport / fullPage", () => {
    const spec = parseSpec({
      ...base,
      outDir: "tmp",
      viewport: { width: 800, height: 600 },
      fullPage: true,
      steps: [{ action: "goto", url: "/" }, shot],
    });
    expect(spec.viewport).toEqual({ width: 800, height: 600 });
  });

  it.each([
    ["not a URL", { baseUrl: "nope", steps: [{ action: "goto", url: "/" }, shot] }, "baseUrl"],
    ["empty steps", { ...base, steps: [] }, "steps"],
    ["no goto first", { ...base, steps: [shot] }, "first step must be 'goto'"],
    ["no screenshot", { ...base, steps: [{ action: "goto", url: "/" }] }, "no 'screenshot' step"],
    [
      "unknown action",
      { ...base, steps: [{ action: "goto", url: "/" }, { action: "hover", selector: "a" }, shot] },
      "steps.1",
    ],
    [
      "missing field",
      { ...base, steps: [{ action: "goto", url: "/" }, { action: "click" }, shot] },
      "steps.1.selector",
    ],
    [
      "waitFor with both",
      { ...base, steps: [{ action: "goto", url: "/" }, { action: "waitFor", selector: "a", text: "b" }, shot] },
      "exactly one",
    ],
    [
      "waitFor with neither",
      { ...base, steps: [{ action: "goto", url: "/" }, { action: "waitFor" }, shot] },
      "exactly one",
    ],
    [
      "path-like screenshot name",
      { ...base, steps: [{ action: "goto", url: "/" }, { action: "screenshot", name: "../evil" }] },
      "plain file stem",
    ],
    [
      "negative wait",
      { ...base, steps: [{ action: "goto", url: "/" }, { action: "wait", ms: -1 }, shot] },
      "steps.1.ms",
    ],
    [
      "extra key",
      { ...base, steps: [{ action: "goto", url: "/", extra: 1 }, shot] },
      "steps.0",
    ],
  ])("rejects: %s", (_label, input, fragment) => {
    expect(() => parseSpec(input)).toThrow(CaptureError);
    expect(() => parseSpec(input)).toThrow(fragment);
  });
});

describe("paths", () => {
  it("finds the repo root", () => {
    expect(repoRoot(here)).toBe(path.resolve(here, "../../.."));
  });

  it("resolves relative outDir against the repo root and keeps absolute ones", () => {
    const root = repoRoot(here);
    expect(resolveOutDir("docs/learn/img")).toBe(path.join(root, "docs/learn/img"));
    expect(resolveOutDir("/tmp/x")).toBe("/tmp/x");
  });

  it("resolves goto URLs against baseUrl", () => {
    expect(resolveUrl("/case/001-57619", "http://localhost:3100")).toBe(
      "http://localhost:3100/case/001-57619",
    );
    expect(resolveUrl("https://example.com/a", "http://localhost:3100")).toBe("https://example.com/a");
  });
});

describe("shipped specs", () => {
  it.each(["home.json", "example-highlight-crop.json"])("%s is valid", (file) => {
    const raw = JSON.parse(readFileSync(path.join(here, "../specs", file), "utf8"));
    expect(() => parseSpec(raw)).not.toThrow();
  });
});
