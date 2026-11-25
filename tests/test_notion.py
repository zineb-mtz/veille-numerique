import json

import httpx
import pytest

from veille import notion
from veille.modeles import Axe, Canal, Fiche

from .conftest import MAINTENANT

FICHE = Fiche(
    "Titre",
    "https://a.fr/1",
    "Mistral AI",
    Canal.RSS,
    Axe.IA,
    MAINTENANT.date(),
    MAINTENANT,
    extrait="Résumé",
    cle="https://a.fr/1",
)


def test_page_colonnes():
    page = notion.page(FICHE, "base")
    proprietes = page["properties"]
    assert proprietes["Statut"] == {"select": {"name": "À lire"}}
    assert proprietes["Canal"] == {"select": {"name": "RSS"}}
    assert proprietes["Publié le"] == {"date": {"start": "2026-11-24"}}
    assert proprietes["Identifiant"]["rich_text"][0]["text"]["content"] == FICHE.identifiant
    assert "À retenir" not in proprietes  # colonne remplie seulement si Mistral a écrit une phrase


def test_page_a_retenir():
    from dataclasses import replace

    proprietes = notion.page(replace(FICHE, a_retenir="Le fait : l'enjeu."), "base")["properties"]
    assert proprietes["À retenir"]["rich_text"][0]["text"]["content"] == "Le fait : l'enjeu."
    assert proprietes["Hors sujet"] == {"checkbox": False}
    hors_sujet = notion.page(replace(FICHE, a_retenir="Hors sujet : robotique."), "base")["properties"]
    assert hors_sujet["Hors sujet"] == {"checkbox": True}


def test_lettre_longue_decoupee_et_bornee():
    lettre = Fiche(
        "Lettre",
        "",
        "Localtis",
        Canal.LETTRE,
        Axe.PUBLIC,
        None,
        MAINTENANT,
        texte="ligne\n" * 60_000,
        liens_cites=tuple(f"https://a.fr/{i}" for i in range(50)),
        cle="mail:1",
    )
    page = notion.page(lettre, "base")
    blocs = page["children"]
    assert len(blocs) <= notion.MAX_BLOCS
    assert all(len(json.dumps(b)) < 4000 for b in blocs)  # aucun bloc au-delà de la limite Notion
    assert page["properties"]["Lien"] == {"url": None}


def test_identifiant_base(monkeypatch):
    monkeypatch.setenv("NOTION_BASE_ID", "https://www.notion.so/moi/Veille-0123456789abcdef0123456789abcdef?v=1")
    assert notion.identifiant_base() == "0123456789abcdef0123456789abcdef"


def test_jeton_nettoye(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "  Bearer ntn_abc\n")
    assert notion.jeton() == "ntn_abc"


def test_ranger_respecte_le_429(monkeypatch):
    appels = []

    def api(requete: httpx.Request) -> httpx.Response:
        appels.append(1)
        return httpx.Response(429, headers={"Retry-After": "0"}) if len(appels) == 1 else httpx.Response(200, json={})

    boite = notion.Boite(httpx.Client(transport=httpx.MockTransport(api)), "base", pause_s=0)
    boite.ranger(FICHE)
    assert len(appels) == 2


def test_refus_sans_fuite_de_cle(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "ntn_tres_secret")

    def api(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad token {requete.headers['Authorization']}")

    boite = notion.Boite(httpx.Client(transport=httpx.MockTransport(api)), "base", pause_s=0)
    with pytest.raises(notion.ErreurNotion) as erreur:
        boite.ranger(FICHE)
    assert "ntn_tres_secret" not in str(erreur.value) and "partagée" in str(erreur.value)


def test_identifiant_base_formes(monkeypatch):
    for forme in (
        "0123456789abcdef0123456789abcdef",
        "01234567-89ab-cdef-0123-456789abcdef",
        "https://www.notion.so/0123456789abcdef0123456789abcdef",
    ):
        monkeypatch.setenv("NOTION_BASE_ID", forme)
        assert notion.identifiant_base() == "0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("NOTION_BASE_ID", "pas-un-identifiant")
    assert notion.identifiant_base() == ""


def test_virgule_retiree_de_la_source():
    from dataclasses import replace

    page = notion.page(replace(FICHE, source="Banque, Territoires"), "base")
    assert page["properties"]["Source"] == {"select": {"name": "Banque  Territoires"}}
