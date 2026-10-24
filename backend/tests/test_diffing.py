"""Word-level diff: what counts as a change."""

from app.diffing import word_diff

ORIG = "Storm Boelo to bring 80mph gusts and heavy rain to parts of UK"


def test_no_change():
    assert word_diff(ORIG, ORIG).num_changes == 0


def test_case_and_punctuation_are_not_changes():
    assert word_diff(ORIG, ORIG.lower() + ".").num_changes == 0
    assert word_diff("Rates rise, bank says", "Rates rise bank says").num_changes == 0


def test_single_substitution():
    d = word_diff(ORIG, ORIG.replace("80mph", "120mph"))
    assert d.num_changes == 1
    assert d.changed_words == [{"op": "replace", "before": "80mph", "after": "120mph", "count": 1}]


def test_insert_and_delete():
    assert word_diff(ORIG, ORIG.replace("heavy rain", "no heavy rain")).num_changes == 1
    assert word_diff(ORIG, ORIG.replace("heavy ", "")).num_changes == 1


def test_uneven_replace_counts_the_longer_side():
    d = word_diff("Prices rose 5% in March", "Prices fell sharply by 9% in March")
    assert d.num_changes == 4


def test_multiple_separate_edits_add_up():
    edited = ORIG.replace("80mph", "40mph").replace("heavy", "light").replace("UK", "France")
    assert word_diff(ORIG, edited).num_changes == 3
