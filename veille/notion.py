"""Rangement dans la base Notion « Veille numérique » (la boîte de veille).

Colonnes attendues (noms exacts) : Titre (titre) · Lien (URL) · Source (sélection)
· Canal (sélection) · Axe (sélection) · Publié le (date) · Collecté le (date)
· Extrait (texte) · Statut (sélection) · Identifiant (texte).

Pour une lettre d'information, le texte complet et la liste des liens cités
vont dans le corps de la page. Ce contenu reste privé : il n'est jamais republié.

Ce module est isolé exprès : le jour de la migration vers Obsidian, seul ce
fichier sera remplacé (décision D5).

Bases techniques :
  - Notion se pilote par une API web : on envoie une page décrite en JSON
    (un format texte de données) à une adresse, avec la clé de l'intégration.
  - Une intégration Notion ne voit que les pages et bases qu'on lui a
    partagées (menu « … » de la base, puis « Connexions »).
  - Notion accepte environ 3 requêtes par seconde ; au-delà, il répond 429
    « trop de requêtes » avec un délai d'attente, que le robot respecte.
"""

from __future__ import annotations

import os
import re
import time

import httpx

from .modeles import Fiche
from .texte import masquer

API_PAGES = "https://api.notion.com/v1/pages"
VERSION = "2022-06-28"
TAILLE_TEXTE = 1900  # Notion refuse plus de 2000 caractères par bloc de texte
MAX_BLOCS = 100  # et plus de 100 blocs par envoi
PAUSE_S = 0.35  # environ 3 requêtes par seconde
STATUT_INITIAL = "À lire"


class ErreurNotion(RuntimeError):
    pass


def jeton() -> str:
    """La clé Notion, nettoyée des erreurs de copier-coller (« Bearer », espaces, retours à la ligne)."""
    valeur = re.sub(r"^\s*bearer\s+", "", os.environ.get("NOTION_TOKEN", ""), flags=re.I)
    return re.sub(r"[\s\"'«»]", "", valeur)


def identifiant_base() -> str:
    """Les 32 caractères hexadécimaux de la base, même si on a collé son adresse complète."""
    valeur = os.environ.get("NOTION_BASE_ID", "").strip()
    if "notion" in valeur:
        valeur = valeur.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    # L'identifiant est à la FIN (« Veille-0123…cdef ») : chercher au début prendrait le « e » de « Veille ».
    trouve = re.search(r"[0-9a-f]{32}$", valeur.replace("-", ""), re.I)
    return trouve.group(0).lower() if trouve else ""


def configure() -> bool:
    return bool(jeton() and identifiant_base())


def _texte(valeur: str) -> list[dict[str, object]]:
    return [{"text": {"content": valeur[:TAILLE_TEXTE]}}] if valeur else []


def _paragraphe(valeur: str) -> dict[str, object]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _texte(valeur)}}


def _titre(valeur: str) -> dict[str, object]:
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": _texte(valeur)}}


def _puce_lien(adresse: str) -> dict[str, object]:
    texte = {"text": {"content": adresse[:TAILLE_TEXTE], "link": {"url": adresse}}}
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [texte]}}


def _morceaux(texte: str) -> list[str]:
    """Découpe un long texte en blocs de moins de 1900 caractères, sur les fins de ligne si possible."""
    blocs, courant = [], ""
    for ligne in texte.splitlines():
        while len(ligne) > TAILLE_TEXTE:
            blocs.append(ligne[:TAILLE_TEXTE])
            ligne = ligne[TAILLE_TEXTE:]
        if len(courant) + len(ligne) + 1 > TAILLE_TEXTE:
            blocs.append(courant)
            courant = ""
        courant = f"{courant}\n{ligne}" if courant else ligne
    if courant:
        blocs.append(courant)
    return blocs


def page(fiche: Fiche, base_id: str) -> dict[str, object]:
    """La page Notion d'une fiche (fonction pure, testée sans réseau)."""
    proprietes: dict[str, object] = {
        "Titre": {"title": _texte(fiche.titre)},
        "Lien": {"url": fiche.lien or None},
        # Notion refuse les virgules dans une option de sélection.
        "Source": {"select": {"name": fiche.source.replace(",", " ")[:100]}},
        "Canal": {"select": {"name": fiche.canal.value}},
        "Axe": {"select": {"name": fiche.axe.value}},
        "Collecté le": {"date": {"start": fiche.collecte_le.date().isoformat()}},
        "Extrait": {"rich_text": _texte(fiche.extrait)},
        "Statut": {"select": {"name": STATUT_INITIAL}},
        "Identifiant": {"rich_text": _texte(fiche.identifiant)},
    }
    if fiche.a_retenir:
        proprietes["À retenir"] = {"rich_text": _texte(fiche.a_retenir)}
        # Range l'info dans l'onglet « Hors sujet » de Notion plutôt que dans « À lire ».
        proprietes["Hors sujet"] = {"checkbox": fiche.a_retenir.lower().startswith("hors sujet")}
    if fiche.publie_le:
        proprietes["Publié le"] = {"date": {"start": fiche.publie_le.isoformat()}}

    blocs: list[dict[str, object]] = []
    if fiche.texte:
        blocs.append(_titre("Texte reçu (privé, ne pas republier tel quel)"))
        blocs += [_paragraphe(m) for m in _morceaux(fiche.texte)]
    elif fiche.extrait:
        blocs.append(_paragraphe(fiche.extrait))
    if fiche.liens_cites:
        place = MAX_BLOCS - len(blocs) - 1
        if place > 0:
            blocs.append(_titre("Liens cités (non ouverts par le robot)"))
            blocs += [_puce_lien(lien) for lien in fiche.liens_cites[:place]]
    if len(blocs) > MAX_BLOCS:
        blocs = blocs[: MAX_BLOCS - 1] + [_paragraphe("… texte tronqué : voir l'e-mail d'origine (colonne Lien).")]
    return {"parent": {"database_id": base_id}, "properties": proprietes, "children": blocs}


class Boite:
    """La boîte de veille dans Notion. `session` est un client httpx (simulable dans les tests)."""

    def __init__(self, session: httpx.Client, base_id: str | None = None, pause_s: float = PAUSE_S) -> None:
        self.session = session
        self.base_id = base_id or identifiant_base()
        self.pause_s = pause_s

    def ranger(self, fiche: Fiche) -> None:
        entetes = {"Authorization": f"Bearer {jeton()}", "Notion-Version": VERSION}
        for tentative in range(4):
            reponse = self.session.post(API_PAGES, json=page(fiche, self.base_id), headers=entetes)
            if reponse.status_code == 429 and tentative < 3:
                attente = reponse.headers.get("Retry-After", "1")
                time.sleep(min(float(attente) if attente.replace(".", "", 1).isdigit() else 1.0, 30.0))
                continue
            if reponse.is_error:
                droits = reponse.status_code in {401, 403, 404}
                aide = " : vérifier que la base est partagée avec l'intégration" if droits else ""
                raise ErreurNotion(
                    masquer(
                        f"Notion a refusé « {fiche.titre[:60]} » ({reponse.status_code}){aide} : {reponse.text[:200]}"
                    )
                )
            time.sleep(self.pause_s)
            return
        raise ErreurNotion("Notion répond « trop de requêtes » de façon répétée")
