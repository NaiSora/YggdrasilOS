"""Un assistant : une consigne, une mémoire de conversation (bornée), et un modèle."""

from __future__ import annotations

from collections.abc import Iterator

from .ollama import Ollama

CONSIGNE = "Tu es {{name}}, un assistant qui répond en français, clairement et brièvement."


class Assistant:
    def __init__(self, client: Ollama, modele: str, consigne: str = CONSIGNE, memoire: int = 20) -> None:
        self.client = client
        self.modele = modele
        self.consigne = consigne
        self.memoire = memoire
        self.historique: list[dict[str, str]] = []

    def messages(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.consigne}, *self.historique[-self.memoire:]]

    def demander(self, question: str) -> Iterator[str]:
        self.historique.append({"role": "user", "content": question})
        reponse = []
        for morceau in self.client.discuter(self.modele, self.messages()):
            reponse.append(morceau)
            yield morceau
        self.historique.append({"role": "assistant", "content": "".join(reponse)})

    def oublier(self) -> None:
        self.historique.clear()
