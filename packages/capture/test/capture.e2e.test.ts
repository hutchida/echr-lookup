import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import os from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { capture, CaptureError } from "../src/index.js";

const PAGE = `<!doctype html><title>t</title>
<main><h1 id="title">Hello capture</h1>
<input id="q" /><button id="go" onclick="document.getElementById('out').textContent='Searched: '+document.getElementById('q').value">Go</button>
<p id="out"></p></main>`;

async function chromiumInstalled(): Promise<boolean> {
  try {
    const { chromium } = await import("playwright");
    return existsSync(chromium.executablePath());
  } catch {
    return false;
  }
}

const hasChromium = await chromiumInstalled();
const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47]);

let server: Server;
let baseUrl: string;
let outDir: string;

beforeAll(async () => {
  outDir = mkdtempSync(path.join(os.tmpdir(), "echr-capture-"));
  server = createServer((_req, res) => {
    res.setHeader("content-type", "text/html");
    res.end(PAGE);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

afterAll(async () => {
  await new Promise((resolve) => server.close(resolve));
  rmSync(outDir, { recursive: true, force: true });
});

describe("capture (needs no browser)", () => {
  it("fails clearly when nothing is listening", async () => {
    const dead = createServer();
    await new Promise<void>((resolve) => dead.listen(0, "127.0.0.1", resolve));
    const port = (dead.address() as AddressInfo).port;
    await new Promise((resolve) => dead.close(resolve));
    const run = capture({
      baseUrl: `http://127.0.0.1:${port}`,
      outDir,
      steps: [
        { action: "goto", url: "/" },
        { action: "screenshot", name: "never" },
      ],
    });
    await expect(run).rejects.toThrow(CaptureError);
    await expect(run).rejects.toThrow(/Is `pnpm dev` running on 127\.0\.0\.1/);
  });
});

describe.skipIf(!hasChromium)("capture (end to end, needs Chromium)", () => {
  it("drives the page and writes deterministic PNGs", async () => {
    const steps = [
      { action: "goto", url: "/" },
      { action: "fill", selector: "#q", value: "Soering" },
      { action: "click", selector: "#go" },
      { action: "waitFor", text: "Searched: Soering" },
      { action: "highlight", selector: "#out" },
      { action: "screenshot", name: "full" },
      { action: "screenshot", name: "crop", selector: "#title" },
    ] as const;
    const files = await capture({ baseUrl, outDir, steps: [...steps] });
    expect(files.map((f) => path.basename(f))).toEqual(["full.png", "crop.png"]);
    for (const f of files) expect(readFileSync(f).subarray(0, 4)).toEqual(PNG_MAGIC);
    const full = statSync(files[0]!).size;
    const crop = statSync(files[1]!).size;
    expect(crop).toBeLessThan(full);

    // Re-running overwrites the same names instead of adding new files.
    const again = await capture({ baseUrl, outDir, steps: [...steps] });
    expect(again).toEqual(files);
  }, 30_000);

  it("reports which step failed", async () => {
    const run = capture({
      baseUrl,
      outDir,
      steps: [
        { action: "goto", url: "/" },
        { action: "waitFor", selector: "#missing", timeoutMs: 500 },
        { action: "screenshot", name: "never" },
      ],
    });
    await expect(run).rejects.toThrow(/Step 2 .*failed/);
  }, 30_000);
});
