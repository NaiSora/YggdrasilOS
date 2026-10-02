"""Le temps qui passe : tâches planifiées et thème jour/nuit.

    ygg taches                              tes tâches planifiées, leur prochain passage
    ygg taches ajouter NOM "COMMANDE" --quand quotidien|horaire|hebdomadaire|mensuel|
                                              au-demarrage|HH:MM|expression OnCalendar
    ygg taches retirer|lancer|journal NOM

    ygg theme                               le thème actuel
    ygg theme nuit|aube                     bleu nuit (par défaut) ou parchemin clair
    ygg theme auto [--aube 07:30] [--nuit 20:00]   suit l'heure de la journée

Les tâches sont des minuteries systemd de l'utilisateur (~/.config/systemd/user/
ygg-tache-NOM.timer) : elles tournent même sans terminal ouvert, et leurs sorties
vont dans le journal (ygg taches journal NOM).
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shlex
from pathlib import Path

from . import common
from .common import Runner, YggError

NOM_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
HEURE_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
PREFIXE = "ygg-tache-"
QUAND = {
    "horaire": "OnCalendar=hourly",
    "quotidien": "OnCalendar=daily",
    "hebdomadaire": "OnCalendar=weekly",
    "mensuel": "OnCalendar=monthly",
    "au-demarrage": "OnStartupSec=2min",
}


def dossier_unites() -> Path:
    return common.user_config_dir().parent / "systemd" / "user"


def declencheur(quand: str) -> str:
    """« quotidien », « 18:30 » ou une expression OnCalendar → ligne de la section [Timer]."""
    quand = quand.strip()
    if quand in QUAND:
        return QUAND[quand]
    m = HEURE_RE.match(quand)
    if m:
        return f"OnCalendar=*-*-* {int(m.group(1)):02d}:{m.group(2)}:00"
    if not quand or "\n" in quand or "=" in quand:
        raise YggError(f"moment invalide « {quand} »")
    return f"OnCalendar={quand}"


def unites(nom: str, commande: str, quand: str) -> tuple[str, str]:
    """Le service et la minuterie d'une tâche."""
    if not NOM_RE.match(nom):
        raise YggError(f"nom de tâche invalide « {nom} » : minuscules, chiffres et tirets.")
    if not commande.strip() or "\n" in commande:
        raise YggError("la commande doit tenir sur une ligne.")
    service = (f"[Unit]\nDescription=Tâche Yggdrasil : {nom}\n\n"
               f"[Service]\nType=oneshot\n"
               f"ExecStart=/bin/bash -lc {shlex.quote(commande)}\n"
               f"Nice=10\n")
    timer = (f"[Unit]\nDescription=Quand lancer la tâche Yggdrasil « {nom} »\n\n"
             f"[Timer]\n{declencheur(quand)}\nPersistent=true\nAccuracySec=1min\n\n"
             f"[Install]\nWantedBy=timers.target\n")
    return service, timer


def commande_de(service: str) -> str:
    for line in service.splitlines():
        if line.startswith("ExecStart=/bin/bash -lc "):
            try:
                return shlex.split(line.removeprefix("ExecStart=/bin/bash -lc "))[0]
            except (ValueError, IndexError):
                return line
    return ""


def quand_de(timer: str) -> str:
    for line in timer.splitlines():
        for cle, valeur in QUAND.items():
            if line == valeur:
                return cle
        if line.startswith("OnCalendar="):
            expr = line.removeprefix("OnCalendar=")
            m = re.match(r"^\*-\*-\* (\d\d:\d\d):00$", expr)
            return f"chaque jour à {m.group(1)}" if m else expr
    return "?"


def taches() -> list[str]:
    return sorted(p.name.removeprefix(PREFIXE).removesuffix(".timer")
                  for p in dossier_unites().glob(f"{PREFIXE}*.timer"))


def cmd_taches(args, runner: Runner, config) -> int:
    action = {"list": "liste", "add": "ajouter", "remove": "retirer", "run": "lancer", "log": "journal"}.get(
        args.action, args.action) or "liste"
    if action == "liste":
        common.title("Tâches planifiées")
        noms = taches()
        if not noms:
            common.info("Aucune tâche. Exemple : ygg taches ajouter sauvegarde \"norns backup\" --quand 21:00")
            return 0
        rows = []
        for nom in noms:
            d = dossier_unites()
            service = common.read_text(d / f"{PREFIXE}{nom}.service")
            _, prochain = runner.query(["systemctl", "--user", "show", f"{PREFIXE}{nom}.timer",
                                        "-p", "NextElapseUSecRealtime", "--value"])
            commande = commande_de(service)
            rows.append((nom, quand_de(common.read_text(d / f"{PREFIXE}{nom}.timer")),
                         prochain.strip() or "-", commande if len(commande) < 50 else commande[:47] + "…"))
        print(common.table(rows, headers=("tâche", "quand", "prochain passage", "commande")))
        return 0
    if not args.nom:
        raise YggError("indique le nom de la tâche.")
    unite = f"{PREFIXE}{args.nom}"
    if action == "ajouter":
        if not args.commande or not args.quand:
            raise YggError('il faut une commande et un moment : ygg taches ajouter NOM "COMMANDE" --quand quotidien')
        service, timer = unites(args.nom, args.commande, args.quand)
        expr = declencheur(args.quand)
        if expr.startswith("OnCalendar=") and common.which("systemd-analyze"):
            code, _ = runner.query(["systemd-analyze", "calendar", expr.removeprefix("OnCalendar=")])
            if code != 0:
                raise YggError(f"systemd ne comprend pas le moment « {args.quand} ».")
        d = dossier_unites()
        runner.write_file(d / f"{unite}.service", service)
        runner.write_file(d / f"{unite}.timer", timer)
        runner.run(["systemctl", "--user", "daemon-reload"])
        runner.run(["systemctl", "--user", "enable", "--now", f"{unite}.timer"])
        common.ok(f"tâche « {args.nom} » planifiée ({quand_de(timer)}).")
        return 0
    if args.nom not in taches():
        raise YggError(f"aucune tâche « {args.nom} » (ygg taches pour la liste).")
    if action == "retirer":
        runner.run(["systemctl", "--user", "disable", "--now", f"{unite}.timer"], check=False)
        if not runner.dry_run:
            for suffixe in (".timer", ".service"):
                (dossier_unites() / f"{unite}{suffixe}").unlink(missing_ok=True)
        runner.run(["systemctl", "--user", "daemon-reload"])
        common.ok(f"tâche « {args.nom} » retirée.")
        return 0
    if action == "lancer":
        runner.run(["systemctl", "--user", "start", f"{unite}.service"])
        common.ok(f"tâche « {args.nom} » lancée (ygg taches journal {args.nom} pour sa sortie).")
        return 0
    if action == "journal":
        return runner.run(["journalctl", "--user", "-u", f"{unite}.service", "-n", "40", "--no-pager"],
                          check=False).returncode
    raise YggError(f"action inconnue : {action}")


