"""puits — le puits de Mímir : ce qu'il peut consulter pour te répondre.

Sources, en lecture seule : la documentation d'Yggdrasil et, si tu l'indiques,
ton coffre de notes Markdown (Obsidian ou autre). Les textes sont découpés en
extraits, changés en vecteurs par un modèle d'Ollama (« embeddings ») et rangés
dans ~/.local/share/yggdrasil/puits.sqlite. Tout reste sur ta machine.

Rien n'est indexé sans toi (« mimir puits remplir ») et « mimir puits vider »
efface tout. Les extraits retrouvés sont joints aux questions comme des données
(jamais comme des consignes), avec leur source pour que Mímir la cite.
"""

from __future__ import annotations

import array
import hashlib
import html.parser
import json
import math
import re
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import __version__, common
from .common import YggError

DOC_DIR = Path("/usr/share/doc/yggdrasil")
TAILLE_EXTRAIT = 900  # caractères
CHEVAUCHEMENT = 150
SEUIL = 0.35  # similarité minimale pour qu'un extrait soit retenu
LOT = 16  # extraits envoyés à Ollama par requête


def chemin_base() -> Path:
    return common.user_data_dir() / "yggdrasil" / "puits.sqlite"


# --------------------------------------------------------------------------
# Textes : lecture et découpage
# --------------------------------------------------------------------------

class _TexteHTML(html.parser.HTMLParser):
    """Texte lisible d'une page HTML (sans scripts ni styles)."""

    def __init__(self):
        super().__init__()
        self.parties: list[str] = []
        self._ignorer = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._ignorer += 1
        elif tag in ("p", "li", "tr", "h1", "h2", "h3", "h4", "pre", "br", "section"):
            self.parties.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._ignorer:
            self._ignorer -= 1

    def handle_data(self, data):
        if not self._ignorer:
            self.parties.append(data)


def texte_html(source: str) -> str:
    p = _TexteHTML()
    p.feed(source)
    texte = "".join(p.parties)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", texte)).strip()


def texte_markdown(source: str) -> str:
    """Retire l'en-tête YAML d'une note, garde le reste tel quel."""
    if source.startswith("---\n"):
        fin = source.find("\n---", 4)
        if fin != -1:
            source = source[fin + 4:]
    return source.strip()


def decouper(texte: str, taille: int = TAILLE_EXTRAIT, recouvrement: int = CHEVAUCHEMENT) -> list[str]:
    """Extraits d'environ `taille` caractères, coupés entre deux paragraphes si possible."""
    paragraphes = [p.strip() for p in re.split(r"\n\s*\n", texte) if p.strip()]
    extraits, courant = [], ""
    for para in paragraphes:
        while len(para) > taille:  # paragraphe géant : coupé net
            if courant:
                extraits.append(courant)
                courant = ""
            extraits.append(para[:taille])
            para = para[taille - recouvrement:]
        if courant and len(courant) + len(para) + 2 > taille:
            extraits.append(courant)
            courant = courant[-recouvrement:] + "\n\n" + para if recouvrement else para
        else:
            courant = f"{courant}\n\n{para}" if courant else para
    if courant:
        extraits.append(courant)
    return extraits


def documents(coffre: Path | None) -> Iterable[tuple[str, Path]]:
    """(nom de la source, fichier) pour la documentation et le coffre de notes."""
    if DOC_DIR.is_dir():
        for f in sorted(DOC_DIR.rglob("*.html")):
            yield f"doc:{f.relative_to(DOC_DIR)}", f
    if coffre and coffre.is_dir():
        for f in sorted(coffre.rglob("*.md")):
            if any(part.startswith(".") for part in f.relative_to(coffre).parts):
                continue  # .obsidian, .trash…
            yield f"coffre:{f.relative_to(coffre)}", f


def lire(fichier: Path) -> str:
    brut = fichier.read_text(encoding="utf-8", errors="replace")
    return texte_html(brut) if fichier.suffix.lower() in (".html", ".htm") else texte_markdown(brut)


# --------------------------------------------------------------------------
# Vecteurs (Ollama)
# --------------------------------------------------------------------------

