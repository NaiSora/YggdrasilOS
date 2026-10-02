# {{name}}

Outil en ligne de commande forgé par **Brokkr** sur Yggdrasil le {{date}}.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
{{slug}} README.md
pytest && ruff check .
brokkr package          # un .deb installable
```

- `src/{{snake}}/core.py` : la logique (sans entrées/sorties, facile à tester)
- `src/{{snake}}/cli.py` : la ligne de commande
