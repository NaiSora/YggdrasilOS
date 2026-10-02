import json

import pytest

from yggdrasil import heimdall
from yggdrasil.common import YggError


@pytest.mark.parametrize("spec, expected", [
    ("25565", ("25565", "tcp")),
    ("25565/udp", ("25565", "udp")),
    ("1714-1764/both", ("1714-1764", "both")),
])
def test_parse_port_spec(spec, expected):
    assert heimdall.parse_port_spec(spec) == expected


@pytest.mark.parametrize("spec", ["0", "70000", "80-20", "abc", "22/icmp", "22; drop"])
def test_parse_port_spec_rejects(spec):
    with pytest.raises(YggError):
        heimdall.parse_port_spec(spec)


def test_sources():
    assert heimdall.normalize_source("LAN") == "lan"
    assert heimdall.normalize_source("192.168.1.7/24") == "192.168.1.0/24"
    with pytest.raises(YggError):
        heimdall.normalize_source("partout")


def test_resolve_named_service():
    assert heimdall.resolve_target("minecraft") == [("25565", "tcp")]
    assert heimdall.resolve_target("8080/tcp") == [("8080", "tcp")]


def test_render_desktop_profile():
    cfg = heimdall.Config(enabled=True, profile="desktop", rules=[
        heimdall.Rule("25565", "tcp", "lan", "minecraft"),
        heimdall.Rule("1714-1764", "both", "any", "kdeconnect"),
        heimdall.Rule("8096", "tcp", "192.168.1.0/24", "jellyfin"),
    ])
    out = heimdall.render_ruleset(cfg)
    assert out.startswith("#!/usr/sbin/nft -f")
    assert "table inet heimdall\ndelete table inet heimdall" in out
    assert "policy drop;" in out
    assert "ct state established,related accept" in out
    assert 'ip saddr @lan4 tcp dport 25565 accept comment "minecraft (lan)"' in out
    assert 'ip6 saddr @lan6 tcp dport 25565 accept comment "minecraft (lan)"' in out
    assert "meta l4proto { tcp, udp } th dport 1714-1764 accept" in out
    assert "ip saddr 192.168.1.0/24 tcp dport 8096 accept" in out
    assert "echo-request" in out and "5353" in out
    assert out.count("{") == out.count("}")


def test_render_server_and_strict_profiles():
    server = heimdall.render_ruleset(heimdall.Config(enabled=True, profile="server"))
    assert "tcp dport 22 accept" in server
    strict = heimdall.render_ruleset(heimdall.Config(enabled=True, profile="strict"))
    assert "echo-request" not in strict and "5353" not in strict
    assert "tcp dport 22" not in strict


def test_comment_cannot_escape_its_quotes():
    cfg = heimdall.Config(rules=[heimdall.Rule("80", "tcp", "any", 'x" ; flush ruleset ; "')])
    out = heimdall.render_ruleset(cfg)
    rule = [line for line in out.splitlines() if "dport 80" in line][0]
    assert rule.count('"') == 2 and ";" not in rule
    for line in out.splitlines():
        if "comment" in line:
            assert line.count('"') == 2


def test_config_roundtrip_and_validation():
    cfg = heimdall.Config(enabled=True, rules=[heimdall.Rule("22", "tcp", "lan", "ssh")])
    again = heimdall.Config.from_dict(json.loads(cfg.to_json()))
    assert again == cfg
    with pytest.raises(YggError):
        heimdall.Config.from_dict({"profile": "passoire"})


SS = """tcp   LISTEN 0      4096       127.0.0.1:631        0.0.0.0:*    users:(("cupsd",pid=812,fd=7))
tcp   LISTEN 0      128          0.0.0.0:22         0.0.0.0:*    users:(("sshd",pid=900,fd=3))
tcp   LISTEN 0      511             [::]:25565         [::]:*
udp   UNCONN 0      0            0.0.0.0:5353       0.0.0.0:*
udp   UNCONN 0      0      [fe80::1%eth0]:546          [::]:*
tcp   LISTEN 0      4096   127.0.0.53%lo:53         0.0.0.0:*
"""


def test_parse_ss_and_exposure():
    listeners = heimdall.parse_ss(SS)
    assert [(x.proto, x.address, x.port) for x in listeners] == [
        ("tcp", "127.0.0.1", 631), ("tcp", "0.0.0.0", 22), ("tcp", "::", 25565),
        ("udp", "0.0.0.0", 5353), ("udp", "fe80::1", 546), ("tcp", "127.0.0.53", 53),
    ]
    assert listeners[0].process == "cupsd"
    cfg = heimdall.Config(enabled=True, rules=[heimdall.Rule("25565", "tcp", "lan")])
    exp = [heimdall.exposure(x, cfg) for x in listeners]
    assert exp[0] == "local uniquement"
    assert exp[1] == "bloqué par heimdall"
    assert exp[2] == "ouvert (lan)"
    assert exp[3] == "ouvert (mDNS)"
    assert exp[5] == "local uniquement"
    off = heimdall.Config(enabled=False)
    assert heimdall.exposure(listeners[1], off).startswith("EXPOSÉ")


