"""ratatoskr — l'écureuil messager qui court le long du tronc.

Lancé par un minuteur systemd (utilisateur) une minute après l'ouverture de
session, puis toutes les 6 heures et au réveil d'une veille, il rassemble les
nouvelles — mises à jour, problèmes graves vus par « ygg doctor », alertes des
autres gardiens (Heimdall, les Nornes, Bifröst…) — et prévient, sans jamais rien
modifier lui-même :

  * une notification avec des boutons : Mettre à jour, Demander à Mímir, Plus tard ;
  * jamais pendant une partie (GameMode), un live (OBS) ou en mode « ne pas déranger » :
    il repassera plus tard ;
  * et, si tu le veux, sur ton téléphone (ntfy).

    ratatoskr check [--print] [--force] [--attendre]
    ratatoskr bilan                   le bilan de la machine (envoyé seul après l'installation)
    ratatoskr telephone [ntfy|URL|test|non]
    ratatoskr enable | disable | status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import common, doctor, voix
from .common import Runner, YggError


def state_path() -> Path:
    return common.user_state_dir() / "ratatoskr" / "state.json"


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


REFRESH_UNIT = "ratatoskr-refresh.service"
SOURCES = {"heimdall": "Heimdall", "norns": "Les Nornes", "bifrost": "Bifröst", "disques": "Disques",
           "huginn": "Huginn", "ygg": "Yggdrasil"}


def wait_until_ready(runner: Runner, *, network_timeout: int = 90, refresh_timeout: int = 240,
                     sleep=time.sleep, clock=time.monotonic) -> None:
    """Au démarrage : laisse le réseau monter, puis la liste des paquets se
    rafraîchir (ratatoskr-refresh.service), avant de vérifier quoi que ce soit."""
    if common.which("nm-online"):
        runner.query(["nm-online", "-q", "-t", str(network_timeout)], timeout=network_timeout + 5)
    deadline = clock() + refresh_timeout
    while clock() < deadline:
        _, state = runner.query(["systemctl", "is-active", REFRESH_UNIT])
        if state.strip() != "activating":
            return
        sleep(5)


def cle_alerte(a: dict) -> str:
    return str(a.get("cle") or f"{a.get('date')}:{a.get('message')}")


def nouvelles_alertes(alertes: list[dict], vues: set[str] | list[str]) -> list[tuple[str, str]]:
    """Les alertes des gardiens pas encore relayées : (urgence, message)."""
    vues = set(vues)
    return [(a.get("urgence", "normal"), f"{SOURCES.get(a.get('source', ''), a.get('source', '?'))} : {a['message']}")
            for a in alertes if cle_alerte(a) not in vues]


def gather(runner: Runner, vues: set[str] | list[str] = ()) -> list[tuple[str, str]]:
    """Renvoie une liste (urgence, message) : urgence ∈ {normal, critical}."""
    messages: list[tuple[str, str]] = []
    if common.which("apt"):
        _, out = runner.query(["apt", "list", "--upgradable"], timeout=60)
        total, security = doctor.parse_upgradable(out)
        if security:
            messages.append(("critical", f"{security} mise(s) à jour de sécurité à installer (sur {total})."))
        elif total:
            messages.append(("normal", f"{total} mise(s) à jour disponible(s)."))
    doc = doctor.Doctor(runner)
    for check in (doc.check_disk, doc.check_failed_units, doc.check_dpkg, doc.check_reboot):
        try:
            for c in check():
                if c.status == doctor.FAIL:
                    messages.append(("critical", f"{c.label} : {c.message}"))
                elif c.status == doctor.WARN and c.key == "reboot":
                    messages.append(("normal", "Un redémarrage est nécessaire pour finir les mises à jour."))
        except Exception:  # la notification ne doit jamais planter
            continue
    messages += nouvelles_alertes(common.lire_alertes(), vues)
    rappel = rappel_sauvegarde(common.load_config())
    if rappel:
        messages.append(("normal", rappel))
    return messages


def rappel_sauvegarde(config: dict, maintenant: float | None = None, jours: int = 7) -> str:
    """Les Nornes s'inquiètent quand le fil n'a pas été tissé depuis une semaine."""
    from . import toile

    if not (config.get("norns") or {}).get("backup_target"):
        return ""
    derniere = float(toile.charger_etat().get("sauvegarde_ok", 0))
    age = ((maintenant or time.time()) - derniere) / 86400
    if derniere and age < jours:
        return ""
    quand = f"il y a {int(age)} jours" if derniere else "jamais faite"
    return f"Les Nornes : dernière sauvegarde du dossier personnel {quand} — branche ton disque (verdandi)."


def should_notify(messages: list[tuple[str, str]], state: dict, remind_hours: float, now: float) -> bool:
    if not messages:
        return False
    digest = hashlib.sha256(json.dumps(messages).encode()).hexdigest()
    if state.get("digest") != digest:
        return True
    return now - float(state.get("time", 0)) >= remind_hours * 3600


# --------------------------------------------------------------------------
# Ne pas déranger
# --------------------------------------------------------------------------

def derangement(runner: Runner) -> str:
    """Pourquoi ce n'est pas le moment (ou "" si on peut prévenir à l'écran)."""
    code, out = runner.query(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                              "--object-path", "/org/freedesktop/Notifications", "--method",
                              "org.freedesktop.DBus.Properties.Get", "org.freedesktop.Notifications", "Inhibited"])
    if code == 0 and "true" in out:
        return "mode « ne pas déranger »"
    _, out = runner.query(["gamemoded", "-s"])
    if "is active" in out:
        return "une partie est en cours (GameMode)"
    code, _ = runner.query(["pgrep", "-x", "obs"])
    if code == 0:
        return "OBS est ouvert (enregistrement ou direct)"
    return ""


# --------------------------------------------------------------------------
# Prévenir : le bureau, le téléphone
# --------------------------------------------------------------------------

BOUTONS = {"maj": "Mettre à jour", "mimir": "Demander à Mímir", "plus-tard": "Plus tard"}


def corps(messages: list[tuple[str, str]], config: dict | None) -> str:
    return voix.dire("ratatoskr", "intro", config=config) + "\n" + "\n".join(f"• {m}" for _, m in messages)


def notify(runner: Runner, messages: list[tuple[str, str]], config: dict | None = None) -> str:
    """Notification à boutons ; renvoie le bouton choisi ("" sinon)."""
    urgency = "critical" if any(u == "critical" for u, _ in messages) else "normal"
    body = corps(messages, config)
    if not common.which("notify-send"):
        print(body)
        return ""
    cmd = ["notify-send", "--app-name=Yggdrasil", "--icon=yggdrasil", f"--urgency={urgency}", "--wait"]
    boutons = dict(BOUTONS)
    if not any("mise(s) à jour" in m for _, m in messages):
        boutons.pop("maj")
    cmd += [f"--action={cle}={texte}" for cle, texte in boutons.items()]
    proc = runner.run([*cmd, voix.dire("ratatoskr", "titre", config=config), body], check=False, capture=True)
    return (proc.stdout or "").strip()


def agir(bouton: str) -> None:
    from .welcome import launch_in_terminal

    if bouton == "maj":
        launch_in_terminal("ygg update", "Mises à jour")
    elif bouton == "mimir":
        launch_in_terminal("mimir doctor", "Mímir")


def telephone_url(config: dict) -> str:
    return str((config.get("ratatoskr") or {}).get("telephone", "") or "")


def requete_ntfy(url: str, titre: str, texte: str, urgent: bool) -> urllib.request.Request:
    """Une notification ntfy : titre et priorité passent par l'adresse (accents compris)."""
    params = urllib.parse.urlencode({"title": titre, "priority": "urgent" if urgent else "default",
                                     "tags": "chipmunk"})
    return urllib.request.Request(f"{url}?{params}", data=texte.encode("utf-8"), method="POST",
                                  headers={"User-Agent": "ratatoskr (Yggdrasil)"})


