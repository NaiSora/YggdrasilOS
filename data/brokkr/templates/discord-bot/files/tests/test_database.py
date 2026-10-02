import asyncio

from database import Database


def test_tables_and_queries():
    async def scenario():
        db = Database(":memory:")
        await db.connect()
        await db.ensure("CREATE TABLE IF NOT EXISTS t (cle TEXT PRIMARY KEY, valeur INTEGER);")
        await db.execute("INSERT INTO t VALUES (?, ?)", ("a", 1))
        await db.execute("INSERT INTO t VALUES (?, ?)", ("b", 2))
        une = await db.fetchone("SELECT valeur FROM t WHERE cle = ?", ("b",))
        toutes = await db.fetchall("SELECT cle FROM t ORDER BY cle")
        await db.close()
        return une, toutes

    assert asyncio.run(scenario()) == ((2,), [("a",), ("b",)])
