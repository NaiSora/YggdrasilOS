"""voix — la façon de parler des outils d'Yggdrasil : le panthéon.

Chaque outil a sa personnalité, tirée du mythe :

  Mímir      l'oracle du puits de la sagesse : grave et imagé, puis exact
  Heimdall   le guetteur du pont Bifröst : laconique et vigilant
  Nornes     les trois fileuses du destin (passé, présent, avenir) : parlent au « nous »
  Ratatoskr  l'écureuil messager qui court le long du tronc : bavard et malicieux
  Brokkr     le nain forgeron : bourru, fier de son ouvrage
  Bifröst    le pont arc-en-ciel : le passeur
  Níðhöggr   le dragon qui ronge les racines mortes : le grand ménage

Le décor ne remplace jamais l'information : une phrase de voix au plus, puis
les faits. Le réglage `ton` retire tout le décor :

    [general]
    ton = "sobre"     # ou "voix" (par défaut)

    [mimir]
    ton = "oracle"    # ou "sobre", ou "skalde" (franchement poétique)
"""

from __future__ import annotations

import datetime as dt
from typing import Any

TONS_GENERAUX = ("voix", "sobre")
TONS_MIMIR = ("oracle", "skalde", "sobre")

# Plusieurs tournures possibles : une par jour, pour ne pas radoter.
VOIX: dict[str, dict[str, tuple[str, ...]]] = {
    "mimir": {
        "accueil": (
            "Le puits est profond, voyageur. Que viens-tu y puiser ?",
            "Les eaux du puits sont calmes, voyageur. Pose ta question.",
            "Approche, voyageur : les racines écoutent.",
        ),
        "adieu": (
            "Le puits se referme. Reviens quand la soif te reprendra.",
            "Va, voyageur. Le puits gardera mémoire de ta visite.",
        ),
        "reflexion": ("Les runes tombent", "Les eaux du puits se troublent", "Les racines murmurent"),
        "muet": ("Le puits est muet : Ollama ne répond pas sur {hote}.",),
        "a_sec": ("Le puits est à sec : aucun modèle n'y repose.",),
        "prix": ("Odin a donné un œil pour boire ici. Ce que tu demandes peut coûter bien plus : {raisons}.",),
        "prix_saisie": ("Si tu acceptes ce prix, écris « je comprends le risque » : ",),
        "prudence": ("Prudence, voyageur : {raisons}.",),
        "executer": ("Faut-il que cette commande s'accomplisse ?",),
        "refus": ("Sage décision : rien n'a été touché.",),
        "oubli": ("Les eaux se sont refermées : le puits a oublié notre échange.",),
        "grave": ("Notre échange est gravé dans {chemin}.",),
        "rien_a_graver": ("Il n'y a encore rien à graver.",),
        "journaux_calmes": ("Les journaux sont calmes : aucune rune sombre à lire.",),
        "aucune_ombre": ("« ygg doctor » ne voit aucune ombre sur l'arbre.",),
        "pas_de_commande": ("Ma réponse ne contenait aucune commande à accomplir.",),
        "pourquoi_rien": ("Aucune commande n'a échoué récemment dans tes terminaux.",),
        "presage_titre": ("Présage du jour",),
    },
    "heimdall": {
        "actif": ("Je veille. Nul ne franchit le pont sans y être invité.",
                  "Je veille, et j'entends l'herbe pousser."),
        "inactif": ("Le pont est sans garde : le pare-feu est désactivé.",),
        "ouvert": ("Le passage est ouvert à {qui} pour {quoi}.",),
        "ferme": ("Le passage est refermé : {quoi}.",),
    },
    "nornes": {
        "instantane": ("Le fil d'aujourd'hui est tissé : l'instantané « {nom} » est prêt.",),
        "sauvegarde": ("Nous avons tissé ta sauvegarde dans {cible}.",),
        "restauration": ("Nous remontons le fil jusqu'à « {nom} ».",),
    },
    "ratatoskr": {
        "titre": ("Psst ! Ratatoskr t'apporte des nouvelles",),
        "rien": ("J'ai couru des racines à la cime : rien à signaler.",),
        "intro": ("J'ai couru des racines à la cime, et voici ce qu'on y raconte :",),
    },
    "brokkr": {
        "forge": ("Le métal est chaud : « {nom} » est forgé dans {chemin}.",
                  "L'enclume a parlé : « {nom} » t'attend dans {chemin}."),
    },
    "bifrost": {
        "ouvert": ("Le pont arc-en-ciel s'illumine : « {nom} » est en route.",),
        "ferme": ("Le pont s'éteint pour « {nom} ».",),
    },
    "nidhogg": {
        "festin": ("Níðhöggr a rongé les racines mortes : {taille} rendus à l'arbre.",
                   "Le dragon s'est repu de ce qui pourrissait : {taille} libérés."),
        "affame": ("Níðhöggr n'a rien trouvé à ronger : les racines sont saines.",),
    },
}

