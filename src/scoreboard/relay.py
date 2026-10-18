"""Media-relay observations (RQ4) per copy.

Built by scoreboard.extract.run from the review sheet and the extraction; writes
outputs/tables/pilot_relay_<year>.csv. Rows hold structured values, the outlet and the
URL, never body text.

  copy conflict             a copy whose body value for an outcome differs from the majority
                            value of its briefing, or any copy with a value when the briefing's
                            value is a tie.
  headline-body difference  a figure in a copy's headline that is absent from the same copy's
                            body (detected_by "rule"); for copies the review sheet codes as
                            differing, also a headline figure that differs from the copy's own
                            body value for that outcome (detected_by "review").
Both record the direction against the majority value: higher, lower, equal (headline rows
only) or no majority (tie or no value).

Labels:
  rounded           headline row: the headline figure carries "over", "more than", "about",
                    "nearly" or "almost", and the copy's body figure for the same outcome is
                    equal to it or within the rounding unit implied by its trailing zeros.
  minor difference  copy-conflict row: the copy value is within MINOR_SHARE of the larger of it
                    and the majority value (in a tie, of every other value reported).
  differs           any other row.
"""

import re

import pandas as pd

from scoreboard.extract import NUM, OUTCOMES, QUAL, SUBSET_WORDS, is_minor, parse_number, spell_out_digits

ROUNDING_QUALIFIERS = {"over", "more than", "about", "nearly", "almost"}

# Headline verbs: present tense and misspellings are common in titles.
HEADLINE_KEYWORDS = {
    "neutralised": r"n(?:eu|ue)trali[sz]e[sd]?|eliminate[sd]?|kill(?:s|ed)?",
    "arrested": r"arrest(?:s|ed)?|apprehend(?:s|ed)?|captured?|nab(?:s|bed)?",
    "rescued": r"rescue[sd]?|freed",
}
HEADLINE_AFTER = {o: re.compile(rf"\b(?:{k})\s+(?:(?P<q>{QUAL})\s+)?(?P<n>{NUM})", re.I) for o, k in HEADLINE_KEYWORDS.items()}
HEADLINE_BEFORE = {o: re.compile(rf"(?:(?P<q>{QUAL})\s+)?(?P<n>{NUM})(?:\s+[^\s\d,]+){{0,3}}?\s+(?:{k})\b", re.I)
                   for o, k in HEADLINE_KEYWORDS.items()}
RELAY_COLUMNS = [
    "confirmed_group_id",
    "relay_type",
    "outcome",
    "outlet",
    "url",
    "copy_value",
    "copy_qualifier",
    "body_value",
    "majority_value",
    "direction",
    "label",
    "review_coded",
    "detected_by",
]


NEXT_FIGURE_RE = re.compile(rf"^.*?,\s*(?:(?P<q>{QUAL})\s+)?(?P<n>{NUM})(?P<rest>(?:\s+\S+){{0,3}})", re.I)
SPLIT_THOUSANDS_RE = re.compile(r"(\d), (\d{3})\b")
# Body numbers, including those run into a word ("apprehended103").
BODY_NUM_RE = re.compile(r"(?<![\d.,])(?:\d{1,3}(?:,\d{3})+|\d+)(?![.,]?\d)")


def _figure(m) -> dict:
    return {"value": parse_number(m.group("n")), "qualifier": (m.group("q") or "").lower()}


def headline_figures(title: str) -> dict[str, dict]:
    """The first figure per outcome in a headline: a number right after the verb ("kills 2,351")
    or up to three words before it ("624 terrorists killed"). A figure for a named subset
    ("16 terrorists' commanders") is skipped for the figure after the next comma ("1,166 others")."""
    title = SPLIT_THOUSANDS_RE.sub(r"\1,\2", title)
    out = {}
    for outcome in OUTCOMES:
        for m in HEADLINE_AFTER[outcome].finditer(title):
            rest = title[m.end():]
            if not SUBSET_WORDS.search(" ".join(rest.split()[:3])):
                out[outcome] = _figure(m)
                break
            nxt = NEXT_FIGURE_RE.match(rest)
            if nxt and not SUBSET_WORDS.search(nxt.group("rest")):
                out[outcome] = _figure(nxt)
                break
        if outcome in out:
            continue
        for m in HEADLINE_BEFORE[outcome].finditer(title):
            if not SUBSET_WORDS.search(m.group(0)):
                out[outcome] = _figure(m)
                break
    return out


def numbers_in(text: str) -> set[int]:
    return {parse_number(n) for n in BODY_NUM_RE.findall(spell_out_digits(text))}


