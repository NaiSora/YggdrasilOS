#!/usr/bin/env python3
"""Vérifie le site assemblé par build-site.sh, avant sa publication.

    verifier-site.py DOSSIER_DU_SITE [--externes]

Chaque lien interne (ancres comprises), image et police doit exister ; chaque page doit avoir
un titre, une langue, une description, son adresse canonique, son aperçu de partage et ses
icônes ; chaque image, un texte de remplacement ; le plan du site doit lister exactement les
pages à indexer ; aucune image ne doit dépasser 250 ko ; app.js doit se compiler (moteur
JavaScript de Qt, s'il est là). --externes vérifie aussi les liens vers d'autres sites (réseau).
Code 1 au moindre manque, avec la liste.
"""
import html.parser
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ADRESSE = "https://naisora.github.io/YggdrasilOS/"  # comme dans build-site.sh
PREFIXE = urllib.parse.urlsplit(ADRESSE).path  # 404.html l'utilise : liens absolus
POIDS_MAX = 250_000
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".svg"}
DESCRIPTION = (50, 160)  # au-delà, les moteurs de recherche coupent


class Page(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.liens, self.ids, self.meta, self.rel = [], set(), {}, {}
        self.titre, self.langue, self.dans_titre = "", None, False
        self.sans_alt, self.externes = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.langue = a.get("lang")
        if tag == "title":
            self.dans_titre = True
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "meta" and (a.get("name") or a.get("property")):
            self.meta[a.get("name") or a.get("property")] = a.get("content") or ""
        if tag == "link":
            for rel in (a.get("rel") or "").split():
                self.rel.setdefault(rel, []).append(a.get("href") or "")
        if tag == "img" and "alt" not in a:
            self.sans_alt.append(a.get("src") or "?")
        for cle in ("href", "src", "data-grand"):
            if a.get(cle):
                self.liens.append(a[cle])
        if a.get("srcset"):
            self.liens += [c.split()[0] for c in a["srcset"].split(",") if c.strip()]
        if tag == "a" and (a.get("href") or "").startswith(("http://", "https://")):
            self.externes.append(a["href"])

    def handle_endtag(self, tag):
        if tag == "title":
            self.dans_titre = False

    def handle_data(self, data):
        if self.dans_titre:
            self.titre += data


def cible(racine: Path, depuis: Path, lien: str) -> Path | None:
    """Le fichier visé par un lien interne (ou une adresse absolue du site), None s'il sort du site."""
    if lien.startswith(ADRESSE):
        lien = PREFIXE + lien[len(ADRESSE):]
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


def adresse_publique(racine: Path, page: Path) -> str:
    """L'adresse d'une page une fois publiée (index.html → le dossier)."""
    return ADRESSE + re.sub(r"(^|/)index\.html$", r"\1", page.relative_to(racine).as_posix())


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


def metadonnees(nom: str, p: Page, attendue: str) -> list[str]:
    """Ce qui manque à l'en-tête d'une page à indexer (description, canonique, partage, icônes)."""
    manques = []
    description = p.meta.get("description", "")
    if not DESCRIPTION[0] <= len(description) <= DESCRIPTION[1]:
        manques.append(f"{nom} : description de {len(description)} caractères "
                       f"(il en faut {DESCRIPTION[0]} à {DESCRIPTION[1]})")
    if p.rel.get("canonical") != [attendue]:
        manques.append(f"{nom} : adresse canonique {p.rel.get('canonical')}, attendue {attendue}")
    if p.meta.get("og:url") != attendue:
        manques.append(f"{nom} : og:url {p.meta.get('og:url')!r}, attendue {attendue}")
    for cle in ("og:title", "og:description", "og:image", "og:image:alt", "og:type", "twitter:card"):
        if not p.meta.get(cle):
            manques.append(f"{nom} : pas de {cle}")
    if p.meta.get("og:image") and not p.meta["og:image"].startswith(ADRESSE):
        manques.append(f"{nom} : og:image doit être une adresse absolue du site ({p.meta['og:image']})")
    if "robots" in p.meta and "noindex" in p.meta["robots"]:
        manques.append(f"{nom} : marquée noindex, mais dans le plan du site")
    return manques


def externes(liens: set[str]) -> list[str]:
    """Les liens vers d'autres sites qui ne répondent pas (HEAD, puis GET si HEAD est refusé)."""
    cassés = []
    for lien in sorted(liens):
        statut = None
        for methode in ("HEAD", "GET"):
            requete = urllib.request.Request(lien, method=methode, headers={
                "User-Agent": "Mozilla/5.0 (verifier-site.py ; site d'Yggdrasil)", "Accept": "*/*"})
            try:
                with urllib.request.urlopen(requete, timeout=30) as r:  # noqa: S310
                    statut = r.status
            except urllib.error.HTTPError as e:
                statut = e.code
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                statut = f"injoignable ({getattr(e, 'reason', e)})"
            if statut == 200:
                break
        if statut != 200:
            cassés.append(f"lien externe {lien} : {statut}")
    return cassés


def main(argv: list[str]) -> int:
    racine = Path(argv[1]).resolve()
    manques = []
    pages = {page: Page() for page in sorted(racine.rglob("*.html"))}
    for page, p in pages.items():
        p.feed(page.read_text(encoding="utf-8"))
    a_indexer = set()
    liens_externes = set()
    for page, p in pages.items():
        nom = page.relative_to(racine).as_posix()
        if not p.titre.strip():
            manques.append(f"{nom} : pas de <title>")
        if not p.langue:
            manques.append(f"{nom} : pas de langue (<html lang>)")
        if not p.rel.get("icon"):
            manques.append(f"{nom} : pas d'icône (<link rel=\"icon\">)")
        for src in p.sans_alt:
            manques.append(f"{nom} : image sans texte de remplacement (alt) : {src}")
        if nom == "404.html":
            if "noindex" not in p.meta.get("robots", ""):
                manques.append("404.html : doit porter <meta name=\"robots\" content=\"noindex\">")
        else:
            a_indexer.add(adresse_publique(racine, page))
            manques += metadonnees(nom, p, adresse_publique(racine, page))
        liens = p.liens + p.rel.get("canonical", []) + [p.meta.get("og:image", "")]
        for lien in filter(None, liens):
            fichier = cible(racine, page, lien)
            if fichier is not None and not fichier.resolve().is_file():
                manques.append(f"{nom} : lien cassé {lien}")
                continue
            ancre = urllib.parse.urlsplit(lien).fragment
            visee = page if lien.startswith("#") else fichier
            if ancre and visee is not None and visee.suffix == ".html":
                cibles = pages.get(visee.resolve()) or pages.get(visee)
                if cibles is not None and ancre not in cibles.ids:
                    manques.append(f"{nom} : ancre introuvable {lien}")
        liens_externes.update(lien for lien in p.externes if not lien.startswith(ADRESSE))

    # Le plan du site : exactement les pages à indexer
    plan = racine / "sitemap.xml"
    if plan.is_file():
        espace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        listees = {loc.text for loc in ET.parse(plan).getroot().iter(f"{espace}loc")}
        for adresse in sorted(listees - a_indexer):
            manques.append(f"sitemap.xml : {adresse} n'est pas une page du site à indexer")
        for adresse in sorted(a_indexer - listees):
            manques.append(f"sitemap.xml : il manque {adresse}")
    else:
        manques.append("pas de sitemap.xml")

    for feuille in racine.rglob("*.css"):
        for lien in re.findall(r"url\([\"']?([^\"')]+)", feuille.read_text(encoding="utf-8")):
            fichier = cible(racine, feuille, lien)
            if fichier is not None and not fichier.resolve().is_file():
                manques.append(f"{feuille.relative_to(racine).as_posix()} : police ou image absente {lien}")
    for image in racine.rglob("*"):
        if image.suffix.lower() in IMAGES and image.stat().st_size > POIDS_MAX:
            manques.append(f"{image.relative_to(racine).as_posix()} : {image.stat().st_size // 1000} ko, "
                           f"plus de {POIDS_MAX // 1000} ko")
    app = racine / "app.js"
    if app.is_file():
        erreur = syntaxe_js(app.read_text(encoding="utf-8"))
        if erreur:
            manques.append(f"app.js : {erreur}")
    if "--externes" in argv:
        manques += externes(liens_externes)

    for manque in manques:
        print(manque, file=sys.stderr)
    if not manques:
        print(f"{len(pages)} pages : liens, ancres, images, polices, en-têtes et plan du site complets"
              + (f", {len(liens_externes)} liens externes joignables" if "--externes" in argv else ""))
    return 1 if manques else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