def envoyer_telephone(url: str, titre: str, texte: str, urgent: bool, runner: Runner) -> bool:
    if runner.dry_run:
        print(common.style("  [simulation] ", "magenta") + f"ntfy → {url}")
        return True
    try:
        with urllib.request.urlopen(requete_ntfy(url, titre, texte, urgent), timeout=15):  # noqa: S310
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------

def cmd_check(args, runner: Runner, config) -> int:
    if args.attendre:
        wait_until_ready(runner)
    path = state_path()
    state = load_state(path)
    if not state.get("bilan") and not common.is_live_session() and not args.print:
        envoyer_bilan(runner, config)
        state["bilan"] = time.time()
        save_state(path, state)
    vues = [] if args.force else list(state.get("vues", []))
    messages = gather(runner, vues)
    if args.print:
        if not messages:
            print(voix.dire("ratatoskr", "rien", config=config))
        for urgency, msg in messages:
            print(("[!] " if urgency == "critical" else "[ ] ") + msg)
        return 0
    remind = float(config.get("ratatoskr", {}).get("remind_hours", 24))
    now = time.time()
    if not (args.force or should_notify(messages, state, remind, now)):
        return 0
    digest = hashlib.sha256(json.dumps(messages).encode()).hexdigest()
    url = telephone_url(config)
    if url and state.get("digest_tel") != digest:
        urgent = any(u == "critical" for u, _ in messages)
        if envoyer_telephone(url, voix.dire("ratatoskr", "titre", config=config), corps(messages, config),
                             urgent, runner):
            state["digest_tel"] = digest
            save_state(path, state)
    pourquoi = "" if args.force else derangement(runner)
    if pourquoi:
        # Pas maintenant : rien n'est noté, la prochaine course réessaiera
        common.info(f"Ratatoskr attend : {pourquoi}.")
        return 0
    toutes = list(dict.fromkeys(list(state.get("vues", [])) + [cle_alerte(a) for a in common.lire_alertes()]))
    state.update({"digest": digest, "time": now, "vues": toutes[-500:]})
    save_state(path, state)
    bouton = notify(runner, messages, config)
    if bouton == "plus-tard":
        state["time"] = now  # rappel dans remind_hours
        save_state(path, state)
    elif bouton:
        agir(bouton)
    return 0


