#!/bin/bash
# Forge un projet avec chaque modèle Brokkr (chaque variante, le bot Discord avec tous
# ses modules), puis le teste dans des conteneurs officiels : pip + pytest + ruff
# (Python 3.13), npm + tsc + vitest (Node 22), QML hors écran (PySide6 de Debian) et
# analyse shellcheck. Essaie aussi « brokkr package », « add » et « save ». Nécessite Docker.
#
#   scripts/test-templates.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=$REPO/out/templates-test
rm -rf "$OUT"
mkdir -p "$OUT"

step() { printf '\n\033[1;33m» %s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✔\033[0m %s\n' "$*"; }

step "Forge des projets"
docker run --rm -v "$REPO:/src:ro" -v "$OUT:/out" -e PYTHONPATH=/src/src -e YGG_DATA_DIR=/src/data \
    -e NO_COLOR=1 -e HOME=/tmp/maison yggdrasil-builder bash -c '
        set -e
        b() { python3 -m yggdrasil.brokkr "$@" --dir /out --no-git --author Brokkr >/dev/null; }
        b new discord-bot Bot-Complet --modules moderation,niveaux,economie,tickets,musique,annonces,roles,concours
        b new discord-bot Bot-Simple --modules moderation
        b new discord-bot-js Bot-Ts
        for v in cli gui service automatisation; do b new python-app "App-$v" --variante "$v"; done
        for v in portfolio blog appli documentation; do b new site-web "Site-$v" --variante "$v"; done
        b new ia-locale Oracle
        b new qt-app Carnet
        b new jeu Etoiles --variante pygame
        b new jeu Etoiles-Godot --variante godot
        b new minecraft-pack Pack-Data --variante datapack
        b new minecraft-pack Pack-Ressources --variante resourcepack
        b new script-bash Compteur
        ls /out | sed "s/^/  forgé : /"
        chmod -R a+rwX /out'

step "Bot Discord, tous les modules (pip + pytest)"
docker run --rm -v "$OUT/bot-complet:/projet" -w /projet python:3.13-slim bash -c '
    pip install -q --root-user-action=ignore -r requirements-dev.txt -r requirements-musique.txt
    python -m pytest -q
    python -c "import importlib, pathlib; [importlib.import_module(\"cogs.\" + p.stem) for p in pathlib.Path(\"cogs\").glob(\"*.py\")]"
    python -m compileall -q bot.py database.py cogs'
ok "bot-complet : 8 modules importés, tests passés"
if [ -e "$OUT/bot-simple/cogs/musique.py" ] || [ ! -e "$OUT/bot-simple/cogs/moderation.py" ]; then
    echo "le bot simple ne doit avoir que ses modules" >&2; exit 1
fi
ok "bot-simple : seuls les modules choisis"

step "Bot Discord TypeScript (npm + tsc + vitest)"
docker run --rm -v "$OUT/bot-ts:/projet" -w /projet node:22-slim bash -c \
    'npm install --no-audit --no-fund --loglevel=error >/dev/null && npx tsc --noEmit && npm test --silent'
ok "bot-ts"

step "Projets Python (pip + pytest + ruff)"
py() { # py <projet> <commandes…>
    docker run --rm -v "$OUT/$1:/projet" -w /projet python:3.13-slim bash -c "$2"
    ok "$1"
}
py app-cli "pip install -q --root-user-action=ignore -e '.[dev]' && python -m pytest -q && ruff check . && app-cli README.md"
py app-gui "pip install -q --root-user-action=ignore pytest ruff && pip install -q --root-user-action=ignore --no-deps -e . && python -m pytest -q && ruff check ."
py app-service "pip install -q --root-user-action=ignore -e '.[dev]' && python -m pytest -q && ruff check ."
py app-automatisation "pip install -q --root-user-action=ignore -e '.[dev]' && python -m pytest -q && ruff check . \
    && app-automatisation --simulation /tmp"
py oracle "pip install -q --root-user-action=ignore -e '.[dev]' && python -m pytest -q && ruff check ."
py etoiles "pip install -q --root-user-action=ignore -e '.[dev]' && python -m pytest -q && ruff check ."
py carnet "pip install -q --root-user-action=ignore pytest ruff && pip install -q --root-user-action=ignore --no-deps -e . && python -m pytest -q && ruff check ."

