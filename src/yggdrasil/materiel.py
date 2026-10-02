"""Le matériel : inventaire, pilotes, énergie, démarrage et noyaux.

    ygg materiel                 processeur, mémoire, cartes graphiques, disques (santé SMART),
                                 températures et batterie
    ygg pilotes [installer]      pilotes et micrologiciels manquants (NVIDIA, Wi-Fi…)
    ygg energie [profil]         profil d'énergie : performance, equilibre, economie
    ygg energie limite 80        la batterie s'arrête de charger à 80 % (portable souvent branché)
    ygg demarrage [delai N]      ce qui ralentit le démarrage ; délai du menu GRUB
    ygg noyaux [nettoyer|recent] noyaux Linux installés ; retirer les anciens ; noyau des rétroportages

Les fonctions d'analyse (parse_*) sont pures : elles prennent la sortie des
commandes système et sont testées sans matériel.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import common, sysinfo
from .common import Runner, YggError

# --------------------------------------------------------------------------
# Inventaire
# --------------------------------------------------------------------------


@dataclass
class Disque:
    nom: str
    taille: str
    modele: str
    rotatif: bool
    transport: str
    sante: str = ""  # « bonne », « DÉFAILLANTE », ou vide si inconnue


def parse_lsblk(text: str) -> list[Disque]:
    """Sortie de « lsblk -J -d -o NAME,SIZE,MODEL,ROTA,TRAN,TYPE » → disques physiques."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    disques = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk" or str(dev.get("name", "")).startswith(("loop", "zram", "ram")):
            continue
        rota = dev.get("rota")
        disques.append(Disque(
            nom=str(dev.get("name", "")),
            taille=str(dev.get("size") or "?"),
            modele=str(dev.get("model") or "").strip() or "modèle inconnu",
            rotatif=rota in (True, 1, "1", "true"),
            transport=str(dev.get("tran") or "").strip(),
        ))
    return disques


def parse_smart_health(text: str) -> str:
    """Sortie de « smartctl -H » → « bonne », « DÉFAILLANTE » ou ""."""
    for line in text.splitlines():
        if "overall-health" in line or "SMART Health Status" in line:
            verdict = line.split(":", 1)[-1].strip().upper()
            return "bonne" if verdict in ("PASSED", "OK") else "DÉFAILLANTE"
    return ""


