/** The three demo questions (docs/orchestration/tasks/gate2-common.md). Used by the home page and /ask. */
export const DEMO_QUESTIONS = [
  { short: "Deporting criminals", question: "Does the Convention stop the UK deporting criminals?" },
  { short: "Article 8 and immigration", question: "How has Article 8 been applied in UK immigration cases?" },
  {
    short: "Inadmissible deportation complaints (SQL)",
    question:
      "How many UK deportation complaints in the corpus were declared inadmissible, and the most common reasons?",
  },
] as const;

export const askHref = (question: string): string => `/ask?q=${encodeURIComponent(question)}`;
