import random

from {{snake}}.monde import HAUTEUR, LARGEUR, RAYON_JOUEUR, Monde


def test_deplacement_borne_et_ramassage():
    monde = Monde(rng=random.Random(1))
    monde.avancer(-1, 0, 100)  # très loin à gauche : arrêté au bord
    assert monde.x == RAYON_JOUEUR
    monde.etoiles[0] = (monde.x + 5, monde.y)
    monde.avancer(0, 0, 0.1)
    assert monde.score == 1 and len(monde.etoiles) == 5
    monde.avancer(1, 1, 100)
    assert (monde.x, monde.y) == (LARGEUR - RAYON_JOUEUR, HAUTEUR - RAYON_JOUEUR)
