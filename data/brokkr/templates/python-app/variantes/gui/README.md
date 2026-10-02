# {{name}}

Application graphique Qt (PySide6) forgée par **Brokkr** sur Yggdrasil le {{date}}.

```bash
python3 -m venv --system-site-packages .venv && . .venv/bin/activate   # PySide6 de Debian
pip install -e ".[dev]"
{{slug}}
brokkr package          # .deb avec lanceur dans le menu (python3-pyside6 en dépendance)
```
