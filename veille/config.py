"""Lecture et vérification de la liste des sources (fichier TOML).

Le fichier est vérifié EN ENTIER avant le moindre appel réseau : une faute de
frappe donne un message clair qui liste toutes les erreurs, au lieu d'un
plantage au milieu d'un passage.

Bases techniques :
  - TOML est un format de fichier de réglages lisible par un humain
    (« clé = valeur », sections entre crochets). Python sait le lire sans
    bibliothèque supplémentaire (module `tomllib`).
  - `[[flux]]` (double crochet) veut dire « une entrée de plus dans la liste
    des flux » : chaque bloc décrit une source.

Emplacement : `config/sources.toml` (privé, hors du dépôt) s'il existe, sinon
`config.exemple/sources.toml` (publié, sert d'exemple).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .modeles import Axe, Canal

RACINE = Path(__file__).resolve().parent.parent
CHEMINS = (RACINE / "config" / "sources.toml", RACINE / "config.exemple" / "sources.toml")

AXES = {"IA": Axe.IA, "PUBLIC": Axe.PUBLIC, "CONFIANCE": Axe.CONFIANCE}
_CHAINE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")  # identifiant de chaîne YouTube : « UC » + 22 caractères
_DOMAINE = re.compile(r"^(?=.{4,253}$)([a-z0-9-]+\.)+[a-z]{2,}$")
_ADRESSE = re.compile(r"^[^@\s]+@([a-z0-9-]+\.)+[a-z]{2,}$")


class ErreurConfig(ValueError):
    """La liste des sources contient au moins une erreur (toutes sont listées)."""


@dataclass(frozen=True, slots=True)
class Flux:
    nom: str
    url: str
    axe: Axe
    canal: Canal = Canal.RSS


@dataclass(frozen=True, slots=True)
class Expediteur:
    nom: str
    axe: Axe
    domaine: str = ""  # tout expéditeur de ce domaine (ex. infos.banquedesterritoires.fr)
    adresse: str = ""  # ou une adresse exacte (ex. importai@substack.com, domaine partagé)

    def reconnait(self, expediteur: str) -> bool:
        expediteur = expediteur.lower()
        if self.adresse:
            return expediteur == self.adresse
        domaine = expediteur.rpartition("@")[2]
        return domaine == self.domaine or domaine.endswith("." + self.domaine)


@dataclass(frozen=True, slots=True)
class Reglages:
    fraicheur_jours: int = 7  # une info plus ancienne est ignorée (évite l'avalanche du 1er passage)
    max_par_source: int = 20  # au plus N infos par source et par passage
    gmail_libelle: str = "Veille numérique"
    gmail_jours: int = 3  # profondeur de lecture de la boîte, en jours
    taille_max_octets: int = 5_000_000
    delai_s: float = 20.0


@dataclass(frozen=True, slots=True)
class Config:
    reglages: Reglages
    flux: tuple[Flux, ...] = field(default_factory=tuple)
    expediteurs: tuple[Expediteur, ...] = field(default_factory=tuple)

    def expediteur(self, adresse: str) -> Expediteur | None:
        return next((e for e in self.expediteurs if e.reconnait(adresse)), None)


def url_youtube(chaine_id: str, sans_shorts: bool) -> str:
    """Adresse du flux d'une chaîne. Variante sans Shorts : la playlist « UULF » + fin de l'identifiant."""
    if sans_shorts:
        return f"https://www.youtube.com/feeds/videos.xml?playlist_id=UULF{chaine_id[2:]}"
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={chaine_id}"


def charger(chemin: Path | None = None) -> Config:
    chemin = chemin or next((c for c in CHEMINS if c.exists()), CHEMINS[-1])
    try:
        donnees = tomllib.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError as erreur:
        raise ErreurConfig(f"fichier de sources introuvable : {chemin}") from erreur
    except tomllib.TOMLDecodeError as erreur:
        raise ErreurConfig(f"{chemin.name} n'est pas un TOML valide : {erreur}") from erreur
    return lire(donnees)


def lire(donnees: dict[str, Any]) -> Config:
    erreurs: list[str] = []
    reglages = _reglages(donnees.get("reglages", {}), erreurs)
    flux: list[Flux] = []
    noms: set[str] = set()

    def nom_unique(entree: dict[str, Any], ou: str) -> str:
        nom = str(entree.get("nom", "")).strip()
        if not nom:
            erreurs.append(f"{ou} : « nom » manquant")
        elif nom in noms:
            erreurs.append(f"{ou} : le nom « {nom} » est déjà utilisé")
        noms.add(nom)
        return nom

    def axe_de(entree: dict[str, Any], ou: str) -> Axe:
        cle = str(entree.get("axe", "")).upper()
        if cle not in AXES:
            erreurs.append(f"{ou} : axe « {entree.get('axe', '')} » inconnu (valeurs : {', '.join(AXES)})")
            return Axe.IA
        return AXES[cle]

    for i, entree in enumerate(donnees.get("flux", []), 1):
        ou = f"flux n°{i}"
        nom, axe = nom_unique(entree, ou), axe_de(entree, ou)
        url = str(entree.get("url", "")).strip()
        morceaux = urlsplit(url)
        if morceaux.scheme != "https" or not morceaux.hostname:
            erreurs.append(f"{ou} ({nom}) : l'adresse doit commencer par https:// (reçu « {url} »)")
        flux.append(Flux(nom, url, axe))

    for i, entree in enumerate(donnees.get("youtube", []), 1):
        ou = f"chaîne YouTube n°{i}"
        nom, axe = nom_unique(entree, ou), axe_de(entree, ou)
        chaine = str(entree.get("chaine_id", "")).strip()
        if not _CHAINE.match(chaine):
            erreurs.append(f"{ou} ({nom}) : « chaine_id » doit commencer par UC et faire 24 caractères")
        flux.append(Flux(nom, url_youtube(chaine, bool(entree.get("sans_shorts", False))), axe, Canal.YOUTUBE))

    expediteurs: list[Expediteur] = []
    for i, entree in enumerate(donnees.get("expediteurs", []), 1):
        ou = f"expéditeur n°{i}"
        nom, axe = nom_unique(entree, ou), axe_de(entree, ou)
        domaine = str(entree.get("domaine", "")).strip().lower()
        adresse = str(entree.get("adresse", "")).strip().lower()
        if bool(domaine) == bool(adresse):
            erreurs.append(f"{ou} ({nom}) : indiquer soit « domaine », soit « adresse » (un seul des deux)")
        elif domaine and not _DOMAINE.match(domaine):
            erreurs.append(f"{ou} ({nom}) : domaine « {domaine} » invalide")
        elif adresse and not _ADRESSE.match(adresse):
            erreurs.append(f"{ou} ({nom}) : adresse « {adresse} » invalide")
        expediteurs.append(Expediteur(nom, axe, domaine, adresse))

    if not flux and not expediteurs:
        erreurs.append("aucune source : ajouter au moins un [[flux]], [[youtube]] ou [[expediteurs]]")
    if erreurs:
        raise ErreurConfig("liste des sources invalide :\n- " + "\n- ".join(erreurs))
    return Config(reglages, tuple(flux), tuple(expediteurs))


def _reglages(brut: dict[str, Any], erreurs: list[str]) -> Reglages:
    defaut = Reglages()

    def entier(cle: str, mini: int, maxi: int) -> int:
        valeur = brut.get(cle, getattr(defaut, cle))
        if not isinstance(valeur, int) or isinstance(valeur, bool) or not mini <= valeur <= maxi:
            erreurs.append(f"réglage « {cle} » : un nombre entier entre {mini} et {maxi} est attendu")
            return int(getattr(defaut, cle))
        return valeur

    libelle = str(brut.get("gmail_libelle", defaut.gmail_libelle)).strip()
    if not libelle or '"' in libelle or "\\" in libelle:
        erreurs.append("réglage « gmail_libelle » : nom de libellé vide ou invalide")
        libelle = defaut.gmail_libelle
    return Reglages(
        fraicheur_jours=entier("fraicheur_jours", 1, 60),
        max_par_source=entier("max_par_source", 1, 100),
        gmail_libelle=libelle,
        gmail_jours=entier("gmail_jours", 1, 30),
    )
