# {{name}}

Application Qt (PySide6 + QML) forgée par **Brokkr** sur Yggdrasil le {{date}}.

```bash
python3 -m venv --system-site-packages .venv && . .venv/bin/activate
pip install -e ".[dev]"
{{slug}}
pytest
brokkr package       # dist/{{slug}}_0.1.0_all.deb : sudo apt install ./dist/…
```

- `carnet.py` : la logique, sans Qt (testée)
- `main.py` : le pont entre Python et QML
- `qml/Main.qml` : l'interface
