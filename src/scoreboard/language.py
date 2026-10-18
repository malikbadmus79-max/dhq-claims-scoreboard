"""Language measures (RQ3) per briefing.

Built by scoreboard.extract.run from the stored body text; writes
outputs/tables/pilot_language_<year>.csv. Evidence sentences for own losses go to
data_raw/extract/ only.

For each briefing the table records:
  - the spokesperson named as Director of Defence Media Operations or DHQ spokesperson;
  - per outcome, the qualifier or vague term attached to the reported value, and how many
    independent copies carry that wording;
  - the vague-term dictionary terms found anywhere in the copies;
  - whether any copy reports soldiers or security personnel killed, wounded or missing.
Each wording measure carries an evidence grade: 1 DHQ's own text, 2 two or more independent
copies, 3 one independent copy.
"""

import re
from collections import Counter
from difflib import SequenceMatcher

import pandas as pd

from scoreboard.extract import (
    DHQ_OUTLETS,
    EVIDENCE_CHARS,
    OUTCOMES,
    QUALIFIERS,
    count_independent,
    split_sentences,
)

VAGUE_TERMS = [
    "several",
    "scores",
    "dozens",
    "many",
    "a large number",
    "a cache of",
    "among others",
    "assorted",
    "significant results",
]
VAGUE_TERM_RES = {t: re.compile(rf"\b{re.escape(t)}\b", re.I) for t in VAGUE_TERMS}

PERSONNEL = r"(?:soldiers?|personnel|servicemen|officers|security operatives)"
LOSS = r"(?:killed|wounded|injured|missing|martyred)"
OWN_LOSS_RES = [
    # "nine soldiers killed", "two personnel were wounded"
    re.compile(rf"\b{PERSONNEL}\s+(?:were\s+|have been\s+|had been\s+|was\s+)?(?:declared\s+)?{LOSS}\b", re.I),
    # "troops" act in most sentences, so only the passive counts: "troops were killed"
    re.compile(rf"\btroops\s+(?:were|have been|had been)\s+{LOSS}\b", re.I),
    # "the killing of five soldiers", "the loss of 18 personnel"
    re.compile(rf"\b(?:killing|death|deaths|loss|murder)\s+of\s+(?:\S+\s+){{0,4}}?{PERSONNEL}", re.I),
    re.compile(rf"\b(?:{PERSONNEL}|troops)\s+(?:who\s+)?(?:died|lost their lives|paid the supreme price)", re.I),
    re.compile(rf"\blost\s+(?:\S+\s+){{0,2}}?(?:{PERSONNEL}|troops)\b", re.I),
]

TITLE = r"(?:Maj(?:or)?\.?[-\s]*Gen(?:eral)?\.?|Brig(?:adier)?\.?[-\s]*Gen(?:eral)?\.?|Air Vice Marshal|Rear Admiral)"
NAME = r"([A-Z][a-z]+\s+[A-Z][a-z]+)"
SPOKESPERSON_RES = [
    re.compile(rf"(?i:defen[cs]e media operations?)(?:\s*\(DMO\))?[,\s]+(?:(?i:{TITLE})\s*)?{NAME}"),
    re.compile(rf"(?i:DHQ|defen[cs]e)(?:’s|'s)?\s+(?i:spokes(?:man|person|woman))[,\s]+(?:(?i:{TITLE})\s*)?{NAME}"),
]
# Site furniture inside some stored bodies: related-article links and follow prompts.
BOILERPLATE_RE = re.compile(r"^\W*(?:read also|also read|related|follow us)\b", re.I)
SURNAME_SIMILARITY = 0.75

LANGUAGE_QUALIFIERS = set(QUALIFIERS) | {t for t in VAGUE_TERMS}


def own_loss_sentence(text: str) -> str:
    """The first sentence reporting soldiers or security personnel killed, wounded or missing."""
    for s in split_sentences(text):
        if not BOILERPLATE_RE.search(s) and any(r.search(s) for r in OWN_LOSS_RES):
            return s[:EVIDENCE_CHARS]
    return ""


def resolve_spelling(name: str, texts: list[str]) -> str:
    """Replace the surname by the most frequent near-identical capitalised word in the copies,
    so a single misspelling ("Edward Baba" beside "Mr Buba") does not split a spokesperson."""
    first, surname = name.rsplit(" ", 1)
    words = Counter(w for t in texts for w in re.findall(r"\b[A-Z][a-z]+\b", t))
    near = [w for w in words if w[0] == surname[0] and len(w) == len(surname)
            and SequenceMatcher(None, w, surname).ratio() >= SURNAME_SIMILARITY]
    best = max(near, key=lambda w: (words[w], w == surname), default=surname)
    return f"{first} {best}"


def spokesperson(text: str) -> str:
    for r in SPOKESPERSON_RES:
        m = r.search(text)
        if m:
            return m.group(1)
    return ""


def vague_terms_in(text: str) -> set[str]:
    return {t for t, r in VAGUE_TERM_RES.items() if r.search(text)}


