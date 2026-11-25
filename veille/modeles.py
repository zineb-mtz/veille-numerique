"""Le format commun : chaque info collectée devient une « fiche brute ».

Toutes les sources (flux RSS, chaînes YouTube, lettres d'information) produisent
ce même objet. Le reste du robot (doublons, Notion, bilan) n'a donc jamais
besoin de savoir d'où vient une info.

Bases techniques :
  - Une « dataclass » est une classe Python qui sert surtout à ranger des
    données nommées (comme une ligne de tableau), avec des types déclarés.
  - `frozen=True` rend l'objet non modifiable après création : une fiche ne
    change pas en cours de route, ce qui évite des erreurs difficiles à suivre.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class Canal(StrEnum):
    RSS = "RSS"
    YOUTUBE = "YouTube"
    LETTRE = "Lettre d'info"


class Axe(StrEnum):
    """Les trois axes de veille, adaptés au secteur public (décision D2)."""

    IA = "IA et innovation"
    PUBLIC = "Numérique public"
    CONFIANCE = "Confiance et cadre"


TAILLE_EXTRAIT = 500


@dataclass(frozen=True, slots=True)
class Fiche:
    titre: str
    lien: str  # adresse nettoyée (sans paramètres de suivi) ; vide pour une lettre sans lien web
    source: str  # nom lisible : « Mistral AI », « Localtis »…
    canal: Canal
    axe: Axe
    publie_le: date | None
    collecte_le: datetime
    extrait: str = ""
    texte: str = ""  # texte complet, gardé en privé (corps de la page Notion), jamais republié
    liens_cites: tuple[str, ...] = field(default_factory=tuple)  # liens trouvés dans une lettre, jamais ouverts
    cle: str = ""  # identité stable de l'info, sert au dédoublonnage
    a_retenir: str = ""  # phrase « À retenir » écrite par Mistral (facultatif, voir resume.py)

    @property
    def identifiant(self) -> str:
        """Empreinte courte et stable : la même info donne toujours le même identifiant.

        SHA-256 est une fonction qui transforme un texte en une suite de caractères
        de longueur fixe ; deux textes différents ne donnent (en pratique) jamais
        la même empreinte. On garde les 16 premiers caractères, largement assez ici.
        """
        base = self.cle or self.lien or f"{self.source}|{self.titre}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def extrait(texte: str, taille: int = TAILLE_EXTRAIT) -> str:
    """Les `taille` premiers caractères, coupés sur un mot entier."""
    texte = " ".join(texte.split())
    if len(texte) <= taille:
        return texte
    coupe = texte[:taille].rsplit(" ", 1)[0]
    return f"{coupe}…"
