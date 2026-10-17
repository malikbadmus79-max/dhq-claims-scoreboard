"""Briefing-level and operation-level figures from the stored body text of confirmed briefings.

Usage: python -m scoreboard.extract --year 2024

Reads data/review/pilot_review_<year>.csv and data_raw/text/. No requests are made.
Per-copy values with their evidence sentences go to data_raw/extract/ only; the tables in
outputs/tables hold structured values, URLs and copy counts, never body text.

Extraction rule, per copy and per outcome:
  1. the first sentence that reports a national total (a national marker such as "across
     the country" or "theatres of operation"), else
  2. the first sentence that reports a total and names no region, state or operation, else
  3. the first such sentence that reports the outcome only with a vague term ("several",
     "scores"), recorded as a qualifier with no value.
A figure attached to a named subset ("65 notable terrorist leaders") is not a total and is
skipped. Qualifiers ("no fewer than", "over", "at least" and similar) are kept in their own
column. "Neutralised" is the outcome name for neutralised, neutralized, eliminated and killed.
"""

import argparse
import calendar
import logging
import re
from collections import Counter
from datetime import date, timedelta
from itertools import combinations

import pandas as pd

from scoreboard.config import PROJECT_ROOT
from scoreboard.discover import TABLES_DIR
from scoreboard.wirecheck import (
    REVIEW_DIR,
    SAME_WIRE_THRESHOLD,
    has_nan_credit,
    independent_copies,
    load_bodies,
    similarity,
)

log = logging.getLogger(__name__)

EXTRACT_DIR = PROJECT_ROOT / "data_raw" / "extract"
EVIDENCE_CHARS = 300
OUTCOMES = ["neutralised", "arrested", "rescued"]
OPERATION_OUTCOMES = ["neutralised", "arrested"]
OPERATION_BRIEFINGS = {2024: ["B2024-035", "B2024-038"]}

# The keyword may run into a number ("apprehended103"), so the right edge is "no letter follows".
KEYWORDS = {
    "neutralised": re.compile(r"\b(?:neutrali[sz]ed|eliminated|killed)(?![a-z])", re.I),
    # "nabbed" is used for arrests in the third-quarter operation paragraphs.
    "arrested": re.compile(r"\b(?:arrested|apprehended|nabbed)(?![a-z])", re.I),
    "rescued": re.compile(r"\brescued(?![a-z])", re.I),
}
ANY_KEYWORD = re.compile("|".join(p.pattern for p in KEYWORDS.values()), re.I)

NUM = r"(?<![\w.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?![.,]?\d)"
QUALIFIERS = [
    "no fewer than",
    "not fewer than",
    "not less than",
    "at least",
    "more than",
    "over",
    "about",
    "approximately",
    "nearly",
    "almost",
]
QUAL = "|".join(re.escape(q) for q in QUALIFIERS)
VAGUE = r"several|scores"
FILLER = r"(?:a total of|an additional|another)"
AFTER_RE = re.compile(
    rf"^\s*(?:{FILLER}\s+)?(?:(?P<q>{QUAL})\s+)?(?:{FILLER}\s+)?(?P<n>{NUM})(?P<rest>(?:\s+\S+){{0,3}})", re.I
)
BEFORE_RE = re.compile(rf"(?:(?P<q>{QUAL})\s+)?(?P<n>{NUM})(?P<gap>(?:\s+[^\s\d]+){{0,8}}?)\s*$", re.I)
VAGUE_AFTER_RE = re.compile(rf"^\s*(?P<v>{VAGUE})\b", re.I)
VAGUE_BEFORE_RE = re.compile(rf"\b(?P<v>{VAGUE})\b(?:\s+[^\s\d]+){{0,6}}?\s*$", re.I)
# A comma followed by a space; commas inside numbers ("10,937") do not count.
SKIP_TO_COMMA_RE = re.compile(r"^.*?,(?=\s)")
SMALL_COUNTS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10}
# "apprehended a terrorist commander, Usman Maisaje, and 182 others": the stated number is kept and
# the named individuals are recorded as a qualifier.
NAMED_PLUS_RE = re.compile(
    rf"^\s*(?P<k>{'|'.join(SMALL_COUNTS)}|\d)\s+[^\d.]*?(?:,|\band)\s+(?:{FILLER}\s+)?(?P<n>{NUM})\s+others?\b", re.I
)
# A number directly after an outcome word belongs to that word.
CLAIMED_RE = re.compile(
    rf"(?:{'|'.join(p.pattern for p in KEYWORDS.values())})\s*(?:{FILLER}\s+)?(?:(?:{QUAL})\s+)?$", re.I
)

