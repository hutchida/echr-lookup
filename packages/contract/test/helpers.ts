import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { z } from "zod";

export const root = join(dirname(fileURLToPath(import.meta.url)), "..");
export const repoRoot = join(root, "..", "..");
export const readJson = (p: string): unknown => JSON.parse(readFileSync(p, "utf8"));

/** fixtures/<Name>.json is the primary fixture; fixtures/<Name>.<variant>.json covers extra branches. */
export const FIXTURE_FILE = /^([A-Za-z]+)(?:\.([a-z0-9-]+))?\.json$/;

export interface FixtureFile {
  file: string;
  name: string;
  variant: string | null;
}

export function listFixtures(): FixtureFile[] {
  return readdirSync(join(root, "fixtures"))
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((file) => {
      const m = FIXTURE_FILE.exec(file);
      return { file, name: m?.[1] ?? file, variant: m?.[2] ?? null };
    });
}

interface Def {
  type: string;
  shape?: Record<string, z.ZodType>;
  element?: z.ZodType;
  innerType?: z.ZodType;
  options?: z.ZodType[];
}
const defOf = (s: z.ZodType): Def => (s as unknown as { _zod: { def: Def } })._zod.def;

/** Every object property path a schema can contain, e.g. `hits[].scores.bm25_rank`. */
export function schemaPaths(schema: z.ZodType, prefix = ""): string[] {
  const def = defOf(schema);
  switch (def.type) {
    case "object":
      return Object.entries(def.shape ?? {}).flatMap(([key, child]) => {
        const path = prefix ? `${prefix}.${key}` : key;
        return [path, ...schemaPaths(child, path)];
      });
    case "array":
      return schemaPaths(def.element!, `${prefix}[]`);
    case "optional":
    case "nullable":
    case "default":
    case "readonly":
      return schemaPaths(def.innerType!, prefix);
    case "union":
      return (def.options ?? []).flatMap((o) => schemaPaths(o, prefix));
    default:
      return [];
  }
}

/** Every object key path present in a JSON value (a key with value null counts as present). */
export function dataPaths(value: unknown, prefix = ""): string[] {
  if (Array.isArray(value)) return value.flatMap((v) => dataPaths(v, `${prefix}[]`));
  if (value !== null && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) => {
      const path = prefix ? `${prefix}.${key}` : key;
      return [path, ...dataPaths(child, path)];
    });
  }
  return [];
}
