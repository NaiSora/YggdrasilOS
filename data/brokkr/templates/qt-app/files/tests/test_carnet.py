from {{snake}}.carnet import Carnet


def test_carnet(tmp_path):
    fichier = tmp_path / "notes.json"
    carnet = Carnet(fichier)
    assert carnet.ajouter("première") and carnet.ajouter("seconde")
    assert not carnet.ajouter("   ")
    carnet.retirer(5)
    assert Carnet(fichier).notes == ["seconde", "première"]
    carnet.retirer(0)
    assert Carnet(fichier).notes == ["première"]
