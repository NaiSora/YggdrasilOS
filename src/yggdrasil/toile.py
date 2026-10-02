"""La toile des Nornes : passé, présent, avenir de tes données.

Trois commandes, une par Norne :

    urd                        le passé : la frise de tes sauvegardes et instantanés
    urd fichier CHEMIN         les versions précédentes d'un fichier (aussi : clic droit dans Dolphin)
    urd systeme                restaurer un instantané du système

    verdandi                   le présent : instantané + sauvegarde + copie distante, maintenant

    skuld                      l'avenir : ce qui est planifié
    skuld sauvegarde quotidien|hebdomadaire|non
    skuld distant quotidien|hebdomadaire|non
    skuld verification mensuel|non

Et dans « norns » :

    norns disque               sauvegarder tout seul quand tu branches ton disque
    norns distant init DEPOT   une copie chiffrée hors de chez toi (restic : NAS, serveur SFTP, cloud S3…)
    norns distant sauvegarder | liste | restaurer [CHEMIN]
    norns versions FICHIER     les versions d'un fichier dans tes sauvegardes
    norns verifier             relire des fichiers sauvegardés pour s'assurer qu'ils se restaurent
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import common, norns, voix
from .common import Runner, YggError

# --------------------------------------------------------------------------
# Versions précédentes d'un fichier (N5)
# --------------------------------------------------------------------------


@dataclass
class Version:
    chemin: Path
    sauvegarde: str  # nom de la sauvegarde (date)
    date: dt.datetime  # date de modification du fichier dans cette sauvegarde
    taille: int


def versions_de(fichier: Path, sauvegardes: list[Path], maison: Path | None = None) -> list[Version]:
    """Les versions distinctes d'un fichier dans les sauvegardes, de la plus récente à la plus ancienne.

    Deux sauvegardes qui partagent le même fichier (lien dur, ou même taille et même date)
    ne comptent qu'une fois.
    """
    maison = maison or Path.home()
    try:
        rel = fichier.resolve().relative_to(maison.resolve())
    except ValueError as exc:
        raise YggError("seuls les fichiers de ton dossier personnel sont sauvegardés.") from exc
    vues: set[tuple[int, int]] = set()
    trouvees = []
    for s in sorted(sauvegardes, key=lambda p: p.name, reverse=True):
        candidat = s / rel
        try:
            st = candidat.stat()
        except OSError:
            continue
        if not candidat.is_file():
            continue
        cle = (int(st.st_mtime), st.st_size)
        if cle in vues:
            continue
        vues.add(cle)
        trouvees.append(Version(candidat, s.name, dt.datetime.fromtimestamp(st.st_mtime), st.st_size))
    return trouvees


def nom_restauration(fichier: Path, date: dt.datetime) -> Path:
    """« rapport.odt » → « rapport (version du 01-10-2026 14h05).odt », à côté de l'original."""
    suffixe = "".join(fichier.suffixes[-1:])
    base = fichier.name[: -len(suffixe)] if suffixe else fichier.name
    return fichier.with_name(f"{base} (version du {date:%d-%m-%Y %Hh%M}){suffixe}")


def sauvegardes_locales(config: dict) -> list[Path]:
    cible = config.get("norns", {}).get("backup_target", "")
    if not cible or not common.expand(cible).is_dir():
        return []
    return norns.list_backups(norns.backup_root(common.expand(cible)))