def direction(value: int | None, majority: int | None) -> str:
    if value is None or majority is None:
        return "no majority"
    return "higher" if value > majority else "lower" if value < majority else "equal"


def rounding_unit(value: int) -> int:
    """10 to the power of the trailing zeros: 40 -> 10, 2,300 -> 100, 1,000 -> 1,000, 43 -> 1."""
    unit = 1
    while value and value % (unit * 10) == 0:
        unit *= 10
    return unit


def is_rounded(headline: int, qualifier: str, body: int | None) -> bool:
    """A qualified headline figure that rounds the body figure: "over 40" for 43, "over 2,300"
    for 2,351, "nearly 7,000" for 6,998, "about 200" for 197."""
    if body is None or qualifier not in ROUNDING_QUALIFIERS:
        return False
    if body == headline:
        return True
    unit = rounding_unit(headline)
    if unit == 1:
        return False
    if qualifier in ("over", "more than"):
        return headline < body < headline + unit
    if qualifier in ("nearly", "almost"):
        return headline - unit < body < headline
    return abs(body - headline) <= unit / 2  # about


def conflict_label(value: int, majority: int | None, others: list[int]) -> str:
    """"minor difference" when the copy value is within MINOR_SHARE of the majority value, or,
    in a tie, of every other value reported; else "differs"."""
    against = [majority] if majority is not None else others
    return "minor difference" if against and all(is_minor(value, o) for o in against) else "differs"


def _value(v):
    return None if v is None or pd.isna(v) else int(v)


def build_relay(review: pd.DataFrame, items: pd.DataFrame, copies: pd.DataFrame, briefings: pd.DataFrame,
                bodies: pd.Series) -> pd.DataFrame:
    rows = []
    majority = briefings.set_index("confirmed_group_id")
    coded = set(review.loc[review["headline_body_check"] == "differs", "url"])
    titles = review.set_index("url")["title"]
    body_values = {(r.url, r.outcome): (_value(r.value), r.qualifier) for r in copies.itertuples()}

    for b in briefings.itertuples():
        for outcome in OUTCOMES:
            if not getattr(b, f"{outcome}_conflict"):
                continue
            m = _value(getattr(b, outcome))
            group = items[items["confirmed_group_id"] == b.confirmed_group_id]
            reported = {body_values.get((u, outcome), (None, ""))[0] for u in group["url"]} - {None}
            for item in group.itertuples():
                v, q = body_values.get((item.url, outcome), (None, ""))
                if v is None or (m is not None and v == m):
                    continue
                rows.append({
                    "confirmed_group_id": b.confirmed_group_id, "relay_type": "copy conflict",
                    "outcome": outcome, "outlet": item.outlet, "url": item.url,
                    "copy_value": v, "copy_qualifier": q, "body_value": v, "majority_value": m,
                    "direction": direction(v, m), "label": conflict_label(v, m, sorted(reported - {v})),
                    "review_coded": "", "detected_by": "extraction",
                })

    for item in items.itertuples():
        body = bodies[item.url]
        if not body:
            continue
        present = numbers_in(body)
        for outcome, f in headline_figures(titles[item.url]).items():
            body_value = body_values.get((item.url, outcome), (None, ""))[0]
            absent = f["value"] not in present
            # A review-coded copy can carry a headline figure that occurs elsewhere in its body
            # under another outcome ("rescue 481" where 481 is the neutralised figure).
            reviewed = item.url in coded and body_value is not None and f["value"] != body_value
            if not absent and not reviewed:
                continue
            m = _value(majority.at[item.confirmed_group_id, outcome])
            # The copy's own body figure; the majority value when the copy has none.
            compare_to = body_value if body_value is not None else m
            rows.append({
                "confirmed_group_id": item.confirmed_group_id, "relay_type": "headline-body difference",
                "outcome": outcome, "outlet": item.outlet, "url": item.url,
                "copy_value": f["value"], "copy_qualifier": f["qualifier"],
                "body_value": body_value,
                "majority_value": m, "direction": direction(f["value"], m),
                "label": "rounded" if is_rounded(f["value"], f["qualifier"], compare_to) else "differs",
                "review_coded": "yes" if item.url in coded else "no",
                "detected_by": "rule and review" if absent and item.url in coded else "rule" if absent else "review",
            })
    df = pd.DataFrame(rows, columns=RELAY_COLUMNS)
    for col in ["copy_value", "body_value", "majority_value"]:
        df[col] = df[col].astype("Int64")
    return df.sort_values(["confirmed_group_id", "relay_type", "outcome", "outlet"], kind="stable").reset_index(drop=True)