def parse_sensors(text: str) -> list[tuple[str, float]]:
    """Sortie de « sensors -j » → [(capteur, °C)], la plus haute valeur de chaque puce."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    temperatures = []
    for puce, contenu in data.items():
        if not isinstance(contenu, dict):
            continue
        valeurs = []
        for capteur in contenu.values():
            if isinstance(capteur, dict):
                valeurs += [v for k, v in capteur.items()
                            if k.startswith("temp") and k.endswith("_input") and isinstance(v, (int, float))]
        if valeurs:
            temperatures.append((puce.split("-")[0], float(max(valeurs))))
    return temperatures


def thermal_zones(base: Path = Path("/sys/class/thermal")) -> list[tuple[str, float]]:
    """Repli sans lm-sensors : les zones thermiques du noyau."""
    zones = []
    for zone in sorted(base.glob("thermal_zone*")):
        try:
            milli = int(common.read_text(zone / "temp").strip())
        except ValueError:
            continue
        nom = common.read_text(zone / "type").strip() or zone.name
        if milli > 0:
            zones.append((nom, milli / 1000))
    return zones


@dataclass
class Batterie:
    nom: str
    charge: int
    etat: str
    usure: int | None  # capacité restante par rapport à la neuve, en %


ETATS_BATTERIE = {"Charging": "en charge", "Discharging": "sur batterie", "Full": "pleine",
                  "Not charging": "branchée, pas en charge", "Unknown": "état inconnu"}


def batteries(base: Path = Path("/sys/class/power_supply")) -> list[Batterie]:
    resultat = []
    for bat in sorted(base.glob("BAT*")):
        lire = lambda nom: common.read_text(bat / nom).strip()  # noqa: E731
        try:
            charge = int(lire("capacity") or 0)
        except ValueError:
            charge = 0
        usure = None
        for plein, neuf in (("energy_full", "energy_full_design"), ("charge_full", "charge_full_design")):
            try:
                usure = round(100 * int(lire(plein)) / int(lire(neuf)))
                break
            except (ValueError, ZeroDivisionError):
                continue
        etat = lire("status")
        resultat.append(Batterie(bat.name, charge, ETATS_BATTERIE.get(etat, etat or "?"), usure))
    return resultat


def cmd_materiel(args, runner: Runner, config) -> int:
    info = sysinfo.collect(runner)
    common.title("Le corps de l'arbre : ton matériel")
    print(f"  {common.style('Processeur', 'gold')}  {info['cpu']} ({info['cores']} cœurs)")
    if info["mem_total"]:
        libre = common.human_size(info["mem_available"])
        print(f"  {common.style('Mémoire', 'gold')}     {common.human_size(info['mem_total'])} ({libre} disponibles)")
    for gpu in info["gpus"] or ["aucune carte graphique détectée"]:
        print(f"  {common.style('Graphique', 'gold')}   {gpu}")

    common.title("Disques")
    _, out = runner.query(["lsblk", "-J", "-d", "-o", "NAME,SIZE,MODEL,ROTA,TRAN,TYPE"])
    disques = parse_lsblk(out)
    smart = common.which("smartctl") or Path("/usr/sbin/smartctl").exists()
    for d in disques:
        if smart and common.is_root():
            _, sortie = runner.query(["smartctl", "-H", f"/dev/{d.nom}"], timeout=20)
            d.sante = parse_smart_health(sortie)
    rows = [(d.nom, d.taille, d.modele, "disque dur" if d.rotatif else "SSD",
             d.transport or "-", d.sante or "-") for d in disques]
    print(common.table(rows, headers=("disque", "taille", "modèle", "type", "liaison", "santé")))
    if not smart:
        common.info(common.dim("santé des disques : installe smartmontools (ygg install smartmontools)."))
    elif not common.is_root():
        common.info(common.dim("santé des disques : relance avec sudo pour lire les données SMART."))
    if any(d.sante == "DÉFAILLANTE" for d in disques):
        common.warn("un disque annonce une défaillance : sauvegarde tes données sans attendre (norns backup).")

    common.title("Températures")
    _, out = runner.query(["sensors", "-j"]) if common.which("sensors") else (1, "")
    temps = parse_sensors(out) or thermal_zones()
    if temps:
        for nom, valeur in temps:
            couleur = "red" if valeur >= 90 else "yellow" if valeur >= 75 else "green"
            print(f"  {nom:<16} {common.style(f'{valeur:.0f} °C', couleur)}")
    else:
        common.info("aucun capteur lisible (machine virtuelle ?)")

    bats = batteries()
    if bats:
        common.title("Batterie")
        for b in bats:
            usure = f", capacité {b.usure} % de la neuve" if b.usure is not None else ""
            print(f"  {b.nom}  {b.charge} % — {b.etat}{usure}")
            if b.usure is not None and b.usure < 70:
                common.warn(f"{b.nom} est usée ({b.usure} %) : l'autonomie a nettement baissé.")
    return 0


# --------------------------------------------------------------------------
# Pilotes et micrologiciels
# --------------------------------------------------------------------------

@dataclass
class Peripherique:
    classe: str
    vendeur: str  # identifiant PCI, ex. 10de
    produit: str
    libelle: str


LSPCI_RE = re.compile(r"^\S+\s+(?P<classe>.+?)\s\[[0-9a-f]{4}\]:\s(?P<libelle>.+?)\s\[(?P<v>[0-9a-f]{4}):(?P<p>[0-9a-f]{4})\]")


def parse_lspci_nn(text: str) -> list[Peripherique]:
    """Sortie de « lspci -nn » → périphériques avec identifiants PCI."""
    resultat = []
    for line in text.splitlines():
        m = LSPCI_RE.match(line)
        if m:
            resultat.append(Peripherique(m["classe"], m["v"], m["p"], m["libelle"]))
    return resultat


FIRMWARE_RE = re.compile(r"(?:firmware: failed to load|Direct firmware load for)\s+(\S+?)(?:\s|$)")

# Préfixe du fichier de micrologiciel manquant → paquet Debian qui le fournit
FIRMWARE_PAQUETS = (
    ("iwlwifi", "firmware-iwlwifi"),
    ("intel/ibt", "firmware-iwlwifi"),
    ("rtw88", "firmware-realtek"), ("rtw89", "firmware-realtek"), ("rtl", "firmware-realtek"),
    ("ath", "firmware-atheros"), ("qca", "firmware-atheros"),
    ("brcm", "firmware-brcm80211"),
    ("mediatek", "firmware-mediatek"), ("mt7", "firmware-mediatek"),
    ("amdgpu", "firmware-amd-graphics"), ("radeon", "firmware-amd-graphics"),
    ("i915", "firmware-intel-graphics"), ("xe/", "firmware-intel-graphics"),
    ("nvidia", "firmware-nvidia-graphics"),
    ("bnx2", "firmware-bnx2"), ("tigon", "firmware-misc-nonfree"),
    ("intel/sof", "firmware-sof-signed"), ("intel/avs", "firmware-intel-sound"),
)


def parse_missing_firmware(text: str) -> list[str]:
    """Journal du noyau → fichiers de micrologiciel que le noyau n'a pas trouvés."""
    vus: list[str] = []
    for m in FIRMWARE_RE.finditer(text):
        fichier = m.group(1).rstrip(",")
        if fichier not in vus:
            vus.append(fichier)
    return vus


