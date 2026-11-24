"""Lecture des flux RSS et Atom (dont les flux de chaînes YouTube).

Bases techniques :
  - Un flux RSS ou Atom est un fichier XML que le site met à jour seul : la
    liste de ses dernières publications (titre, lien, date, résumé).
  - XML est un format à balises, comme le HTML. Un fichier XML piégé peut
    déclarer des « entités » qui se recopient en cascade et saturent la mémoire.
    On le lit donc avec defusedxml, qui refuse ces déclarations (DTD).
  - RSS (2.0 ou 1.0) et Atom sont deux formats concurrents. Les balises sont
    lues par leur nom « local » (sans l'espace de noms), ce qui couvre les deux.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as SafeET
from defusedxml import DefusedXmlException

from ..config import Flux
from ..modeles import Fiche, extrait
from ..texte import en_date, html_vers_texte, nettoyer_lien


class FluxIllisible(ValueError):
    pass


def _local(balise: str) -> str:
    """« {http://www.w3.org/2005/Atom}entry » -> « entry »."""
    return balise.rsplit("}", 1)[-1]


def _enfants(element: Element, nom: str) -> list[Element]:
    return [e for e in element if _local(e.tag) == nom]


def _texte(element: Element, *noms: str) -> str:
    """Texte du premier enfant qui porte l'un des noms (cherché aussi un niveau plus bas, ex. media:group)."""
    for nom in noms:
        for enfant in element.iter():
            valeur = (enfant.text or "").strip()
            if enfant is not element and _local(enfant.tag) == nom and valeur:
                return valeur
    return ""


def _lien(element: Element) -> str:
    """RSS : <link>adresse</link>. Atom : <link rel="alternate" href="…"/>.

    Repli : <guid> quand il contient une adresse (le flux de Hugging Face met
    l'adresse de l'article dans <guid> et pas dans <link>).
    """
    for lien in _enfants(element, "link"):
        href = lien.get("href")
        if href and lien.get("rel", "alternate") == "alternate":
            return href.strip()
        texte = (lien.text or "").strip()
        if texte:
            return texte
    for guid in _enfants(element, "guid") + _enfants(element, "id"):
        valeur = (guid.text or "").strip()
        if valeur.startswith(("http://", "https://")):
            return valeur
    return ""


def _entrees(racine: Element) -> Iterable[Element]:
    return (e for e in racine.iter() if _local(e.tag) in {"item", "entry"})


def lire(contenu: bytes, flux: Flux, collecte_le: datetime, fraicheur_jours: int, maximum: int) -> list[Fiche]:
    """Transforme le contenu d'un flux en fiches (fonction pure, sans réseau)."""
    try:
        racine = SafeET.fromstring(contenu, forbid_dtd=True)
    except (DefusedXmlException, SafeET.ParseError) as erreur:
        raise FluxIllisible(f"{flux.nom} : flux XML illisible ou refusé ({type(erreur).__name__})") from erreur
    if _local(racine.tag) not in {"rss", "feed", "RDF"}:
        raise FluxIllisible(f"{flux.nom} : ce n'est pas un flux RSS ou Atom (balise racine « {_local(racine.tag)} »)")

    limite: date = (collecte_le - timedelta(days=fraicheur_jours)).date()
    fiches: list[Fiche] = []
    for entree in _entrees(racine):
        lien = nettoyer_lien(_lien(entree))
        titre = " ".join(_texte(entree, "title").split())
        if not lien or not titre:
            continue  # lien dangereux ou entrée vide : ignorée
        publie_le = en_date(_texte(entree, "pubDate", "published", "updated", "date"))
        if publie_le and publie_le < limite:
            continue
        resume_html = _texte(entree, "description", "summary", "encoded", "content")
        resume, _ = html_vers_texte(resume_html)
        fiches.append(
            Fiche(
                titre=titre,
                lien=lien,
                source=flux.nom,
                canal=flux.canal,
                axe=flux.axe,
                publie_le=publie_le,
                collecte_le=collecte_le,
                extrait=extrait(resume),
                cle=lien,
            )
        )
    # Certains flux ne sont pas triés par date (OpenAI) : on trie nous-mêmes, plus récent d'abord.
    fiches.sort(key=lambda f: f.publie_le or date.min, reverse=True)
    return fiches[:maximum]
