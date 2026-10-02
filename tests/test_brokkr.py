"""Brokkr : modèles, variantes, modules, idée, add, package, save."""

import json
import py_compile
from types import SimpleNamespace

import pytest

from yggdrasil import brokkr
from yggdrasil.common import YggError

TEMPLATES = ["discord-bot", "discord-bot-js", "python-app", "site-web", "ia-locale", "qt-app", "jeu",
             "minecraft-pack", "script-bash"]
RETIRES = ["twitch-bot", "paper-plugin", "velocity-plugin", "web-api", "flutter-app"]


def test_naming_helpers():
    assert brokkr.slugify("Mon Super-Bot") == "mon-super-bot"
    assert brokkr.pascal_case("sheep-wars") == "SheepWars"
    assert brokkr.pascal_case("42bot") == "Projet42bot"
    assert brokkr.snake_case("SheepWars") == "sheep_wars"
    assert brokkr.snake_case("mon-bot") == "mon_bot"


def test_build_variables():
    v = brokkr.build_variables("SheepWars", "Alice Martin")
    assert (v["class"], v["slug"], v["snake"]) == ("SheepWars", "sheepwars", "sheep_wars")
    assert v["app_id"] == "io.github.alicemartin.SheepWars" and v["modules"] == "aucun"
    with pytest.raises(YggError):
        brokkr.build_variables("../evil", "x")


def test_the_forge_holds_the_chosen_templates():
    loaded = brokkr.load_templates()
    assert set(TEMPLATES) == set(loaded) and not set(RETIRES) & set(loaded)
    bot = loaded["discord-bot"]
    assert [m.id for m in bot.modules] == ["moderation", "niveaux", "economie", "tickets", "musique", "annonces",
                                           "roles", "concours"]
    assert [v.id for v in loaded["python-app"].variantes] == ["cli", "gui", "service", "automatisation"]
    assert [v.id for v in loaded["site-web"].variantes] == ["portfolio", "blog", "appli", "documentation"]


def combinaisons():
    for nom in TEMPLATES:
        tpl = brokkr.load_templates()[nom]
        for v in tpl.variantes or [None]:
            yield nom, (v.id if v else None)


@pytest.mark.parametrize("nom, variante", list(combinaisons()))
def test_render_every_template_and_variant(nom, variante, tmp_path):
    tpl = brokkr.load_templates()[nom]
    tous = [m.id for m in tpl.modules]
    choix_v, choix_m = tpl.variante(variante), tpl.choisir_modules(tous)
    variables = brokkr.build_variables("SheepWars", "Testeur", choix_v, choix_m)
    created = brokkr.render_template(tpl, tmp_path, variables, choix_v, choix_m)
    assert created
    for path in created:
        text = path.read_text(encoding="utf-8")
        assert "{{" not in text, f"variable non remplacée dans {path}"
        assert "{{" not in str(path)
        if path.suffix == ".py":
            py_compile.compile(str(path), doraise=True)
        if path.suffix in (".json", ".mcmeta"):
            json.loads(text)
        if path.suffix == ".sh":
            assert path.stat().st_mode & 0o111, f"{path} n'est pas exécutable"


def test_modules_and_variants_are_overlays(tmp_path):
    bot = brokkr.load_templates()["discord-bot"]
    mods = bot.choisir_modules(["tickets"])
    created = brokkr.render_template(bot, tmp_path, brokkr.build_variables("B", "x", None, mods), None, mods)
    noms = {p.relative_to(tmp_path).as_posix() for p in created}
    assert "cogs/tickets.py" in noms and "cogs/moderation.py" not in noms and "bot.py" in noms
    assert "requirements-musique.txt" not in noms
    assert [m.id for m in bot.choisir_modules(None)] == ["moderation", "niveaux"]
    with pytest.raises(YggError, match="module inconnu"):
        bot.choisir_modules(["fusee"])
    app = brokkr.load_templates()["python-app"]
    with pytest.raises(YggError, match="variante inconnue"):
        app.variante("mobile")
    assert app.variante(None).id == "cli"


def test_idea_by_keywords():
    bot = brokkr.load_templates()["discord-bot"]
    assert brokkr.modules_par_mots(bot, "Un bot pour gérer les tickets de support et des concours, avec de la "
                                        "musique") == ["tickets", "musique", "concours"]
    assert brokkr.modules_par_mots(bot, "il annonce mes lives Twitch") == ["annonces"]


def test_unknown_variable_is_an_error():
    with pytest.raises(YggError):
        brokkr.substitute("{{inconnue}}", {"name": "x"})


def forge(tmp_path, modele, nom, **kw):
    tpl = brokkr.load_templates()[modele]
    runner = SimpleNamespace(dry_run=False, query=lambda *a, **k: (1, ""))
    return brokkr.forger(tpl, nom, tmp_path, runner, {}, auteur="Testeur", git=False, **kw)


def test_new_records_the_choices_and_add_module(tmp_path, fake_runner):
    dest = forge(tmp_path, "discord-bot", "Gardien", modules=["moderation"])
    marque = json.loads((dest / brokkr.MARQUE).read_text())
    assert marque == {"modele": "discord-bot", "variante": "", "modules": ["moderation"], "nom": "Gardien",
                      "cree": marque["cree"]}
    args = SimpleNamespace(dir=str(dest), brique="module", nom="concours", yes=True)
    assert brokkr.cmd_add(args, fake_runner(), {}) == 0
    assert (dest / "cogs" / "concours.py").exists()
    assert json.loads((dest / brokkr.MARQUE).read_text())["modules"] == ["moderation", "concours"]


def test_add_docker_and_ci(tmp_path, fake_runner):
    dest = forge(tmp_path, "python-app", "Outil", variante="service")
    assert brokkr.cmd_add(SimpleNamespace(dir=str(dest), brique="docker", nom=None, yes=True), fake_runner(), {}) == 0
    dockerfile = (dest / "Dockerfile").read_text()
    assert "pip install --no-cache-dir -e ." in dockerfile and 'CMD ["outil"]' in dockerfile
    brokkr.cmd_add(SimpleNamespace(dir=str(dest), brique="ci", nom=None, yes=True), fake_runner(), {})
    assert "python -m pytest" in (dest / ".github" / "workflows" / "tests.yml").read_text()


def test_save_turns_a_project_into_a_template(tmp_path, fake_runner, monkeypatch):
    dest = forge(tmp_path, "python-app", "Rangeur", variante="automatisation")
    (dest / ".env").write_text("SECRET=1")
    args = SimpleNamespace(dir=str(dest), modele="rangement", titre="Mon rangement", yes=True)
    assert brokkr.cmd_save(args, fake_runner(), {}) == 0
    modele = brokkr.user_templates_dir() / "rangement"
    assert (modele / "files" / "src" / "{{snake}}" / "tache.py").exists()
    assert not (modele / "files" / "dot-env").exists() and (modele / "files" / "dot-gitignore").exists()
    tpl = brokkr.load_templates()["rangement"]
    assert tpl.perso and tpl.title == "Mon rangement"
    autre = forge(tmp_path, "rangement", "Classeur")
    assert "classeur" in (autre / "pyproject.toml").read_text()
    assert (autre / "src" / "classeur" / "tache.py").exists()


def test_deb_control():
    texte = brokkr.control_deb("outil", "0.1.0", "Un outil", ["python3 (>= 3.11)"], "testeur")
    assert texte.startswith("Package: outil\nVersion: 0.1.0\nArchitecture: all\n")
    assert "Depends: python3 (>= 3.11)\n" in texte
