"""Les comptes des personnes qui utilisent la machine.

    ygg comptes                          les comptes, et qui est administrateur
    ygg comptes ajouter NOM [--admin] [--nom-complet "Prénom Nom"]
    ygg comptes admin NOM oui|non        donner ou retirer les droits d'administration
    ygg comptes retirer NOM [--supprimer-fichiers]

Rien n'est retiré sans confirmation ; le dernier administrateur ne peut pas perdre
ses droits, et personne ne peut retirer son propre compte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import common
from .common import Runner, YggError

NOM_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
COQUILLES_INACTIVES = ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false", "/usr/bin/false")
# Groupes utiles sur un poste de travail (seuls ceux qui existent sont ajoutés)
GROUPES_BUREAU = ("audio", "video", "plugdev", "netdev", "bluetooth", "lpadmin", "scanner", "users")
ADMIN = "sudo"


@dataclass
class Compte:
    nom: str
    uid: int
    nom_complet: str
    maison: str
    groupes: list[str] = field(default_factory=list)

    @property
    def admin(self) -> bool:
        return ADMIN in self.groupes


def parse_group(text: str) -> dict[str, list[str]]:
    groupes = {}
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) >= 4:
            groupes[parts[0]] = [m for m in parts[3].split(",") if m]
    return groupes


def parse_passwd(text: str, groupes: dict[str, list[str]] | None = None) -> list[Compte]:
    """Les comptes de personnes (UID 1000 à 59999, avec un shell), pas ceux des services."""
    groupes = groupes or {}
    comptes = []
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) < 7:
            continue
        try:
            uid = int(parts[2])
        except ValueError:
            continue
        if not 1000 <= uid < 60000 or parts[6] in COQUILLES_INACTIVES:
            continue
        membre_de = sorted(g for g, membres in groupes.items() if parts[0] in membres)
        comptes.append(Compte(parts[0], uid, parts[4].split(",")[0], parts[5], membre_de))
    return comptes


def charger() -> tuple[list[Compte], dict[str, list[str]]]:
    groupes = parse_group(common.read_text("/etc/group"))
    return parse_passwd(common.read_text("/etc/passwd"), groupes), groupes


def verifier_nom(nom: str) -> None:
    if not NOM_RE.match(nom or ""):
        raise YggError(f"identifiant invalide « {nom} » : minuscules, chiffres, - et _ (32 au plus), "
                       "en commençant par une lettre.")


def cmd_comptes(args, runner: Runner, config) -> int:
    comptes, groupes = charger()
    action = {"list": "liste", "add": "ajouter", "remove": "retirer"}.get(args.action, args.action) or "liste"
    if action == "liste":
        common.title("Les habitants de Midgard : comptes de la machine")
        rows = [(c.nom, c.nom_complet or "-", "oui" if c.admin else "non", c.maison) for c in comptes]
        print(common.table(rows, headers=("identifiant", "nom", "administrateur", "dossier")))
        return 0
    verifier_nom(args.nom)
    existant = next((c for c in comptes if c.nom == args.nom), None)
    if action == "ajouter":
        if existant:
            raise YggError(f"le compte « {args.nom} » existe déjà.")
        cmd = ["adduser"]
        if args.nom_complet:
            cmd += ["--comment", args.nom_complet]
        runner.run([*cmd, args.nom], root=True)  # demande le mot de passe
        for groupe in (g for g in GROUPES_BUREAU if g in groupes):
            runner.run(["adduser", "--quiet", args.nom, groupe], root=True, check=False)
        if args.admin:
            runner.run(["adduser", "--quiet", args.nom, ADMIN], root=True)
        common.ok(f"compte « {args.nom} » créé{' (administrateur)' if args.admin else ''}.")
        return 0
    if not existant:
        raise YggError(f"aucun compte « {args.nom} » (ygg comptes pour la liste).")
    if action == "admin":
        if args.valeur not in ("oui", "non"):
            raise YggError("ygg comptes admin NOM oui|non")
        if args.valeur == "oui":
            runner.run(["adduser", "--quiet", args.nom, ADMIN], root=True)
            common.ok(f"{args.nom} est administrateur (effectif à sa prochaine connexion).")
        else:
            admins = [c for c in comptes if c.admin]
            if existant.admin and len(admins) <= 1:
                raise YggError("c'est le dernier administrateur : la machine ne pourrait plus être gérée.")
            runner.run(["deluser", "--quiet", args.nom, ADMIN], root=True)
            common.ok(f"{args.nom} n'est plus administrateur.")
        return 0
    if action == "retirer":
        if args.nom == common.target_user():
            raise YggError("impossible de retirer ton propre compte.")
        if existant.admin and len([c for c in comptes if c.admin]) <= 1:
            raise YggError("c'est le dernier administrateur.")
        if args.supprimer_fichiers:
            common.warn(f"tous les fichiers de {existant.maison} seront supprimés définitivement.")
            if common.ask(f"Pour confirmer, tape l'identifiant « {args.nom} »") != args.nom and not args.yes:
                common.info("rien n'a été supprimé.")
                return 1
        elif not common.confirm(f"Retirer le compte « {args.nom} » (ses fichiers restent dans "
                                f"{existant.maison}) ?", assume_yes=args.yes):
            return 1
        cmd = ["deluser"] + (["--remove-home"] if args.supprimer_fichiers else []) + [args.nom]
        runner.run(cmd, root=True)
        common.ok(f"compte « {args.nom} » retiré.")
        return 0
    raise YggError(f"action inconnue : {action}")


def ajouter_commandes(sub, common_opts) -> None:
    p = sub.add_parser("comptes", aliases=["users"], help="comptes des utilisateurs", parents=[common_opts])
    p.add_argument("action", nargs="?", choices=["liste", "ajouter", "admin", "retirer", "list", "add", "remove"])
    p.add_argument("nom", nargs="?")
    p.add_argument("valeur", nargs="?", help="oui ou non (pour « admin »)")
    p.add_argument("--admin", action="store_true", help="à la création : droits d'administration")
    p.add_argument("--nom-complet", help="prénom et nom affichés")
    p.add_argument("--supprimer-fichiers", action="store_true", help="supprimer aussi son dossier personnel")
    p.set_defaults(func=cmd_comptes)
