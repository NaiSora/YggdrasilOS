"""Bifröst : services, exemplaires, options, Minecraft (saveurs, modpacks, Bedrock), Discord, Velocity, deploy, portail."""

import json
import re
from types import SimpleNamespace

import pytest

from yggdrasil import bifrost, common
from yggdrasil.common import YggError

ATTENDUS = {"minecraft", "minecraft-proxy", "playit", "valheim", "terraria", "factorio", "satisfactory",
            "palworld", "enshrouded", "zomboid", "open-webui", "searxng", "whisper", "comfyui", "metube",
            "restreamer", "code-server", "bases", "lavalink", "n8n", "fileshare", "ntfy", "portail"}
RETIRES = {"jellyfin", "homeassistant", "portainer", "uptime-kuma", "adguard", "forgejo", "syncthing"}


def test_services_load_and_reference_their_variables():
    stacks = bifrost.load_stacks()
    assert set(stacks) == ATTENDUS and not RETIRES & set(stacks)
    for stack in stacks.values():
        compose = (stack.directory / "compose.yml").read_text(encoding="utf-8")
        used = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)\}", compose))
        declared = {v.name for v in stack.env} | {"BIND_ADDR", "PUID", "PGID", "TZ", "INSTANCE"}
        assert used <= declared, f"{stack.name} : variables non déclarées {used - declared}"
        assert "image:" in compose and "restart: unless-stopped" in compose
        if not stack.host_network:
            assert "name: bifrost" in compose, f"{stack.name} : pas sur le réseau commun"
            # Aucun port ouvert au réseau sans passer par BIND_ADDR (ou 127.0.0.1)
            for line in compose.splitlines():
                if re.match(r'\s*- "?\d+[:-]', line):
                    raise AssertionError(f"{stack.name} : port publié sans BIND_ADDR : {line}")
        if stack.instances:
            assert "${INSTANCE}" in compose, f"{stack.name} : nom de conteneur non unique"
        for var in stack.env:
            if var.kind == "port":
                assert var.default.isdigit()
    par_categorie = {c: [s for s in stacks.values() if s.categorie == c] for c in bifrost.CATEGORIES}
    assert all(par_categorie.values())


def test_minecraft_flavours_and_extras():
    o = bifrost.ajuster_minecraft({"type": "Fabric", "version": "1.21.4", "bedrock": "", "carte": ""})
    assert o == {"type": "FABRIC", "version": "1.21.4", "mods": "geyser,floodgate,bluemap"}
    o = bifrost.ajuster_minecraft({"modpack": "modrinth:cobblemon-fabric"})
    assert o == {"type": "MODRINTH", "modpack-modrinth": "cobblemon-fabric"}
    o = bifrost.ajuster_minecraft({"modpack": "curseforge:all-the-mods-10"})
    assert o["type"] == "AUTO_CURSEFORGE" and o["modpack-curseforge"] == "all-the-mods-10"
    assert bifrost.ajuster_minecraft({"mods": "lithium,lithium", "bedrock": ""})["mods"] == "lithium,geyser,floodgate"
    for mauvais in ({"type": "bedrock-edition"}, {"modpack": "ailleurs:x"}, {"type": "vanilla", "mods": "lithium"}):
        with pytest.raises(YggError):
            bifrost.ajuster_minecraft(mauvais)
    assert set(bifrost.SAVEURS) >= {"vanilla", "paper", "spigot", "forge", "neoforge", "fabric", "purpur"}


def test_options_parsing():
    assert bifrost.parse_options(["--type", "fabric", "--bedrock", "--mods=a,b", "--memoire", "6G"]) == {
        "type": "fabric", "bedrock": "", "mods": "a,b", "memoire": "6G"}
    with pytest.raises(YggError):
        bifrost.parse_options(["fabric"])