def wording_terms(qualifier: str) -> set[str]:
    """Qualifier and vague terms in a copy's qualifier field. "plus N named" is an extraction
    note, not wording, and is left out."""
    return {q.strip() for q in qualifier.split(";") if q.strip() in LANGUAGE_QUALIFIERS}


def evidence_grade(urls: list[str], pairs, nan_urls, dhq_urls) -> tuple[int, int | str]:
    """Independent copies among `urls` and the evidence grade ("" when no copy)."""
    if not urls:
        return 0, ""
    n = count_independent(urls, pairs, nan_urls)
    return n, 1 if set(urls) & dhq_urls else 2 if n >= 2 else 3


def build_language(items: pd.DataFrame, copies: pd.DataFrame, bodies: pd.Series, wire: dict,
                   briefings: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, evidence = [], []
    by_id = briefings.set_index("confirmed_group_id")
    for gid, grp in items.groupby("confirmed_group_id", sort=True):
        pairs, nan_urls = wire[gid]
        urls = list(grp["url"])
        dhq_urls = set(grp.loc[grp["outlet"].isin(DHQ_OUTLETS), "url"])
        b = by_id.loc[gid]
        texts = [bodies[u] for u in urls]
        names = {u: resolve_spelling(n, texts) if n else "" for u in urls for n in [spokesperson(bodies[u])]}
        surnames = [n.split()[-1] for n in names.values() if n]
        top = max(set(surnames), key=lambda s: (surnames.count(s), s)) if surnames else ""
        full = next((n for n in names.values() if n.endswith(top)), "") if top else ""
        sp_n, _ = evidence_grade([u for u, n in names.items() if n and n.endswith(top)], pairs, nan_urls, dhq_urls)
        row = {
            "confirmed_group_id": gid,
            "briefing_date": b["briefing_date"],
            "year": pd.Timestamp(b["briefing_date"]).year,
            "spokesperson": full,
            "spokesperson_independent_copies": sp_n,
        }
        gc = copies[copies["confirmed_group_id"] == gid]
        for outcome in OUTCOMES:
            oc = gc[gc["outcome"] == outcome]
            reported = bool(oc["value"].notna().any() or oc["qualifier"].map(bool).any())
            by_term: dict[str, list[str]] = {}
            for u, q in zip(oc["url"], oc["qualifier"]):
                for t in wording_terms(q):
                    by_term.setdefault(t, []).append(u)
            counted = {t: evidence_grade(us, pairs, nan_urls, dhq_urls) for t, us in by_term.items()}
            best = min(counted, key=lambda t: (counted[t][1], -counted[t][0], t)) if counted else ""
            row.update({
                f"{outcome}_reported": reported,
                f"{outcome}_wording": best,
                f"{outcome}_wording_independent_copies": counted[best][0] if best else 0,
                f"{outcome}_wording_grade": counted[best][1] if best else "",
            })
        terms: dict[str, list[str]] = {}
        for u in urls:
            for t in vague_terms_in(bodies[u]):
                terms.setdefault(t, []).append(u)
        graded = {t: evidence_grade(us, pairs, nan_urls, dhq_urls) for t, us in terms.items()}
        row["vague_terms_any"] = "; ".join(t for t in VAGUE_TERMS if t in graded)
        row["vague_terms_grade2"] = "; ".join(t for t in VAGUE_TERMS if t in graded and graded[t][1] in (1, 2))
        losses = {u: own_loss_sentence(bodies[u]) for u in urls}
        loss_urls = [u for u, s in losses.items() if s]
        n, g = evidence_grade(loss_urls, pairs, nan_urls, dhq_urls)
        row.update({
            "own_losses_copies": len(loss_urls),
            "own_losses_independent_copies": n,
            "own_losses_grade": g,
        })
        evidence += [{"confirmed_group_id": gid, "url": u, "measure": "own losses", "evidence": s}
                     for u, s in losses.items() if s]
        rows.append(row)
    return pd.DataFrame(rows), pd.DataFrame(evidence, columns=["confirmed_group_id", "url", "measure", "evidence"])


def language_measures(language: pd.DataFrame) -> pd.DataFrame:
    """The two RQ3 measures by year and spokesperson, counting only wording at grade 1 or 2:
    share of reported outcome values with a qualifier or vague term, and share of briefings
    mentioning own losses."""
    rows = []
    for (year, person), grp in language.groupby(["year", "spokesperson"], dropna=False):
        reported = sum(int(grp[f"{o}_reported"].sum()) for o in OUTCOMES)
        worded = sum(int(grp[f"{o}_wording_grade"].isin([1, 2]).sum()) for o in OUTCOMES)
        losses = int(grp["own_losses_grade"].isin([1, 2]).sum())
        rows.append({
            "year": year,
            "spokesperson": person,
            "briefings": len(grp),
            "outcome_values_reported": reported,
            "outcome_values_with_wording_grade_1_2": worded,
            "share_with_wording": round(worded / reported, 3) if reported else "",
            "briefings_with_own_losses_grade_1_2": losses,
            "share_with_own_losses": round(losses / len(grp), 3),
        })
    return pd.DataFrame(rows)
