#!/usr/bin/env python3
"""Démarre une image ISO (ou un disque) dans QEMU et prend des captures d'écran selon un scénario.

    qemu-shots.py ISO DOSSIER [--uefi] --script "wait:20,shot:menu,key:ret,wait:120,shot:bureau"
    qemu-shots.py - DOSSIER --disque systeme.qcow2 --uefi --efivars vars.fd --script "…"

Étapes : wait:SECONDES, veille:SECONDES (attendre sans laisser la session se verrouiller),
shot:NOM (capture PNG), key:QCODE[+QCODE] (ex. ret, tab, ctrl+alt+t),
type:TEXTE (lettres, chiffres, espaces et « -_.:/|=>*+&@ » ; tient compte du clavier AZERTY),
type-us:TEXTE (même chose en QWERTY, pour GRUB qui n'a pas de disposition chargée),
clic:X:Y (clic gauche, en pixels de l'écran 1920 × 1080), double:X:Y (double clic),
fin:SECONDES (attendre que la machine s'éteigne d'elle-même, au plus SECONDES),
serie:MOTIF:SECONDES (attendre MOTIF dans le journal du port série, avec --serie),
pilote:FICHIER (suivre FICHIER : chaque nouvelle ligne est un scénario exécuté aussitôt,
jusqu'à une ligne « stop » ; pour mettre au point un scénario sur une machine qui tourne).
Une virgule s'écrit « \\, » dans un texte (la virgule sépare les étapes).
Le pilotage passe par QMP (protocole machine de QEMU), sans interface graphique.

Chaque touche est envoyée appui et relâchement dans le même message : sans KVM, la
machine virtuelle est si lente qu'un relâchement envoyé à part arrive parfois après
le délai de répétition du clavier (« sttttatus »).
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import socket
import subprocess
import sys
import time

# Touches physiques (qcodes, positions QWERTY) et modificateurs pour chaque caractère.
AZERTY_LETTERS = {"a": "q", "q": "a", "z": "w", "w": "z", "m": "semicolon"}
AZERTY_SIGNS = {
    " ": ["spc"], "-": ["6"], "_": ["8"], ",": ["m"], ";": ["comma"], ".": ["shift", "comma"],
    ":": ["dot"], "/": ["shift", "dot"], "!": ["slash"], "|": ["alt_r", "6"], "=": ["equal"],
    ">": ["shift", "less"], "<": ["less"], "'": ["4"], '"': ["3"], "*": ["backslash"], "+": ["shift", "equal"], "&": ["1"],
    "@": ["alt_r", "0"], "~": ["alt_r", "2"], "$": ["bracket_right"],
}
QWERTY_SIGNS = {
    " ": ["spc"], "-": ["minus"], "_": ["shift", "minus"], ",": ["comma"], ";": ["semicolon"],
    ".": ["dot"], ":": ["shift", "semicolon"], "/": ["slash"], "!": ["shift", "1"], "|": ["shift", "backslash"],
    "=": ["equal"], ">": ["shift", "dot"], "<": ["shift", "comma"], "'": ["apostrophe"], '"': ["shift", "apostrophe"],
    "*": ["shift", "8"], "+": ["shift", "equal"], "&": ["shift", "7"], "@": ["shift", "2"], "~": ["shift", "grave_accent"],
    "$": ["shift", "4"],
}


def qcodes_for(text: str, layout: str) -> list[list[str]]:
    """Chaque caractère → les touches à presser ensemble (modificateurs d'abord)."""
    keys = []
    for ch in text:
        if ch.isascii() and ch.isalpha():
            code = ch.lower()
            if layout == "fr":
                code = AZERTY_LETTERS.get(code, code)
            keys.append(["shift", code] if ch.isupper() else [code])
        elif ch.isascii() and ch.isdigit():
            # Sur un clavier AZERTY, les chiffres se tapent avec Maj
            keys.append(["shift", ch] if layout == "fr" else [ch])
        elif ch in (AZERTY_SIGNS if layout == "fr" else QWERTY_SIGNS):
            keys.append((AZERTY_SIGNS if layout == "fr" else QWERTY_SIGNS)[ch])
        else:
            raise ValueError(f"caractère non pris en charge : {ch!r}")
    return keys


def press(qmp: "QMP", codes: list[str]) -> None:
    """Appuie puis relâche (dans l'ordre inverse) des touches, en un seul message QMP."""
    def event(code: str, down: bool) -> dict:
        return {"type": "key", "data": {"down": down, "key": {"type": "qcode", "data": code}}}
    events = [event(c, True) for c in codes] + [event(c, False) for c in reversed(codes)]
    qmp.cmd("input-send-event", events=events)


def click(qmp: "QMP", x: int, y: int, xres: int, yres: int, double: bool = False) -> None:
    """Clic gauche à une position de l'écran (tablette USB : coordonnées absolues 0..32767)."""
    move = [{"type": "abs", "data": {"axis": "x", "value": round(x * 32767 / (xres - 1))}},
            {"type": "abs", "data": {"axis": "y", "value": round(y * 32767 / (yres - 1))}}]
    qmp.cmd("input-send-event", events=move)
    time.sleep(0.3)
    for _ in range(2 if double else 1):
        for down in (True, False):
            qmp.cmd("input-send-event", events=[{"type": "btn", "data": {"down": down, "button": "left"}}])
            time.sleep(0.08)


def split_steps(script: str) -> list[str]:
    """Découpe le scénario sur les virgules, sauf « \\, » (virgule dans un texte)."""
    return [s.replace("\0", ",") for s in script.replace("\\,", "\0").split(",")]


class QMP:
    def __init__(self, path: str, timeout: float = 30):
        deadline = time.time() + timeout
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(path)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.3)
        self.stream = self.sock.makefile("rw", encoding="utf-8")
        json.loads(self.stream.readline())  # message d'accueil
        self.cmd("qmp_capabilities")

    def cmd(self, name: str, **arguments):
        request = {"execute": name}
        if arguments:
            request["arguments"] = arguments
        self.stream.write(json.dumps(request) + "\n")
        self.stream.flush()
        while True:
            line = self.stream.readline()
            if not line:
                raise ConnectionError("QMP fermé")
            msg = json.loads(line)
            if "return" in msg:
                return msg["return"]
            if "error" in msg:
                raise RuntimeError(f"{name} : {msg['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("iso", help="l'image ISO, ou « - » pour démarrer sur --disque ou --cle")
    parser.add_argument("outdir")
    parser.add_argument("--uefi", action="store_true", help="démarrer en UEFI (OVMF)")
    parser.add_argument("--memory", default="4096")
    parser.add_argument("--cpus", default="4")
    parser.add_argument("--layout", default="fr", choices=["fr", "us"], help="disposition clavier de la VM")
    parser.add_argument("--resolution", default="1920x1080", help="définition annoncée par l'écran (EDID)")
    parser.add_argument("--serie", help="fichier où recopier le port série de la machine (console, journaux)")
    parser.add_argument("--disque", help="disque système (qcow2 ou brut) : on démarre dessus sans ISO (« - »)")
    parser.add_argument("--cle", help="image brute branchée comme clé USB (on démarre dessus sans ISO)")
    parser.add_argument("--efivars", help="variables UEFI persistantes (copie de OVMF_VARS, créée au besoin)")
    parser.add_argument("--frappe", type=float, default=0.12,
                        help="secondes entre deux touches (plus lent pour une machine chargée)")
    parser.add_argument("--clavier-virtio", action="store_true",
                        help="clavier virtio en plus du PS/2 (voir plus bas : pas pour GRUB ni l'initramfs)")
    parser.add_argument("--script", required=True)
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    sock = f"/tmp/qmp-{os.getpid()}.sock"
    xres, _, yres = args.resolution.partition("x")
    media = []
    if args.iso != "-":
        media += ["-cdrom", args.iso]
    if args.disque:
        fmt = "qcow2" if args.disque.endswith(".qcow2") else "raw"
        media += ["-drive", f"file={args.disque},if=virtio,format={fmt},cache=unsafe"]
    media += ["-boot", "d" if args.iso != "-" else "c"]
    # La clé USB se branche sur le contrôleur, déclaré après les disques : leur place sur le
    # bus PCI ne change pas d'un démarrage à l'autre (les entrées UEFI s'en souviennent)
    cle = []
    if args.cle:
        cle = ["-drive", f"file={args.cle},if=none,id=cle,format=raw,cache=unsafe",
               "-device", "usb-storage,drive=cle,bootindex=0"]
    cmd = [
        "qemu-system-x86_64", "-accel", "tcg,thread=multi", "-cpu", "max",
        "-smp", args.cpus, "-m", args.memory, *media,
        # Tablette USB : le pointeur suit des coordonnées absolues (étapes clic:X:Y)
        "-device", "qemu-xhci", *cle, "-device", "usb-tablet",
        # Carte VGA standard qui annonce un écran 1920 × 1080 (EDID) : le bureau
        # s'affiche dans cette définition, comme sur un vrai moniteur. 64 Mo de mémoire
        # vidéo : avec les 16 Mo par défaut, deux images 1920 × 1080 ne tiennent pas (écran noir).
        "-vga", "none", "-device", f"VGA,edid=on,vgamem_mb=64,xres={xres},yres={yres}", "-display", "none",
        "-qmp", f"unix:{sock},server=on,wait=off",
        # Un second accès QMP (/tmp/qmp-regard-<pid>.sock, dans le conteneur), pour regarder
        # la machine pendant une longue attente : qmp_capabilities puis screendump
        "-qmp", f"unix:/tmp/qmp-regard-{os.getpid()}.sock,server=on,wait=off",
        "-nic", "user,model=virtio-net-pci",
        "-no-reboot",
    ]
    if args.clavier_virtio:
        # Sa file d'attente est bien plus longue que celle du clavier PS/2 émulé, qui perd des
        # touches quand une machine très chargée tarde à les lire. Mais le pilote virtio du
        # micrologiciel UEFI perd la touche Entrée (dans GRUB), et un initramfs sans pilote
        # virtio n'entend plus rien : à réserver à une session déjà démarrée.
        cmd += ["-device", "virtio-keyboard-pci"]
    if args.uefi and args.efivars:
        # Micrologiciel en deux parties : le code (lecture seule) et les variables, gardées
        # d'un démarrage à l'autre (l'entrée de démarrage créée par l'installateur y vit)
        if not os.path.exists(args.efivars):
            with open("/usr/share/OVMF/OVMF_VARS_4M.fd", "rb") as src, open(args.efivars, "wb") as dst:
                dst.write(src.read())
        cmd += ["-drive", "if=pflash,format=raw,unit=0,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd",
                "-drive", f"if=pflash,format=raw,unit=1,file={args.efivars}"]
    elif args.uefi:
        cmd += ["-bios", "/usr/share/ovmf/OVMF.fd"]
    if args.serie:
        cmd += ["-serial", f"file:{args.serie}"]
    print("$ " + " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd)
    start = time.time()
    try:
        qmp = QMP(sock)
        etapes = collections.deque(split_steps(args.script))
        lu = 0  # position dans le fichier du pilote
        while etapes:
            step = etapes.popleft()
            kind, _, value = step.lstrip().partition(":")
            if proc.poll() is not None:
                if any(e.lstrip().startswith("fin:") for e in [step, *etapes]):
                    # Une extinction était attendue plus loin (fin d'installation) : c'est réussi
                    print(f"[{time.time() - start:5.0f} s] machine éteinte (code {proc.returncode})", flush=True)
                    return 0
                print(f"QEMU s'est arrêté (code {proc.returncode})", file=sys.stderr)
                return 1
            if kind == "wait":
                time.sleep(float(value))
            elif kind == "veille":
                # Attendre sans que la session se verrouille : Maj (qui n'écrit rien) chaque minute
                fin_veille = time.time() + float(value)
                while time.time() < fin_veille and proc.poll() is None:
                    time.sleep(min(60.0, max(0.0, fin_veille - time.time())))
                    if proc.poll() is None:
                        press(qmp, ["shift"])
            elif kind == "shot":
                path = os.path.join(args.outdir, value + ".png")
                qmp.cmd("screendump", filename=path, format="png")
                print(f"[{time.time() - start:5.0f} s] capture : {path}", flush=True)
            elif kind == "key":
                press(qmp, value.split("+"))
                print(f"[{time.time() - start:5.0f} s] touche : {value}", flush=True)
            elif kind in ("clic", "double"):
                x, _, y = value.partition(":")
                click(qmp, int(x), int(y), int(xres), int(yres), double=kind == "double")
                print(f"[{time.time() - start:5.0f} s] {kind} : {x}, {y}", flush=True)
            elif kind == "fin":
                try:
                    proc.wait(timeout=float(value))
                except subprocess.TimeoutExpired:
                    print(f"la machine tourne encore après {value} s", file=sys.stderr)
                    return 1
                print(f"[{time.time() - start:5.0f} s] machine éteinte (code {proc.returncode})", flush=True)
                return 0
            elif kind == "serie":
                motif, _, delai = value.rpartition(":")
                limite = time.time() + float(delai)
                prochaine_vue = time.time() + 600
                while motif not in (open(args.serie, errors="replace").read() if args.serie else ""):
                    if time.time() > limite or proc.poll() is not None:
                        print(f"« {motif} » absent du port série après {delai} s", file=sys.stderr)
                        return 1
                    if time.time() > prochaine_vue:
                        # Pendant une longue attente, l'écran du moment (remplacé toutes les 10 min)
                        qmp.cmd("screendump", filename=os.path.join(args.outdir, "attente.png"), format="png")
                        prochaine_vue = time.time() + 600
                    time.sleep(5)
                print(f"[{time.time() - start:5.0f} s] série : {motif}", flush=True)
            elif kind in ("type", "type-us"):
                # type-us : saisie là où aucune disposition n'est chargée (GRUB, micrologiciel)
                for codes in qcodes_for(value, "us" if kind == "type-us" else args.layout):
                    press(qmp, codes)
                    time.sleep(args.frappe)
                print(f"[{time.time() - start:5.0f} s] saisie : {value}", flush=True)
            elif kind == "pilote":
                # La prochaine ligne complète du fichier : ses étapes, puis on revient écouter
                while True:
                    texte = open(value, encoding="utf-8").read() if os.path.exists(value) else ""
                    if "\n" in texte[lu:]:
                        ligne = texte[lu:].split("\n", 1)[0]
                        lu += len(ligne) + 1
                        break
                    if proc.poll() is not None:
                        return 1
                    time.sleep(1)
                ligne = ligne.strip()
                print(f"[{time.time() - start:5.0f} s] pilote : {ligne}", flush=True)
                if ligne and ligne != "stop":
                    etapes.extendleft(reversed([*split_steps(ligne), step]))
            else:
                raise ValueError(f"étape inconnue : {step}")
        qmp.cmd("quit")
    finally:
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        if os.path.exists(sock):
            os.unlink(sock)
    return 0


if __name__ == "__main__":
    sys.exit(main())
