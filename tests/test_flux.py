import pytest

from veille.config import Flux
from veille.modeles import Axe, Canal
from veille.sources.flux import FluxIllisible, lire

from .conftest import MAINTENANT, RSS, YOUTUBE

SOURCE = Flux("Exemple", "https://exemple.fr/flux.xml", Axe.IA)


def test_rss():
    fiches = lire(RSS, SOURCE, MAINTENANT, fraicheur_jours=7, maximum=20)
    assert [f.titre for f in fiches] == ["Nouveau modèle ouvert", "Sans lien mais guid"]
    premiere = fiches[0]
    assert premiere.lien == "https://exemple.fr/a?id=3"  # pistage retiré
    assert premiere.extrait == "Un résumé"  # HTML retiré
    assert fiches[1].lien == "https://exemple.fr/guid-seul"  # repli sur <guid> (cas Hugging Face)


def test_ancien_et_lien_piege_ecartes():
    titres = [f.titre for f in lire(RSS, SOURCE, MAINTENANT, 7, 20)]
    assert "Article ancien" not in titres and "Lien piégé" not in titres


def test_maximum_par_source():
    assert len(lire(RSS, SOURCE, MAINTENANT, 7, maximum=1)) == 1


def test_youtube_atom():
    chaine = Flux("Chaîne", "https://www.youtube.com/feeds/videos.xml?channel_id=x", Axe.PUBLIC, Canal.YOUTUBE)
    (video,) = lire(YOUTUBE, chaine, MAINTENANT, 7, 20)
    assert video.lien == "https://www.youtube.com/watch?v=abc"
    assert video.canal is Canal.YOUTUBE and video.extrait == "Description de la vidéo"


def test_xml_piege_refuse():
    bombe = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>
    <rss><channel><item><title>&lol2;</title></item></channel></rss>"""
    with pytest.raises(FluxIllisible):
        lire(bombe, SOURCE, MAINTENANT, 7, 20)


def test_page_html_au_lieu_d_un_flux():
    with pytest.raises(FluxIllisible, match="racine"):
        lire(b"<html><body>Accueil</body></html>", SOURCE, MAINTENANT, 7, 20)


def test_contenu_illisible():
    with pytest.raises(FluxIllisible):
        lire(b"pas du xml", SOURCE, MAINTENANT, 7, 20)