def bilan(runner: Runner, config: dict) -> list[str]:
    """Le bilan d'une machine qui vient d'être installée (T2) : des faits, et quoi faire."""
    from . import heimdall, norns

    lignes = []
    _, out = runner.query(["apt", "list", "--upgradable"], timeout=60)
    total, securite = doctor.parse_upgradable(out)
    lignes.append(f"{total} mise(s) à jour en attente" + (f", dont {securite} de sécurité" if securite else "")
                  if total else "système à jour")
    try:
        actif = heimdall.load_config().enabled
    except YggError:
        actif = False
    lignes.append("pare-feu Heimdall actif" if actif else "pare-feu inactif : heimdall enable")
    lignes.append("instantanés configurés" if norns.timeshift_configured()
                  else "pas encore d'instantanés : norns setup")
    lignes.append("Mímir est prêt" if common.which("ollama") else "Mímir dort encore : ygg realm add vanaheim")
    return lignes


def envoyer_bilan(runner: Runner, config: dict) -> None:
    lignes = bilan(runner, config)
    texte = "J'ai fait le tour de ta nouvelle machine :\n" + "\n".join(f"• {x}" for x in lignes)
    if common.which("notify-send"):
        runner.run(["notify-send", "--app-name=Yggdrasil", "--icon=yggdrasil",
                    "Psst ! Ratatoskr a fait le tour de l'arbre", texte], check=False)
    else:
        print(texte)


def cmd_bilan(args, runner: Runner, config) -> int:
    common.title("Le bilan de Ratatoskr")
    for ligne in bilan(runner, config):
        common.step(ligne)
    return 0


