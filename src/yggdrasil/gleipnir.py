"""Gleipnir, le lien qui enchaîne Fenrir : qui a accès à quoi sur cette machine.

    gleipnir            le tour des accès : comptes et pouvoirs, connexions à distance,
                        ports ouverts, dossiers partagés, applications Flatpak trop libres
    gleipnir --json     la même chose pour un script

Gleipnir ne change rien : il montre, et marque d'un ⚠ ce qui mérite un regard.
« sudo gleipnir » voit en plus les clés SSH de tous les comptes et les règles sudo.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import common
from .common import Runner

# Groupes qui donnent un pouvoir : nom → ce qu'ils permettent
GROUPES_PUISSANTS = {
    "sudo": "administrer la machine (tout faire)",
    "docker": "lancer des conteneurs : équivaut à être administrateur",
    "libvirt": "créer et piloter des machines virtuelles",
    "adm": "lire les journaux du système",
    "wireshark": "écouter le trafic réseau",
    "lpadmin": "gérer les imprimantes",
    "sambashare": "partager des dossiers sur le réseau",
}
RISQUES_GROUPES = {"docker"}
PERMISSIONS_FLATPAK_RISQUEES = ("filesystems=host", "filesystems=host;", "devices=all", "filesystem=host",
                                "sockets=system-bus", "talk-name=org.freedesktop.Flatpak")


@dataclass
class Constat:
    sujet: str
    detail: str
    risque: bool = False


@dataclass
class Section:
    titre: str
    constats: list[Constat] = field(default_factory=list)


def section_comptes(passwd: str, groupes_texte: str) -> Section:
    from . import comptes

    groupes = comptes.parse_group(groupes_texte)
    liste = comptes.parse_passwd(passwd, groupes)
    s = Section("Comptes et pouvoirs")
    for c in liste:
        pouvoirs = [g for g in c.groupes if g in GROUPES_PUISSANTS]
        detail = ", ".join(f"{g} ({GROUPES_PUISSANTS[g]})" for g in pouvoirs) or "aucun pouvoir particulier"
        s.constats.append(Constat(c.nom, detail, risque=any(g in RISQUES_GROUPES for g in pouvoirs)))
    for g, membres in groupes.items():
        if g in GROUPES_PUISSANTS and membres:
            humains = {c.nom for c in liste}
            autres = [m for m in membres if m not in humains]
            if autres:
                s.constats.append(Constat(f"groupe {g}", "comptes de service : " + ", ".join(autres)))
    return s


def parse_sshd_effectif(texte: str) -> dict[str, str]:
    """Sortie de « sshd -T » → réglages effectifs (clé en minuscules)."""
    reglages = {}
    for line in texte.splitlines():
        cle, _, valeur = line.strip().partition(" ")
        if cle:
            reglages[cle.lower()] = valeur.strip()
    return reglages


def cles_ssh(maison: Path) -> list[str]:
    """Les clés autorisées d'un compte : type et commentaire (jamais la clé elle-même)."""
    resultat = []
    for line in common.read_text(maison / ".ssh" / "authorized_keys").splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        type_ = next((p for p in parts if p.startswith(("ssh-", "ecdsa-", "sk-"))), parts[0])
        rang = parts.index(type_) if type_ in parts else 0
        commentaire = " ".join(parts[rang + 2:]) or "(sans commentaire)"
        resultat.append(f"{type_} {commentaire}")
    return resultat


def section_distance(runner: Runner, passwd: str) -> Section:
    from . import comptes, partage

    s = Section("Connexions à distance")
    code, _ = runner.query(["systemctl", "is-active", "--quiet", "ssh"])
    if code != 0:
        s.constats.append(Constat("SSH", "serveur arrêté : personne ne se connecte à distance"))
    else:
        _, effectif = runner.query(["sshd", "-T"], root=common.is_root())
        r = parse_sshd_effectif(effectif)
        mots_de_passe = r.get("passwordauthentication", "yes") == "yes"
        root = r.get("permitrootlogin", "") not in ("no", "")
        s.constats.append(Constat("SSH", "actif, " + ("mots de passe acceptés" if mots_de_passe else "clés seulement")
                                  + (", connexion root permise" if root else ""), risque=mots_de_passe or root))
    for c in comptes.parse_passwd(passwd):
        cles = cles_ssh(Path(c.maison))
        if cles:
            s.constats.append(Constat(f"clés SSH de {c.nom}", "; ".join(cles)))
    code, conf = runner.query(["cat", str(partage.WG_CONF)], root=common.is_root())
    if code == 0 and conf:
        clients = partage.wg_infos(conf)["clients"]
        s.constats.append(Constat("WireGuard", f"{len(clients)} appareil(s) : "
                                  + ", ".join(f"{n} ({ip})" for n, ip in clients)))
    return s


