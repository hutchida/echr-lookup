# MCP tools: citations, labels, links and instructions (F1)

## 1. What this is, in plain English

**MCP** (Model Context Protocol) is an open standard that lets an AI app such as Claude call tools that live in another program. echr-lookup runs as an MCP server with six read-only tools. Claude reads what they return and writes the answer; the server never calls a language model itself.

The six tools:

| Tool | What it returns |
|---|---|
| `search_case_law` | the paragraphs that best match a question (keyword + meaning search, reranked), each with a quote |
| `get_paragraphs` | the full text of paragraphs by id, optionally with their neighbours |
| `get_case` | one document's metadata, outcome, operative provisions (what the Court decided) and outline |
| `count_cases` | any "how many" answer, from a fixed, validated SQL template; every number, the definitions, the SQL |
| `corpus_info` | what the corpus contains and what it lacks |
| `check_quote` | whether a quote appears word for word in a paragraph |

Every paragraph a tool returns comes with four fields the answer is built from:

- **`quote`** (search) or **`text`** (get_paragraphs): the verbatim words. Only this text may be quoted.
- **`cite`**: a ready-to-paste citation, such as `[Chahal v. the United Kingdom, Judgment, §79]`. The answer ends every factual sentence with one, copied exactly.
- **`para_label`**: the readable last part of `cite` (`§79`, `Law, para 2`). Display only.
- **`hudoc_url`**: a link to the document on HUDOC (legislation: its official site), which for a quote opens the page **and highlights the quote's first words**.

The stable key of a paragraph is still **`paragraph_id`** (`001-58004§79`, `002-74§u6`). The eval answer keys depend on it; nothing in this change touches it.

## 2. Why it matters

In the first comparison (`docs/mcp-comparison.md`), Claude with these tools answered well, but 58-65% of its claims had no citation, 31-35% of its quoted passages were not verbatim, it added a case from general knowledge, and it opened broad answers with a bare "Yes". Citations like `§u59` also meant nothing to a reader, and a link to a 100-page judgment does not say where to look.

Now `[Harkins and Edwards v. the United Kingdom, Legal summary, Law, para 2]` says what and where, and its link lands on the sentence that was quoted.

## 3. How it works here

```
 tool call ──► py/echr_mcp/tools.py ──► picks a paragraph + its quote
                    │
                    ├─ labels.py   para_label  ("§79" | "Law, para 2" | "Article 8")
                    ├─ common.py   cite(name, doc type, para_label)      -> "[..., ..., ...]"
                    │              unique_cites(items)                   -> doc id added only if two clash
                    └─ common.py   with_text_fragment(url, quote)        -> "...#:~:text=First%20words"
 server.py    INSTRUCTIONS (the system text every client sees) + TOOL_SPECS (one description per tool)
 packages/contract/src/mcp/*.ts   the shapes (zod -> JSON Schema -> fixtures)
```

### `para_label` rules (`py/echr_mcp/labels.py`)

I read how ids look in the 98-document snapshot first: numbered paragraphs are `§79`; unnumbered ones are `§u12` (headings, opinions, every paragraph of a legal summary), `§op3` (operative provisions); legislation uses `§art8`, `§s3`, `§p1-art1`, `§preamble`.

| Paragraph | Label | Example |
|---|---|---|
| numbered | `§<number>` | `§79` |
| unnumbered, in a judgment / decision / communicated case | `<Section>, para <n>`; `n` counts the unnumbered paragraphs of that section in document order; section is the stored one without "The " (Procedure, Facts, Law, Operative provisions, Other) | `Operative provisions, para 2`, `Law, para 28` |
| legal summary (all unnumbered) | `<Part>, para <n>`; the stored section is mostly "Other", so the part comes from the text: `Summary` until a paragraph starting "Facts", then `Facts`, then `Law` from the paragraph starting "Law"; footnotes `[1] …` are `Notes`; `n` counts every paragraph of the part | `Law, para 2` |
| legislation | read from the id | `Article 8`, `section 3`, `Protocol 1, Article 1`, `Preamble` |

`cite` is `[<case name>, <document type>, <para_label>]`. Two different paragraphs in one result never share a `cite` string: if the case name, document type and label would be identical (two documents of one name), the doc id is added to the type, `Judgment (001-58004)`. The eval harness maps `cite` strings back to ids from what the tools returned, so this keeps that mapping one-to-one.

