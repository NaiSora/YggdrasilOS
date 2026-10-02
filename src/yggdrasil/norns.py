"""norns — passé, présent, avenir : instantanés système et sauvegardes.

Deux mécanismes complémentaires :

* les **instantanés système** (Timeshift, mode rsync) protègent / contre une
  mise à jour ratée : « norns snap », « norns list », « norns restore » ;
* les **sauvegardes du dossier personnel** (rsync incrémental à liens durs)
  copient /home/toi vers un disque externe : « norns backup --to /media/… ».
  Chaque sauvegarde est un dossier complet et navigable, mais les fichiers
  inchangés ne prennent pas de place en plus.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import socket
import sys
from pathlib import Path

from . import common, voix
from .common import Runner, YggError

TIMESHIFT_CONFIG = Path("/etc/timeshift/timeshift.json")
TIMESHIFT_DEFAULT = Path("/etc/timeshift/default.json")
GRUB_INSTANTANES = Path("/etc/grub.d/41_yggdrasil-instantanes")
MOUNTINFO = Path("/proc/self/mountinfo")
# La racine d'un système démarré depuis le menu « revenir à un instantané »
RACINE_INSTANTANE = re.compile(r"/timeshift-btrfs/snapshots/([^/]+)/@")
BACKUP_DIRNAME = "yggdrasil-sauvegardes"
COMPLETE_MARKER = ".norns-complete"
STAMP_FORMAT = "%Y-%m-%d_%H%M%S"

DEFAULT_EXCLUDES = [
    ".cache/",
    ".local/share/Trash/",
    ".local/share/Steam/",
    ".var/app/*/cache/",
    ".thumbnails/",
    "**/node_modules/",
    "**/__pycache__/",
    ".ollama/models/",
    "snap/",
]

TIMESHIFT_BASE = {
    "backup_device_uuid": "",
    "parent_device_uuid": "",
    "do_first_run": "false",
    "btrfs_mode": "false",
    "include_btrfs_home_for_backup": "false",
    "include_btrfs_home_for_restore": "false",
    "stop_cron_emails": "true",
    "schedule_monthly": "false",
    "schedule_weekly": "true",
    "schedule_daily": "true",
    "schedule_hourly": "false",
    "schedule_boot": "false",
    "count_monthly": "2",
    "count_weekly": "3",
    "count_daily": "5",
    "count_hourly": "6",
    "count_boot": "5",
    "date_format": "%Y-%m-%d %H:%M:%S",
    "exclude": [],
    "exclude-apps": [],
}


# --------------------------------------------------------------------------
# Instantanés système (Timeshift)
# --------------------------------------------------------------------------

def timeshift_configured(path: Path = TIMESHIFT_CONFIG) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(data.get("backup_device_uuid"))


def root_device(runner: Runner) -> str:
    code, out = runner.query(["findmnt", "-n", "-o", "SOURCE", "/"])
    source = out.strip().split("[", 1)[0]
    if code != 0 or not source.startswith("/dev/"):
        raise YggError(f"impossible de déterminer la partition système (findmnt : « {out.strip()} »).")
    return source


def racine_btrfs(runner: Runner) -> bool:
    """Racine en btrfs, sous-volume @ (installation Calamares) : Timeshift en mode btrfs."""
    _, sortie = runner.query(["findmnt", "-n", "-o", "FSTYPE,OPTIONS", "/"])
    champs = sortie.split()
    return (len(champs) >= 2 and champs[0] == "btrfs"
            and re.search(r"(^|,)subvol=/?@(,|$)", champs[1]) is not None)


def instantane_demarre(mountinfo: Path = MOUNTINFO) -> str | None:
    """L'instantané Timeshift sur lequel le système a démarré (menu de GRUB), sinon None."""
    try:
        lignes = mountinfo.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    racine = None
    for ligne in lignes:  # le dernier montage sur / cache les précédents
        champs = ligne.split()
        if len(champs) > 4 and champs[4] == "/":
            racine = champs[3]
    trouve = RACINE_INSTANTANE.fullmatch(racine or "")
    return trouve.group(1) if trouve else None