# Words after a number that mark it as something other than a count of people.
UNIT_WORDS = re.compile(
    r"^(?:naira|days?|weeks?|months?|years?|hours?|per|percent|%|litres?|rounds?|barrels?|mm|million|billion|km|"
    r"weapons?|ammunitions?|rifles?|guns?|boats?|sites?|vehicles?|motorcycles?|camps?)\b",
    re.I,
)
# Words after a number that mark a named subset rather than a total.
SUBSET_WORDS = re.compile(r"\b(?:leaders?|commanders?|kingpins?|notable)\b", re.I)
# Words after a neutralised number that mark own or civilian losses.
LOSS_WORDS = re.compile(r"(?<!foot )\b(?:soldiers?|troops|personnel|civilians?|villagers|residents|people)\b", re.I)

NATIONAL_RE = re.compile(
    # Plural only: "the North Central theatre of operation" names a region.
    r"across the country|nationwide|across nigeria|parts of the country|theatres of operations?|"
    r"across (?:all )?(?:the )?theatres|in the country",
    re.I,
)
STATES = (
    "Abia|Adamawa|Akwa Ibom|Anambra|Bauchi|Bayelsa|Benue|Borno|Cross River|Delta State|Ebonyi|Edo|Ekiti|"
    "Enugu|Gombe|Imo|Jigawa|Kaduna|Kano|Katsina|Kebbi|Kogi|Kwara|Lagos|Nasarawa|Niger|Ogun|Ondo|Osun|"
    "Oyo|Plateau|Rivers State|Sokoto|Taraba|Yobe|Zamfara"
)
REGION_RE = re.compile(
    rf"\b(?:north[- ]?east|north[- ]?west|north[- ]?central|south[- ]?east|south[- ]?south|south[- ]?west|"
    rf"lake chad|FCT|federal capital territory|area council|local government)\b|\b(?:{STATES})\b",
    re.I,
)
KNOWN_OPERATIONS = [
    "Hadin Kai",
    "Safe Haven",
    "Whirl Stroke",
    "Hadarin Daji",
    "Whirl Punch",
    "Delta Safe",
    "UDO KA",
    "Awatse",
    "Fansan Yamma",
]
OPERATION_RE = re.compile(r"(?<!Media )\bOperations?\s+((?:[A-Z][A-Za-z']*)(?:\s+[A-Z][A-Za-z']*){0,2})")

ABBREVIATIONS = re.compile(r"\b(Maj|Gen|Lt|Col|Brig|Capt|Cdr|Mr|Mrs|Ms|Dr|No|Rtd|Hon|Gov|Sen|St)\.")
# A sentence ends at . ! or ? followed by up to two closing quote marks and a space.
QUOTE = "\"'’”�"
SENTENCE_END = re.compile(rf"(?:(?<=[.!?])|(?<=[.!?][{QUOTE}])|(?<=[.!?][{QUOTE}]{{2}}))\s+")


# Text helpers


def split_sentences(text: str) -> list[str]:
    protected = ABBREVIATIONS.sub(lambda m: m.group(1) + "\x00", text)
    return [s.replace("\x00", ".").strip() for s in SENTENCE_END.split(protected) if s.strip()]


def parse_number(s: str) -> int:
    return int(s.replace(",", ""))


UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
NUMBER_WORD = "|".join([*UNITS, *TENS, *SCALES])
WORD_NUMBER_RE = re.compile(rf"\b(?:{NUMBER_WORD})(?:(?:\s+and\s+|[\s-]+)(?:{NUMBER_WORD}))+\b", re.I)


def words_to_number(phrase: str) -> int:
    total, current = 0, 0
    for w in re.split(r"[\s-]+", phrase.lower()):
        if w in UNITS:
            current += UNITS[w]
        elif w in TENS:
            current += TENS[w]
        elif w == "hundred":
            current = max(current, 1) * 100
        elif w in SCALES:
            total += max(current, 1) * SCALES[w]
            current = 0
    return total + current


