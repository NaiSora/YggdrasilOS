"""{{name}} : la fenêtre, le clavier, le dessin. La logique est dans monde.py."""

from __future__ import annotations

from .monde import HAUTEUR, LARGEUR, RAYON_ETOILE, RAYON_JOUEUR, Monde


def main() -> int:
    import pygame

    pygame.init()
    ecran = pygame.display.set_mode((LARGEUR, HAUTEUR))
    pygame.display.set_caption("{{name}}")
    horloge = pygame.time.Clock()
    police = pygame.font.Font(None, 36)
    monde = Monde()
    while True:
        for evenement in pygame.event.get():
            if evenement.type == pygame.QUIT:
                pygame.quit()
                return 0
        touches = pygame.key.get_pressed()
        dx = (touches[pygame.K_RIGHT] or touches[pygame.K_d]) - (touches[pygame.K_LEFT] or touches[pygame.K_q])
        dy = (touches[pygame.K_DOWN] or touches[pygame.K_s]) - (touches[pygame.K_UP] or touches[pygame.K_z])
        monde.avancer(dx, dy, horloge.tick(60) / 1000)
        ecran.fill((9, 28, 48))
        for ex, ey in monde.etoiles:
            pygame.draw.circle(ecran, (251, 227, 155), (int(ex), int(ey)), RAYON_ETOILE)
        pygame.draw.circle(ecran, (121, 172, 153), (int(monde.x), int(monde.y)), RAYON_JOUEUR)
        ecran.blit(police.render(f"Étoiles : {monde.score}", True, (232, 204, 140)), (16, 12))
        pygame.display.flip()


if __name__ == "__main__":
    raise SystemExit(main())
