"""Petits outils de texte partagés : liens, dates, HTML, titres, secrets.

Toutes ces fonctions sont « pures » : elles ne lisent ni réseau ni fichier,
ce qui les rend faciles à tester.
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Paramètres d'adresse qui ne servent qu'à pister les clics (Google Analytics,
# Mailchimp, HubSpot, Facebook, AT Internet…). Les retirer donne une adresse
# stable : la même page n'apparaît plus deux fois sous deux adresses.
_PISTAGE = re.compile(r"^(utm_.*|mc_cid|mc_eid|fbclid|gclid|_hsenc|_hsmi|mkt_tok|xtor|at_.*|ref_src)$", re.I)


def lien_sur(adresse: str) -> bool:
    """Vrai seulement pour une vraie adresse web (http ou https, avec un nom de site).

    Écarte « javascript: », « data: », « file: »… qu'un flux piégé pourrait contenir.
    """
    try:
        morceaux = urlsplit(adresse.strip())
    except ValueError:
        return False
    return morceaux.scheme in {"http", "https"} and bool(morceaux.hostname)


def nettoyer_lien(adresse: str) -> str:
    """Adresse sans paramètres de pistage ni ancre (#…). Vide si l'adresse n'est pas sûre."""
    adresse = adresse.strip()
    if not lien_sur(adresse):
        return ""
    morceaux = urlsplit(adresse)
    gardes = [(k, v) for k, v in parse_qsl(morceaux.query, keep_blank_values=True) if not _PISTAGE.match(k)]
    return urlunsplit((morceaux.scheme, morceaux.netloc.lower(), morceaux.path, urlencode(gardes), ""))


def normaliser_titre(titre: str) -> str:
    """« L'IA dans les Collectivités ! » -> « l ia dans les collectivites ».

    Minuscules, accents retirés, ponctuation remplacée par des espaces : deux
    titres qui ne diffèrent que par la typographie deviennent identiques.
    """
    sans_accents = unicodedata.normalize("NFKD", titre).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", sans_accents.lower()))


def en_date(valeur: str | None) -> date | None:
    """Lit une date de flux : format e-mail (RSS, « Tue, 24 Nov 2026 08:00:00 GMT ») ou ISO 8601 (Atom)."""
    if not valeur:
        return None
    valeur = valeur.strip()
    try:
        return parsedate_to_datetime(valeur).date()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(valeur.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def maintenant() -> datetime:
    return datetime.now(UTC)


class _LecteurHTML(HTMLParser):
    """Transforme du HTML en texte lisible et relève les liens, dans l'ordre."""

    BLOCS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article"}
    IGNORES = {"script", "style", "head", "title", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.morceaux: list[str] = []
        self.liens: list[str] = []
        self._ignore = 0

    def handle_starttag(self, balise: str, attributs: list[tuple[str, str | None]]) -> None:
        if balise in self.IGNORES:
            self._ignore += 1
        elif balise == "a":
            adresse = dict(attributs).get("href") or ""
            if lien_sur(adresse):
                self.liens.append(adresse)
        elif balise in self.BLOCS:
            self.morceaux.append("\n")

    def handle_endtag(self, balise: str) -> None:
        if balise in self.IGNORES and self._ignore:
            self._ignore -= 1
        elif balise in self.BLOCS:
            self.morceaux.append("\n")

    def handle_data(self, donnees: str) -> None:
        if not self._ignore:
            self.morceaux.append(donnees)


def html_vers_texte(html: str) -> tuple[str, list[str]]:
    """(texte lisible, liens http(s) trouvés). Aucun lien n'est ouvert."""
    lecteur = _LecteurHTML()
    lecteur.feed(html)
    lecteur.close()
    lignes = (" ".join(ligne.split()) for ligne in "".join(lecteur.morceaux).splitlines())
    return "\n".join(ligne for ligne in lignes if ligne), lecteur.liens


_SECRETS = ("NOTION_TOKEN", "GMAIL_APP_PASSWORD", "GMAIL_USER", "MISTRAL_API_KEY")


def masquer(texte: str) -> str:
    """Remplace par *** toute valeur secrète qui se serait glissée dans un message d'erreur."""
    for variable in _SECRETS:
        valeur = os.environ.get(variable, "").strip()
        if len(valeur) >= 6:
            texte = texte.replace(valeur, "***")
            texte = texte.replace(valeur.replace(" ", ""), "***")
    return texte
