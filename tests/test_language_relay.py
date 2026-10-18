from scoreboard.language import own_loss_sentence, resolve_spelling, spokesperson, vague_terms_in, wording_terms
from scoreboard.extract import independent_groups
from scoreboard.relay import conflict_label, direction, headline_figures, is_rounded, numbers_in, rounding_unit


def test_own_loss_sentence_finds_victims_not_actors():
    assert own_loss_sentence("Troops killed 43 terrorists. Nine soldiers were killed in an ambush.").startswith("Nine soldiers")
    assert own_loss_sentence("He condemned the killing of five soldiers by the group.")
    assert own_loss_sentence("We have lost nine personnel this month.")
    assert own_loss_sentence("Troops killed 43 terrorists and arrested 115 others.") == ""


def test_own_loss_sentence_ignores_related_links():
    assert own_loss_sentence("READ ALSO: Military vows to retaliate killing of soldiers by gunmen.") == ""


def test_spokesperson_and_spelling():
    text = "The Director, Defence Media Operations, Maj.-Gen. Edward Baba, said. Mr Buba said. Buba added."
    assert spokesperson(text) == "Edward Baba"
    assert resolve_spelling("Edward Baba", [text]) == "Edward Buba"
    assert spokesperson("The director, defence media operation, Maj.-Gen. Edward Buba, spoke.") == "Edward Buba"


def test_vague_terms_and_wording():
    text = "Troops recovered assorted weapons and a cache of arms, among others."
    assert vague_terms_in(text) == {"assorted", "a cache of", "among others"}
    assert wording_terms("no fewer than; plus 1 named") == {"no fewer than"}


def test_headline_figures():
    assert headline_figures("Military kills 2,351 terrorists, apprehends 2,308 others") == {
        "neutralised": {"value": 2351, "qualifier": ""},
        "arrested": {"value": 2308, "qualifier": ""},
    }
    assert headline_figures("624 terrorists killed in May, 1,000 captured: DHQ")["arrested"]["value"] == 1000
    # A subset figure is skipped for the figure after the next comma.
    title = "Troops neutralised over 16 terrorists’ commanders, 1,166 others"
    assert headline_figures(title)["neutralised"]["value"] == 1166
    title = "Troops neutralised over 1, 000 terrorists’ leaders, 10,937 others"
    assert headline_figures(title)["neutralised"]["value"] == 10937
    assert headline_figures("Over 500 Neutralised As Troops Arrest 790")["neutralised"] == {"value": 500, "qualifier": "over"}


def test_numbers_in_body_and_direction():
    assert {103, 106} <= numbers_in("neutralised 106 terrorists and apprehended103 others")
    assert 7 not in numbers_in("7.62mm rounds")
    assert direction(212, 121) == "higher"
    assert direction(100, 101) == "lower"
    assert direction(5, 5) == "equal"
    assert direction(5, None) == "no majority"


# Rounding rule for headline figures


def test_rounding_unit_from_trailing_zeros():
    assert [rounding_unit(v) for v in (43, 40, 150, 2300, 1000, 7000)] == [1, 10, 10, 100, 1000, 1000]


def test_is_rounded():
    assert is_rounded(40, "over", 43)
    assert is_rounded(1000, "over", 1066)
    assert is_rounded(2300, "more than", 2351)
    assert is_rounded(7000, "nearly", 6998)
    assert is_rounded(200, "about", 197)
    assert is_rounded(100, "almost", 100)
    assert not is_rounded(150, "over", 171)    # outside the unit of 10
    assert not is_rounded(40, "over", 39)      # below an "over" figure
    assert not is_rounded(7000, "nearly", 7001)
    assert not is_rounded(212, "", 121)        # no qualifier
    assert not is_rounded(43, "over", 45)      # no trailing zero, no rounding unit
    assert not is_rounded(40, "over", None)


# Minor difference for copy conflicts


def test_conflict_label():
    assert conflict_label(2352, 2351, []) == "minor difference"
    assert conflict_label(172, 204, []) == "differs"
    # In a tie, the copy value is compared with every other value reported.
    assert conflict_label(256, None, [258]) == "minor difference"
    assert conflict_label(624, None, [640]) == "differs"


def test_independent_groups_join_wire_and_nan_copies():
    urls = ["a", "b", "c", "d", "e"]
    groups = independent_groups(urls, [("a", "b")], nan_urls={"c", "e"})
    assert groups == {"a": 1, "b": 1, "c": 2, "d": 3, "e": 2}


# Material conflicts in the briefing table


def test_conflict_material():
    from scoreboard.extract import conflict_material
    assert not conflict_material([2351, 2351, 2352], 2351)   # 1 in 2,352: within 1%
    assert conflict_material([204, 204, 172], 204)           # 32 in 204
    assert not conflict_material([256, 258], None)           # tie, 2 in 258
    assert conflict_material([624, 640], None)               # tie, 16 in 640
    assert not conflict_material([43, 43], 43)               # no conflict at all
    assert not conflict_material([], None)


def test_rounding_unit_has_no_cap():
    assert is_rounded(1000, "over", 1000)
    assert is_rounded(1000, "over", 1999)
    assert not is_rounded(1000, "over", 2000)
