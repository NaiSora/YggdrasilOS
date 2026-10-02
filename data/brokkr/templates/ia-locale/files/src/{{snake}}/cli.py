"""{{name}} dans le terminal : pose une question, la réponse s'écrit au fil de l'eau."""

from __future__ import annotations

import argparse
import sys

from .assistant import Assistant
from .ollama import Ollama, OllamaErreur


def lignes():
    """Les questions : tapées au clavier, ou lues depuis un tube (echo … | {{slug}})."""
    if not sys.stdin.isatty():
        yield from sys.stdin
        return
    while True:
        try:
            yield input("› ")
        except (EOFError, KeyboardInterrupt):
            print()
            return


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="{{slug}}", description="{{name}} — un assistant 100 % local.")
    p.add_argument("--modele", default="qwen3:8b")
    p.add_argument("--hote", default="http://127.0.0.1:11434")
    args = p.parse_args(argv)
    assistant = Assistant(Ollama(args.hote), args.modele)
    print("{{name}} t'écoute (/oublier pour effacer la conversation, Ctrl+D pour quitter).")
    for ligne in lignes():
        question = ligne.strip()
        if not question:
            continue
        if question == "/oublier":
            assistant.oublier()
            print("Conversation oubliée.")
            continue
        try:
            for morceau in assistant.demander(question):
                print(morceau, end="", flush=True)
            print()
        except OllamaErreur as exc:
            print(f"erreur : {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