def spell_out_digits(sentence: str) -> str:
    """Write spelled-out numbers that contain hundred, thousand or million as digits, so
    "Nine thousand three hundred three have been killed" reads as 9303. Small counts
    ("one week", "nine soldiers") stay as words."""
    def sub(m):
        if not re.search(r"hundred|thousand|million", m.group(0), re.I):
            return m.group(0)
        return str(words_to_number(m.group(0)))
    return WORD_NUMBER_RE.sub(sub, sentence)


def _usable(following: str, outcome: str) -> bool:
    words = following.split()
    if words and UNIT_WORDS.match(words[0]):
        return False
    # "killed, 6,998 arrested": the number belongs to the next outcome word.
    if words and ANY_KEYWORD.match(words[0]):
        return False
    if SUBSET_WORDS.search(following):
        return False
    if outcome == "neutralised" and LOSS_WORDS.search(following):
        return False
    return True


def find_figure(sentence: str, outcome: str) -> dict | None:
    """The first figure for `outcome` in one sentence: {"value", "qualifier"}. A number is read
    right after the outcome word ("neutralised 43 terrorists") or, failing that, shortly before it
    ("43 terrorists being neutralised"). Returns a vague-only figure (value None) when the outcome
    is reported only as "several" or "scores", and None when the outcome is not reported."""
    vague = None
    sentence = spell_out_digits(sentence)
    for m in KEYWORDS[outcome].finditer(sentence):
        after = sentence[m.end():]
        named = NAMED_PLUS_RE.match(after)
        if named:
            k = named.group("k").lower()
            k = int(k) if k.isdigit() else SMALL_COUNTS[k]
            return {"value": parse_number(named.group("n")), "qualifier": f"plus {k} named"}
        for _ in range(3):
            a = AFTER_RE.match(after)
            if not a:
                break
            if _usable(a.group("rest"), outcome):
                return {"value": parse_number(a.group("n")), "qualifier": (a.group("q") or "").lower()}
            # A skipped subset figure may be followed by the total ("over 500 leaders, 8,034 others").
            skip = SKIP_TO_COMMA_RE.match(after[a.end("n"):])
            if not skip:
                break
            after = after[a.end("n") + skip.end():]
        before = sentence[: m.start()]
        b = BEFORE_RE.search(before)
        if b and not ANY_KEYWORD.search(b.group("gap")) and not CLAIMED_RE.search(before[: b.start("n")]):
            following = b.group("gap") if b.group("gap").strip() else sentence[m.end():]
            if _usable(" ".join(following.split()[:3]), outcome):
                return {"value": parse_number(b.group("n")), "qualifier": (b.group("q") or "").lower()}
        if vague is None:
            v = VAGUE_AFTER_RE.match(after) or VAGUE_BEFORE_RE.search(before)
            if v:
                vague = {"value": None, "qualifier": v.group("v").lower()}
    return vague


def is_regional(sentence: str) -> bool:
    return bool(REGION_RE.search(sentence) or OPERATION_RE.search(sentence))


def national_total(text: str, outcome: str) -> dict | None:
    """Apply the extraction rule to one body text. Adds "rule" and "evidence" to the figure."""
    sentences = split_sentences(text)
    # A copy that opens on a region or operation and never reports a national figure is a
    # section report (e.g. the Operation Delta Safe part of a weekly briefing): its sentences
    # that name no region still belong to that section.
    section_copy = bool(sentences) and is_regional(sentences[0]) and not any(NATIONAL_RE.search(s) for s in sentences)
    found = []
    for s in sentences:
        f = find_figure(s, outcome)
        if f is not None:
            found.append((s, f, bool(NATIONAL_RE.search(s)), not section_copy and not is_regional(s)))
    passes = [
        ("national marker", lambda f, national, unregioned: f["value"] is not None and national),
        ("no region named", lambda f, national, unregioned: f["value"] is not None and unregioned),
        ("vague only", lambda f, national, unregioned: f["value"] is None and (national or unregioned)),
    ]
    for rule, ok in passes:
        for s, f, national, unregioned in found:
            if ok(f, national, unregioned):
                return {**f, "rule": rule, "evidence": s[:EVIDENCE_CHARS]}
    return None


