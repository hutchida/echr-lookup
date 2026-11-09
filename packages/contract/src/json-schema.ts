import { z } from "zod";
import { registry } from "./registry";

/** Serialised JSON Schema (draft 2020-12) for every registered schema, keyed by name. */
export function toJsonSchemas(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, schema] of Object.entries(registry)) {
    const json = z.toJSONSchema(schema, { target: "draft-2020-12", io: "output" });
    out[name] = `${JSON.stringify(json, null, 2)}\n`;
  }
  return out;
}