def test_build_env_options_ports_and_secrets():
    stack = bifrost.load_stacks()["minecraft"]
    pris = {25565, 19132}
    v = bifrost.build_env(stack, {}, bind_addr="0.0.0.0", interactive=False,
                          options={"type": "FABRIC", "memoire": "6G", "mods": "lithium"}, instance="survie", pris=pris)
    assert (v["TYPE"], v["MEMORY"], v["MODRINTH_PROJECTS"], v["INSTANCE"]) == ("FABRIC", "6G", "lithium", "survie")
    assert v["PORT"] == "25566" and v["PORT_BEDROCK"] == "19133" and v["PORT_CARTE"] == "8100"
    assert len(v["RCON_PASSWORD"]) >= 24 and v["EULA"] == "FALSE"
    # Relancé : on garde l'existant ; une option explicite le remplace
    again = bifrost.build_env(stack, v, bind_addr="127.0.0.1", interactive=False, options={"version": "1.21.4"},
                              instance="survie")
    assert again["RCON_PASSWORD"] == v["RCON_PASSWORD"] and again["VERSION"] == "1.21.4"
    assert again["PORT"] == "25566" and again["BIND_ADDR"] == "127.0.0.1"
    with pytest.raises(YggError, match="valeur invalide"):
        bifrost.build_env(stack, {}, bind_addr="127.0.0.1", interactive=False, options={"mode": "hardcore"})
    with pytest.raises(YggError, match="port invalide"):
        bifrost.build_env(stack, {}, bind_addr="127.0.0.1", interactive=False, options={"port": "99999"})


def test_env_roundtrip():
    stack = bifrost.load_stacks()["metube"]
    values = {"BIND_ADDR": "127.0.0.1", "DOSSIER": "/home/a/Vidéos/MeTube", "MOT": "avec espace", "LISTE": "a,b"}
    text = bifrost.render_env(values, stack)
    assert "DOSSIER=" in text and "# Où ranger" in text
    assert bifrost.parse_env(text) == values


def test_install_files_never_overwrites(tmp_path):
    stack = bifrost.load_stacks()["searxng"]
    dest = tmp_path / "searxng"
    assert bifrost.install_files(stack, dest) == ["compose.yml", "settings.yml"]
    (dest / "settings.yml").write_text("# modifié\n")
    assert bifrost.install_files(stack, dest) == []
    assert (dest / "settings.yml").read_text().startswith("# modifié")
    assert not (dest / "stack.toml").exists()


@pytest.fixture
def maison(tmp_path):
    config = {"bifrost": {"home": str(tmp_path / "bifrost")}}
    for nom, modele, env in (("survie", "minecraft", "PORT=25565\nPORT_BEDROCK=19132\nPORT_CARTE=8100\n"),
                             ("creatif", "minecraft", "PORT=25566\nPORT_BEDROCK=19133\nPORT_CARTE=8101\n"),
                             ("metube", "metube", "PORT=8081\n")):
        d = tmp_path / "bifrost" / nom
        d.mkdir(parents=True)
        (d / "compose.yml").write_text("services: {}\n")
        (d / ".env").write_text(env)
        (d / bifrost.META).write_text(json.dumps({"modele": modele}))
    return config


def test_instances_are_resolved(maison, monkeypatch):
    assert bifrost.deploiements(maison) == {"creatif": "minecraft", "metube": "metube", "survie": "minecraft"}
    stack, dest = bifrost.resoudre("creatif", maison)
    assert stack.name == "minecraft" and dest.name == "creatif"
    with pytest.raises(YggError, match="pas déployé"):
        bifrost.resoudre("valheim", maison)
    monkeypatch.setattr(bifrost.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=""))
    assert {25565, 25566, 19133, 8081} <= bifrost.ports_pris(maison)
    assert 25565 not in bifrost.ports_pris(maison, exclure="survie")