# --------------------------------------------------------------------------
# Thème jour/nuit
# --------------------------------------------------------------------------

SCHEMAS = {"nuit": "Yggdrasil", "aube": "YggdrasilAube"}
MINUTERIE_THEME = "yggdrasil-theme.timer"


def _minutes(heure: str) -> int:
    m = HEURE_RE.match(heure)
    if not m:
        raise YggError(f"heure invalide « {heure} » (format HH:MM)")
    return int(m.group(1)) * 60 + int(m.group(2))


def schema_pour(mode: str, maintenant: dt.time, aube: str = "07:30", nuit: str = "20:00") -> str:
    """Le jeu de couleurs Plasma à appliquer pour ce mode, à cette heure."""
    if mode in SCHEMAS:
        return SCHEMAS[mode]
    debut, fin = _minutes(aube), _minutes(nuit)
    t = maintenant.hour * 60 + maintenant.minute
    jour = debut <= t < fin if debut < fin else not fin <= t < debut
    return SCHEMAS["aube" if jour else "nuit"]


def schema_actuel(runner: Runner) -> str:
    _, out = runner.query(["kreadconfig6", "--group", "General", "--key", "ColorScheme"])
    return out.strip()


def appliquer_schema(runner: Runner, schema: str) -> None:
    if schema_actuel(runner) == schema:
        return
    runner.run(["plasma-apply-colorscheme", schema], check=False, capture=True)


def cmd_theme(args, runner: Runner, config) -> int:
    reglage = config.get("theme", {})
    aube = args.aube or reglage.get("aube", "07:30")
    nuit = args.nuit or reglage.get("nuit", "20:00")
    for heure in (aube, nuit):
        _minutes(heure)  # vérifie le format
    if args.appliquer:
        # Appelé par la minuterie : silencieux, et seulement en mode auto
        mode = reglage.get("mode", "nuit")
        if mode == "auto":
            appliquer_schema(runner, schema_pour("auto", dt.datetime.now().time(), aube, nuit))
        return 0
    if not args.mode:
        mode = reglage.get("mode", "nuit")
        common.title("Thème")
        details = f" (aube à {aube}, nuit à {nuit})" if mode == "auto" else ""
        common.info(f"mode : {mode}{details} — jeu de couleurs actuel : {schema_actuel(runner) or '?'}")
        common.info(common.dim("ygg theme nuit | aube | auto"))
        return 0
    if args.mode not in (*SCHEMAS, "auto"):
        raise YggError("thème inconnu : nuit, aube ou auto")
    if not runner.dry_run:
        common.save_user_config({"theme": {"mode": args.mode, "aube": aube, "nuit": nuit}})
    if args.mode == "auto":
        runner.run(["systemctl", "--user", "enable", "--now", MINUTERIE_THEME], check=False)
    else:
        runner.run(["systemctl", "--user", "disable", "--now", MINUTERIE_THEME], check=False, capture=True)
    schema = schema_pour(args.mode, dt.datetime.now().time(), aube, nuit)
    appliquer_schema(runner, schema)
    suite = f" : parchemin de {aube} à {nuit}, bleu nuit ensuite" if args.mode == "auto" else ""
    common.ok(f"thème « {args.mode} »{suite}.")
    return 0


def ajouter_commandes(sub, common_opts) -> None:
    p = sub.add_parser("taches", aliases=["tasks"], help="tâches planifiées", parents=[common_opts])
    p.add_argument("action", nargs="?", choices=["liste", "ajouter", "retirer", "lancer", "journal",
                                                 "list", "add", "remove", "run", "log"])
    p.add_argument("nom", nargs="?")
    p.add_argument("commande", nargs="?")
    p.add_argument("--quand", help="quotidien, horaire, hebdomadaire, mensuel, au-demarrage, HH:MM…")
    p.set_defaults(func=cmd_taches)
    p = sub.add_parser("theme", help="thème nuit, aube, ou auto (suit l'heure)", parents=[common_opts])
    p.add_argument("mode", nargs="?")
    p.add_argument("--aube", help="heure du passage au thème clair (07:30)")
    p.add_argument("--nuit", help="heure du retour au thème nuit (20:00)")
    p.add_argument("--appliquer", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_theme)
