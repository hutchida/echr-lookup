import { mkdir } from "node:fs/promises";
import path from "node:path";
import { resolveOutDir, resolveUrl } from "./paths.js";
import { CaptureError, parseSpec, type CaptureSpec, type CaptureStep } from "./steps.js";

export { CaptureError, parseSpec, captureSpecSchema, captureStepSchema } from "./steps.js";
export type { CaptureSpec, CaptureStep } from "./steps.js";
export { repoRoot, resolveOutDir, resolveUrl } from "./paths.js";

export interface CaptureOptions {
  baseUrl: string;
  steps: CaptureStep[];
  /** Relative paths resolve against the repo root. Default "docs/learn/img". */
  outDir?: string;
  /** Default 1280x800. */
  viewport?: { width: number; height: number };
  /** Default for screenshot steps that don't set their own. Default false. */
  fullPage?: boolean;
}

export const DEFAULT_OUT_DIR = "docs/learn/img";
export const DEFAULT_VIEWPORT = { width: 1280, height: 800 };
const DEFAULT_HIGHLIGHT = "#e11d48";
// Next.js dev-mode badge/error overlay: noise in teaching screenshots.
const HIDE_DEV_OVERLAYS = "nextjs-portal { display: none !important; }";
const DEFAULT_TIMEOUT_MS = 15_000;

async function assertReachable(baseUrl: string): Promise<void> {
  try {
    await fetch(baseUrl, { signal: AbortSignal.timeout(5_000), redirect: "manual" });
  } catch (err) {
    const host = new URL(baseUrl).host;
    throw new CaptureError(
      `Could not reach ${baseUrl} (${(err as Error).message}). Is \`pnpm dev\` running on ${host}? ` +
        `(For a non-default port start it with e.g. \`WEB_PORT=3100 pnpm dev\`.)`,
    );
  }
}

/** Drive a browser through `steps`, saving `<outDir>/<name>.png` per screenshot step. Returns the written paths. */
export async function capture(options: CaptureOptions): Promise<string[]> {
  const spec: CaptureSpec = parseSpec(options);
  const outDir = resolveOutDir(spec.outDir ?? DEFAULT_OUT_DIR);
  const viewport = spec.viewport ?? DEFAULT_VIEWPORT;
  const defaultFullPage = spec.fullPage ?? false;

  await assertReachable(spec.baseUrl);
  await mkdir(outDir, { recursive: true });

  const { chromium } = await import("playwright");
  let browser;
  try {
    browser = await chromium.launch();
  } catch (err) {
    throw new CaptureError(
      `Could not start Chromium (${(err as Error).message.split("\n")[0]}). ` +
        "Install it once with: pnpm --filter @echr/capture exec playwright install chromium",
    );
  }

  const written: string[] = [];
  try {
    const page = await browser.newPage({ viewport });
    page.setDefaultTimeout(DEFAULT_TIMEOUT_MS);

    for (const [i, step] of spec.steps.entries()) {
      try {
        switch (step.action) {
          case "goto":
            await page.goto(resolveUrl(step.url, spec.baseUrl), { waitUntil: "load" });
            break;
          case "click":
            await page.locator(step.selector).first().click();
            break;
          case "fill":
            await page.locator(step.selector).first().fill(step.value);
            break;
          case "press":
            if (step.selector) await page.locator(step.selector).first().press(step.key);
            else await page.keyboard.press(step.key);
            break;
          case "wait":
            await page.waitForTimeout(step.ms);
            break;
          case "waitFor": {
            const timeout = step.timeoutMs;
            if (step.selector) await page.locator(step.selector).first().waitFor({ timeout });
            else await page.getByText(step.text ?? "").first().waitFor({ timeout });
            break;
          }
          case "highlight": {
            const color = step.color ?? DEFAULT_HIGHLIGHT;
            await page.locator(step.selector).first().evaluate((el, c) => {
              const style = (el as HTMLElement).style;
              style.outline = `3px solid ${c}`;
              style.outlineOffset = "2px";
            }, color);
            break;
          }
          case "screenshot": {
            const file = path.join(outDir, `${step.name}.png`);
            await page.addStyleTag({ content: HIDE_DEV_OVERLAYS });
            if (step.selector) {
              await page.locator(step.selector).first().screenshot({ path: file });
            } else {
              await page.screenshot({ path: file, fullPage: step.fullPage ?? defaultFullPage });
            }
            written.push(file);
            break;
          }
        }
      } catch (err) {
        if (err instanceof CaptureError) throw err;
        const first = (err as Error).message.split("\n")[0];
        throw new CaptureError(`Step ${i + 1} (${JSON.stringify(step)}) failed: ${first}`);
      }
    }
  } finally {
    await browser.close();
  }
  return written;
}
