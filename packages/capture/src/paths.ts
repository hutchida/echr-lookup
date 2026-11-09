import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** Repo root = nearest ancestor of this package containing pnpm-workspace.yaml. */
export function repoRoot(from: string = path.dirname(fileURLToPath(import.meta.url))): string {
  let dir = from;
  for (;;) {
    if (existsSync(path.join(dir, "pnpm-workspace.yaml"))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) throw new Error(`could not find the repo root above ${from}`);
    dir = parent;
  }
}

export function resolveOutDir(outDir: string, root: string = repoRoot()): string {
  return path.isAbsolute(outDir) ? outDir : path.resolve(root, outDir);
}

/** Absolute URL for a goto step: relative paths ('/ask') resolve against baseUrl. */
export function resolveUrl(url: string, baseUrl: string): string {
  return new URL(url, baseUrl).toString();
}
