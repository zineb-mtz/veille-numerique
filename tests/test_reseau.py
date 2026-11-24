import gzip

import httpx
import pytest

from veille.reseau import ErreurReseau, telecharger

from .conftest import faux_sites

URL = "https://exemple.fr/flux.xml"


def test_telechargement_et_validateurs():
    session = faux_sites({URL: httpx.Response(200, content=b"<rss/>", headers={"ETag": '"v1"'})})
    reponse = telecharger(session, URL)
    assert reponse.contenu == b"<rss/>" and reponse.etag == '"v1"'


def test_requete_conditionnelle_304():
    def site(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(304) if requete.headers.get("If-None-Match") == '"v1"' else httpx.Response(200)

    assert telecharger(faux_sites({URL: site}), URL, etag='"v1"').inchangee


def test_taille_maximale_apres_decompression():
    bombe = gzip.compress(b"a" * 200_000)  # petit une fois compressé, gros une fois ouvert
    session = faux_sites({URL: httpx.Response(200, content=bombe, headers={"Content-Encoding": "gzip"})})
    with pytest.raises(ErreurReseau, match="volumineuse"):
        telecharger(session, URL, taille_max=100_000)


def test_taille_annoncee_trop_grande():
    session = faux_sites({URL: httpx.Response(200, content=b"x", headers={"Content-Length": "999999999"})})
    with pytest.raises(ErreurReseau, match="volumineuse"):
        telecharger(session, URL)


def test_redirection_vers_http_refusee():
    session = faux_sites(
        {
            URL: httpx.Response(301, headers={"Location": "http://exemple.fr/clair"}),
            "http://exemple.fr/clair": httpx.Response(200, content=b"x"),
        }
    )
    with pytest.raises(ErreurReseau, match="non chiffrée"):
        telecharger(session, URL)


def test_erreur_definitive():
    with pytest.raises(ErreurReseau, match="404"):
        telecharger(faux_sites({}), URL)


def test_panne_passagere_une_seule_nouvelle_tentative():
    appels = []

    def site(requete: httpx.Request) -> httpx.Response:
        appels.append(1)
        return httpx.Response(503) if len(appels) == 1 else httpx.Response(200, content=b"ok")

    assert telecharger(faux_sites({URL: site}), URL, attente_s=0).contenu == b"ok"
    assert len(appels) == 2


def test_panne_persistante():
    with pytest.raises(ErreurReseau, match="503"):
        telecharger(faux_sites({URL: httpx.Response(503)}), URL, attente_s=0)