def firmware_package(fichier: str) -> str:
    for prefixe, paquet in FIRMWARE_PAQUETS:
        if fichier.startswith(prefixe):
            return paquet
    return "firmware-misc-nonfree"


@dataclass
class Conseil:
    paquets: list[str]
    raison: str
    composantes: list[str] = field(default_factory=list)  # composantes Debian nécessaires


def recommandations(peripheriques: list[Peripherique], firmwares: list[str]) -> list[Conseil]:
    conseils = []
    graphiques = [p for p in peripheriques if any(m in p.classe for m in ("VGA", "3D", "Display"))]
    for p in graphiques:
        if p.vendeur == "10de":
            conseils.append(Conseil(["nvidia-driver", "firmware-misc-nonfree"],
                                    f"carte NVIDIA ({p.libelle}) : le pilote propriétaire est bien plus "
                                    "rapide que nouveau pour jouer et pour l'IA (CUDA)",
                                    ["contrib", "non-free", "non-free-firmware"]))
        elif p.vendeur == "1002":
            conseils.append(Conseil(["firmware-amd-graphics", "mesa-vulkan-drivers"],
                                    f"carte AMD ({p.libelle}) : micrologiciel et Vulkan", ["non-free-firmware"]))
        elif p.vendeur == "8086":
            conseils.append(Conseil(["intel-media-va-driver-non-free"],
                                    f"graphique Intel ({p.libelle}) : décodage vidéo matériel complet",
                                    ["non-free"]))
    manquants: dict[str, list[str]] = {}
    for fichier in firmwares:
        manquants.setdefault(firmware_package(fichier), []).append(fichier)
    for paquet, fichiers in manquants.items():
        extrait = ", ".join(fichiers[:3]) + (" …" if len(fichiers) > 3 else "")
        conseils.append(Conseil([paquet], f"micrologiciel manquant au démarrage : {extrait}", ["non-free-firmware"]))
    return conseils


SOURCES = Path("/etc/apt/sources.list.d/debian.sources")


def components_of(sources: str) -> set[str]:
    comps: set[str] = set()
    for line in sources.splitlines():
        if line.lower().startswith("components:"):
            comps.update(line.split(":", 1)[1].split())
    return comps


def add_components(sources: str, extra: list[str]) -> str:
    """Ajoute des composantes (contrib, non-free…) à chaque bloc deb822, sans doublon."""
    lignes = []
    for line in sources.splitlines():
        if line.lower().startswith("components:"):
            actuelles = line.split(":", 1)[1].split()
            line = "Components: " + " ".join(actuelles + [c for c in extra if c not in actuelles])
        lignes.append(line)
    return "\n".join(lignes) + ("\n" if sources.endswith("\n") else "")


def pilotes_manquants(runner: Runner) -> list[Conseil]:
    """Les pilotes et micrologiciels conseillés pour ce matériel qui ne sont pas installés."""
    _, lspci = runner.query(["lspci", "-nn"])
    _, noyau = runner.query(["journalctl", "-k", "-b", "--no-pager", "-o", "cat"], timeout=30)
    if not noyau:
        _, noyau = runner.query(["dmesg"])
    a_installer = []
    for c in recommandations(parse_lspci_nn(lspci), parse_missing_firmware(noyau)):
        _, etat = runner.query(["dpkg-query", "-W", "-f=${Status}\n", *c.paquets])
        installes = etat.count("install ok installed")
        if installes < len(c.paquets):
            a_installer.append(c)
    return a_installer


