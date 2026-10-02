"""ygg — le gestionnaire système d'Yggdrasil.

    ygg                      sans argument, dans un terminal : le menu
    ygg info                 résumé de la machine
    ygg update               mise à jour complète (APT + Flatpak), instantané avant
    ygg install/remove/search
    ygg realm list|show|add|remove   ensembles de logiciels prêts à l'emploi
    ygg doctor               diagnostic de santé
    ygg reparer              réparer le système, le bureau, le son, le réseau
    ygg annuler / retour     défaire la dernière action / restaurer un instantané
    ygg nettoyer             Níðhöggr : récupère de l'espace disque
    ygg materiel / pilotes / energie / demarrage / noyaux
    ygg partage / distance   dossiers visibles depuis Windows ; SSH, WireGuard
    ygg taches / theme / comptes / miroir / rapport
    ygg services             gestion simple des services
    ygg saga                 le journal de tout ce que les outils ont fait

Les autres outils sont accessibles aussi via ygg :
    ygg ai …  (mimir)   ygg fw …  (heimdall)   ygg snap … (norns)
    ygg stack … (bifrost)   ygg new … (brokkr)   ygg notify … (ratatoskr)
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import (CODENAME, DEBIAN_BASE, __version__, common, comptes, doctor, entretien, materiel, partage, realms,
               sysinfo, taches)
from .common import Runner, YggError

DELEGATES = {
    "ai": "mimir",
    "mimir": "mimir",
    "fw": "heimdall",
    "firewall": "heimdall",
    "heimdall": "heimdall",
    "snap": "norns",
    "norns": "norns",
    "backup": "norns",
    "stack": "bifrost",
    "bifrost": "bifrost",
    "new": "brokkr",
    "brokkr": "brokkr",
    "notify": "ratatoskr",
    "ratatoskr": "ratatoskr",
}


def delegate(module: str, argv: list[str]) -> int:
    mod = importlib.import_module(f"yggdrasil.{module}")
    return mod.main(argv)


# --------------------------------------------------------------------------
# Commandes
# --------------------------------------------------------------------------

def cmd_info(args, runner: Runner, config) -> int:
    data = sysinfo.collect(runner)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(sysinfo.render(data))
    return 0


def cmd_version(args, runner, config) -> int:
    print(f"Yggdrasil {__version__} « {CODENAME} » — basé sur Debian {DEBIAN_BASE}")
    return 0


def snapshot_before_update(runner: Runner, assume_yes: bool) -> None:
    from . import norns

    if common.is_live_session():
        return
    if not norns.timeshift_configured():
        common.warn("aucun instantané système configuré : en cas de pépin, pas de retour arrière (« norns setup »).")
        return
    common.title("Instantané de sécurité (Norns)")
    try:
        norns.create_snapshot(runner, "avant ygg update")
    except YggError as exc:
        common.error(str(exc))
        if not common.confirm("L'instantané a échoué. Continuer la mise à jour quand même ?", assume_yes=assume_yes):
            raise YggError("mise à jour annulée.") from exc


def cmd_update(args, runner: Runner, config) -> int:
    upd = config.get("update", {})
    if upd.get("snapshot_before", True) and not args.no_snapshot:
        snapshot_before_update(runner, args.yes)

    common.title("Rafraîchissement des dépôts Debian")
    runner.run(["apt-get", "update"], root=True)

    _, out = runner.query(["apt", "list", "--upgradable"], timeout=60)
    total, security = doctor.parse_upgradable(out)
    if total:
        common.title(f"{total} paquet(s) à mettre à jour" + (f", dont {security} de sécurité" if security else ""))
        cmd = ["apt-get", "full-upgrade"]
        if args.yes:
            cmd.append("-y")
        runner.run(cmd, root=True)
        runner.run(["apt-get", "autoremove", "-y"], root=True)
    else:
        common.ok("paquets Debian déjà à jour.")

    if upd.get("flatpak", True) and not args.no_flatpak and common.which("flatpak"):
        common.title("Mise à jour des applications Flatpak")
        runner.run(["flatpak", "update", "--system", "-y", "--noninteractive"], root=True, check=False)
        _, user_remotes = runner.query(["flatpak", "remotes", "--user", "--columns=name"])
        if user_remotes.strip():
            runner.run(["flatpak", "update", "--user", "-y", "--noninteractive"], check=False)

    if Path("/run/reboot-required").exists():
        common.warn("un redémarrage est nécessaire pour terminer la mise à jour (noyau ou bibliothèques).")
    common.ok("mise à jour terminée.")
    return 0


def split_targets(names: list[str]) -> tuple[list[str], list[str]]:
    apt, flat = [], []
    for name in names:
        (flat if realms.FLATPAK_RE.match(name) else apt).append(name)
    bad = [n for n in apt if not realms.APT_RE.match(n)]
    if bad:
        raise YggError("nom de paquet invalide : " + ", ".join(bad))
    return apt, flat


def cmd_install(args, runner: Runner, config) -> int:
    apt, flat = split_targets(args.packages)
    if apt:
        cmd = ["apt-get", "install", *apt]
        if args.yes:
            cmd.insert(2, "-y")
        runner.run(cmd, root=True)
    if flat:
        realms.ensure_flathub(runner)
        cmd = ["flatpak", "install", "--system", "flathub", *flat]
        if args.yes:
            cmd.insert(3, "-y")
        runner.run(cmd, root=True)
    return 0


def cmd_remove(args, runner: Runner, config) -> int:
    apt, flat = split_targets(args.packages)
    if apt:
        cmd = ["apt-get", "purge" if args.purge else "remove", *apt]
        if args.yes:
            cmd.insert(2, "-y")
        runner.run(cmd, root=True)
    if flat:
        cmd = ["flatpak", "uninstall", "--system", *flat]
        if args.yes:
            cmd.insert(3, "-y")
        runner.run(cmd, root=True)
    return 0


def cmd_search(args, runner: Runner, config) -> int:
    term = args.term
    common.title(f"Paquets Debian correspondant à « {term} »")
    _, out = runner.query(["apt-cache", "search", "--names-only", term])
    lines = sorted(out.splitlines())
    for line in lines[: args.limit]:
        name, _, desc = line.partition(" - ")
        print(f"  {common.style(name, 'leaf')}  {desc}")
    if len(lines) > args.limit:
        common.info(common.dim(f"… et {len(lines) - args.limit} autres (--limit pour en voir plus)"))
    if not lines:
        common.info("aucun résultat")
    if common.which("flatpak"):
        common.title(f"Applications Flatpak (Flathub) correspondant à « {term} »")
        _, out = runner.query(["flatpak", "search", "--columns=application,name", term], timeout=60)
        flines = [line for line in out.splitlines() if line.strip() and not line.startswith("No matches")]
        for line in flines[: args.limit]:
            app, _, name = line.partition("\t")
            print(f"  {common.style(app, 'leaf')}  {name}")
        if not flines:
            common.info("aucun résultat (ou Flathub non configuré)")
    return 0


def _ids(valeur: str | None) -> set[str] | None:
    return {x.strip() for x in valeur.split(",") if x.strip()} if valeur else None


def _choix_pour(realm, args) -> list | None:
    """--avec / --sans / --seulement : « id » vaut pour chaque royaume, « royaume.id » pour un seul."""
    def pour_moi(ensemble):
        if ensemble is None:
            return None
        ids = {i.split(".", 1)[1] for i in ensemble if i.startswith(realm.name + ".")}
        ids |= {i for i in ensemble if "." not in i and i in {x.id for x in realm.logiciels}}
        return ids
    avec, sans, seulement = (pour_moi(_ids(getattr(args, k, None))) for k in ("avec", "sans", "seulement"))
    if avec is None and sans is None and seulement is None:
        return None
    return realm.choisir(avec=avec, sans=sans, seulement=seulement or None)


def cmd_realm(args, runner: Runner, config) -> int:
    from . import arbre

    all_realms = realms.load_realms()
    action = {"liste": "list", "voir": "show", "ajouter": "add", "retirer": "remove"}.get(
        args.realm_action, args.realm_action) or "list"
    if action == "list":
        flatpaks = realms.installed_flatpaks(runner)
        common.title("Les neuf mondes de l'arbre")
        rows = []
        for realm in all_realms.values():
            st = realms.realm_status(realm, runner, flatpaks)
            nom = realm.title + (" (perso)" if realm.perso else "")
            rows.append((realm.rune or "·", realm.name, nom, realm.surnom or "-", realm.theme or "-", st.label))
        print(common.table(rows, headers=("", "nom", "royaume", "surnom", "domaine", "état")))
        print()
        common.info(common.dim("ygg realm show <nom> : le détail ; ygg realm add <nom> : installer "
                               "(--sans, --avec, --choisir pour la carte) ; ygg realm voyageur : te conseiller."))
        return 0
    if action == "show":
        realm = realms.get_realm(args.name, all_realms)
        st = realms.realm_status(realm, runner)
        common.title(f"{realm.rune} {realm.nom_complet} — {st.label}".strip())
        if realm.rune_nom:
            common.info(common.style(f"Rune {realm.rune_nom} : {realm.rune_sens}.", "gold", "italic"))
        common.info(realm.description)
        print()
        realms.afficher_choix(realm, realm.choisir(), st.installes)
        print()
        common.info(common.dim("✔ installé   ● choisi par défaut   ○ en option (--avec ID)"))
        for x in realm.logiciels:
            print(common.dim(f"      {x.id:<16} " + " ".join(x.apt + x.flatpak + [f'({a})' for a in x.actions])))
        actions = realms.actions_de(realm, realm.choisir())
        if actions:
            print()
            for a in actions:
                common.step("configuration : " + realms.ACTIONS[a][0])
        return 0
    if action == "add":
        if not args.names:
            raise YggError("quel royaume ? ygg realm add muspelheim")
        success = True
        installes = []
        for name in args.names:
            realm = realms.get_realm(name, all_realms)
            ok = realms.add_realm(realm, runner, assume_yes=args.yes, choix=_choix_pour(realm, args),
                                  interactif=args.choisir)
            success &= ok
            installes += [realm.name] if ok else []
        if installes and not runner.dry_run:
            arbre.rafraichir(runner, config)
        return 0 if success else 1
    if action == "remove":
        realm = realms.get_realm(args.name, all_realms)
        ok = realms.remove_realm(realm, runner, assume_yes=args.yes, purge=args.purge)
        if ok and not runner.dry_run:
            arbre.rafraichir(runner, config)
        return 0 if ok else 1
    if action == "voyageur":
        return _voyageur(args, runner, config, all_realms)
    if action == "arbre":
        return arbre.cmd_arbre(args, runner, config)
    if action == "creer":
        return _creer_royaume(args, runner)
    if action == "exporter":
        texte = realms.to_toml(realms.get_realm(args.name, all_realms))
        if args.sortie:
            Path(args.sortie).expanduser().write_text(texte, encoding="utf-8")
            common.ok(f"royaume écrit dans {args.sortie} : partage ce fichier, il s'importe avec "
                      "« ygg realm importer ».")
        else:
            print(texte, end="")
        return 0
    if action == "importer":
        return _importer_royaume(args, all_realms)
    raise YggError(f"action inconnue : {action}")


def _voyageur(args, runner: Runner, config, all_realms) -> int:
    voyageurs = realms.load_voyageurs()
    common.title("Quel voyageur es-tu ?")
    for i, v in enumerate(voyageurs, 1):
        print(f"  {common.style(str(i), 'gold')}  {v.nom:<22} {common.dim(v.description)}")
    reponse = common.ask("Un ou plusieurs numéros (ex. 1 3)")
    choisis = [voyageurs[int(n) - 1].id for n in re.split(r"[\s,]+", reponse)
               if n.isdigit() and 1 <= int(n) <= len(voyageurs)]
    if not choisis:
        common.info("Aucun profil choisi : « ygg realm list » montre tous les royaumes.")
        return 0
    noms = realms.royaumes_pour(choisis, all_realms)
    common.title("Les royaumes qui t'attendent")
    for nom in noms:
        r = all_realms[nom]
        print(f"  {r.rune}  {common.style(r.nom_complet, 'gold')}  {common.dim(r.theme)}")
    if not common.confirm("Les installer (chacun te montrera son contenu avant) ?", default=True,
                          assume_yes=args.yes):
        common.info("Plus tard : ygg realm add " + " ".join(noms))
        return 0
    for nom in noms:
        realms.add_realm(all_realms[nom], runner, assume_yes=args.yes)
    if not runner.dry_run:
        from . import arbre

        arbre.rafraichir(runner, config)
    return 0


def _creer_royaume(args, runner: Runner) -> int:
    from . import entretien

    nom = realms.sans_accents((args.name or "").lower())
    if not realms.NAME_RE.match(nom):
        raise YggError("donne un nom au royaume (minuscules) : ygg realm creer mon-atelier")
    paquets = entretien.ajoutes(runner.query(["apt-mark", "showmanual"])[1].split(), entretien.paquets_de_base())
    _, sortie = runner.query(["flatpak", "list", "--app", "--columns=application,name,installation"])
    flatpaks = [(ident, libelle) for ident, libelle, _ in entretien.parse_flatpak_apps(sortie)]
    if not paquets and not flatpaks:
        raise YggError("tu n'as encore rien installé toi-même : rien à mettre dans ce royaume.")
    realm = realms.royaume_depuis(nom, args.titre or nom.capitalize(), paquets, flatpaks)
    dossier = realms.user_realms_dir()
    chemin = dossier / f"{nom}.toml"
    if chemin.exists() and not common.confirm(f"{chemin} existe : le remplacer ?", assume_yes=args.yes):
        return 1
    dossier.mkdir(parents=True, exist_ok=True)
    chemin.write_text(realms.to_toml(realm), encoding="utf-8")
    common.ok(f"royaume « {realm.title} » créé ({len(realm.logiciels)} logiciels) : {chemin}")
    common.info("Retouche-le à ta guise, puis partage-le : ygg realm exporter " + nom + " -o " + nom + ".toml")
    return 0


def _importer_royaume(args, all_realms) -> int:
    source = Path(args.name or "").expanduser()
    if not source.is_file():
        raise YggError("indique le fichier du royaume : ygg realm importer atelier.toml")
    realm = realms.Realm.from_dict(common.load_toml(source), source=source.name, perso=True)
    if realm.name in all_realms and not all_realms[realm.name].perso:
        raise YggError(f"« {realm.name} » est un royaume d'Yggdrasil : renomme le royaume importé.")
    common.title(f"Importer le royaume « {realm.title} »")
    realms.afficher_choix(realm, realm.choisir())
    for a in realms.actions_de(realm, realm.logiciels):
        common.step("configuration : " + realms.ACTIONS[a][0])
    if not common.confirm("L'ajouter à tes royaumes (rien n'est installé maintenant) ?", default=True,
                          assume_yes=args.yes):
        return 1
    dossier = realms.user_realms_dir()
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"{realm.name}.toml").write_text(realms.to_toml(realm), encoding="utf-8")
    common.ok(f"royaume « {realm.title} » importé : ygg realm add {realm.name}")
    return 0


def cmd_doctor(args, runner: Runner, config) -> int:
    checks = doctor.Doctor(runner).run()
    if args.json:
        print(json.dumps(doctor.to_json(checks), indent=2, ensure_ascii=False))
    else:
        if not args.quiet:
            common.title("Diagnostic Yggdrasil")
        out = doctor.render(checks, quiet=args.quiet)
        if out:
            print(out)
    return doctor.exit_code(checks)


def thumbnails_dir() -> Path:
    return Path.home() / ".cache" / "thumbnails"


def dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def trash_dir() -> Path:
    return common.user_data_dir() / "Trash"


def parse_journal_usage(text: str) -> int:
    """« Archived and active journals take up 1.2G in the file system. » → octets."""
    m = re.search(r"take up ([\d.]+)\s?([KMGT]?)i?B?", text)
    if not m:
        return 0
    return int(float(m.group(1)) * 1024 ** "_KMGT".index(m.group(2) or "_"))


def gros_caches(cache: Path, seuil: int = 200 * 1024 ** 2) -> list[tuple[str, int]]:
    """Les sous-dossiers de ~/.cache qui pèsent plus de `seuil` (hors miniatures)."""
    resultat = []
    try:
        enfants = [p for p in cache.iterdir() if p.is_dir() and not p.is_symlink() and p.name != "thumbnails"]
    except OSError:
        return []
    for p in enfants:
        taille = dir_size(p)
        if taille >= seuil:
            resultat.append((p.name, taille))
    return sorted(resultat, key=lambda x: -x[1])


def cmd_clean(args, runner: Runner, config) -> int:
    """Níðhöggr, le dragon qui ronge les racines mortes : d'abord l'inventaire, puis le festin."""
    from . import materiel, voix

    common.title("Níðhöggr : ce qui pourrit au pied de l'arbre")
    estimations = []
    apt_cache = dir_size(Path("/var/cache/apt/archives"))
    estimations.append(("cache des paquets téléchargés (apt clean)", apt_cache))
    estimations.append(("paquets devenus inutiles (apt autoremove)", None))
    if common.which("journalctl"):
        _, usage = runner.query(["journalctl", "--disk-usage"])
        estimations.append(("journaux système de plus de 14 jours", parse_journal_usage(usage) or None))
    if common.which("flatpak"):
        estimations.append(("runtimes Flatpak inutilisés", None))
    thumbs = thumbnails_dir()
    estimations.append(("miniatures d'images en cache", dir_size(thumbs) if thumbs.is_dir() else 0))
    _, noyaux_out = runner.query(["dpkg-query", "-W", "-f=${Package} ${Status}\n", "linux-image-*"])
    anciens = materiel.kernels_to_remove(materiel.parse_kernels(noyaux_out), os.uname().release)
    if anciens:
        estimations.append((f"anciens noyaux : {', '.join(anciens)}", None))
    corbeille = trash_dir()
    taille_corbeille = dir_size(corbeille) if corbeille.is_dir() else 0
    for libelle, taille in estimations:
        poids = common.dim(f"  ({common.human_size(taille)})") if taille else ""
        common.step(libelle + poids)
    if taille_corbeille:
        suite = "" if args.corbeille else common.dim(" — seulement avec --corbeille (suppression définitive)")
        common.step(f"corbeille : {common.human_size(taille_corbeille)}{suite}")
    gros = gros_caches(Path.home() / ".cache")
    if gros:
        print()
        common.info(common.dim("Gros caches d'applications (non touchés, à vider depuis l'application) :"))
        for nom, taille in gros[:5]:
            common.info(common.dim(f"  ~/.cache/{nom} : {common.human_size(taille)}"))
    if args.analyse:
        return 0
    if not common.confirm("Laisser Níðhöggr ronger tout cela ?", default=True, assume_yes=args.yes):
        return 1
    before = shutil.disk_usage("/").free
    runner.run(["apt-get", "autoremove", "--purge", "-y"], root=True)
    runner.run(["apt-get", "clean"], root=True)
    if common.which("journalctl"):
        runner.run(["journalctl", "--vacuum-time=14d"], root=True, check=False)
    if common.which("flatpak"):
        runner.run(["flatpak", "uninstall", "--system", "--unused", "-y", "--noninteractive"], root=True, check=False)
        runner.run(["flatpak", "uninstall", "--user", "--unused", "-y", "--noninteractive"], check=False)
    if anciens:
        runner.run(["apt-get", "purge", "-y", *[f"linux-image-{v}" for v in anciens]], root=True, check=False)
    liberes_maison = 0
    for dossier, voulu in ((thumbs, True), (corbeille, args.corbeille)):
        if voulu and dossier.is_dir():
            liberes_maison += dir_size(dossier)
            if runner.dry_run:
                print(common.style("  [simulation] ", "magenta") + f"vidage de {dossier}")
            else:
                shutil.rmtree(dossier, ignore_errors=True)
    freed = max(shutil.disk_usage("/").free - before, 0)
    if Path.home().stat().st_dev != os.stat("/").st_dev:
        freed += liberes_maison
    if freed > 1024 ** 2:
        common.ok(f"terminé — environ {common.human_size(freed)} récupérés.")
        voix.annoncer("nidhogg", "festin", config=config, taille=common.human_size(freed))
    else:
        common.ok("terminé.")
        voix.annoncer("nidhogg", "affame", config=config)
    return 0


def cmd_services(args, runner: Runner, config) -> int:
    action = args.svc_action or "list"
    if action == "list":
        _, out = runner.query(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"])
        rows = []
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 5:
                rows.append((parts[0].removesuffix(".service"), parts[4]))
        print(common.table(rows, headers=("service actif", "description")))
        return 0
    if not args.name:
        raise YggError("précise le nom du service.")
    if action == "status":
        return runner.run(["systemctl", "status", "--no-pager", args.name], check=False).returncode
    if action in ("start", "stop", "restart", "enable", "disable"):
        cmd = ["systemctl", action, args.name]
        if action in ("enable", "disable") and args.now:
            cmd.insert(2, "--now")
        runner.run(cmd, root=True)
        common.ok(f"{args.name} : {action} effectué.")
        return 0
    raise YggError(f"action inconnue : {action}")


def cmd_saga(args, runner, config) -> int:
    """La saga : tout ce que les outils Yggdrasil ont fait sur cette machine, pour toi."""
    import datetime as dt
    import shlex

    entries = common.saga_read()
    if args.outil:
        entries = [e for e in entries if e.get("outil") == args.outil]
    if args.jours:
        limit = (dt.datetime.now() - dt.timedelta(days=args.jours)).isoformat(timespec="seconds")
        entries = [e for e in entries if str(e.get("date", "")) >= limit]
    if args.json:
        print(json.dumps(entries[-args.nombre:], indent=1, ensure_ascii=False))
        return 0
    common.title("La saga d'Yggdrasil")
    if not entries:
        common.info("La saga est encore vierge : aucun outil n'a rien modifié.")
        return 0
    rows = []
    for e in entries[-args.nombre:]:
        cmd = shlex.join(str(c) for c in e.get("commande", []))
        if len(cmd) > 70:
            cmd = cmd[:67] + "…"
        result = "ok" if e.get("code") == 0 else f"échec ({e.get('code')})"
        rows.append((str(e.get("date", "")).replace("T", " ")[:16], e.get("outil", "?"),
                     ("admin  " if e.get("admin") else "       ") + cmd, result))
    print(common.table(rows, headers=("date", "outil", "action", "résultat")))
    common.info(common.dim(f"{len(entries)} actions notées dans {common.saga_path()}"))
    return 0


def cmd_welcome(args, runner, config) -> int:
    from . import welcome

    return welcome.main([])


# --------------------------------------------------------------------------
# Analyse des arguments
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common_opts = argparse.ArgumentParser(add_help=False)
    common_opts.add_argument("-y", "--yes", action="store_true", help="valider automatiquement les confirmations")
    common_opts.add_argument("-n", "--dry-run", action="store_true", help="simuler sans rien modifier")
    common_opts.add_argument("-v", "--verbose", action="store_true", help="afficher les commandes exécutées")

    # Les options communes sont placées après la sous-commande : « ygg update -y ».
    parser = argparse.ArgumentParser(
        prog="ygg",
        description="Gestionnaire système d'Yggdrasil.",
        epilog="Outils associés : ygg ai (Mímir), ygg fw (Heimdall), ygg snap (Norns), "
        "ygg stack (Bifröst), ygg new (Brokkr), ygg notify (Ratatoskr).",
    )
    sub = parser.add_subparsers(dest="command", metavar="commande")

    p = sub.add_parser("info", help="résumé du système", parents=[common_opts])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("version", help="version d'Yggdrasil", parents=[common_opts])
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("update", aliases=["upgrade"], help="mettre tout le système à jour", parents=[common_opts])
    p.add_argument("--no-snapshot", action="store_true", help="ne pas créer d'instantané avant")
    p.add_argument("--no-flatpak", action="store_true", help="ignorer les applications Flatpak")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("install", help="installer des paquets Debian ou des applications Flatpak", parents=[common_opts])
    p.add_argument("packages", nargs="+", metavar="paquet")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("remove", help="désinstaller", parents=[common_opts])
    p.add_argument("packages", nargs="+", metavar="paquet")
    p.add_argument("--purge", action="store_true", help="supprimer aussi la configuration")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("search", help="chercher un logiciel (Debian + Flathub)", parents=[common_opts])
    p.add_argument("term")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("realm", aliases=["royaume", "royaumes"], help="les neuf mondes : ensembles de logiciels",
                       parents=[common_opts])
    rsub = p.add_subparsers(dest="realm_action", metavar="action")
    rsub.add_parser("list", aliases=["liste"], help="lister les royaumes", parents=[common_opts])
    r = rsub.add_parser("show", aliases=["voir"], help="détailler un royaume", parents=[common_opts])
    r.add_argument("name")
    r = rsub.add_parser("add", aliases=["ajouter"], help="installer un ou plusieurs royaumes", parents=[common_opts])
    r.add_argument("names", nargs="+", metavar="nom")
    r.add_argument("--avec", help="ajouter des logiciels en option (ex. android,dbeaver)")
    r.add_argument("--sans", help="retirer des logiciels du choix par défaut (ex. heroic,lutris)")
    r.add_argument("--seulement", help="seulement ces logiciels")
    r.add_argument("--choisir", action="store_true", help="cocher les logiciels un par un")
    r = rsub.add_parser("remove", aliases=["retirer"], help="retirer un royaume", parents=[common_opts])
    r.add_argument("name")
    r.add_argument("--purge", action="store_true")
    rsub.add_parser("voyageur", help="« Quel voyageur es-tu ? » : les royaumes qui te correspondent",
                    parents=[common_opts])
    r = rsub.add_parser("arbre", help="l'arbre vivant : une feuille d'or par royaume sur ton fond d'écran",
                        parents=[common_opts])
    r.add_argument("etat", nargs="?", choices=["oui", "non"], help="activer ou couper l'arbre vivant")
    r = rsub.add_parser("creer", help="un royaume fait de ce que tu as installé toi-même", parents=[common_opts])
    r.add_argument("name", metavar="nom")
    r.add_argument("--titre", help="titre affiché")
    r = rsub.add_parser("exporter", help="un royaume dans un fichier, pour le partager", parents=[common_opts])
    r.add_argument("name", metavar="nom")
    r.add_argument("-o", "--sortie", help="fichier (sinon, affiché)")
    r = rsub.add_parser("importer", help="ajouter un royaume reçu en fichier", parents=[common_opts])
    r.add_argument("name", metavar="fichier")
    p.set_defaults(func=cmd_realm)

    p = sub.add_parser("doctor", help="diagnostic de santé", parents=[common_opts])
    p.add_argument("--json", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true", help="n'afficher que les problèmes")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("nettoyer", aliases=["clean", "nidhogg"], help="Níðhöggr : récupérer de l'espace disque",
                       parents=[common_opts])
    p.add_argument("--analyse", action="store_true", help="seulement montrer ce qui serait libéré")
    p.add_argument("--corbeille", action="store_true", help="vider aussi la corbeille (définitif)")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("services", help="gérer les services", parents=[common_opts])
    p.add_argument("svc_action", nargs="?", choices=["list", "status", "start", "stop", "restart", "enable", "disable"])
    p.add_argument("name", nargs="?")
    p.add_argument("--now", action="store_true", help="avec enable/disable : démarrer/arrêter immédiatement")
    p.set_defaults(func=cmd_services)

    p = sub.add_parser("saga", help="le journal de tout ce que les outils ont fait", parents=[common_opts])
    p.add_argument("--outil", help="seulement cet outil (ygg, heimdall, norns…)")
    p.add_argument("--jours", type=int, help="seulement les N derniers jours")
    p.add_argument("--nombre", type=int, default=40, help="nombre d'actions affichées (40)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_saga)
    p = sub.add_parser("welcome", help="ouvrir Hliðskjálf, le Centre", parents=[common_opts])
    p.set_defaults(func=cmd_welcome)

    for module in (materiel, entretien, partage, taches, comptes):
        module.ajouter_commandes(sub, common_opts)
    # Les alias vers les autres outils (ai, fw, snap, stack, new, notify) sont
    # traités avant argparse dans _main : voir DELEGATES.
    return parser


def _main(argv: list[str] | None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in DELEGATES:
        return delegate(DELEGATES[argv[0]], argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        if not argv and sys.stdin.isatty() and sys.stdout.isatty():
            from . import menu

            return menu.boucle(lambda sous: common.run_main(_main, sous))
        parser.print_help()
        return 0
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    return args.func(args, runner, common.load_config())


def main(argv: list[str] | None = None) -> int:
    return common.run_main(_main, argv)


if __name__ == "__main__":
    sys.exit(main())