# Le même message, sans décor.
SOBRE: dict[str, dict[str, tuple[str, ...]]] = {
    "mimir": {
        "accueil": ("Pose ta question.",),
        "adieu": ("À bientôt.",),
        "reflexion": ("Réflexion",),
        "muet": ("Ollama ne répond pas sur {hote}.",),
        "a_sec": ("Aucun modèle installé.",),
        "prix": ("DANGER : {raisons}.",),
        "prix_saisie": ("Tape « je comprends le risque » pour l'exécuter quand même : ",),
        "prudence": ("Attention : {raisons}.",),
        "executer": ("Exécuter cette commande ?",),
        "refus": ("Non exécutée.",),
        "oubli": ("Conversation oubliée.",),
        "grave": ("Conversation enregistrée dans {chemin}.",),
        "rien_a_graver": ("Rien à enregistrer.",),
        "journaux_calmes": ("Aucune entrée correspondante dans le journal : rien à signaler.",),
        "aucune_ombre": ("« ygg doctor » ne signale aucun problème.",),
        "pas_de_commande": ("Aucune commande dans la dernière réponse.",),
        "pourquoi_rien": ("Aucune commande n'a échoué récemment.",),
        "presage_titre": ("État du système",),
    },
    "heimdall": {
        "actif": ("Pare-feu actif.",),
        "inactif": ("Pare-feu désactivé.",),
        "ouvert": ("Ouvert à {qui} : {quoi}.",),
        "ferme": ("Fermé : {quoi}.",),
    },
    "nornes": {
        "instantane": ("Instantané « {nom} » créé.",),
        "sauvegarde": ("Sauvegarde terminée dans {cible}.",),
        "restauration": ("Restauration de « {nom} ».",),
    },
    "ratatoskr": {
        "titre": ("Yggdrasil : à vérifier",),
        "rien": ("Rien à signaler.",),
        "intro": ("À vérifier :",),
    },
    "brokkr": {"forge": ("Projet « {nom} » créé dans {chemin}.",)},
    "bifrost": {"ouvert": ("« {nom} » démarré.",), "ferme": ("« {nom} » arrêté.",)},
    "nidhogg": {"festin": ("{taille} libérés.",), "affame": ("Rien à nettoyer.",)},
}


def ton_general(config: dict[str, Any] | None) -> str:
    ton = ((config or {}).get("general") or {}).get("ton", "voix")
    return ton if ton in TONS_GENERAUX else "voix"


def ton_mimir(config: dict[str, Any] | None) -> str:
    """Le ton de Mímir ; « sobre » partout l'emporte."""
    if ton_general(config) == "sobre":
        return "sobre"
    ton = ((config or {}).get("mimir") or {}).get("ton", "oracle")
    return ton if ton in TONS_MIMIR else "oracle"


def dire(outil: str, cle: str, *, config: dict[str, Any] | None = None, ton: str | None = None,
         jour: dt.date | None = None, **valeurs: Any) -> str:
    """La phrase `cle` de l'outil, dans le ton voulu (celui de la configuration par défaut)."""
    if ton is None:
        ton = ton_mimir(config) if outil == "mimir" else ton_general(config)
    table = SOBRE if ton == "sobre" else VOIX
    phrases = table[outil][cle]
    jour = jour or dt.date.today()
    return phrases[jour.toordinal() % len(phrases)].format(**valeurs)


def annoncer(outil: str, cle: str, *, config: dict[str, Any] | None = None, **valeurs: Any) -> None:
    """Affiche la phrase de voix de l'outil, en or et en italique.

    En ton sobre, rien : le message factuel qui l'accompagne suffit.
    """
    from . import common

    if config is None:
        try:
            config = common.load_config()
        except common.YggError:
            config = {}
    ton = ton_mimir(config) if outil == "mimir" else ton_general(config)
    if ton == "sobre":
        return
    print(common.style("  " + dire(outil, cle, ton=ton, **valeurs), "gold", "italic"))