def section_reseau(runner: Runner) -> Section:
    from . import gjallarhorn, heimdall

    s = Section("Portes ouvertes (Heimdall)")
    cfg = heimdall.load_config()
    if not cfg.enabled:
        s.constats.append(Constat("pare-feu", "désactivé : tout ce qui écoute est joignable", risque=True))
    s.constats.append(Constat("zone", f"{cfg.zone} — {heimdall.ZONES[cfg.zone]}"))
    for r in cfg.rules:
        qui = {"any": "tout le monde (Internet si ta box redirige)", "lan": "le réseau local"}.get(r.source, r.source)
        s.constats.append(Constat(f"{r.ports}/{r.proto}", f"{r.comment or '-'} : ouvert à {qui}",
                                  risque=r.source == "any"))
    for cle, texte in gjallarhorn.ecoutes_exposees(runner).items():
        if "bloqué" not in texte:
            s.constats.append(Constat("à l'écoute", texte))
    return s


def section_partages(runner: Runner) -> Section:
    from . import partage

    s = Section("Dossiers partagés")
    _, info = runner.query(["net", "usershare", "info"])
    for p in partage.parse_usershares(info):
        droits = "lecture et écriture" if p.ecriture else "lecture seule"
        s.constats.append(Constat(p.nom, f"{p.chemin} — {droits}" + (", sans mot de passe" if p.invites else ""),
                                  risque=p.invites))
    if not s.constats:
        s.constats.append(Constat("Samba", "aucun dossier partagé"))
    return s


def permissions_risquees(texte: str) -> list[str]:
    """Sortie de « flatpak info --show-permissions » → permissions larges."""
    trouvees = []
    for line in texte.splitlines():
        line = line.strip()
        if line.startswith("filesystems=") and any(x in line.split("=", 1)[1].split(";") for x in ("host", "home")):
            trouvees.append("tous tes fichiers" if "host" in line else "ton dossier personnel")
        elif line.startswith("devices=") and "all" in line:
            trouvees.append("tous les périphériques (webcam, micro…)")
        elif line.startswith("sockets=") and "system-bus" in line:
            trouvees.append("le bus système")
    return list(dict.fromkeys(trouvees))


def section_flatpak(runner: Runner) -> Section:
    s = Section("Applications Flatpak aux larges accès")
    if not common.which("flatpak"):
        return s
    _, applis = runner.query(["flatpak", "list", "--app", "--columns=application"])
    for app in [a.strip() for a in applis.splitlines() if a.strip()]:
        _, perms = runner.query(["flatpak", "info", "--show-permissions", app])
        larges = permissions_risquees(perms)
        if larges:
            s.constats.append(Constat(app, "accède à " + ", ".join(larges),
                                      risque="tous tes fichiers" in larges))
    if s.constats:
        s.constats.append(Constat("conseil", "Flatseal (royaume Ásgard) retire les accès inutiles"))
    return s


def tour(runner: Runner) -> list[Section]:
    passwd, groupes = common.read_text("/etc/passwd"), common.read_text("/etc/group")
    sections = [section_comptes(passwd, groupes), section_distance(runner, passwd), section_reseau(runner),
                section_partages(runner), section_flatpak(runner)]
    if common.is_root():
        sudoers = sorted(p.name for p in Path("/etc/sudoers.d").glob("*") if p.name != "README")
        if sudoers:
            sections[0].constats.append(Constat("règles sudo", ", ".join(sudoers)))
    return [s for s in sections if s.constats]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="gleipnir", description="Gleipnir : qui a accès à quoi.")
    p.add_argument("--json", action="store_true")

    def _main(a):
        args = p.parse_args(a)
        sections = tour(Runner())
        if args.json:
            print(json.dumps([asdict(s) for s in sections], ensure_ascii=False, indent=1))
            return 0
        common.title("Gleipnir : qui a accès à quoi")
        common.info(common.style("Plus fin qu'un fil de soie, plus fort qu'une chaîne.", "gold", "italic"))
        risques = 0
        for s in sections:
            print("\n  " + common.style(s.titre, "leaf"))
            for c in s.constats:
                marque = common.style("⚠", "yellow") if c.risque else common.dim("·")
                risques += c.risque
                print(f"    {marque} {c.sujet:<22} {c.detail}")
        print()
        common.info(f"{risques} point(s) à regarder." if risques else "Rien d'inquiétant : Fenrir est bien lié.")
        if not common.is_root():
            common.info(common.dim("« sudo gleipnir » voit aussi les clés SSH des autres comptes et les règles sudo."))
        return 0

    return common.run_main(_main, argv)
