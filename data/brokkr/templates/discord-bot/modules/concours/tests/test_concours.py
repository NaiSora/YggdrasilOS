import random

from cogs.concours import parse_duree, tirer_gagnants


def test_tirage():
    rng = random.Random(4)
    assert sorted(tirer_gagnants([1, 2, 2, 3], 2, rng)) in ([1, 2], [1, 3], [2, 3])
    assert tirer_gagnants([7, 7], 3, rng) == [7]
    assert tirer_gagnants([], 1, rng) == []
    assert parse_duree("1j2h") == 93600
