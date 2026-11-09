import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { capture, CaptureError, parseSpec, repoRoot } from "./index.js";

const USAGE = "usage: pnpm capture <spec.json> [--base-url http://localhost:3100]";

/** `pnpm --filter` runs us inside packages/capture, so try the caller's dir (INIT_CWD) and the repo root too. */
function findSpec(arg: string): string {
  if (path.isAbsolute(arg)) return arg;
  const candidates = [process.env.INIT_CWD, repoRoot(), process.cwd()]
    .filter((d): d is string => !!d)
    .map((d) => path.resolve(d, arg));
  const hit = candidates.find((c) => existsSync(c));
  if (!hit) throw new CaptureError(`Spec file not found: ${arg}\n${USAGE}`);
  return hit;
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  let baseUrlOverride = process.env.CAPTURE_BASE_URL;
  const positional: string[] = [];
  for (let i = 0; i < args.length; i++) {
    const a = args[i] ?? "";
    if (a === "--base-url") baseUrlOverride = args[++i];
    else if (a.startsWith("--base-url=")) baseUrlOverride = a.slice("--base-url=".length);
    else if (a === "-h" || a === "--help") {
      console.log(USAGE);
      return;
    } else positional.push(a);
  }
  const [specArg] = positional;
  if (!specArg || positional.length > 1) throw new CaptureError(USAGE);

  const specPath = findSpec(specArg);
  let raw: unknown;
  try {
    raw = JSON.parse(await readFile(specPath, "utf8"));
  } catch (err) {
    throw new CaptureError(`Could not read ${specPath} as JSON: ${(err as Error).message}`);
  }
  if (baseUrlOverride && typeof raw === "object" && raw !== null) {
    raw = { ...raw, baseUrl: baseUrlOverride };
  }
  const spec = parseSpec(raw);
  const files = await capture(spec);
  for (const f of files) console.log(`wrote ${path.relative(repoRoot(), f)}`);
}

main().catch((err: unknown) => {
  console.error(err instanceof CaptureError ? err.message : err);
  process.exit(1);
});
