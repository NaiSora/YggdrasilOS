import datetime as dt

from cogs.economie import attente_quotidien


def test_quotidien():
    maintenant = dt.datetime(2026, 10, 1, 12, 0)
    assert attente_quotidien(None, maintenant) == dt.timedelta(0)
    assert attente_quotidien("2026-10-01T10:00:00", maintenant) == dt.timedelta(hours=18)
    assert attente_quotidien("2026-09-30T10:00:00", maintenant) == dt.timedelta(0)