def cmd_pilotes(args, runner: Runner, config) -> int:
    a_installer = pilotes_manquants(runner)

    common.title("Pilotes et micrologiciels")
    if not a_installer:
        common.ok("tout le matériel détecté a ses pilotes.")
        return 0
    for c in a_installer:
        print(f"  {common.style(' '.join(c.paquets), 'leaf')}")
        common.info(c.raison)
    if args.action != "installer":
        print()
        common.info(common.dim("« ygg pilotes installer » pour les installer (après confirmation)."))
        return 0

    besoin = sorted({comp for c in a_installer for comp in c.composantes})
    sources = common.read_text(SOURCES)
    manque = [c for c in besoin if c not in components_of(sources)]
    if manque and sources:
        common.warn("ces pilotes viennent des composantes Debian « " + " ".join(manque) + " » (logiciels non libres).")
        if not common.confirm("Les activer dans les sources APT ?", assume_yes=args.yes):
            return 1
        runner.run(["cp", str(SOURCES), f"{SOURCES}.avant-pilotes"], root=True)
        runner.write_file(SOURCES, add_components(sources, manque), root=True)
        runner.run(["apt-get", "update"], root=True)
    paquets = [p for c in a_installer for p in c.paquets]
    if not common.confirm(f"Installer {', '.join(paquets)} ?", default=True, assume_yes=args.yes):
        return 1
    cmd = ["apt-get", "install", *paquets]
    if args.yes:
        cmd.insert(2, "-y")
    runner.run(cmd, root=True)
    common.warn("redémarre pour que les nouveaux pilotes soient chargés.")
    return 0


# --------------------------------------------------------------------------
# Énergie
# --------------------------------------------------------------------------

PROFILS = {"performance": "performance", "equilibre": "balanced", "economie": "power-saver"}
PROFILS_NOMS = {v: k for k, v in PROFILS.items()}
PROFILS_TEXTE = {
    "performance": "tout pour la puissance (jeu, compilation, IA)",
    "equilibre": "le bon compromis, par défaut",
    "economie": "autonomie maximale, ventilateurs discrets",
}


LIMITE_TMPFILES = Path("/etc/tmpfiles.d/yggdrasil-batterie.conf")


def seuils_de_charge(base: Path = Path("/sys/class/power_supply")) -> dict[str, Path]:
    """Les batteries dont le micrologiciel accepte une limite de charge."""
    return {bat.name: bat / "charge_control_end_threshold"
            for bat in sorted(base.glob("BAT*")) if (bat / "charge_control_end_threshold").exists()}


def tmpfiles_limite(seuils: dict[str, Path], limite: int) -> str:
    """Règle systemd-tmpfiles qui réapplique la limite à chaque démarrage."""
    lignes = ["# Écrit par « ygg energie limite » : la batterie s'arrête de charger à ce pourcentage"]
    lignes += [f"w {chemin} - - - - {limite}" for chemin in seuils.values()]
    return "\n".join(lignes) + "\n"


def cmd_limite(args, runner: Runner) -> int:
    seuils = seuils_de_charge()
    if not seuils:
        raise YggError("cette machine ne permet pas de limiter la charge de la batterie (ou n'en a pas).")
    if args.valeur is None:
        for nom, chemin in seuils.items():
            common.info(f"{nom} : charge jusqu'à {common.read_text(chemin).strip() or '?'} %")
        common.info(common.dim("ygg energie limite 80 : ménage la batterie d'un portable souvent branché."))
        return 0
    limite = 100 if args.valeur in ("aucune", "100") else int(args.valeur) if str(args.valeur).isdigit() else -1
    if not 50 <= limite <= 100:
        raise YggError("limite entre 50 et 100 %, ou « aucune ».")
    for chemin in seuils.values():
        runner.run(["tee", str(chemin)], root=True, input=f"{limite}\n", capture=True)
    if limite == 100:
        runner.run(["rm", "-f", str(LIMITE_TMPFILES)], root=True)
        common.ok("plus de limite : la batterie charge jusqu'au bout.")
    else:
        runner.write_file(LIMITE_TMPFILES, tmpfiles_limite(seuils, limite), root=True)
        common.ok(f"la batterie s'arrêtera de charger à {limite} % (réglage gardé au redémarrage).")
    return 0