step "Application Qt : la fenêtre QML se charge (PySide6 de Debian, hors écran)"
docker run --rm -v "$OUT/carnet:/projet:ro" -e QT_QPA_PLATFORM=offscreen -e QT_QUICK_BACKEND=software \
    -e XDG_DATA_HOME=/tmp yggdrasil-builder python3 - <<'EOF'
import sys
sys.path.insert(0, "/projet/src")
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, Property, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
app = QGuiApplication(sys.argv)
class Pont(QObject):
    changement = Signal()
    notes = Property("QStringList", lambda self: ["une note"], notify=changement)
moteur = QQmlApplicationEngine()
pont = Pont()
moteur.rootContext().setContextProperty("pont", pont)
moteur.load(QUrl.fromLocalFile("/projet/src/carnet/qml/Main.qml"))
assert moteur.rootObjects(), "Main.qml ne se charge pas"
print("  Main.qml chargé :", moteur.rootObjects()[0].property("title"))
EOF
ok "carnet (QML)"

step "Packs Minecraft, sites, Godot (formats)"
docker run --rm -v "$OUT:/out:ro" yggdrasil-builder python3 - <<'EOF'
import json, pathlib
from html.parser import HTMLParser
for pack, fmt in (("pack-data", 61), ("pack-ressources", 46)):
    racine = pathlib.Path("/out") / pack
    for f in list(racine.rglob("*.json")) + [racine / "pack.mcmeta"]:
        json.loads(f.read_text())
    assert json.loads((racine / "pack.mcmeta").read_text())["pack"]["pack_format"] == fmt
assert (pathlib.Path("/out/pack-data/data/pack_data/function/load.mcfunction")).exists()
for site in ("site-portfolio", "site-blog", "site-appli", "site-documentation"):
    pages = list((pathlib.Path("/out") / site).rglob("*.html"))
    assert pages, site
    for page in pages:
        HTMLParser().feed(page.read_text())
godot = pathlib.Path("/out/etoiles-godot")
assert "run/main_scene=\"res://scenes/principale.tscn\"" in (godot / "project.godot").read_text()
assert "\tvelocity = direction * VITESSE" in (godot / "scripts/joueur.gd").read_text()
print("  packs (pack_format 61 et 46), 4 sites, projet Godot : formats valides")
EOF
ok "formats"

step "Script bash (shellcheck + tests)"
docker run --rm -v "$OUT/compteur:/projet" -w /projet yggdrasil-builder bash -c \
    '[ -x compteur.sh ] && shellcheck compteur.sh tests/test.sh && ./tests/test.sh'
ok "compteur"

step "brokkr package, add, save"
docker run --rm -v "$REPO:/src:ro" -v "$OUT:/out" -e PYTHONPATH=/src/src -e YGG_DATA_DIR=/src/data \
    -e NO_COLOR=1 -e HOME=/tmp/maison yggdrasil-builder bash -c '
        set -e
        b() { python3 -m yggdrasil.brokkr "$@"; }
        b package --dir /out/app-cli >/dev/null
        dpkg-deb -c /out/app-cli/dist/app-cli_0.1.0_all.deb | grep -q "usr/bin/app-cli"
        dpkg-deb -c /out/app-cli/dist/app-cli_0.1.0_all.deb | grep -q "usr/lib/app-cli/app_cli/core.py"
        b package --dir /out/carnet >/dev/null
        dpkg-deb -f /out/carnet/dist/carnet_0.1.0_all.deb Depends | grep -q python3-pyside6.qtquick
        dpkg-deb -c /out/carnet/dist/carnet_0.1.0_all.deb | grep -q "usr/share/applications/carnet.desktop"
        echo "  .deb : app-cli et carnet (lanceur, menu, dépendances Qt)"
        b add docker --dir /out/app-service -y >/dev/null && grep -q "pip install" /out/app-service/Dockerfile
        b add ci --dir /out/bot-ts -y >/dev/null && grep -q "npm test" /out/bot-ts/.github/workflows/tests.yml
        b add module tickets --dir /out/bot-simple >/dev/null && [ -e /out/bot-simple/cogs/tickets.py ]
        grep -q tickets /out/bot-simple/.brokkr.json
        echo "  add : docker, ci, module tickets"
        b save mon-modele --dir /out/app-cli >/dev/null
        b new mon-modele Autre-Projet --dir /tmp --no-git >/dev/null
        grep -q "prog=.autre-projet." /tmp/autre-projet/src/autre_projet/cli.py
        echo "  save : le projet est devenu un modèle, réutilisé"'
ok "package, add, save"

step "Tous les modèles se forgent, compilent et passent leurs tests"