def test_apply_feeds_nft_through_stdin(fake_runner):
    runner = fake_runner()
    heimdall.apply(heimdall.Config(enabled=True), runner, keep_copy=False)
    run = [c for c in runner.calls if c[0] == "run"][0]
    assert run[1] == "nft -f /dev/stdin" and run[2] is True
    assert "table inet heimdall" in run[3]
    assert not [c for c in runner.calls if c[0] == "write"]


# --------------------------------------------------------------------------
# Zones, LAN party, Gjallarhorn
# --------------------------------------------------------------------------

def config(**kw):
    return heimdall.Config(enabled=True, rules=[heimdall.Rule("25565", "tcp", "lan", "minecraft"),
                                                heimdall.Rule("8080", "tcp", "any", "web")], **kw)


def test_public_zone_lets_nothing_in():
    maison = heimdall.render_ruleset(config())
    assert "dport 25565" in maison and "dport 8080" in maison and "mDNS" in maison
    public = heimdall.render_ruleset(config(zone="public"))
    assert "dport 25565" not in public and "dport 8080" not in public
    assert "mDNS" not in public and "echo-request" not in public
    assert "client DHCP" in public  # le réseau doit rester utilisable


def test_lan_party_rules_expire(fake_runner):
    cfg = config()
    assert heimdall.ouvrir_fete(cfg, ["terraria", "valheim"], 2, now=1000) == 2
    ruleset = heimdall.render_ruleset(cfg, now=1000 + 3600)
    assert "dport 7777" in ruleset and "dport 2456-2458" in ruleset
    assert "dport 7777" not in heimdall.render_ruleset(cfg, now=1000 + 2 * 3600)
    # Rouvrir prolonge, sans doublon ; la fin ne touche pas aux règles permanentes
    assert heimdall.ouvrir_fete(cfg, ["terraria"], 4, now=2000) == 0
    assert max(r.expire for r in cfg.rules) == 2000 + 4 * 3600
    assert heimdall.fermer_fete(cfg) == 2
    assert [r.comment for r in cfg.rules] == ["minecraft", "web"]
    relu = heimdall.Config.from_dict(json.loads(cfg.to_json()))
    assert relu.zone == "maison"