def cmd_energie(args, runner: Runner, config) -> int:
    if args.profil == "limite":
        return cmd_limite(args, runner)
    if not common.which("powerprofilesctl"):
        raise YggError("power-profiles-daemon n'est pas installé (ygg install power-profiles-daemon).")
    if args.profil:
        if args.profil not in PROFILS:
            raise YggError(f"profil inconnu « {args.profil} » : {', '.join(PROFILS)}")
        runner.run(["powerprofilesctl", "set", PROFILS[args.profil]])
        common.ok(f"profil d'énergie : {args.profil} — {PROFILS_TEXTE[args.profil]}.")
        return 0
    _, actuel = runner.query(["powerprofilesctl", "get"])
    _, liste = runner.query(["powerprofilesctl", "list"])
    actuel = PROFILS_NOMS.get(actuel.strip(), actuel.strip() or "?")
    common.title("Énergie")
    for nom, texte in PROFILS_TEXTE.items():
        disponible = PROFILS[nom] in liste or not liste
        marque = common.style("●", "gold") if nom == actuel else "○"
        suffixe = "" if disponible else common.dim(" (non pris en charge par ce matériel)")
        print(f"  {marque} {nom:<12} {texte}{suffixe}")
    seuils = seuils_de_charge()
    for b in batteries():
        print()
        limite = common.read_text(seuils[b.nom]).strip() if b.nom in seuils else ""
        suite = f", charge limitée à {limite} %" if limite and limite != "100" else ""
        common.info(f"{b.nom} : {b.charge} %, {b.etat}{suite}")
    print()
    common.info(common.dim("ygg energie <profil> pour changer ; ygg energie limite 80 pour ménager la batterie."))
    return 0


# --------------------------------------------------------------------------
# Démarrage
# --------------------------------------------------------------------------

def parse_analyze_time(text: str) -> dict[str, float]:
    """« Startup finished in 3.2s (firmware) + 2.1s (loader) + 1.9s (kernel) + 8.4s (userspace) = 15.6s »."""
    etapes = {}
    for valeur, nom in re.findall(r"([\d.]+(?:min)?\s?[\d.]*m?s)\s\((\w+)\)", text):
        etapes[nom] = _secondes(valeur)
    total = re.search(r"=\s*([\d.]+(?:min)?\s?[\d.]*m?s)", text)
    if total:
        etapes["total"] = _secondes(total.group(1))
    return etapes


def _secondes(valeur: str) -> float:
    total = 0.0
    for nombre, unite in re.findall(r"([\d.]+)\s?(min|ms|s)", valeur):
        total += float(nombre) * {"min": 60, "s": 1, "ms": 0.001}[unite]
    return round(total, 3)


def parse_blame(text: str, limite: int = 10) -> list[tuple[str, float]]:
    """Sortie de « systemd-analyze blame » → [(unité, secondes)], les plus lentes d'abord."""
    resultat = []
    for line in text.splitlines():
        # « 1min 2.345s foo.service » : la durée peut avoir deux morceaux
        m = re.match(r"^((?:[\d.]+min\s)?[\d.]+m?s)\s+(\S+)$", line.strip())
        if m:
            resultat.append((m.group(2), _secondes(m.group(1))))
    return resultat[:limite]


def lire_desktop(texte: str) -> dict[str, str]:
    """La section [Desktop Entry] d'un fichier .desktop."""
    valeurs: dict[str, str] = {}
    dans = False
    for line in texte.splitlines():
        line = line.strip()
        if line.startswith("["):
            dans = line == "[Desktop Entry]"
        elif dans and "=" in line and not line.startswith("#"):
            cle, _, valeur = line.partition("=")
            valeurs.setdefault(cle.strip(), valeur.strip())
    return valeurs


