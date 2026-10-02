"""Interface en ligne de commande de {{name}}."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .core import word_stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="{{slug}}", description="{{name}} — exemple : statistiques d'un texte.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("fichier", nargs="?", help="fichier texte à analyser (défaut : entrée standard)")
    parser.add_argument("-n", "--top", type=int, default=5, help="nombre de mots les plus fréquents")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.fichier:
        try:
            with open(args.fichier, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"erreur : {exc}", file=sys.stderr)
            return 1
    else:
        text = sys.stdin.read()
    stats = word_stats(text, top=args.top)
    print(f"{stats.lines} lignes, {stats.words} mots, {stats.characters} caractères")
    for word, count in stats.most_common:
        print(f"  {word:<20} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
