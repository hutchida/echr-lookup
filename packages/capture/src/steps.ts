import { z } from "zod";

const name = z
  .string()
  .regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/, "name must be a plain file stem like 'C1-home' (no slashes)");

const selector = z.string().min(1);

export const captureStepSchema = z.discriminatedUnion("action", [
  z.object({ action: z.literal("goto"), url: z.string().min(1) }).strict(),
  z.object({ action: z.literal("click"), selector }).strict(),
  z.object({ action: z.literal("fill"), selector, value: z.string() }).strict(),
  z
    .object({ action: z.literal("press"), key: z.string().min(1), selector: selector.optional() })
    .strict(),
  z.object({ action: z.literal("wait"), ms: z.number().int().min(0).max(60_000) }).strict(),
  z
    .object({
      action: z.literal("waitFor"),
      selector: selector.optional(),
      text: z.string().min(1).optional(),
      timeoutMs: z.number().int().positive().max(120_000).optional(),
    })
    .strict()
    .refine((s) => (s.selector === undefined) !== (s.text === undefined), {
      message: "waitFor needs exactly one of 'selector' or 'text'",
    }),
  z
    .object({
      action: z.literal("screenshot"),
      name,
      selector: selector.optional(),
      fullPage: z.boolean().optional(),
    })
    .strict(),
  z
    .object({ action: z.literal("highlight"), selector, color: z.string().min(1).optional() })
    .strict(),
]);

export type CaptureStep = z.infer<typeof captureStepSchema>;

export const viewportSchema = z.object({
  width: z.number().int().positive(),
  height: z.number().int().positive(),
});

export const captureSpecSchema = z
  .object({
    baseUrl: z.url(),
    steps: z.array(captureStepSchema).min(1),
    outDir: z.string().min(1).optional(),
    viewport: viewportSchema.optional(),
    fullPage: z.boolean().optional(),
  })
  .strict()
  .superRefine((spec, ctx) => {
    if (spec.steps[0]?.action !== "goto") {
      ctx.addIssue({ code: "custom", path: ["steps", 0], message: "the first step must be 'goto'" });
    }
    if (!spec.steps.some((s) => s.action === "screenshot")) {
      ctx.addIssue({ code: "custom", path: ["steps"], message: "spec has no 'screenshot' step" });
    }
  });

export type CaptureSpec = z.infer<typeof captureSpecSchema>;

export class CaptureError extends Error {
  override name = "CaptureError";
}

/** Parse + validate an untrusted spec (e.g. JSON from disk). Throws CaptureError with a readable list. */
export function parseSpec(input: unknown): CaptureSpec {
  const result = captureSpecSchema.safeParse(input);
  if (result.success) return result.data;
  const lines = result.error.issues.map((i) => `  - ${i.path.join(".") || "(spec)"}: ${i.message}`);
  throw new CaptureError(`Invalid capture spec:\n${lines.join("\n")}`);
}
