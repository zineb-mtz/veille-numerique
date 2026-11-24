"""La liste des sources est vérifiée avant tout appel réseau."""

from pathlib import Path

import pytest

from veille.config import CHEMINS, ErreurConfig, charger, lire, url_youtube
from veille.modeles import Axe, Canal

from .conftest import SOURCES


def test_lecture_complete(cfg):
    assert [f.nom for f in cfg.flux] == ["Exemple", "Chaîne"]
    assert cfg.flux[1].canal is Canal.YOUTUBE
    assert cfg.flux[1].url.endswith("playlist_id=UULF" + "a" * 22)  # variante sans Shorts
    assert cfg.expediteurs[0].axe is Axe.PUBLIC
    assert cfg.reglages.gmail_libelle == "Veille numérique"


def test_toutes_les_erreurs_sont_listees():
    with pytest.raises(ErreurConfig) as erreur:
        lire(
            {
                "flux": [
                    {"nom": "A", "url": "http://non-chiffre.fr", "axe": "IA"},
                    {"nom": "A", "url": "https://ok.fr", "axe": "INCONNU"},
                ],
                "youtube": [{"nom": "B", "chaine_id": "pas-un-id", "axe": "IA"}],
                "expediteurs": [{"nom": "C", "domaine": "x.fr", "adresse": "a@x.fr", "axe": "IA"}],
            }
        )
    message = str(erreur.value)
    for attendu in ("https://", "déjà utilisé", "axe « INCONNU »", "UC", "un seul des deux"):
        assert attendu in message


def test_reglage_hors_bornes():
    with pytest.raises(ErreurConfig, match="fraicheur_jours"):
        lire({**SOURCES, "reglages": {"fraicheur_jours": 0}})


def test_libelle_avec_guillemet_refuse():
    with pytest.raises(ErreurConfig, match="gmail_libelle"):
        lire({**SOURCES, "reglages": {"gmail_libelle": 'a"b'}})


def test_aucune_source():
    with pytest.raises(ErreurConfig, match="aucune source"):
        lire({})


def test_expediteur_domaine_et_sous_domaine(cfg):
    assert cfg.expediteur("lettre@infos.banquedesterritoires.fr").nom == "Localtis"
    assert cfg.expediteur("x@news.infos.banquedesterritoires.fr").nom == "Localtis"
    assert cfg.expediteur("x@faux-infos.banquedesterritoires.fr.pirate.com") is None
    assert cfg.expediteur("importai@substack.com").nom == "Import AI"
    assert cfg.expediteur("autre@substack.com") is None  # domaine partagé : adresse exacte seulement


def test_url_youtube_avec_shorts():
    assert url_youtube("UC" + "b" * 22, False).endswith("channel_id=UC" + "b" * 22)


def test_fichier_exemple_valide():
    """Le fichier d'exemple publié doit toujours être valide."""
    config = charger(CHEMINS[-1])
    assert config.flux and config.expediteurs


def test_fichier_absent(tmp_path: Path):
    with pytest.raises(ErreurConfig, match="introuvable"):
        charger(tmp_path / "absent.toml")


def test_toml_invalide(tmp_path: Path):
    chemin = tmp_path / "sources.toml"
    chemin.write_text("[[flux]\nnom=", encoding="utf-8")
    with pytest.raises(ErreurConfig, match="TOML"):
        charger(chemin)


def test_plafond_propre_a_un_flux():
    cfg = lire({"flux": [{"nom": "A", "url": "https://a.fr/flux", "axe": "IA", "maximum": 5}]})
    assert cfg.flux[0].maximum == 5


@pytest.mark.parametrize("valeur", [0, 101, "5", True])
def test_plafond_invalide_refuse(valeur):
    with pytest.raises(ErreurConfig, match="maximum"):
        lire({"flux": [{"nom": "A", "url": "https://a.fr/flux", "axe": "IA", "maximum": valeur}]})
