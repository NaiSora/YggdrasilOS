from {{snake}}.service import tour


def test_tour(tmp_path):
    (tmp_path / "a.txt").write_text("un deux trois", encoding="utf-8")
    (tmp_path / "b.md").write_text("ignoré", encoding="utf-8")
    assert tour(tmp_path) == 3