def vectoriser_ollama(hote: str, modele: str, textes: list[str], timeout: float = 300) -> list[list[float]]:
    """Vecteurs des textes via /api/embed d'Ollama."""
    payload = json.dumps({"model": modele, "input": textes}).encode()
    req = urllib.request.Request(hote.rstrip("/") + "/api/embed", data=payload, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": f"mimir/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            vecteurs = json.loads(resp.read().decode()).get("embeddings") or []
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise YggError(f"le modèle « {modele} » n'est pas installé : mimir pull {modele}") from exc
        raise YggError(f"Ollama a répondu {exc.code} au calcul des vecteurs") from exc
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        raise YggError(f"Ollama ne répond pas sur {hote}") from exc
    if len(vecteurs) != len(textes):
        raise YggError("Ollama n'a pas renvoyé un vecteur par extrait")
    return vecteurs


def normaliser(vecteur: list[float]) -> array.array:
    norme = math.sqrt(sum(x * x for x in vecteur)) or 1.0
    return array.array("f", (x / norme for x in vecteur))


# --------------------------------------------------------------------------
# Le puits
# --------------------------------------------------------------------------

@dataclass
class Extrait:
    source: str
    texte: str
    score: float


class Puits:
    def __init__(self, base: Path | None = None):
        self.base = base or chemin_base()

    def _connexion(self) -> sqlite3.Connection:
        self.base.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.base)
        con.execute("CREATE TABLE IF NOT EXISTS fichiers (source TEXT PRIMARY KEY, empreinte TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS extraits (source TEXT, texte TEXT, vecteur BLOB)")
        con.execute("CREATE INDEX IF NOT EXISTS par_source ON extraits(source)")
        return con

    def existe(self) -> bool:
        return self.base.exists()

    def etat(self) -> tuple[int, int]:
        """(nombre de fichiers, nombre d'extraits)."""
        if not self.existe():
            return 0, 0
        with self._connexion() as con:
            fichiers = con.execute("SELECT COUNT(*) FROM fichiers").fetchone()[0]
            extraits = con.execute("SELECT COUNT(*) FROM extraits").fetchone()[0]
        return fichiers, extraits

    def remplir(self, sources: Iterable[tuple[str, Path]], vectoriser: Callable[[list[str]], list[list[float]]],
                progression: Callable[[str], None] | None = None) -> tuple[int, int, int]:
        """Indexe les fichiers nouveaux ou modifiés, oublie ceux qui ont disparu.

        Renvoie (fichiers indexés, fichiers inchangés, fichiers oubliés).
        """
        indexes = inchanges = 0
        vus: set[str] = set()
        with self._connexion() as con:
            connus = dict(con.execute("SELECT source, empreinte FROM fichiers"))
            for source, fichier in sources:
                vus.add(source)
                try:
                    texte = lire(fichier)
                except OSError:
                    continue
                empreinte = hashlib.sha256(texte.encode()).hexdigest()
                if connus.get(source) == empreinte:
                    inchanges += 1
                    continue
                if progression:
                    progression(source)
                morceaux = decouper(texte)
                vecteurs: list[list[float]] = []
                for i in range(0, len(morceaux), LOT):
                    vecteurs += vectoriser(morceaux[i:i + LOT])
                con.execute("DELETE FROM extraits WHERE source = ?", (source,))
                con.executemany(
                    "INSERT INTO extraits VALUES (?, ?, ?)",
                    [(source, m, normaliser(v).tobytes()) for m, v in zip(morceaux, vecteurs, strict=True)],
                )
                con.execute("INSERT OR REPLACE INTO fichiers VALUES (?, ?)", (source, empreinte))
                con.commit()
                indexes += 1
            disparus = set(connus) - vus
            for source in disparus:
                con.execute("DELETE FROM extraits WHERE source = ?", (source,))
                con.execute("DELETE FROM fichiers WHERE source = ?", (source,))
        return indexes, inchanges, len(disparus)

    def chercher(self, vecteur_question: list[float], k: int = 4, seuil: float = SEUIL) -> list[Extrait]:
        if not self.existe():
            return []
        q = normaliser(vecteur_question)
        meilleurs: list[Extrait] = []
        with self._connexion() as con:
            for source, texte, blob in con.execute("SELECT source, texte, vecteur FROM extraits"):
                v = array.array("f")
                v.frombytes(blob)
                if len(v) != len(q):
                    continue  # indexé avec un autre modèle
                score = sum(a * b for a, b in zip(q, v))
                if score >= seuil:
                    meilleurs.append(Extrait(source, texte, score))
        meilleurs.sort(key=lambda e: e.score, reverse=True)
        return meilleurs[:k]

    def vider(self) -> bool:
        if self.existe():
            self.base.unlink()
            return True
        return False
