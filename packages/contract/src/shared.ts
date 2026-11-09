import { z } from "zod";
import { LIMITS } from "./limits";

export const DOC_TYPES = ["judgment", "decision", "communicated", "legal_summary", "legislation"] as const;
export const DocType = z.enum(DOC_TYPES);

export const CHAMBERS = ["Grand Chamber", "Chamber", "Committee"] as const;

/**
 * Normalised outcome (derived from HUDOC's raw `conclusion`):
 * - mixed: at least one violation AND at least one "no violation" finding
 * - violation / no_violation: only that kind of finding
 * - inadmissible: whole application declared inadmissible
 * - partly_inadmissible: partly admissible / partly inadmissible / partly struck out
 * - struck_out, admissible: as HUDOC says
 * - other: none of the above (e.g. just-satisfaction rulings, preliminary objections)
 * - not_applicable: legislation, communicated cases
 */
export const OUTCOMES = [
  "violation",
  "no_violation",
  "mixed",
  "inadmissible",
  "partly_inadmissible",
  "struck_out",
  "admissible",
  "other",
  "not_applicable",
] as const;
export const Outcome = z.enum(OUTCOMES);

/**
 * Why an application (or part of it) was declared inadmissible. HUDOC's `conclusion` names the ground for only
 * a small minority of decisions (18 of 671 Court decisions); the rest come from the decision text.
 * - manifestly_ill_founded: Art 35 s3(a), "manifestly ill-founded"
 * - non_exhaustion: Art 35 s1, domestic remedies not exhausted (includes "premature")
 * - out_of_time: Art 35 s1, six-month rule
 * - incompatible_ratione_*: Art 35 s3(a), outside the Convention's subject matter / persons / time / territory
 * - abuse_of_right: Art 35 s3(a)
 * - no_significant_disadvantage: Art 35 s3(b)
 * - substantially_same: Art 35 s2(b), already examined by the Court / another procedure
 * - not_a_victim: Art 34, applicant is not (or no longer) a victim
 * - other: a stated ground that is none of the above
 */
export const INADMISSIBILITY_GROUNDS = [
  "manifestly_ill_founded",
  "non_exhaustion",
  "out_of_time",
  "incompatible_ratione_materiae",
  "incompatible_ratione_personae",
  "incompatible_ratione_temporis",
  "incompatible_ratione_loci",
  "abuse_of_right",
  "no_significant_disadvantage",
  "substantially_same",
  "not_a_victim",
  "other",
] as const;
export const InadmissibilityGround = z.enum(INADMISSIBILITY_GROUNDS);

export const DataSource = z.enum(["snapshot", "full"]);
export const ChunkStrategy = z.enum(["fixed", "recursive", "by_section"]);
export const SearchMode = z.enum(["bm25", "vector", "hybrid", "hybrid_rerank"]);
export const Section = z.enum(["Procedure", "The Facts", "The Law", "Operative provisions", "Other"]);

/** HUDOC item id (`001-57619`) or a legislation id (`echr-convention`, `ukpga-1998-42`). */
export const DocId = z
  .string()
  .max(LIMITS.docIdMaxChars)
  .regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/);

/**
 * `<doc-id>§<ref>`. ref is: `88` (numbered paragraph), `op3` (operative-provisions item),
 * `u12` (unnumbered or non-main-text paragraph, 1-based running index), or for legislation
 * `art8` / `s3` (article or section).
 */
export const ParagraphId = z
  .string()
  .max(LIMITS.paragraphIdMaxChars)
  .regex(/^[A-Za-z0-9][A-Za-z0-9._-]*§[A-Za-z0-9._-]+$/);

export const IsoDateTime = z.iso.datetime();
export const IsoDate = z.iso.date();
export const Count = z.number().int().min(0);
export const Score01 = z.number().min(0).max(1);