def cmd_versions(args, runner: Runner, config: dict) -> int:
    fichier = common.expand(args.fichier)
    sauvegardes = sauvegardes_locales(config)
    if not sauvegardes:
        message = "Aucune sauvegarde accessible : branche ton disque de sauvegarde (norns status)."
        if args.gui and common.which("kdialog"):
            subprocess.run(["kdialog", "--title", "Versions précédentes", "--sorry", message], check=False)
            return 1
        raise YggError(message)
    versions = versions_de(fichier, sauvegardes)
    if not versions:
        texte = f"Aucune version de « {fichier.name} » dans les sauvegardes."
        if args.gui and common.which("kdialog"):
            subprocess.run(["kdialog", "--title", "Versions précédentes", "--sorry", texte], check=False)
            return 0
        common.info(texte)
        return 0
    if args.gui and common.which("kdialog"):
        choix = []
        for i, v in enumerate(versions):
            choix += [str(i), f"{v.date:%d/%m/%Y à %H:%M} — {common.human_size(v.taille)}"]
        proc = subprocess.run(["kdialog", "--title", f"Versions précédentes de {fichier.name}",
                               "--menu", "Laquelle remettre à côté du fichier actuel ?", *choix],
                              capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not proc.stdout.strip().isdigit():
            return 0
        rang = int(proc.stdout.strip())
    elif args.restaurer is not None:
        rang = args.restaurer - 1
    else:
        common.title(f"Versions précédentes de {fichier.name}")
        for i, v in enumerate(versions, 1):
            print(f"  {i:>2}  {v.date:%d/%m/%Y %H:%M}  {common.human_size(v.taille):>10}  {common.dim(v.sauvegarde)}")
        common.info(common.dim(f"norns versions {shlex.quote(str(args.fichier))} --restaurer N : la remettre à côté."))
        return 0
    if not 0 <= rang < len(versions):
        raise YggError("numéro de version inconnu.")
    v = versions[rang]
    cible = nom_restauration(fichier, v.date)
    if not runner.dry_run:
        shutil.copy2(v.chemin, cible)
    common.ok(f"version du {v.date:%d/%m/%Y %H:%M} remise à côté : {cible.name}")
    if args.gui and common.which("notify-send"):
        runner.run(["notify-send", "--app-name=Yggdrasil", "--icon=view-history", "Versions précédentes",
                    f"« {cible.name} » est à côté de l'original."], check=False)
    return 0


# --------------------------------------------------------------------------
# Le disque qu'on branche (N3)
# --------------------------------------------------------------------------

ETAT = "norns-etat.json"


def etat_path() -> Path:
    return common.user_state_dir() / "yggdrasil" / ETAT


def charger_etat() -> dict:
    try:
        return json.loads(etat_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def noter(**valeurs) -> None:
    etat = charger_etat() | valeurs
    etat_path().parent.mkdir(parents=True, exist_ok=True)
    etat_path().write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")


def uuid_de(runner: Runner, chemin: Path) -> str:
    _, out = runner.query(["findmnt", "-n", "-o", "UUID", "-T", str(chemin)])
    return out.strip()


def cmd_disque(args, runner: Runner, config: dict) -> int:
    cible = norns.resolve_target(args, config)
    uuid = uuid_de(runner, cible)
    if not uuid:
        raise YggError(f"impossible d'identifier le disque qui porte {cible}.")
    if not runner.dry_run:
        common.save_user_config({"norns": {"backup_target": str(cible), "disque_uuid": uuid}})
    common.ok(f"dès que ce disque sera branché, les Nornes sauvegarderont ton dossier dans {cible} "
              "(au plus une fois par jour).")
    common.info(common.dim("« norns disque --non » pour arrêter."))
    return 0


def attendre_montage(runner: Runner, uuid: str, delai: float = 90, pause=time.sleep) -> str:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        _, out = runner.query(["findmnt", "-n", "-o", "TARGET", "-S", f"UUID={uuid}"])
        if out.strip():
            return out.strip().splitlines()[0]
        pause(3)
    return ""


def cmd_auto(args, runner: Runner, config: dict) -> int:
    """Lancé par udev (norns-branchement@UUID.service) à chaque disque branché."""
    nc = config.get("norns", {})
    if not nc.get("disque_uuid") or args.uuid != nc["disque_uuid"]:
        return 0
    derniere = float(charger_etat().get("sauvegarde_ok", 0))
    if time.time() - derniere < 20 * 3600:
        return 0
    if not attendre_montage(runner, args.uuid):
        return 0
    titre = "Les Nornes"
    if common.which("notify-send"):
        runner.run(["notify-send", "--app-name=Yggdrasil", "--icon=document-save", titre,
                    "Ton disque est là : nous tissons ta sauvegarde…"], check=False)
    code = norns.main(["backup", "--yes"])
    if code == 0:
        noter(sauvegarde_ok=time.time())
        message = voix.dire("nornes", "sauvegarde", config=config, cible=nc.get("backup_target", ""))
    else:
        common.alerter("norns", "critical", "la sauvegarde automatique a échoué (norns backup pour voir pourquoi)")
        message = "La sauvegarde a échoué : ouvre un terminal, « norns backup »."
    if common.which("notify-send"):
        runner.run(["notify-send", "--app-name=Yggdrasil", "--icon=document-save", titre, message], check=False)
    return code


# --------------------------------------------------------------------------
# La copie chiffrée hors de chez toi (N4) : restic
# --------------------------------------------------------------------------

def mot_de_passe_distant() -> Path:
    return common.user_config_dir() / "norns-distant.motdepasse"


def restic(depot: str, *args: str) -> list[str]:
    return ["restic", "-r", depot, "--password-file", str(mot_de_passe_distant()), *args]


EXCLUSIONS_DISTANT = [".cache", ".local/share/Trash", "Téléchargements", "Downloads", ".local/share/Steam",
                      ".var/app/*/cache", "norns-restauration"]


def cmd_distant(args, runner: Runner, config: dict) -> int:
    depot = config.get("norns", {}).get("distant", "")
    action = args.action or "etat"
    if action == "init":
        if not args.depot:
            raise YggError("indique le dépôt : sftp:moi@nas:/sauvegardes, rest:http://…, s3:…, ou un dossier")
        if not common.which("restic"):
            if not common.confirm("restic (sauvegardes chiffrées) n'est pas installé : l'installer ?", default=True,
                                  assume_yes=args.yes):
                return 1
            runner.run(["apt-get", "install", "-y", "restic"], root=True)
        mdp = mot_de_passe_distant()
        if not mdp.exists() and not runner.dry_run:
            mdp.parent.mkdir(parents=True, exist_ok=True)
            mdp.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
            os.chmod(mdp, 0o600)
        runner.run(restic(args.depot, "init"))
        if not runner.dry_run:
            common.save_user_config({"norns": {"distant": args.depot}})
        common.ok(f"dépôt chiffré prêt : {args.depot}")
        common.warn(f"le mot de passe est dans {mdp} : garde-en une copie ailleurs (gestionnaire de mots de passe, "
                    "papier). Sans lui, personne — pas même toi — ne pourra relire la sauvegarde.")
        return 0
    if not depot:
        raise YggError("aucun dépôt distant : norns distant init sftp:moi@nas:/sauvegardes")
    if action == "sauvegarder":
        exclusions = [f"--exclude={Path.home() / x}" for x in EXCLUSIONS_DISTANT]
        code = runner.run(restic(depot, "backup", str(Path.home()), *exclusions, "--tag", "yggdrasil"),
                          check=False).returncode
        if code not in (0, 3):  # 3 : quelques fichiers illisibles, la sauvegarde est faite
            common.alerter("norns", "critical", "la copie distante a échoué (norns distant sauvegarder)")
            raise YggError(f"restic a échoué (code {code}).")
        runner.run(restic(depot, "forget", "--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "6",
                          "--prune"), check=False)
        noter(distant_ok=time.time())
        common.ok("copie distante faite et chiffrée.")
        return 0
    if action == "liste":
        return runner.run(restic(depot, "snapshots"), check=False).returncode
    if action == "restaurer":
        cible = Path.home() / "norns-restauration" / f"distant-{dt.datetime.now():%Y%m%d-%H%M}"
        cmd = restic(depot, "restore", args.instantane or "latest", "--target", str(cible))
        if args.depot:
            cmd += ["--include", str(Path.home() / norns.safe_relative(args.depot))]
        runner.run(cmd)
        common.ok(f"restauré dans {cible}")
        return 0
    common.title("La copie chiffrée hors de chez toi")
    common.info(f"dépôt : {depot}")
    derniere = charger_etat().get("distant_ok")
    if derniere:
        common.info(f"dernière copie : {dt.datetime.fromtimestamp(derniere):%d/%m/%Y %H:%M}")
    return 0


# --------------------------------------------------------------------------
# Vérifier que les sauvegardes se restaurent (N7)
# --------------------------------------------------------------------------

def empreinte(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as fh:
        for bloc in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def echantillon(sauvegarde: Path, maison: Path, nombre: int = 20, alea: random.Random | None = None) -> list[Path]:
    """Des fichiers de la sauvegarde restés identiques (taille, date) dans le dossier personnel."""
    alea = alea or random.Random()
    candidats = []
    for racine, dossiers, fichiers in os.walk(sauvegarde):
        dossiers[:] = [d for d in dossiers if not d.startswith(".cache")]
        for nom in fichiers:
            if nom == norns.COMPLETE_MARKER:
                continue
            p = Path(racine) / nom
            original = maison / p.relative_to(sauvegarde)
            try:
                a, b = p.stat(), original.stat()
            except OSError:
                continue
            if p.is_file() and a.st_size == b.st_size and int(a.st_mtime) == int(b.st_mtime) and a.st_size < 200 << 20:
                candidats.append(p)
        if len(candidats) > 5000:
            break
    return alea.sample(candidats, min(nombre, len(candidats)))


def verifier(sauvegarde: Path, maison: Path, nombre: int = 20) -> tuple[int, list[str]]:
    """(fichiers relus, fichiers abîmés) : la sauvegarde relue doit être identique à l'original."""
    abimes = []
    fichiers = echantillon(sauvegarde, maison, nombre)
    for p in fichiers:
        rel = p.relative_to(sauvegarde)
        try:
            if empreinte(p) != empreinte(maison / rel):
                abimes.append(str(rel))
        except OSError:
            abimes.append(str(rel))
    return len(fichiers), abimes


def cmd_verifier(args, runner: Runner, config: dict) -> int:
    common.title("Les Nornes relisent leur fil")
    probleme = False
    sauvegardes = sauvegardes_locales(config)
    if sauvegardes:
        lus, abimes = verifier(sauvegardes[-1], Path.home(), args.nombre)
        if abimes:
            probleme = True
            common.error(f"{len(abimes)} fichier(s) sur {lus} ne se relisent pas à l'identique : "
                         + ", ".join(abimes[:5]))
            common.alerter("norns", "critical", f"sauvegarde {sauvegardes[-1].name} abîmée : "
                           f"{len(abimes)} fichier(s) illisible(s) — vérifie le disque (ygg materiel)")
        else:
            common.ok(f"sauvegarde {sauvegardes[-1].name} : {lus} fichiers relus, tous identiques.")
    else:
        common.info("disque de sauvegarde absent : rien à relire ici.")
    depot = config.get("norns", {}).get("distant", "")
    if depot and common.which("restic"):
        code = runner.run(restic(depot, "check", "--read-data-subset", "5%"), check=False).returncode
        if code != 0:
            probleme = True
            common.alerter("norns", "critical", "le dépôt distant ne se relit pas (norns distant liste)")
        else:
            common.ok("copie distante : 5 % des données relues, intactes.")
    noter(verification=time.time(), verification_ok=not probleme)
    return 1 if probleme else 0


# --------------------------------------------------------------------------
# Skuld : ce qui est planifié
# --------------------------------------------------------------------------

PLANS = {
    "sauvegarde": ("norns-sauvegarde", "norns backup --yes --si-present", ("quotidien", "hebdomadaire")),
    "distant": ("norns-distant", "norns distant sauvegarder", ("quotidien", "hebdomadaire")),
    "verification": ("norns-verification", "norns verifier", ("mensuel",)),
}


def unites_skuld(nom: str, commande: str, quand: str) -> tuple[str, str]:
    from . import taches

    service = (f"[Unit]\nDescription=Les Nornes : {nom}\n\n[Service]\nType=oneshot\n"
               f"ExecStart=/bin/bash -lc {shlex.quote(commande)}\nNice=10\nIOSchedulingClass=idle\n")
    timer = (f"[Unit]\nDescription=Quand les Nornes s'occupent de « {nom} »\n\n"
             f"[Timer]\n{taches.declencheur(quand)}\nPersistent=true\nRandomizedDelaySec=15min\n\n"
             "[Install]\nWantedBy=timers.target\n")
    return service, timer


def cmd_skuld(args, runner: Runner, config: dict) -> int:
    from . import taches

    dossier = taches.dossier_unites()
    if not args.quoi:
        common.title("Skuld, ce qui doit être")
        common.info("instantanés du système : " + ("planifiés (Timeshift)" if norns.timeshift_configured()
                                                 else "non planifiés → norns setup"))
        for quoi, (unite, _, _) in PLANS.items():
            timer = dossier / f"{unite}.timer"
            plan = taches.quand_de(common.read_text(timer)) if timer.exists() else "non planifié"
            print(f"  {quoi:<14} {plan}")
        common.info(common.dim("skuld sauvegarde quotidien | skuld distant hebdomadaire | "
                               "skuld verification mensuel | … non"))
        return 0
    if args.quoi not in PLANS:
        raise YggError(f"à planifier : {', '.join(PLANS)}")
    unite, commande, rythmes = PLANS[args.quoi]
    if args.quand == "non":
        runner.run(["systemctl", "--user", "disable", "--now", f"{unite}.timer"], check=False)
        if not runner.dry_run:
            for suffixe in (".timer", ".service"):
                (dossier / f"{unite}{suffixe}").unlink(missing_ok=True)
        common.ok(f"{args.quoi} : plus de planification.")
        return 0
    if args.quand not in rythmes:
        raise YggError(f"rythme pour {args.quoi} : {', '.join(rythmes)} ou non")
    service, timer = unites_skuld(args.quoi, commande, args.quand)
    runner.write_file(dossier / f"{unite}.service", service)
    runner.write_file(dossier / f"{unite}.timer", timer)
    runner.run(["systemctl", "--user", "daemon-reload"])
    runner.run(["systemctl", "--user", "enable", "--now", f"{unite}.timer"])
    common.ok(f"{args.quoi} : {args.quand}.")
    return 0


# --------------------------------------------------------------------------
# Urd et Verdandi
# --------------------------------------------------------------------------

def cmd_urd(args, runner: Runner, config: dict) -> int:
    if args.quoi == "fichier":
        if not args.chemin:
            raise YggError("urd fichier CHEMIN")
        return cmd_versions(argparse.Namespace(fichier=args.chemin, gui=False, restaurer=args.restaurer),
                            runner, config)
    if args.quoi == "systeme":
        return norns.main(["restore"] + (["--yes"] if args.yes else []))
    if args.quoi == "dossier":
        return norns.main(["recover"] + ([args.chemin] if args.chemin else []))
    common.title("Urd, ce qui a été")
    sauvegardes = sauvegardes_locales(config)
    if sauvegardes:
        for s in reversed(sauvegardes[-10:]):
            quand = dt.datetime.strptime(s.name, norns.STAMP_FORMAT)
            print(f"  {quand:%d/%m/%Y %H:%M}  sauvegarde du dossier personnel")
    else:
        common.info("aucune sauvegarde accessible (disque débranché, ou jamais faite : verdandi).")
    etat = charger_etat()
    if etat.get("distant_ok"):
        print(f"  {dt.datetime.fromtimestamp(etat['distant_ok']):%d/%m/%Y %H:%M}  copie distante chiffrée")
    common.info(common.dim("urd fichier CHEMIN : versions d'un fichier ; urd dossier [CHEMIN] : le récupérer ; "
                           "urd systeme : restaurer un instantané (norns list)"))
    return 0


def cmd_verdandi(args, runner: Runner, config: dict) -> int:
    common.title("Verdandi, ce qui est : le fil d'aujourd'hui")
    if not common.is_live_session() and norns.timeshift_configured():
        norns.main(["snap", "tissé par Verdandi"])
    cible = config.get("norns", {}).get("backup_target", "")
    if cible and common.expand(cible).is_dir():
        if norns.main(["backup", "--yes"]) == 0:
            noter(sauvegarde_ok=time.time())
    else:
        common.info("disque de sauvegarde absent : pas de sauvegarde du dossier personnel aujourd'hui.")
    if config.get("norns", {}).get("distant"):
        cmd_distant(argparse.Namespace(action="sauvegarder", depot=None, instantane=None, yes=True), runner, config)
    voix.annoncer("nornes", "instantane", config=config, nom=dt.datetime.now().strftime("%d/%m/%Y"))
    return 0


def _main(argv, prog: str) -> int:
    opts = argparse.ArgumentParser(add_help=False)
    opts.add_argument("-y", "--yes", action="store_true")
    opts.add_argument("-n", "--dry-run", action="store_true")
    opts.add_argument("-v", "--verbose", action="store_true")
    parser = argparse.ArgumentParser(prog=prog, parents=[opts], description={
        "urd": "Urd, la Norne du passé : sauvegardes, versions de fichiers, restauration.",
        "verdandi": "Verdandi, la Norne du présent : instantané et sauvegardes, maintenant.",
        "skuld": "Skuld, la Norne de l'avenir : ce qui est planifié.",
    }[prog])
    if prog == "urd":
        parser.add_argument("quoi", nargs="?", choices=["fichier", "dossier", "systeme"])
        parser.add_argument("chemin", nargs="?")
        parser.add_argument("--restaurer", type=int, help="numéro de la version à remettre à côté")
        func = cmd_urd
    elif prog == "skuld":
        parser.add_argument("quoi", nargs="?", help=", ".join(PLANS))
        parser.add_argument("quand", nargs="?", help="quotidien, hebdomadaire, mensuel ou non")
        func = cmd_skuld
    else:
        func = cmd_verdandi
    args = parser.parse_args(argv)
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    return func(args, runner, common.load_config())


def main_urd(argv=None) -> int:
    return common.run_main(lambda a: _main(a, "urd"), argv)


def main_verdandi(argv=None) -> int:
    return common.run_main(lambda a: _main(a, "verdandi"), argv)


def main_skuld(argv=None) -> int:
    return common.run_main(lambda a: _main(a, "skuld"), argv)


def ajouter_commandes(sub, opts) -> None:
    """Les sous-commandes de « norns » qui vivent ici."""
    p = sub.add_parser("versions", help="les versions précédentes d'un fichier", parents=[opts])
    p.add_argument("fichier")
    p.add_argument("--restaurer", type=int, help="remettre la version N à côté de l'original")
    p.add_argument("--gui", action="store_true", help="fenêtre de choix (menu de Dolphin)")
    p.set_defaults(func=cmd_versions)
    p = sub.add_parser("disque", help="sauvegarder dès que ton disque est branché", parents=[opts])
    p.add_argument("--to", help="dossier de sauvegarde sur le disque")
    p.add_argument("--non", action="store_true", help="arrêter la sauvegarde au branchement")
    p.set_defaults(func=_disque)
    p = sub.add_parser("auto", help=argparse.SUPPRESS, parents=[opts])
    p.add_argument("uuid")
    p.set_defaults(func=cmd_auto)
    p = sub.add_parser("distant", help="copie chiffrée hors de chez toi (restic)", parents=[opts])
    p.add_argument("action", nargs="?", choices=["etat", "init", "sauvegarder", "liste", "restaurer"])
    p.add_argument("depot", nargs="?", help="dépôt (init) ou chemin à restaurer (restaurer)")
    p.add_argument("--instantane", help="identifiant d'un instantané restic (restaurer)")
    p.set_defaults(func=cmd_distant)
    p = sub.add_parser("verifier", help="relire des fichiers sauvegardés (test de restauration)", parents=[opts])
    p.add_argument("--nombre", type=int, default=20)
    p.set_defaults(func=cmd_verifier)


def _disque(args, runner: Runner, config: dict) -> int:
    if args.non:
        if not runner.dry_run:
            common.save_user_config({"norns": {"disque_uuid": ""}})
        common.ok("plus de sauvegarde au branchement.")
        return 0
    return cmd_disque(args, runner, config)


if __name__ == "__main__":
    sys.exit(main_verdandi())