### Text fragments

A **text fragment** is a browser feature: a link that ends `#:~:text=some%20words` makes the browser scroll to the first place on the page where "some words" appears and highlight it. `:~:` marks the part as a **fragment directive** (browser-only, never sent to the server, hidden from the page's own JavaScript); `text=` names the kind.

We append it to every `hudoc_url` that has a quote: the first 8 whole words of the result's `quote` (search) or `text` (get_paragraphs), exactly as returned (no normalising, a leading or trailing `…` cut marker excluded). If a URL already has a `#…` part, `:~:text=` is added after it with no second `#`; our stored HUDOC links are `…/eng?i=<id>` with none, so a `#` is added. If eight words would encode to more than 120 characters (very long words), fewer are used; `hudoc_url` is capped at 400 characters in the contract (it was uncapped before; the worst case search result stays under 25 KB: 24,754 bytes, was 22,804).

The words are **percent-encoded**: each unsafe character becomes `%` plus two hex digits of its UTF-8 bytes (space `%20`, `§` `%C2%A7`, `é` `%C3%A9`, curly `’` `%E2%80%99`). Letters, digits and `_ . ! ~ * ' ( )` stay as they are (what JavaScript's `encodeURIComponent` leaves). Three characters are additionally encoded because the directive's own syntax uses them: **`-`** (`%2D`, separates the optional prefix/suffix parts of a directive: `prefix-,start,end,-suffix`), **`,`** (`%2C`, separates start from end) and **`&`** (`%26`, separates several directives). Left raw, a hyphen in "well-established" or a comma in "Court, however" would be read as syntax and the match would fail.

Where a result has **no quote** the URL is left as it is: `get_case.hudoc_url` and `count_cases.matching_cases[].hudoc_url` link to the case, not to a passage.

**Untested in a browser.** I cannot open a browser here, and HUDOC is a JavaScript app that builds its page after loading, and may rewrite the address. The highlight may therefore fail. If it does, the link still opens the case. Dan verifies (try-it 3).

### The server instructions

`INSTRUCTIONS` (about 240 words) is text the server hands every client; Claude reads it as guidance. In order of importance: (1) every factual sentence ends with a `cite` copied from a tool result, otherwise it does not go in; (2) quote only text copied from results and call `check_quote` first; (3) use only cases the tools returned, and if nothing relevant comes back, say so and state the corpus limits, never add cases from memory; (4) open with one sentence that answers the question, then grouped evidence, about 8-10 claims; (5) no bare Yes/No unless a cited paragraph states the general rule, lead with the holding's reach ("Only where…"); (6) `count_cases` for every "how many"; then the legal-summary and neutrality lines. Each tool's description also says what its `cite`, `quote` and `hudoc_url` are for.

## 4. Try it

All commands from the repo root; the database must be up (`pnpm db:up`) and loaded (`DATABASE_URL` in `.env`).

**1. `cite` with `para_label`, and `hudoc_url` with a text fragment**

```bash
cd py && uv run --group ml python ../scripts/mcp_call.py call search_case_law \
  '{"query":"extradition life imprisonment without parole","limit":2}' 2>/dev/null \
  | grep -E '"(paragraph_id|para_label|hudoc_url|cite)"'
```

Expected (first hit; ranking can shift if models change):

```
      "paragraph_id": "002-74§u4",
      "para_label": "Facts, para 1",
      "hudoc_url": "https://hudoc.echr.coe.int/eng?i=002-74#:~:text=Facts%20%E2%80%93%20Both%20applicants%20faced%20extradition%20from%20the",
      "cite": "[Harkins and Edwards v. the United Kingdom, Legal summary, Facts, para 1]"
```

Proves: the readable label is in `cite`, the id is unchanged, and the link carries the quote's first eight words with the en dash `–` encoded.

**2. A numbered paragraph, an unnumbered one, `check_quote`**

```bash
cd py && uv run --group ml python ../scripts/mcp_call.py call check_quote \
  '{"paragraph_id":"002-74§u6","quote":"presumption of good faith"}' 2>/dev/null \
  | grep -E '"(verbatim|para_label|cite)"'
```

Expected: `"verbatim": true`, `"para_label": "Law, para 2"`, `"cite": "[Harkins and Edwards v. the United Kingdom, Legal summary, Law, para 2]"`. Proves: the Harkins legal summary's `Law` part starts at `§u5` ("Law – Article 3"), so `§u6` is its paragraph 2.

**3. Three links to open by hand (Dan)**

Built from the real database (`echr_f1`, 98-document snapshot) with `get_paragraphs`:

```bash
cd py && uv run --group ml python ../scripts/mcp_call.py call get_paragraphs \
  '{"paragraph_ids":["002-74§u6","001-58004§79","001-98645§14"]}' 2>/dev/null \
  | grep -E '"(cite|hudoc_url)"'
```

| # | Document | Link | The page should highlight |
|---|---|---|---|
| 1 | Harkins and Edwards, legal summary, `[… Legal summary, Law, para 2]` | <https://hudoc.echr.coe.int/eng?i=002-74#:~:text=(a)%20Death%20penalty%20%E2%80%93%20The%20Court%20reiterated%20that> | "(a) Death penalty – The Court reiterated that" |
| 2 | Chahal, judgment, `[… Judgment, §79]` | <https://hudoc.echr.coe.int/eng?i=001-58004#:~:text=Article%203%20(art.%203)%20enshrines%20one%20of%20the> | "Article 3 (art. 3) enshrines one of the" (start of §79) |
| 3 | Miah, decision, `[Miah v. the United Kingdom, Decision, §14]` | <https://hudoc.echr.coe.int/eng?i=001-98645#:~:text=In%20the%20Court's%20view%2C%20neither%20of%20these%20complaints> | "In the Court's view, neither of these complaints" (start of §14) |

**Untested in a browser.** HUDOC is a JavaScript app and may drop or ignore the fragment, or render the text after the browser has stopped looking, in which case nothing is highlighted. The link then just opens the case (for #1, the legal summary), which is the fallback. Please open each in Chrome (or Edge/Safari) and note which highlight; HUDOC's text may differ slightly from the database's (spacing, `(art. 3)`).

**4. The encoding and label unit tests**

```bash
cd py && uv run pytest echr_mcp/tests/test_fragments.py echr_mcp/tests/test_labels.py -q
```

Expected: `31 passed`. Proves: `-` `&` `,` quotes `“ ”` `’` accents `é` and `§` encode as described; a URL with an existing `#…` gets no second `#`; labels follow the table above; clashing cites get the doc id; `paragraph_id`s match a golden list recorded before the change (`golden_paragraph_ids.json`).

**5. The whole contract, both sides**

```bash
pnpm check
```

Expected: TypeScript and Python tests pass (the Python run includes the stdio MCP test, `py/echr_mcp/tests/test_stdio.py`, which starts the real server and calls all six tools against the published schemas). Proves: results still validate against the JSON Schemas and stay under 25 KB.

**6. The instructions**

```bash
cd py && uv run python -c "from echr_mcp.server import INSTRUCTIONS; print(len(INSTRUCTIONS.split()), 'words'); print(INSTRUCTIONS)"
```

Expected: about 240 words, the eight points above.

Fixtures with real tool output are regenerated, not edited: `cd py && uv run --group ml python -m echr_mcp.regen_fixtures`.

## 5. Limits / what can go wrong

- A text fragment needs the words to appear contiguously in the page text. HUDOC's rendering may differ from our stored text (spacing, typographic characters, footnote marks), and it is a JavaScript app, so the highlight may fail. Fragments only highlight the first match on the page.
- `para_label` for a legal summary depends on its "Facts" and "Law" paragraphs; a summary without them is all `Summary`. For judgments the counter `n` is among the **unnumbered** paragraphs of the section, so `Law, para 2` is not "paragraph 2 of the Law" in a judgment that also has numbered paragraphs.
- Labels are display only and are not stable across re-ingests that change the paragraph order. Use `paragraph_id` for anything stored.
- Instructions are guidance, not enforcement: a host model can still ignore them. The eval (F3) measures how well they work.
- `docs/interfaces-mcp.md` §3 and the eval harness's fake server still hold the earlier instruction text; they are outside this task and unchanged.
