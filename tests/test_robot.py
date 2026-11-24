"""Passages complets avec de faux sites, une fausse boîte Gmail et un faux Notion."""

from dataclasses import replace

import httpx

from veille import notion
from veille.memoire import Memoire
from veille.robot import main, passage

from .conftest import RSS, YOUTUBE, courriel, faux_sites

FLUX = "https://exemple.fr/flux.xml"
CHAINE = "https://www.youtube.com/feeds/videos.xml?playlist_id=UULF" + "a" * 22


class FauxNotion(notion.Boite):
    def __init__(self, echoue_apres: int | None = None) -> None:
        self.rangees: list[str] = []
        self.echoue_apres = echoue_apres

    def ranger(self, fiche):
        if self.echoue_apres is not None and len(self.rangees) >= self.echoue_apres:
            raise notion.ErreurNotion("Notion indisponible")
        self.rangees.append(fiche.titre)


def sites(etag: str = '"v1"'):
    return faux_sites(
        {
            FLUX: httpx.Response(200, content=RSS, headers={"ETag": etag}),
            CHAINE: httpx.Response(200, content=YOUTUBE),
        }
    )


def lettres(libelle, jours):
    return [courriel()]


def test_passage_complet(cfg):
    memoire, boite = Memoire(), FauxNotion()
    bilan = passage(cfg, sites(), memoire, boite, lettres)
    assert set(boite.rangees) == {
        "Nouveau modèle ouvert",
        "Sans lien mais guid",
        "L'IA dans les collectivités",
        "La Quotidienne de Localtis",
    }
    assert bilan.rangees == 4 and not bilan.echec
    assert memoire.validateurs(FLUX)[0] == '"v1"'


def test_plafond_propre_au_flux(cfg):
    cfg = replace(cfg, flux=type(cfg.flux)([replace(cfg.flux[0], maximum=1), *cfg.flux[1:]]))
    boite = FauxNotion()
    passage(cfg, sites(), Memoire(), boite, lettres)
    assert len({"Nouveau modèle ouvert", "Sans lien mais guid"} & set(boite.rangees)) == 1


def test_second_passage_sans_doublon(cfg):
    memoire = Memoire()
    passage(cfg, sites(), memoire, FauxNotion(), lettres)
    boite = FauxNotion()
    bilan = passage(cfg, sites(), memoire, boite, lettres)
    assert boite.rangees == [] and bilan.doublons == 4


def test_source_en_panne_non_bloquante(cfg):
    session = faux_sites({CHAINE: httpx.Response(200, content=YOUTUBE)})  # le flux RSS répond 404
    boite = FauxNotion()
    bilan = passage(cfg, session, Memoire(), boite, lettres)
    assert "L'IA dans les collectivités" in boite.rangees
    assert [ligne.source for ligne in bilan.sources_en_erreur] == ["Exemple"]
    assert not bilan.echec


def test_echec_notion_rien_n_est_perdu(cfg):
    memoire = Memoire()
    bilan = passage(cfg, sites(), memoire, FauxNotion(echoue_apres=1), lettres)
    assert bilan.erreur_rangement and bilan.echec and bilan.rangees == 1
    assert memoire.validateurs(FLUX) == ("", "")  # le flux sera relu en entier au prochain passage
    boite = FauxNotion()
    passage(cfg, sites(), memoire, boite, lettres)
    assert len(boite.rangees) == 3  # les 3 infos non rangées arrivent ; aucune en double


def test_essai_n_envoie_rien(cfg, capsys):
    memoire = Memoire()
    bilan = passage(cfg, sites(), memoire, None, lettres)
    assert bilan.essai and bilan.nouvelles == 4 and bilan.rangees == 0
    assert "[essai]" in capsys.readouterr().out
    assert memoire.validateurs(FLUX) == ("", "")


def test_main_configuration_fausse(tmp_path, capsys):
    chemin = tmp_path / "sources.toml"
    chemin.write_text('[[flux]]\nnom = "A"\nurl = "http://x.fr"\naxe = "IA"\n', encoding="utf-8")
    assert main(["--sources", str(chemin)]) == 2
    assert "https://" in capsys.readouterr().err
