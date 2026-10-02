# {{name}}

Bot Discord forgé par **Brokkr** sur Yggdrasil le {{date}}. Modules : {{modules}}.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env     # colle ton jeton
python bot.py
python -m pytest -q
```

- `bot.py` : démarrage, chargement automatique des modules de `cogs/`
- `database.py` : la base SQLite (chaque module y crée ses tables)
- `cogs/` : un fichier par module ; `brokkr add module <id>` en ajoute un
- hébergement : `brokkr deploy` (Bifröst le relance s'il plante, `bifrost logs {{slug}} -f`)
