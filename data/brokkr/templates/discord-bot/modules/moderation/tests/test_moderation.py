from cogs.moderation import parse_duree


def test_durees():
    assert parse_duree("10m") == 600
    assert parse_duree("1h30m") == 5400
    assert parse_duree("2j") == 172800
    assert parse_duree("45 s") == 45
    assert parse_duree("demain") == 0
