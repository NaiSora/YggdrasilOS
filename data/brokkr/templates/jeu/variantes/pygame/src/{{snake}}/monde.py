"""La logique du jeu, sans pygame : un joueur, des étoiles, un score. Facile à tester."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

LARGEUR, HAUTEUR = 960, 540
VITESSE = 300.0  # pixels par seconde
RAYON_JOUEUR, RAYON_ETOILE = 18, 10


@dataclass
class Monde:
    x: float = LARGEUR / 2
    y: float = HAUTEUR / 2
    score: int = 0
    etoiles: list[tuple[float, float]] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)

    def __post_init__(self) -> None:
        while len(self.etoiles) < 5:
            self.etoiles.append(self.nouvelle_etoile())

    def nouvelle_etoile(self) -> tuple[float, float]:
        return (self.rng.uniform(20, LARGEUR - 20), self.rng.uniform(20, HAUTEUR - 20))

    def avancer(self, dx: float, dy: float, dt: float) -> None:
        """Déplace le joueur (dx, dy entre -1 et 1), le garde à l'écran, ramasse les étoiles."""
        norme = (dx * dx + dy * dy) ** 0.5 or 1.0
        self.x = min(max(self.x + dx / norme * VITESSE * dt, RAYON_JOUEUR), LARGEUR - RAYON_JOUEUR)
        self.y = min(max(self.y + dy / norme * VITESSE * dt, RAYON_JOUEUR), HAUTEUR - RAYON_JOUEUR)
        for i, (ex, ey) in enumerate(self.etoiles):
            if (ex - self.x) ** 2 + (ey - self.y) ** 2 <= (RAYON_JOUEUR + RAYON_ETOILE) ** 2:
                self.score += 1
                self.etoiles[i] = self.nouvelle_etoile()
