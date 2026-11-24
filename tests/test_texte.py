from datetime import date

from veille.modeles import extrait
from veille.texte import en_date, html_vers_texte, lien_sur, masquer, nettoyer_lien, normaliser_titre


def test_liens_dangereux_refuses():
    for lien in ("javascript:alert(1)", "data:text/html;base64,xx", "file:///etc/passwd", "https://", ""):
        assert not lien_sur(lien)
    assert lien_sur("https://exemple.fr/a")


def test_parametres_de_pistage_retires():
    assert nettoyer_lien("https://Exemple.fr/a?utm_source=x&id=3&fbclid=y#ancre") == "https://exemple.fr/a?id=3"
    assert nettoyer_lien("javascript:alert(1)") == ""


def test_titre_normalise():
    assert normaliser_titre("L'IA dans les Collectivités !") == "l ia dans les collectivites"


def test_dates():
    assert en_date("Mon, 23 Nov 2026 08:00:00 GMT") == date(2026, 11, 23)
    assert en_date("2026-11-23T10:00:00Z") == date(2026, 11, 23)
    assert en_date("n'importe quoi") is None and en_date(None) is None


def test_html_vers_texte_ignore_scripts():
    texte, liens = html_vers_texte(
        '<script>alert(1)</script><p>Bonjour</p><a href="javascript:x">a</a><a href="https://ok.fr">b</a>'
    )
    assert texte == "Bonjour\nab" or "Bonjour" in texte
    assert "alert" not in texte
    assert liens == ["https://ok.fr"]


def test_extrait_coupe_sur_un_mot():
    assert extrait("un deux trois", taille=8) == "un deux…"
    assert extrait("court") == "court"


def test_masquer(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "ntn_secret_123456")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    assert masquer("clé ntn_secret_123456 et abcdefghijklmnop") == "clé *** et ***"
