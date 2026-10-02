# {{name}}

Service forgé par **Brokkr** sur Yggdrasil le {{date}}.

```bash
pipx install .                                   # installe la commande {{slug}} dans ~/.local/bin
cp {{slug}}.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now {{slug}}
journalctl --user -u {{slug}} -f                 # ses messages
```