def operation_name(raw: str) -> str:
    for name in KNOWN_OPERATIONS:
        if raw.lower().startswith(name.lower()):
            return name
    return raw.strip()


def operation_figures(text: str) -> dict[str, dict]:
    """Per-operation figures in one body text. A sentence naming an operation opens its section;
    the section runs until another operation is named or a region is named without one. The first
    numeric figure per outcome inside an operation's sections is kept."""
    ops: dict[str, dict] = {}
    current = None
    for s in split_sentences(text):
        named = OPERATION_RE.search(s)
        if named:
            current = operation_name(named.group(1))
            ops.setdefault(current, {})
        elif REGION_RE.search(s):
            current = None
        if current is None:
            continue
        for outcome in OPERATION_OUTCOMES:
            if outcome in ops[current]:
                continue
            f = find_figure(s, outcome)
            if f and f["value"] is not None:
                ops[current][outcome] = {**f, "evidence": s[:EVIDENCE_CHARS]}
    return ops


# Copies and majority values


def same_wire_pairs(urls: list[str], bodies: pd.Series, threshold: float = SAME_WIRE_THRESHOLD):
    return [
        (a, b)
        for a, b in combinations(urls, 2)
        if bodies[a] and bodies[b] and similarity(bodies[a], bodies[b]) >= threshold
    ]


def count_independent(urls: list[str], pairs: list[tuple[str, str]], nan_urls: set[str]) -> int:
    """Independent copies among `urls`: same_wire pairs at the primary threshold plus the NAN merge."""
    keep = set(urls)
    return independent_copies(
        list(urls), [(a, b) for a, b in pairs if a in keep and b in keep], [u for u in urls if u in nan_urls]
    )


def majority(values: dict[str, int | None], pairs, nan_urls: set[str]) -> dict:
    """The value reported by most independent copies. Copies without a value do not vote.
    A tie between values leaves the value blank."""
    by_value: dict[int, list[str]] = {}
    for url, v in values.items():
        if v is not None:
            by_value.setdefault(v, []).append(url)
    counts = {v: count_independent(urls, pairs, nan_urls) for v, urls in by_value.items()}
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(by_value[kv[0]]), kv[0]))
    tie = len(ranked) > 1 and ranked[0][1] == ranked[1][1]
    value, agreeing = (None, ranked[0][1]) if tie else ranked[0] if ranked else (None, 0)
    summary = "; ".join(f"{v} ({len(by_value[v])} copies, {c} independent)" for v, c in ranked)
    return {
        "value": value,
        "independent_copies_agreeing": agreeing,
        "copies_reporting": sum(len(u) for u in by_value.values()),
        "conflict": len(by_value) > 1,
        "tie": tie,
        "values": summary,
        "agreeing_urls": [] if tie or not ranked else by_value[ranked[0][0]],
    }


# Periods

MONTH_NUMBERS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
ORDINAL_QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
PERIOD_NOTE_RE = re.compile(r"Period: ([^.]*)\.")


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def period_note(notes: list[str]) -> str:
    found = [m.group(1) for n in notes for m in [PERIOD_NOTE_RE.search(n)] if m]
    return Counter(found).most_common(1)[0][0] if found else ""


