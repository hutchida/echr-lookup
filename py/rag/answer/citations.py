# ruff: noqa: E501
"""Small helpers that turn a paragraph id into what a reader sees: marker, quote, link."""

from __future__ import annotations

import re

QUOTE_MAX_CHARS = 300


def split_paragraph_id(paragraph_id: str) -> tuple[str, str]:
    """'001-57619§88' -> ('001-57619', '88')."""
    doc_id, _, ref = paragraph_id.partition("§")
    return doc_id, ref


def link_target(paragraph_id: str) -> str:
    """Gate 2's case viewer anchors each paragraph as id="p<ref>" (e.g. #p88, #pop3, #pu2)."""
    doc_id, ref = split_paragraph_id(paragraph_id)
    return f"/case/{doc_id}#p{ref}"


def _title_word(word: str) -> str:
    if word in ("UK", "v"):
        return word
    if word in ("V", "AND"):
        return word.lower()
    if re.fullmatch(r"(?:[A-Z]\.)+[A-Z]?\.?", word):  # initials such as "A.H." stay as written
        return word
    return "-".join(part.capitalize() for part in word.split("-"))


def short_case_name(case_name: str, max_chars: int = 40) -> str:
    """'SOERING v. THE UNITED KINGDOM' -> 'Soering v UK' (used inside inline markers)."""
    name = re.sub(r"^CASE OF\s+", "", case_name.strip(), flags=re.IGNORECASE)
    name = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", name)  # [GC], (dec.)
    name = re.sub(r"\bthe united kingdom\b", "UK", name, flags=re.IGNORECASE)
    name = re.sub(r"\bv\.", "v", name)
    letters = [c for c in name if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        name = " ".join(_title_word(w) for w in name.split())
    name = re.sub(r"\s+", " ", name).strip().replace("[", "(").replace("]", ")")
    return name if len(name) <= max_chars else name[: max_chars - 1].rstrip() + "…"


def marker(case_name: str, paragraph_id: str) -> str:
    """'[Soering v UK §88]' -- the inline citation marker in answer_text."""
    return f"[{short_case_name(case_name)} §{split_paragraph_id(paragraph_id)[1]}]"


# A sentence ends at . ! or ? (optionally followed by a closing quote or bracket), then whitespace, then a capital
# letter, digit or opening quote/bracket; a line break (list items such as "v. The ...") always ends one.
# ";" and ":" do not end a sentence, so a quote never opens on "and ...".
_SENTENCE_BREAK = re.compile(r"[.!?][\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-Z0-9])|[ \t]*\n\s*")
_CLAUSE_BREAK = re.compile(r"[;,:]\s+")
# Abbreviations that end in a full stop inside a sentence ("Soering v. the United Kingdom", "(art. 3)", "no. 1234/56").
_ABBREVIATIONS = frozenset(
    re.findall(
        r"\w+",
        "v vs no nos art arts para paras mr mrs ms dr cf eg ie st vol p pp ibid op cit seq ch sec cl sch inc ltd co "
        "jr sr rev",
    )
)
_TOKEN = re.compile(r"[a-z]{4,}|\d+")
_STOPWORDS = frozenset(
    re.findall(
        r"\w+",
        "that this these those with from have been were which would there their they them also under into upon such "
        "than will shall only other where when what whether about after before because being does said made case "
        "cases court held found article articles applicant applicants government united kingdom convention "
        "paragraph paragraphs",
    )
)


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS}


