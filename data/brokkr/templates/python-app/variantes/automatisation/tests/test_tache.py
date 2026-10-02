from {{snake}}.tache import main, plan


def test_rangement(tmp_path):
    for nom in ("photo.JPG", "facture.pdf", "inconnu.xyz"):
        (tmp_path / nom).write_text("x")
    (tmp_path / "Images").mkdir()
    (tmp_path / "Images" / "photo.JPG").write_text("déjà là")
    assert [(s.name, c.parent.name) for s, c in plan(tmp_path)] == [("facture.pdf", "Documents")]
    assert main([str(tmp_path)]) == 0
    assert (tmp_path / "Documents" / "facture.pdf").exists() and (tmp_path / "inconnu.xyz").exists()