def cmd_telephone(args, runner: Runner, config) -> int:
    action = args.cible or ""
    url = telephone_url(config)
    if not action:
        common.title("Ratatoskr et ton téléphone")
        if url:
            common.info(f"Les nouvelles partent aussi vers : {url}")
        else:
            common.info("Aucun téléphone relié. « ratatoskr telephone ntfy » crée un canal privé ntfy.")
        return 0
    if action == "non":
        common.save_user_config({"ratatoskr": {"telephone": ""}})
        common.ok("plus de notifications sur le téléphone.")
        return 0
    if action == "test":
        if not url:
            raise YggError("aucun téléphone relié : ratatoskr telephone ntfy")
        ok = envoyer_telephone(url, "Ratatoskr", "Psst ! L'écureuil sait courir jusqu'à ta poche.", False, runner)
        if not ok:
            raise YggError(f"le serveur ntfy ne répond pas ({url}).")
        common.ok("message de test envoyé.")
        return 0
    if action == "ntfy":
        url = f"https://ntfy.sh/ygg-{secrets.token_hex(8)}"
    elif action.startswith(("https://", "http://")):
        url = action.rstrip("/")
    else:
        raise YggError("ratatoskr telephone ntfy | <adresse du sujet ntfy> | test | non")
    if not runner.dry_run:
        common.save_user_config({"ratatoskr": {"telephone": url}})
    common.ok(f"canal relié : {url}")
    common.info("Sur le téléphone : application ntfy → « + » → s'abonner à ce sujet (ou scanne ce code).")
    common.info(common.dim("Le nom du sujet est ton secret : ne le partage pas. Pour garder tout chez toi, "
                           "héberge ntfy avec Bifröst et donne son adresse ici."))
    if common.which("qrencode") and not runner.dry_run:
        subprocess.run(["qrencode", "-t", "ansiutf8", url], check=False)
    return 0


def cmd_enable(args, runner: Runner, config) -> int:
    runner.run(["systemctl", "--user", "enable", "--now", "ratatoskr.timer"])
    common.ok("Ratatoskr surveillera ta machine (à l'ouverture de session, puis toutes les 6 heures).")
    return 0


def cmd_disable(args, runner: Runner, config) -> int:
    runner.run(["systemctl", "--user", "disable", "--now", "ratatoskr.timer"])
    common.ok("Ratatoskr se repose.")
    return 0


def cmd_status(args, runner: Runner, config) -> int:
    _, active = runner.query(["systemctl", "--user", "is-active", "ratatoskr.timer"])
    print(f"  Minuteur : {active.strip() or 'inconnu'}")
    state = load_state(state_path())
    if state.get("time"):
        print(f"  Dernière notification : {time.strftime('%d/%m/%Y %H:%M', time.localtime(state['time']))}")
    url = telephone_url(config)
    print(f"  Téléphone : {url or 'non relié (ratatoskr telephone ntfy)'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    opts = argparse.ArgumentParser(add_help=False)
    opts.add_argument("-n", "--dry-run", action="store_true")
    opts.add_argument("-v", "--verbose", action="store_true")
    parser = argparse.ArgumentParser(prog="ratatoskr", description="Notifications système d'Yggdrasil.")
    sub = parser.add_subparsers(dest="command", metavar="commande")
    p = sub.add_parser("check", help="vérifier et notifier si besoin", parents=[opts])
    p.add_argument("--print", action="store_true", help="afficher au lieu de notifier")
    p.add_argument("--force", action="store_true", help="notifier même si rien n'a changé (et même en jeu)")
    p.add_argument("--attendre", action="store_true",
                   help="attendre le réseau et le rafraîchissement de la liste des paquets (démarrage)")
    p.set_defaults(func=cmd_check)
    sub.add_parser("bilan", help="le bilan de la machine", parents=[opts]).set_defaults(func=cmd_bilan)
    p = sub.add_parser("telephone", help="prévenir aussi ton téléphone (ntfy)", parents=[opts])
    p.add_argument("cible", nargs="?", help="ntfy (canal privé sur ntfy.sh), une adresse ntfy, test ou non")
    p.set_defaults(func=cmd_telephone)
    sub.add_parser("enable", help="activer le minuteur", parents=[opts]).set_defaults(func=cmd_enable)
    sub.add_parser("disable", help="désactiver le minuteur", parents=[opts]).set_defaults(func=cmd_disable)
    sub.add_parser("status", help="état", parents=[opts]).set_defaults(func=cmd_status)
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