def _matches(claim_token: str, word: str) -> bool:
    if claim_token.isdigit() or word.isdigit():
        return claim_token == word  # "Article 3" must not match "13" or "1993"
    return word.startswith(claim_token) or claim_token.startswith(
        word
    )  # "deport" finds "deportation"


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence; `end` excludes the whitespace before the next sentence."""
    spans, start = [], 0
    for m in _SENTENCE_BREAK.finditer(text):
        if "\n" not in m.group(0) and text[m.start()] == ".":
            before = re.search(r"(\S+)$", text[start : m.start()])
            token = (before.group(1) if before else "").lstrip("([\"'“‘").lower()
            if token.replace(".", "") in _ABBREVIATIONS or re.fullmatch(
                r"(?:[a-z]\.)*[a-z]", token
            ):
                continue  # "v.", "(art. 3)", "no. 1234/56", "A.H. Khan" do not end a sentence
        end = m.start() + len(m.group(0).rstrip())
        spans.append((start, end))
        start = m.end()
    spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def best_quote(paragraph_text: str, claim_text: str, max_chars: int = QUOTE_MAX_CHARS) -> str:
    """A verbatim snippet of the paragraph that shows the claim, at most `max_chars` long.

    The quote is a run of whole sentences that contains the sentence matching the claim best (its distinctive words,
    and above all its numbers, such as an Article). Within the budget it also takes the neighbouring sentences that
    share the claim's words, so it does not stop just before the sentence that mentions the Article. Only when that
    sentence alone is too long is it cut, at a clause boundary if possible. Always an exact substring of the text.
    """
    text = paragraph_text.strip()
    if len(text) <= max_chars:
        return text
    spans = _sentence_spans(text)
    wanted = _tokens(claim_text)
    sentence_words = [_TOKEN.findall(text[s:e].lower()) for s, e in spans]
    in_sentences = {
        t: sum(any(_matches(t, w) for w in words) for words in sentence_words) for t in wanted
    }
    # numbers (Articles, sections) weigh most; a word found in only one sentence is more telling than a common one
    weight = {t: 3 if t.isdigit() else (2 if in_sentences[t] == 1 else 1) for t in wanted}
    covers = [{t for t in wanted if any(_matches(t, w) for w in words)} for words in sentence_words]

    def score(tokens: set[str]) -> int:
        return sum(weight[t] for t in tokens)

    best = max(range(len(spans)), key=lambda i: (score(covers[i]), -i))

    def windows(must_contain: int | None):
        for i in range(len(spans) if must_contain is None else must_contain + 1):
            for j in range(i if must_contain is None else must_contain, len(spans)):
                if spans[j][1] - spans[i][0] > max_chars:
                    break
                union = set().union(*covers[i : j + 1])
                matched = sum(1 for k in range(i, j + 1) if covers[k])
                idle = (j - i + 1) - matched
                yield (score(union), matched, -idle, -i), i, j

    candidates = list(windows(best))
    if candidates:
        _, i, j = max(candidates)
        return text[spans[i][0] : spans[j][1]]
    # The best sentence alone is over the budget. Prefer whole sentences elsewhere if they show the claim as well
    # as a cut of that sentence would; otherwise cut it, at a clause boundary if possible.
    cut = _cut_long_sentence(text[spans[best][0] : spans[best][1]], wanted, max_chars)
    cut_words = _TOKEN.findall(cut.lower())
    cut_score = score({t for t in wanted if any(_matches(t, w) for w in cut_words)})
    whole = list(windows(None))
    if whole:
        key, i, j = max(whole)
        if key[0] >= cut_score:
            return text[spans[i][0] : spans[j][1]]
    return cut


def _cut_long_sentence(sentence: str, wanted: set[str], max_chars: int) -> str:
    """One sentence longer than the budget: start at the sentence or a clause boundary that keeps most claim words."""
    starts = [0] + [m.end() for m in _CLAUSE_BREAK.finditer(sentence)]

    def window(start: int) -> str:
        cut = sentence[start : start + max_chars]
        if start + max_chars < len(sentence):
            space = cut.rfind(" ")
            cut = cut[:space] if space > max_chars * 0.6 else cut
        return cut.strip()

    def covered(start: int) -> int:
        words = _TOKEN.findall(window(start).lower())
        return sum(3 if t.isdigit() else 1 for t in wanted if any(_matches(t, w) for w in words))

    start = max(starts, key=lambda s: (covered(s), -s))
    return window(start)
