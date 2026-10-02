#!/usr/bin/env python3
"""Vérifie le site assemblé par build-site.sh, avant sa publication.

    verifier-site.py DOSSIER_DU_SITE

Chaque lien interne, image et police doit exister ; chaque page doit avoir un titre et une
langue ; app.js doit se compiler (moteur JavaScript de Qt, s'il est là). Code 1 au moindre
manque, avec la liste.
"""
import html.parser
import re
import sys
import urllib.parse
from pathlib import Path

PREFIXE = "/YggdrasilOS/"  # l'adresse du site sur GitHub Pages (404.html l'utilise)


class Page(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.liens, self.titre, self.langue, self.dans_titre = [], "", None, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.langue = attrs.get("lang")
        if tag == "title":
            self.dans_titre = True
        for cle in ("href", "src"):
            if attrs.get(cle):
                self.liens.append(attrs[cle])

    def handle_endtag(self, tag):
        if tag == "title":
            self.dans_titre = False

    def handle_data(self, data):
        if self.dans_titre:
            self.titre += data


def cible(racine: Path, depuis: Path, lien: str) -> Path | None:
    """Le fichier visé par un lien interne, ou None si le lien sort du site."""
    morceaux = urllib.parse.urlsplit(lien)
    if morceaux.scheme or morceaux.netloc or lien.startswith(("#", "mailto:")) or not morceaux.path:
        return None
    chemin = urllib.parse.unquote(morceaux.path)
    if chemin.startswith(PREFIXE):
        fichier = racine / chemin[len(PREFIXE):]
    elif chemin.startswith("/"):
        fichier = racine / "__absolu__" / chemin.lstrip("/")  # hors du site publié : manquant
    else:
        fichier = depuis.parent / chemin
    if chemin.endswith("/") or fichier.is_dir():
        fichier = fichier / "index.html"
    return fichier


def syntaxe_js(code: str) -> str | None:
    """Erreur de syntaxe d'app.js, compilé sans l'exécuter (enveloppé dans une fonction)."""
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtQml import QJSEngine
    except ImportError:
        return None
    application = QCoreApplication.instance() or QCoreApplication([])  # Qt l'exige avant le moteur
    moteur = QJSEngine(application)
    resultat = moteur.evaluate("(function () {\n" + code + "\n})")
    if resultat.isError():
        return resultat.toString()
    return None


def main(argv: list[str]) -> int:
    racine = Path(argv[1]).resolve()
    manques = []
    pages = sorted(racine.rglob("*.html"))
    for page in pages:
        p = Page()
        p.feed(page.read_text(encoding="utf-8"))
        nom = page.relative_to(racine).as_posix()
        if not p.titre.strip():
            manques.append(f"{nom} : pas de <title>")
        if not p.langue:
            manques.append(f"{nom} : pas de langue (<html lang>)")
        for lien in p.liens:
            fichier = cible(racine, page, lien)
            if fichier is not None and not fichier.resolve().is_file():
                manques.append(f"{nom} : lien cassé {lien}")
    for feuille in racine.rglob("*.css"):
        for lien in re.findall(r"url\([\"']?([^\"')]+)", feuille.read_text(encoding="utf-8")):
            fichier = cible(racine, feuille, lien)
            if fichier is not None and not fichier.resolve().is_file():
                manques.append(f"{feuille.relative_to(racine).as_posix()} : police ou image absente {lien}")
    app = racine / "app.js"
    if app.is_file():
        erreur = syntaxe_js(app.read_text(encoding="utf-8"))
        if erreur:
            manques.append(f"app.js : {erreur}")
    for manque in manques:
        print(manque, file=sys.stderr)
    if not manques:
        print(f"{len(pages)} pages, tous les liens internes, images et polices présents")
    return 1 if manques else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
