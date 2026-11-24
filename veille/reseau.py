"""Requêtes web polies et sûres.

Règles appliquées à chaque téléchargement :
  - délai maximal (20 s) : un site lent ne bloque pas le passage ;
  - taille maximale vérifiée APRÈS décompression : un flux compressé piégé
    (« bombe de décompression ») ne peut pas remplir la mémoire ;
  - https obligatoire, y compris après une redirection ;
  - un robot qui se présente honnêtement (pas d'imitation de navigateur) ;
  - requête conditionnelle : on dit au site ce qu'on a déjà vu (ETag,
    Last-Modified) ; s'il répond 304 « rien de neuf », rien n'est téléchargé ;
  - une seule nouvelle tentative, en cas de panne passagère.

Les sources sont lues l'une après l'autre : jamais plus d'une requête à la fois
vers un même site.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .texte import masquer

AGENT = "veille-numerique/0.1 (robot de veille personnel ; +https://github.com/zineb-mtz)"
PANNES_PASSAGERES = {429, 500, 502, 503, 504}


class ErreurReseau(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Reponse:
    statut: int
    contenu: bytes = b""
    etag: str = ""
    modifie_le: str = ""

    @property
    def inchangee(self) -> bool:
        return self.statut == 304


def client(delai_s: float = 20.0, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Client HTTP commun. `transport` permet aux tests de simuler les sites, sans réseau."""
    return httpx.Client(
        timeout=httpx.Timeout(delai_s),
        follow_redirects=True,
        max_redirects=5,
        headers={"User-Agent": AGENT, "Accept-Encoding": "gzip, deflate"},
        transport=transport,
    )


def telecharger(
    session: httpx.Client,
    url: str,
    *,
    etag: str = "",
    modifie_le: str = "",
    taille_max: int = 5_000_000,
    attente_s: float = 2.0,
) -> Reponse:
    entetes = {}
    if etag:
        entetes["If-None-Match"] = etag
    if modifie_le:
        entetes["If-Modified-Since"] = modifie_le
    derniere: Exception | None = None
    for tentative in range(2):
        try:
            return _une_fois(session, url, entetes, taille_max)
        except _Passagere as erreur:
            derniere = erreur
            if tentative == 0:
                time.sleep(attente_s)
    raise ErreurReseau(masquer(f"{url} : {derniere}"))


class _Passagere(Exception):
    pass


def _une_fois(session: httpx.Client, url: str, entetes: dict[str, str], taille_max: int) -> Reponse:
    try:
        with session.stream("GET", url, headers=entetes) as reponse:
            if urlsplit(str(reponse.url)).scheme != "https":
                raise ErreurReseau(f"{url} : redirigé vers une adresse non chiffrée ({reponse.url})")
            if reponse.status_code == 304:
                return Reponse(
                    304, etag=reponse.headers.get("ETag", ""), modifie_le=reponse.headers.get("Last-Modified", "")
                )
            if reponse.status_code in PANNES_PASSAGERES:
                raise _Passagere(f"le site a répondu {reponse.status_code}")
            if reponse.is_error:
                raise ErreurReseau(f"{url} : le site a répondu {reponse.status_code}")
            annonce = reponse.headers.get("Content-Length", "")
            if annonce.isdigit() and int(annonce) > taille_max:
                raise ErreurReseau(f"{url} : réponse trop volumineuse ({annonce} octets)")
            morceaux, total = [], 0
            for morceau in reponse.iter_bytes():  # iter_bytes = contenu DÉJÀ décompressé
                total += len(morceau)
                if total > taille_max:
                    raise ErreurReseau(f"{url} : réponse trop volumineuse (plus de {taille_max} octets)")
                morceaux.append(morceau)
            return Reponse(
                reponse.status_code,
                b"".join(morceaux),
                reponse.headers.get("ETag", ""),
                reponse.headers.get("Last-Modified", ""),
            )
    except (httpx.TimeoutException, httpx.TransportError) as erreur:
        raise _Passagere(f"{type(erreur).__name__}") from erreur
    except httpx.TooManyRedirects as erreur:
        raise ErreurReseau(f"{url} : trop de redirections") from erreur
    except httpx.DecodingError as erreur:
        raise ErreurReseau(f"{url} : contenu compressé illisible") from erreur
