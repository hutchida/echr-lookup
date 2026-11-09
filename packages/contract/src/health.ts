import { z } from "zod";

export const Health = z
  .object({
    status: z.enum(["ok", "degraded"]),
    service: z.literal("echr-lookup-api"),
    version: z.string(),
    db: z.object({
      reachable: z.boolean(),
      extensions: z.array(z.string()).describe("Postgres extensions installed, e.g. vector, pg_search"),
    }),
    data_source: z.enum(["snapshot", "full"]),
  })
  .strict()
  .meta({ id: "Health", description: "GET /health response" });

export type Health = z.infer<typeof Health>;