def parse_period(note: str, briefing: date, all_notes: str = "") -> dict:
    """Period type, start and end from the review note. period_flag says whether the period is
    stated in the text or inferred. stated_period_end is the end of the period as the text names it."""
    n = note.lower()
    y = briefing.year
    out = {"period_type": "", "period_label": note, "period_start": None, "period_end": None,
           "period_flag": "", "stated_period_end": None}
    if n.startswith("weekly"):
        out.update(period_type="weekly", period_start=briefing - timedelta(days=6), period_end=briefing,
                   period_flag="inferred: 7 days ending on the briefing date")
    elif n.startswith("fortnightly"):
        out.update(period_type="fortnightly", period_start=briefing - timedelta(days=13), period_end=briefing,
                   period_flag="inferred: 14 days ending on the briefing date")
    elif n.startswith("monthly"):
        month = next(i for name, i in MONTH_NUMBERS.items() if name in n)
        out.update(period_type="monthly", period_start=date(y, month, 1), period_end=month_end(y, month),
                   period_flag="stated: month named", stated_period_end=month_end(y, month))
    elif n.startswith("quarterly"):
        named = [i for name, i in MONTH_NUMBERS.items() if re.search(rf"\b{name}\b", n)]
        ordinal = next((q for word, q in ORDINAL_QUARTERS.items() if f"{word} quarter" in n), None)
        first, last = (min(named), max(named)) if len(named) >= 2 else (3 * ordinal - 2, 3 * ordinal)
        out.update(period_type="quarterly", period_start=date(y, first, 1), period_end=month_end(y, last),
                   period_flag="stated: quarter named", stated_period_end=month_end(y, last))
    elif n.startswith("year to date"):
        months = int(re.search(r"(\d+) months", n).group(1))
        stated = date(y, 12, 31) if "january to december" in all_notes.lower() else None
        out.update(period_type="year to date", period_start=date(y, 1, 1), period_end=month_end(y, months),
                   period_flag=f"inferred: {months} months to date", stated_period_end=stated)
    elif n.startswith("annual"):
        out.update(period_type="annual", period_start=date(y, 1, 1), period_end=date(y, 12, 31),
                   period_flag="stated: year named", stated_period_end=date(y, 12, 31))
    elif n.startswith("one year"):
        out.update(period_type="one year", period_start=briefing.replace(year=y - 1) + timedelta(days=1),
                   period_end=briefing, period_flag="inferred: 12 months ending on the briefing date")
    return out


# Pipeline


def confirmed_items(review: pd.DataFrame) -> pd.DataFrame:
    items = review[(review["is_operational_briefing"] == "yes") & (review["confirmed_group_id"] != "")]
    return items.reset_index(drop=True)


def extract_copies(items: pd.DataFrame, bodies: pd.Series) -> pd.DataFrame:
    rows = []
    for item in items.itertuples():
        body = bodies[item.url]
        for outcome in OUTCOMES:
            f = national_total(body, outcome) if body else None
            rows.append({
                "confirmed_group_id": item.confirmed_group_id,
                "url": item.url,
                "outlet": item.outlet,
                "publish_date": item.publish_date,
                "outcome": outcome,
                "value": f["value"] if f else None,
                "qualifier": f["qualifier"] if f else "",
                "rule": f["rule"] if f else ("no text" if not body else "not reported"),
                "evidence": f["evidence"] if f else "",
            })
    df = pd.DataFrame(rows)
    df["value"] = df["value"].astype("Int64")
    return df


def build_briefings(items: pd.DataFrame, copies: pd.DataFrame, bodies: pd.Series):
    """One row per confirmed_group_id. Also returns the same_wire pairs and NAN-credited URLs
    per group, for reuse by the operation table."""
    rows, wire = [], {}
    for gid, grp in items.groupby("confirmed_group_id", sort=True):
        urls = list(grp["url"])
        pairs = same_wire_pairs(urls, bodies)
        nan_urls = {u for u in urls if has_nan_credit(bodies[u])}
        wire[gid] = (pairs, nan_urls)
        briefing = min(date.fromisoformat(d) for d in grp["publish_date"])
        notes = list(grp["notes"])
        row = {
            "confirmed_group_id": gid,
            "briefing_date": briefing,
            **parse_period(period_note(notes), briefing, " ".join(notes)),
            "copies": len(urls),
            "copies_with_text": sum(bool(bodies[u]) for u in urls),
            "independent_copies": count_independent(urls, pairs, nan_urls),
        }
        gc = copies[copies["confirmed_group_id"] == gid]
        for outcome in OUTCOMES:
            oc = gc[gc["outcome"] == outcome].set_index("url")
            vals = {u: (None if pd.isna(v) else int(v)) for u, v in oc["value"].items()}
            m = majority(vals, pairs, nan_urls)
            quals = sorted({q for u, q in oc["qualifier"].items() if q and (u in m["agreeing_urls"] or vals[u] is None)})
            row.update({
                outcome: m["value"],
                f"{outcome}_qualifier": "; ".join(quals),
                f"{outcome}_copies_reporting": m["copies_reporting"],
                f"{outcome}_independent_copies_agreeing": m["independent_copies_agreeing"],
                f"{outcome}_conflict": m["conflict"],
                f"{outcome}_tie": m["tie"],
                f"{outcome}_values": m["values"],
            })
        rows.append(row)
    df = pd.DataFrame(rows)
    for outcome in OUTCOMES:
        df[outcome] = df[outcome].astype("Int64")
    return df, wire


