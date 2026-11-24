from dataclasses import replace

from veille.memoire import Memoire
from veille.modeles import Axe, Canal, Fiche

from .conftest import MAINTENANT

FICHE = Fiche(
    "Un titre assez long pour comparer",
    "https://a.fr/1",
    "A",
    Canal.RSS,
    Axe.IA,
    None,
    MAINTENANT,
    cle="https://a.fr/1",
)


def test_meme_identifiant():
    memoire = Memoire()
    assert not memoire.deja_vue(FICHE)
    memoire.retenir(FICHE)
    assert memoire.deja_vue(FICHE)


def test_meme_titre_autre_site():
    memoire = Memoire()
    memoire.retenir(FICHE)
    reprise = replace(
        FICHE, lien="https://b.fr/x", source="B", cle="https://b.fr/x", titre="Un titre assez LONG pour comparer !"
    )
    assert memoire.deja_vue(reprise)


def test_titre_court_ou_lettre_non_compares():
    memoire = Memoire()
    lettre = replace(FICHE, canal=Canal.LETTRE, cle="mail:1")
    memoire.retenir(lettre)
    assert not memoire.deja_vue(replace(lettre, cle="mail:2"))  # même sujet, autre semaine
    court = replace(FICHE, titre="Édito", cle="c1")
    memoire.retenir(court)
    assert not memoire.deja_vue(replace(court, cle="c2"))


def test_validateurs():
    memoire = Memoire()
    assert memoire.validateurs("https://f") == ("", "")
    memoire.noter_validateurs("https://f", '"v1"', "Mon, 23 Nov 2026 08:00:00 GMT")
    assert memoire.validateurs("https://f") == ('"v1"', "Mon, 23 Nov 2026 08:00:00 GMT")
    memoire.oublier_validateurs("https://f")
    assert memoire.validateurs("https://f") == ("", "")


def test_fichier_persistant(tmp_path):
    chemin = tmp_path / "sous" / "memoire.sqlite"
    memoire = Memoire(chemin)
    memoire.retenir(FICHE)
    memoire.fermer()
    assert Memoire(chemin).deja_vue(FICHE)


def test_copie_pour_essai_sans_toucher_au_fichier(tmp_path):
    chemin = tmp_path / "memoire.sqlite"
    vraie = Memoire(chemin)
    vraie.retenir(FICHE)
    vraie.fermer()
    avant = chemin.read_bytes()

    essai = Memoire.copie(chemin)
    assert essai.deja_vue(FICHE)  # l'essai voit les doublons réels
    essai.retenir(replace(FICHE, lien="https://exemple.fr/autre", cle=""))
    essai.fermer()
    assert chemin.read_bytes() == avant  # le fichier n'a pas bougé


def test_copie_sans_fichier(tmp_path):
    essai = Memoire.copie(tmp_path / "absent.sqlite")
    assert not essai.deja_vue(FICHE)
    assert not (tmp_path / "absent.sqlite").exists()
