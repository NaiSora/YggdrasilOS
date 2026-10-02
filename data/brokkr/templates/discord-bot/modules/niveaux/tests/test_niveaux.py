from cogs.niveaux import niveau_de, points_pour


def test_niveaux():
    assert [niveau_de(p) for p in (0, 49, 50, 199, 200, 450, 10_000)] == [0, 0, 1, 1, 2, 3, 14]
    assert all(niveau_de(points_pour(n)) == n for n in range(50))