def extract_operations(items: pd.DataFrame, bodies: pd.Series, groups: list[str]) -> pd.DataFrame:
    rows = []
    for item in items[items["confirmed_group_id"].isin(groups)].itertuples():
        for op, figs in operation_figures(bodies[item.url]).items():
            for outcome in OPERATION_OUTCOMES:
                f = figs.get(outcome)
                rows.append({
                    "confirmed_group_id": item.confirmed_group_id,
                    "url": item.url,
                    "outlet": item.outlet,
                    "operation": op,
                    "outcome": outcome,
                    "value": f["value"] if f else None,
                    "qualifier": f["qualifier"] if f else "",
                    "evidence": f["evidence"] if f else "",
                })
    df = pd.DataFrame(rows, columns=["confirmed_group_id", "url", "outlet", "operation", "outcome", "value",
                                     "qualifier", "evidence"])
    df["value"] = df["value"].astype("Int64")
    return df


def build_operations(op_copies: pd.DataFrame, items: pd.DataFrame, wire: dict) -> pd.DataFrame:
    rows = []
    for (gid, op), grp in op_copies.groupby(["confirmed_group_id", "operation"], sort=False):
        pairs, nan_urls = wire[gid]
        group_urls = list(items.loc[items["confirmed_group_id"] == gid, "url"])
        row = {
            "confirmed_group_id": gid,
            "operation": op,
            "copies_in_briefing": len(group_urls),
            "copies_naming_operation": grp["url"].nunique(),
        }
        for outcome in OPERATION_OUTCOMES:
            oc = grp[grp["outcome"] == outcome].set_index("url")
            vals = {u: (None if pd.isna(v) else int(v)) for u, v in oc["value"].items()}
            m = majority(vals, pairs, nan_urls)
            quals = sorted({q for u, q in oc["qualifier"].items() if q and u in m["agreeing_urls"]})
            row.update({
                outcome: m["value"],
                f"{outcome}_qualifier": "; ".join(quals),
                f"{outcome}_copies_reporting": m["copies_reporting"],
                f"{outcome}_independent_copies_agreeing": m["independent_copies_agreeing"],
                f"{outcome}_conflict": m["conflict"],
                f"{outcome}_values": m["values"],
            })
        rows.append(row)
    df = pd.DataFrame(rows)
    for outcome in OPERATION_OUTCOMES:
        df[outcome] = df[outcome].astype("Int64")
    return df


def run(year: int, tables_dir=TABLES_DIR, review_dir=REVIEW_DIR, extract_dir=EXTRACT_DIR):
    review = pd.read_csv(review_dir / f"pilot_review_{year}.csv", keep_default_na=False, dtype=str)
    items = confirmed_items(review)
    bodies = load_bodies(items["url"])
    copies = extract_copies(items, bodies)
    briefings, wire = build_briefings(items, copies, bodies)
    op_copies = extract_operations(items, bodies, OPERATION_BRIEFINGS.get(year, []))
    operations = build_operations(op_copies, items, wire)

    extract_dir.mkdir(parents=True, exist_ok=True)
    copies.to_csv(extract_dir / f"pilot_national_copies_{year}.csv", index=False)
    op_copies.to_csv(extract_dir / f"pilot_operation_copies_{year}.csv", index=False)
    tables_dir.mkdir(parents=True, exist_ok=True)
    briefings.to_csv(tables_dir / f"pilot_briefings_{year}.csv", index=False)
    operations.to_csv(tables_dir / f"pilot_operations_{year}.csv", index=False)
    return briefings, operations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    briefings, operations = run(args.year)
    log.info("%d briefings, %d operation rows", len(briefings), len(operations))


if __name__ == "__main__":
    main()
