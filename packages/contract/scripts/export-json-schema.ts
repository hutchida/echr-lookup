import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { toJsonSchemas } from "../src/json-schema";

const schemaDir = join(dirname(fileURLToPath(import.meta.url)), "..", "schema");
mkdirSync(schemaDir, { recursive: true });

for (const [name, json] of Object.entries(toJsonSchemas())) {
  writeFileSync(join(schemaDir, `${name}.json`), json);
  console.log(`wrote schema/${name}.json`);
}