def test_lan_party_refused_on_public_networks(fake_runner, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(heimdall, "load_config", lambda: config(zone="public"))
    with pytest.raises(YggError, match="public"):
        heimdall.cmd_fete(SimpleNamespace(fin=False, jeux=[], heures=3), fake_runner())


def test_zone_follows_the_network(tmp_path, fake_runner, monkeypatch):
    from types import SimpleNamespace

    from yggdrasil import common
    etat = {"cfg": config()}
    monkeypatch.setattr(heimdall, "load_config", lambda: etat["cfg"])
    monkeypatch.setattr(heimdall, "save_config", lambda cfg, runner: etat.update(cfg=cfg))
    monkeypatch.setattr(heimdall, "apply", lambda cfg, runner, keep_copy=True: None)
    monkeypatch.setattr(common, "STATE_DIR", tmp_path)
    (tmp_path / "wlan0").mkdir()
    (tmp_path / "wlan0" / "wireless").mkdir()
    (tmp_path / "eth0").mkdir()
    assert heimdall.zone_par_defaut("wlan0", tmp_path) == "public"
    assert heimdall.zone_par_defaut("eth0", tmp_path) == "maison"
    monkeypatch.setattr(heimdall, "zone_par_defaut", lambda itf: "public" if itf == "wlan0" else "maison")
    auto = lambda uuid, nom, itf: heimdall.cmd_zone(SimpleNamespace(auto=uuid, nom=nom, interface=itf,  # noqa: E731
                                                                     zone=None), fake_runner())
    auto("u-cafe", "Café du port", "wlan0")
    assert etat["cfg"].zone == "public" and etat["cfg"].reseaux["u-cafe"]["zone"] == "public"
    assert "Café du port" in common.lire_alertes(common.alertes_systeme())[0]["message"]
    auto("u-box", "Livebox", "eth0")
    assert etat["cfg"].zone == "maison"
    # Le café, déclaré de confiance par l'utilisateur, le reste
    etat["cfg"].reseaux["u-cafe"]["zone"] = "maison"
    auto("u-cafe", "Café du port", "wlan0")
    assert etat["cfg"].zone == "maison"


NEIGH = json.dumps([
    {"dst": "192.168.1.1", "dev": "wlan0", "lladdr": "f4:ca:e5:01:02:03", "state": ["REACHABLE"]},
    {"dst": "192.168.1.42", "dev": "wlan0", "lladdr": "da:a1:19:aa:bb:cc", "state": ["STALE"]},
    {"dst": "192.168.1.9", "dev": "wlan0", "state": ["FAILED"]},
    {"dst": "fe80::1", "dev": "wlan0", "lladdr": "f4:ca:e5:01:02:03", "state": ["REACHABLE"]},
])


def test_neighbours_and_vendors():
    from yggdrasil import gjallarhorn
    voisins = gjallarhorn.parse_neigh(NEIGH)
    assert [(v.ip, v.mac) for v in voisins] == [("192.168.1.1", "f4:ca:e5:01:02:03"), ("192.168.1.42", "da:a1:19:aa:bb:cc")]
    table = gjallarhorn.parse_oui("F4-CA-E5   (hex)\t\tFREEBOX SAS\nF4CAE5     (base 16)\t\tFREEBOX SAS\n")
    assert table == {"f4:ca:e5": "FREEBOX SAS"}
    assert gjallarhorn.fabricant("f4:ca:e5:01:02:03", table) == "FREEBOX SAS"
    assert "privée" in gjallarhorn.fabricant("da:a1:19:aa:bb:cc", table)


def test_ssh_failures():
    from yggdrasil import gjallarhorn
    journal = ("Failed password for root from 203.0.113.9 port 4242 ssh2\n" * 25
               + "Invalid user admin from 198.51.100.7 port 22\n"
               + "pam_unix(sshd:auth): authentication failure; logname= uid=0 rhost=203.0.113.9 user=root\n")
    assert gjallarhorn.echecs_ssh(journal) == {"203.0.113.9": 26, "198.51.100.7": 1}


def test_gjallarhorn_round(tmp_path, fake_runner, monkeypatch):
    from yggdrasil import gjallarhorn
    monkeypatch.setattr(gjallarhorn, "STATE_DIR", tmp_path)
    monkeypatch.setattr(gjallarhorn, "etat_path", lambda: tmp_path / "gjallarhorn.json")
    monkeypatch.setattr(gjallarhorn.common, "which", lambda cmd: None)
    monkeypatch.setattr(heimdall, "load_config", lambda: config())
    ss = "tcp LISTEN 0 4096 0.0.0.0:25565 0.0.0.0:* users:((\"java\",pid=1,fd=3))\n"
    runner = fake_runner({"ss": (0, ss), "ip -j neigh": (0, NEIGH), "journalctl": (0, "")})
    assert gjallarhorn.ronde(runner, 1000) == []  # première ronde : on apprend, sans sonner
    ss2 = ss + "tcp LISTEN 0 4096 0.0.0.0:8080 0.0.0.0:* users:((\"python3\",pid=2,fd=3))\n"
    neigh2 = json.dumps(json.loads(NEIGH) + [{"dst": "192.168.1.77", "lladdr": "f4:ca:e5:09:09:09",
                                             "state": ["REACHABLE"]}])
    journal = "Failed password for root from 203.0.113.9 port 1 ssh2\n" * 30
    runner = fake_runner({"ss": (0, ss2), "ip -j neigh": (0, neigh2), "journalctl": (0, journal)})
    alertes = gjallarhorn.ronde(runner, 2000)
    messages = [m for _, m, _ in alertes]
    assert any("8080/tcp (python3)" in m for m in messages)
    assert any("192.168.1.77" in m for m in messages)
    assert ("critical" in [u for u, m, _ in alertes if "SSH" in m])
    assert not any("25565" in m for m in messages)


def test_ecoutes_sans_doublon_inconnu(fake_runner, monkeypatch):
    from yggdrasil import gjallarhorn
    monkeypatch.setattr(heimdall, "load_config", lambda: config())
    ss = ("udp UNCONN 0 0 0.0.0.0:5353 0.0.0.0:* users:((\"kdeconnectd\",pid=9,fd=3))\n"
          "udp UNCONN 0 0 0.0.0.0:5353 0.0.0.0:*\n"
          "udp UNCONN 0 0 0.0.0.0:631 0.0.0.0:*\n")
    ecoutes = gjallarhorn.ecoutes_exposees(fake_runner({"ss": (0, ss)}))
    assert sorted(ecoutes) == ["udp:5353:kdeconnectd", "udp:631:?"]


def test_status_montre_le_ssh_du_profil_serveur(fake_runner, monkeypatch, capsys):
    monkeypatch.setattr(heimdall, "load_config", lambda: heimdall.Config(enabled=True, profile="server"))
    heimdall.cmd_status(None, fake_runner({}))
    sortie = capsys.readouterr().out
    assert "ssh (profil serveur)" in sortie and "Aucune ouverture" not in sortie
    monkeypatch.setattr(heimdall, "load_config", lambda: heimdall.Config(enabled=True, profile="server",
                                                                      zone="public"))
    heimdall.cmd_status(None, fake_runner({}))
    assert "Aucune ouverture" in capsys.readouterr().out  # en zone publique, rien n'entre
