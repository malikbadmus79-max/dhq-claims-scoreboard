import pytest

from scoreboard.spokesperson import _person, names_near_phrases


@pytest.mark.parametrize("seq, name", [
    ("Maj.-Gen. John Enenche", "John Enenche"),
    ("Brigadier General Benard Onyeuko", "Benard Onyeuko"),
    ("Major-general Musa Danmadami", "Musa Danmadami"),
    ("Maj. Gen. Bernard Onyeuko", "Bernard Onyeuko"),
    ("Brig.-Gen. Ibrahim Abu-Mawashi", "Ibrahim Abu-Mawashi"),
    ("Sokoto State. Maj.-Gen. Bernard Onyeuko", "Bernard Onyeuko"),
    ("Major General Edward Buba. According", "Edward Buba"),
])
def test_person_takes_name_after_rank(seq, name):
    assert _person(seq) == name


@pytest.mark.parametrize("seq", ["Zamfara State", "Borno State Coordinator", "North East Nigeria", "Niger Republic",
                                 "Maj.-Gen. Enenche"])
def test_person_rejects_place_names_and_lone_surnames(seq):
    assert _person(seq) is None


def test_names_found_before_and_after_the_phrase():
    after = "in Zamfara State. The Coordinator, Defence Media Operations, Maj.-Gen. John Enenche, said."
    before = "in Sokoto State. Maj.-Gen. Bernard Onyeuko, the Director, Defence Media Operations, said this."
    assert names_near_phrases(after) == {"John Enenche"}
    assert names_near_phrases(before) == {"Bernard Onyeuko"}


def test_no_name_without_a_phrase():
    assert names_near_phrases("Maj.-Gen. John Enenche visited troops in Borno State.") == set()
