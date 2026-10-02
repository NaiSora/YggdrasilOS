"""Client minimal pour Ollama (http://127.0.0.1:11434), sans dépendance."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator


class OllamaErreur(RuntimeError):
    pass


class Ollama:
    def __init__(self, hote: str = "http://127.0.0.1:11434", delai: float = 300) -> None:
        self.hote = hote.rstrip("/")
        self.delai = delai

    def _requete(self, chemin: str, donnees: dict | None = None):
        corps = json.dumps(donnees).encode() if donnees is not None else None
        req = urllib.request.Request(self.hote + chemin, data=corps,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if corps is not None else "GET")
        try:
            return urllib.request.urlopen(req, timeout=self.delai)
        except (urllib.error.URLError, OSError) as exc:
            raise OllamaErreur(f"Ollama ne répond pas sur {self.hote} ({exc})") from exc

    def modeles(self) -> list[str]:
        with self._requete("/api/tags") as reponse:
            return [m["name"] for m in json.load(reponse).get("models", [])]

    def discuter(self, modele: str, messages: list[dict[str, str]]) -> Iterator[str]:
        """La réponse, morceau par morceau, au fil de l'écriture du modèle."""
        with self._requete("/api/chat", {"model": modele, "messages": messages, "stream": True}) as reponse:
            for ligne in reponse:
                if not ligne.strip():
                    continue
                morceau = json.loads(ligne)
                if "error" in morceau:
                    raise OllamaErreur(morceau["error"])
                yield morceau.get("message", {}).get("content", "")
                if morceau.get("done"):
                    break