def test_discord_events():
    assert bifrost.evenement("[Server thread/INFO]: Done (12.345s)! For help, type \"help\"", "survie") == \
        "🟢 Le serveur **survie** est prêt."
    assert bifrost.evenement("[Server thread/INFO]: Astrid joined the game", "survie") == \
        "➡️ **Astrid** a rejoint **survie**."
    assert "a quitté" in bifrost.evenement("Leif_42 left the game", "x")
    assert bifrost.evenement("[Server thread/INFO]: <Astrid> bonjour", "x") == ""


def test_velocity_servers_section():
    toml = 'bind = "0.0.0.0:25577"\n\n[servers]\nlobby = "127.0.0.1:30066"\ntry = ["lobby"]\n\n[forced-hosts]\n"a" = ["lobby"]\n'
    nouveau = bifrost.velocity_serveurs(toml, ["survie", "creatif"])
    assert 'survie = "mc-survie:25565"' in nouveau and 'creatif = "mc-creatif:25565"' in nouveau
    assert 'try = ["survie"]' in nouveau and "lobby" not in nouveau.split("[forced-hosts]")[0]
    assert nouveau.count("[forced-hosts]") == 1 and nouveau.startswith('bind = "0.0.0.0:25577"')


def test_mods_command(maison, fake_runner, monkeypatch):
    d = common.Path(maison["bifrost"]["home"]) / "survie"
    (d / ".env").write_text("TYPE=FABRIC\nVERSION=1.21.4\nMODRINTH_PROJECTS=lithium\n")
    monkeypatch.setattr(bifrost, "modrinth_compatible", lambda p, s, v: p != "plugin-paper")
    monkeypatch.setattr(bifrost.Docker, "compose", lambda self, *a, **k: None)
    args = SimpleNamespace(stack="survie", action="ajouter", projets=["sodium", "lithium"])
    assert bifrost.cmd_mods(args, fake_runner(), maison) == 0
    assert "MODRINTH_PROJECTS=lithium,sodium" in (d / ".env").read_text()
    with pytest.raises(YggError, match="pas de version"):
        bifrost.cmd_mods(SimpleNamespace(stack="survie", action="ajouter", projets=["plugin-paper"]), fake_runner(),
                         maison)
    bifrost.cmd_mods(SimpleNamespace(stack="survie", action="retirer", projets=["lithium"]), fake_runner(), maison)
    assert "MODRINTH_PROJECTS=sodium" in (d / ".env").read_text()
    with pytest.raises(YggError, match="Minecraft"):
        bifrost.cmd_mods(SimpleNamespace(stack="metube", action="liste", projets=[]), fake_runner(), maison)


def test_deploy_compose_for_a_project(tmp_path):
    projet = tmp_path / "MonBot"
    projet.mkdir()
    (projet / ".env").write_text("TOKEN=x\n")
    texte = bifrost.compose_projet("monbot", projet)
    assert f'build: "{projet}"' in texte and "env_file: .env" in texte and "restart: unless-stopped" in texte
    assert "name: bifrost" in texte


def test_portal_caddyfile():
    texte = bifrost.caddyfile([("metube", "metube", 8081), ("survie", "mc-survie", 8100)])
    assert "metube.localhost {\n\treverse_proxy metube:8081\n}" in texte
    assert "survie.localhost {\n\treverse_proxy mc-survie:8100\n}" in texte
    assert "local_certs" in texte


def test_cli_accepts_service_options(monkeypatch):
    vus = {}
    monkeypatch.setattr(bifrost, "cmd_up", lambda args, runner, config: vus.update(vars(args)) or 0)
    parser = bifrost.build_parser()
    args, reste = parser.parse_known_args(["up", "minecraft", "--nom", "survie", "--type", "fabric", "--bedrock"])
    assert args.nom == "survie" and reste == ["--type", "fabric", "--bedrock"]
    assert bifrost.main(["up", "minecraft", "--nom", "survie", "--type", "fabric", "-n"]) == 0
    assert vus["options"] == ["--type", "fabric"] and vus["dry_run"]
    with pytest.raises(SystemExit):
        bifrost.main(["logs", "survie", "--bizarre"])