def libelle_instantane(nom: str) -> str:
    """« du 02/10/2026 à 06:00 » pour un instantané nommé par Timeshift, sinon son nom."""
    try:
        quand = dt.datetime.strptime(nom, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return f"« {nom} »"
    return f"du {quand:%d/%m/%Y} à {quand:%H:%M}"


def build_timeshift_config(base: dict, uuid: str, daily: int, weekly: int, monthly: int, boot: int,
                           btrfs: bool = False) -> dict:
    cfg = dict(TIMESHIFT_BASE)
    cfg.update(base)
    cfg.update({
        "backup_device_uuid": uuid,
        "do_first_run": "false",
        "btrfs_mode": str(btrfs).lower(),
        "include_btrfs_home_for_backup": "false",
        "include_btrfs_home_for_restore": "false",
        "schedule_daily": str(daily > 0).lower(),
        "count_daily": str(max(daily, 1)),
        "schedule_weekly": str(weekly > 0).lower(),
        "count_weekly": str(max(weekly, 1)),
        "schedule_monthly": str(monthly > 0).lower(),
        "count_monthly": str(max(monthly, 1)),
        "schedule_boot": str(boot > 0).lower(),
        "count_boot": str(max(boot, 1)),
    })
    return cfg


def require_timeshift() -> None:
    if not common.which("timeshift"):
        raise YggError("Timeshift n'est pas installé (sudo apt install timeshift).")


def create_snapshot(runner: Runner, comment: str) -> None:
    require_timeshift()
    # Sans --tags : un instantané à la demande est marqué O de lui-même (Timeshift 24.06
    # refuse « --tags O » à la création, bien qu'il le cite parmi les valeurs permises)
    runner.run(["timeshift", "--create", "--comments", comment, "--scripted"], root=True)
    common.ok(f"instantané créé : « {comment} »")
    if racine_btrfs(runner) and GRUB_INSTANTANES.exists() and common.which("update-grub"):
        # Le nouvel instantané rejoint le menu de démarrage (« revenir à un instantané »)
        runner.run(["update-grub"], root=True, check=False, capture=True)
    voix.annoncer("nornes", "instantane", nom=comment)


def cmd_setup(args, runner: Runner, config) -> int:
    require_timeshift()
    if common.is_live_session():
        raise YggError("instantanés impossibles en session live : installe d'abord Yggdrasil sur le disque.")
    device = args.device or root_device(runner)
    code, uuid = runner.query(["blkid", "-s", "UUID", "-o", "value", device], root=True)
    uuid = uuid.strip()
    if code != 0 or not uuid:
        raise YggError(f"UUID introuvable pour {device}.")
    base = {}
    if TIMESHIFT_DEFAULT.exists():
        try:
            base = json.loads(TIMESHIFT_DEFAULT.read_text(encoding="utf-8"))
        except ValueError:
            base = {}
    btrfs = racine_btrfs(runner)
    cfg = build_timeshift_config(base, uuid, args.daily, args.weekly, args.monthly, args.boot, btrfs=btrfs)
    common.title("Configuration des instantanés système")
    common.step(f"partition de stockage : {device} (UUID {uuid})")
    if btrfs:
        common.step("btrfs : instantanés immédiats et légers, et visibles au menu de démarrage")
    common.step(f"rétention : {args.daily} quotidiens, {args.weekly} hebdomadaires, {args.monthly} mensuels, {args.boot} au démarrage")
    common.step("ton dossier personnel est exclu (utilise « norns backup » pour lui)")
    if not common.confirm("Appliquer ?", default=True, assume_yes=args.yes):
        return 1
    runner.write_file(TIMESHIFT_CONFIG, json.dumps(cfg, indent=2) + "\n", root=True)
    common.ok("instantanés configurés.")
    if common.confirm("Créer un premier instantané maintenant ?", default=True, assume_yes=args.yes):
        create_snapshot(runner, "premier instantané (norns setup)")
    return 0


def cmd_snap(args, runner: Runner, config) -> int:
    if not timeshift_configured():
        raise YggError("instantanés non configurés : lance d'abord « norns setup ».")
    comment = " ".join(args.comment) or f"manuel {dt.datetime.now():%d/%m/%Y %H:%M}"
    create_snapshot(runner, comment)
    return 0


def cmd_list(args, runner: Runner, config) -> int:
    require_timeshift()
    return runner.run(["timeshift", "--list", "--scripted"], root=True, check=False).returncode


def cmd_delete(args, runner: Runner, config) -> int:
    require_timeshift()
    if not common.confirm(f"Supprimer définitivement l'instantané {args.name} ?", assume_yes=args.yes):
        return 1
    runner.run(["timeshift", "--delete", "--snapshot", args.name, "--scripted"], root=True)
    return 0


def cmd_restore(args, runner: Runner, config) -> int:
    require_timeshift()
    common.title("Restauration du système")
    common.warn("la restauration remplace les fichiers système par ceux de l'instantané, puis redémarre.")
    common.info("Tes fichiers personnels (/home) ne sont pas touchés.")
    common.info("Si le système ne démarre plus, lance la restauration depuis la clé USB live Yggdrasil.")
    if not common.confirm("Continuer vers l'assistant de restauration Timeshift ?", assume_yes=args.yes):
        return 1
    cmd = ["timeshift", "--restore"]
    if args.name:
        cmd += ["--snapshot", args.name]
    return runner.run(cmd, root=True, check=False).returncode


# --------------------------------------------------------------------------
# Sauvegardes du dossier personnel (rsync + liens durs)
# --------------------------------------------------------------------------

def backup_root(target: Path, user: str | None = None, host: str | None = None) -> Path:
    user = user or common.target_user()
    host = host or socket.gethostname()
    return target / BACKUP_DIRNAME / f"{host}-{user}"


def list_backups(root: Path) -> list[Path]:
    """Sauvegardes complètes, de la plus ancienne à la plus récente."""
    if not root.is_dir():
        return []
    found = []
    for entry in root.iterdir():
        if entry.is_dir() and (entry / COMPLETE_MARKER).exists():
            try:
                dt.datetime.strptime(entry.name, STAMP_FORMAT)
            except ValueError:
                continue
            found.append(entry)
    return sorted(found, key=lambda p: p.name)


def to_prune(backups: list[Path], keep: int) -> list[Path]:
    keep = max(keep, 1)
    return backups[:-keep] if len(backups) > keep else []


def rsync_command(source: Path, dest: Path, link_dest: Path | None, excludes: list[str],
                  hardlinks_ok: bool = True, dry_run: bool = False) -> list[str]:
    cmd = ["rsync", "-a", "--human-readable", "--info=progress2,stats1", "--delete", "--delete-excluded"]
    if dry_run:
        cmd.append("--dry-run")
    for pattern in excludes:
        cmd.append(f"--exclude={pattern}")
    if link_dest is not None and hardlinks_ok:
        cmd.append(f"--link-dest={link_dest}")
    cmd += [f"{source}/", f"{dest}/"]
    return cmd


NO_HARDLINK_FS = {"vfat", "exfat", "msdos", "fuseblk"}


def filesystem_type(runner: Runner, path: Path) -> str:
    _, out = runner.query(["findmnt", "-n", "-o", "FSTYPE", "-T", str(path)])
    return out.strip()


def resolve_target(args, config) -> Path:
    target = getattr(args, "to", None) or config.get("norns", {}).get("backup_target", "")
    if not target:
        raise YggError("indique où sauvegarder : « norns backup --to /media/toi/MonDisque » "
                       "(ou règle norns.backup_target dans ~/.config/yggdrasil/config.toml).")
    path = common.expand(target)
    if not path.is_dir():
        raise YggError(f"{path} n'existe pas ou n'est pas monté.")
    return path


def cmd_backup(args, runner: Runner, config) -> int:
    if not common.which("rsync"):
        raise YggError("rsync est requis (sudo apt install rsync).")
    if getattr(args, "si_present", False):
        # Lancé par Skuld : disque absent = rien à faire, sans erreur
        cible = getattr(args, "to", None) or config.get("norns", {}).get("backup_target", "")
        if not cible or not common.expand(cible).is_dir():
            return 0
    target = resolve_target(args, config)
    source = Path.home()
    try:
        target.resolve().relative_to(source.resolve())
        raise YggError("la destination est à l'intérieur de ton dossier personnel : choisis un autre disque.")
    except ValueError:
        pass
    norns_cfg = config.get("norns", {})
    keep = args.keep if args.keep is not None else int(norns_cfg.get("keep", 7))
    excludes = DEFAULT_EXCLUDES + list(norns_cfg.get("exclude", [])) + list(args.exclude or [])

    fstype = filesystem_type(runner, target)
    hardlinks_ok = fstype not in NO_HARDLINK_FS
    root = backup_root(target)
    backups = list_backups(root)
    latest = backups[-1] if backups else None
    stamp = dt.datetime.now().strftime(STAMP_FORMAT)
    dest = root / stamp
    partial = root / (stamp + ".partiel")

    common.title("Sauvegarde du dossier personnel")
    common.step(f"source      : {source}")
    common.step(f"destination : {dest}" + (f" ({fstype})" if fstype else ""))
    if latest and hardlinks_ok:
        common.step(f"incrémentale par rapport à {latest.name} (fichiers inchangés partagés)")
    elif latest:
        common.warn(f"le système de fichiers {fstype} ne gère pas les liens durs : copie complète à chaque fois. "
                    "Formate le disque en ext4 pour des sauvegardes incrémentales.")
    common.step(f"conservation : {keep} sauvegarde(s)")
    if not args.dry_run and not common.confirm("Lancer la sauvegarde ?", default=True, assume_yes=args.yes):
        return 1

    if not args.dry_run:
        partial.mkdir(parents=True, exist_ok=True)
    cmd = rsync_command(source, partial, latest, excludes, hardlinks_ok, dry_run=args.dry_run)
    # En simulation, rsync --dry-run tourne vraiment : il liste ce qui serait copié sans rien écrire.
    proc = (Runner(verbose=runner.verbose) if args.dry_run else runner).run(cmd, check=False)
    # 24 = des fichiers ont disparu pendant la copie : sans gravité pour un /home vivant
    if proc.returncode not in (0, 24):
        raise YggError(f"rsync a échoué (code {proc.returncode}) ; la sauvegarde partielle reste dans {partial}.")
    if args.dry_run:
        common.ok("simulation terminée : rien n'a été écrit.")
        return 0
    (partial / COMPLETE_MARKER).write_text(dt.datetime.now().isoformat() + "\n", encoding="utf-8")
    partial.rename(dest)
    common.ok(f"sauvegarde terminée : {dest}")
    voix.annoncer("nornes", "sauvegarde", cible=dest.parent)
    from . import toile

    toile.noter(sauvegarde_ok=dt.datetime.now().timestamp())

    for old in to_prune(list_backups(root), keep):
        shutil.rmtree(old, ignore_errors=True)
        common.info(f"ancienne sauvegarde supprimée : {old.name}")
    return 0


def cmd_backups(args, runner: Runner, config) -> int:
    target = resolve_target(args, config)
    root = backup_root(target)
    backups = list_backups(root)
    if not backups:
        common.info(f"aucune sauvegarde dans {root}")
        return 0
    common.title(f"Sauvegardes dans {root}")
    for b in reversed(backups):
        when = dt.datetime.strptime(b.name, STAMP_FORMAT)
        print(f"  {b.name}   {when:%d/%m/%Y à %H:%M}")
    return 0


def safe_relative(path: str) -> Path:
    rel = Path(path)
    if rel.is_absolute():
        try:
            rel = rel.relative_to(Path.home())
        except ValueError as exc:
            raise YggError("le chemin à restaurer doit être dans ton dossier personnel.") from exc
    if ".." in rel.parts:
        raise YggError("chemin invalide.")
    return rel


def cmd_recover(args, runner: Runner, config) -> int:
    target = resolve_target(args, config)
    root = backup_root(target)
    backups = list_backups(root)
    if not backups:
        raise YggError(f"aucune sauvegarde dans {root}.")
    if args.snapshot:
        matches = [b for b in backups if b.name.startswith(args.snapshot)]
        if not matches:
            raise YggError(f"sauvegarde « {args.snapshot} » introuvable (norns backups --to …).")
        snapshot = matches[-1]
    else:
        snapshot = backups[-1]
    rel = safe_relative(args.path) if args.path else Path(".")
    src = snapshot / rel
    if not src.exists():
        raise YggError(f"{rel} n'existe pas dans la sauvegarde {snapshot.name}.")
    if args.in_place:
        dest = Path.home() / rel
        common.warn(f"les fichiers existants dans {dest} seront écrasés par ceux de {snapshot.name}.")
    else:
        dest = Path.home() / "norns-restauration" / snapshot.name / rel
    common.title("Récupération de fichiers")
    common.step(f"depuis : {src}")
    common.step(f"vers   : {dest}")
    if not common.confirm("Continuer ?", default=not args.in_place, assume_yes=args.yes):
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        runner.run(["rsync", "-a", "--info=progress2", "--exclude", COMPLETE_MARKER, f"{src}/", f"{dest}/"])
    else:
        runner.run(["rsync", "-a", str(src), str(dest)])
    common.ok(f"récupéré dans {dest}")
    return 0


def cmd_status(args, runner: Runner, config) -> int:
    common.title("Norns — instantanés et sauvegardes")
    nom = instantane_demarre()
    if nom:
        common.warn(f"démarré sur l'instantané {libelle_instantane(nom)} : ton système habituel est intact.")
        common.info(f"Pour revenir à cet instantané pour de bon : norns restore {nom} — sinon, redémarre simplement.")
    if common.is_live_session():
        common.info("session live : instantanés sans objet.")
    elif timeshift_configured():
        common.ok("instantanés système configurés (norns list pour les voir).")
    else:
        common.warn("instantanés système non configurés → norns setup")
    target = config.get("norns", {}).get("backup_target", "")
    if target and common.expand(target).is_dir():
        backups = list_backups(backup_root(common.expand(target)))
        if backups:
            last = dt.datetime.strptime(backups[-1].name, STAMP_FORMAT)
            age = dt.datetime.now() - last
            msg = f"dernière sauvegarde perso : {last:%d/%m/%Y %H:%M} (il y a {common.human_duration(age.total_seconds())})"
            (common.warn if age.days >= 7 else common.ok)(msg)
        else:
            common.warn(f"aucune sauvegarde perso dans {target} → norns backup")
    elif target:
        common.info(f"disque de sauvegarde {target} non branché.")
    else:
        common.info("aucun disque de sauvegarde configuré (norns.backup_target).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    opts = argparse.ArgumentParser(add_help=False)
    opts.add_argument("-y", "--yes", action="store_true", help="valider automatiquement")
    opts.add_argument("-n", "--dry-run", action="store_true", help="simuler")
    opts.add_argument("-v", "--verbose", action="store_true")

    parser = argparse.ArgumentParser(prog="norns", description="Instantanés système et sauvegardes d'Yggdrasil.")
    sub = parser.add_subparsers(dest="command", metavar="commande")
    sub.add_parser("status", help="état général", parents=[opts]).set_defaults(func=cmd_status)

    p = sub.add_parser("setup", help="configurer les instantanés système", parents=[opts])
    p.add_argument("--device", help="partition de stockage (défaut : celle du système)")
    p.add_argument("--daily", type=int, default=5)
    p.add_argument("--weekly", type=int, default=3)
    p.add_argument("--monthly", type=int, default=0)
    p.add_argument("--boot", type=int, default=0)
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("snap", help="créer un instantané système", parents=[opts])
    p.add_argument("comment", nargs="*")
    p.set_defaults(func=cmd_snap)
    sub.add_parser("list", help="lister les instantanés", parents=[opts]).set_defaults(func=cmd_list)
    p = sub.add_parser("delete", help="supprimer un instantané", parents=[opts])
    p.add_argument("name")
    p.set_defaults(func=cmd_delete)
    p = sub.add_parser("restore", help="restaurer un instantané système", parents=[opts])
    p.add_argument("name", nargs="?")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("backup", help="sauvegarder ton dossier personnel", parents=[opts])
    p.add_argument("--to", help="dossier de destination (disque externe)")
    p.add_argument("--keep", type=int, help="nombre de sauvegardes conservées")
    p.add_argument("--exclude", action="append", help="motif à exclure (répétable)")
    p.add_argument("--si-present", action="store_true", help="ne rien faire si le disque n'est pas branché")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("backups", help="lister les sauvegardes perso", parents=[opts])
    p.add_argument("--to")
    p.set_defaults(func=cmd_backups)

    p = sub.add_parser("recover", help="récupérer des fichiers depuis une sauvegarde perso", parents=[opts])
    p.add_argument("path", nargs="?", help="chemin dans ton dossier perso (défaut : tout)")
    p.add_argument("--to")
    p.add_argument("--snapshot", help="date de la sauvegarde (préfixe, ex. 2026-09-30)")
    p.add_argument("--in-place", action="store_true", help="écraser les fichiers actuels au lieu de copier à côté")
    p.set_defaults(func=cmd_recover)

    from . import toile

    toile.ajouter_commandes(sub, opts)
    return parser


def _main(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["status"])
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    return args.func(args, runner, common.load_config())


def main(argv=None) -> int:
    return common.run_main(_main, argv)


if __name__ == "__main__":
    sys.exit(main())