def applis_au_demarrage(systeme: Path, utilisateur: Path, bureau: str = "KDE") -> list[tuple[str, str, bool]]:
    """(nom, fichier, actif) des applications lancées à l'ouverture de session.

    Un fichier de l'utilisateur remplace celui du système qui porte le même nom.
    """
    fichiers: dict[str, Path] = {}
    for dossier in (systeme, utilisateur):
        for p in sorted(dossier.glob("*.desktop")):
            fichiers[p.name] = p
    resultat = []
    for nom_fichier, chemin in sorted(fichiers.items()):
        d = lire_desktop(common.read_text(chemin))
        seulement = [b for b in d.get("OnlyShowIn", "").split(";") if b]
        jamais = [b for b in d.get("NotShowIn", "").split(";") if b]
        actif = (d.get("Hidden", "false").lower() != "true"
                 and d.get("X-GNOME-Autostart-enabled", "true").lower() != "false"
                 and (not seulement or bureau in seulement) and bureau not in jamais)
        resultat.append((d.get("Name", nom_fichier.removesuffix(".desktop")), nom_fichier, actif))
    return resultat


GRUB_DELAI = Path("/etc/default/grub.d/90-yggdrasil-delai.cfg")


def cmd_demarrage(args, runner: Runner, config) -> int:
    if args.action == "delai":
        if args.valeur is None or not 0 <= args.valeur <= 60:
            raise YggError("indique un délai entre 0 et 60 secondes : ygg demarrage delai 3")
        runner.write_file(GRUB_DELAI, f"# Écrit par « ygg demarrage delai »\nGRUB_TIMEOUT={args.valeur}\n", root=True)
        runner.run(["update-grub"], root=True)
        common.ok(f"le menu de démarrage attendra {args.valeur} s.")
        return 0
    _, temps = runner.query(["systemd-analyze", "time"])
    _, blame = runner.query(["systemd-analyze", "blame", "--no-pager"])
    etapes = parse_analyze_time(temps)
    common.title("Le réveil de l'arbre : durée du démarrage")
    noms = {"firmware": "micrologiciel (BIOS/UEFI)", "loader": "chargeur (GRUB)", "kernel": "noyau Linux",
            "initrd": "initrd", "userspace": "services du système"}
    for cle, libelle in noms.items():
        if cle in etapes:
            print(f"  {libelle:<28} {etapes[cle]:6.1f} s")
    if "total" in etapes:
        print(f"  {common.style('total', 'gold'):<28} {etapes['total']:6.1f} s")
    lents = parse_blame(blame)
    if lents:
        common.title("Les services les plus lents")
        for nom, duree in lents:
            print(f"  {duree:6.1f} s  {nom}")
        if lents[0][0].startswith("NetworkManager-wait-online") and lents[0][1] > 5:
            common.info(common.dim("NetworkManager-wait-online attend le réseau : sans montage réseau, "
                                   "« sudo systemctl disable NetworkManager-wait-online » le supprime."))
    applis = [a for a in applis_au_demarrage(Path("/etc/xdg/autostart"), common.user_config_dir().parent / "autostart")
              if a[2]]
    if applis:
        common.title("Lancées à l'ouverture de session")
        for nom, fichier, _ in applis:
            print(f"  {nom:<40} {common.dim(fichier)}")
        common.info(common.dim("Pour en retirer : Configuration du système → Démarrage automatique."))
    print()
    common.info(common.dim("ygg demarrage delai N : durée d'affichage du menu GRUB."))
    return 0


# --------------------------------------------------------------------------
# Noyaux
# --------------------------------------------------------------------------

def parse_kernels(text: str) -> list[str]:
    """Sortie de « dpkg-query -W -f='${Package} ${Status}\\n' 'linux-image-*' » → versions installées."""
    versions = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[-1] == "installed" and parts[0].startswith("linux-image-"):
            version = parts[0].removeprefix("linux-image-")
            if re.match(r"^\d", version) and not version.endswith("-dbg"):
                versions.append(version)
    return sorted(versions, key=version_key)


def version_key(version: str) -> list:
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-+~]", version)]


def kernels_to_remove(installes: list[str], courant: str, garder: int = 2) -> list[str]:
    """Les anciens noyaux : jamais celui en cours, toujours les `garder` plus récents."""
    tries = sorted(installes, key=version_key)
    gardes = set(tries[-garder:]) | {courant}
    return [v for v in tries if v not in gardes]


BACKPORTS = Path("/etc/apt/sources.list.d/yggdrasil-backports.sources")


