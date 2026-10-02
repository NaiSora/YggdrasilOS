# {{name}}

Assistant 100 % local forgé par **Brokkr** sur Yggdrasil le {{date}}.

```bash
pip install -e ".[dev]"
{{slug}} --modele qwen3:8b
pytest
```

- `ollama.py` : le client (réponses en continu)
- `assistant.py` : consigne, mémoire de conversation
- `cli.py` : le terminal ; écris ton interface Qt ou ton bot par-dessus `Assistant`