def backports_source(suite: str) -> str:
    return (f"# Rétroportages Debian (logiciels plus récents, dont le noyau) — ajouté par « ygg noyaux recent »\n"
            f"Types: deb\nURIs: http://deb.debian.org/debian/\nSuites: {suite}-backports\n"
            f"Components: main contrib non-free non-free-firmware\n"
            f"Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\n")


def cmd_noyau_recent(args, runner: Runner) -> int:
    from . import DEBIAN_BASE

    suite = f"{DEBIAN_BASE}-backports"
    common.title("Un noyau plus récent (rétroportages Debian)")
    common.info("Utile pour du matériel très récent que le noyau de Debian stable ne connaît pas encore.")
    common.warn("un pilote NVIDIA propriétaire ou un module externe (DKMS) peut ne pas suivre : "
                "l'ancien noyau reste installé et choisissable dans le menu de démarrage.")
    if not common.confirm(f"Installer le noyau de {suite} ?", assume_yes=args.yes):
        return 1
    _, sources = runner.query(["grep", "-rhs", f"{suite}", "/etc/apt/sources.list", "/etc/apt/sources.list.d"])
    if suite not in sources:
        runner.write_file(BACKPORTS, backports_source(DEBIAN_BASE), root=True)
    runner.run(["apt-get", "update"], root=True)
    runner.run(["apt-get", "install", "-y", "-t", suite, "linux-image-amd64"], root=True)
    common.ok("noyau récent installé : il sera utilisé au prochain démarrage.")
    return 0


def cmd_noyaux(args, runner: Runner, config) -> int:
    if args.action == "recent":
        return cmd_noyau_recent(args, runner)
    _, out = runner.query(["dpkg-query", "-W", "-f=${Package} ${Status}\n", "linux-image-*"])
    installes = parse_kernels(out)
    courant = os.uname().release
    anciens = kernels_to_remove(installes, courant, args.garder)
    common.title("Noyaux Linux")
    for v in installes:
        marque = common.style("● en cours", "gold") if v == courant else (
            common.dim("ancien") if v in anciens else "")
        print(f"  {v:<28} {marque}")
    if args.action != "nettoyer":
        if anciens:
            common.info(common.dim(f"« ygg noyaux nettoyer » retire {len(anciens)} ancien(s) noyau(x)."))
        return 0
    if not anciens:
        common.ok("rien à retirer.")
        return 0
    if not common.confirm(f"Retirer {', '.join(anciens)} ?", assume_yes=args.yes):
        return 1
    runner.run(["apt-get", "purge", "-y", *[f"linux-image-{v}" for v in anciens]], root=True)
    common.ok(f"{len(anciens)} noyau(x) retiré(s).")
    return 0


def ajouter_commandes(sub, common_opts) -> None:
    """Déclare les sous-commandes de ce module dans l'analyseur de « ygg »."""
    p = sub.add_parser("materiel", aliases=["hw"], help="inventaire du matériel (disques, températures, batterie)",
                       parents=[common_opts])
    p.set_defaults(func=cmd_materiel)
    p = sub.add_parser("pilotes", aliases=["drivers"], help="pilotes et micrologiciels manquants",
                       parents=[common_opts])
    p.add_argument("action", nargs="?", choices=["installer"])
    p.set_defaults(func=cmd_pilotes)
    p = sub.add_parser("energie", help="profil d'énergie (performance, equilibre, economie), limite de charge",
                       parents=[common_opts])
    p.add_argument("profil", nargs="?", help="performance, equilibre, economie, ou « limite »")
    p.add_argument("valeur", nargs="?", help="avec « limite » : pourcentage (50 à 100) ou « aucune »")
    p.set_defaults(func=cmd_energie)
    p = sub.add_parser("demarrage", aliases=["boot"], help="durée du démarrage, délai du menu GRUB",
                       parents=[common_opts])
    p.add_argument("action", nargs="?", choices=["delai"])
    p.add_argument("valeur", nargs="?", type=int)
    p.set_defaults(func=cmd_demarrage)
    p = sub.add_parser("noyaux", aliases=["kernels"], help="noyaux installés, retirer les anciens",
                       parents=[common_opts])
    p.add_argument("action", nargs="?", choices=["nettoyer", "recent"])
    p.add_argument("--garder", type=int, default=2, help="nombre de noyaux récents à garder (2)")
    p.set_defaults(func=cmd_noyaux)
