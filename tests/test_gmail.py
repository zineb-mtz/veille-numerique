from veille.modeles import Canal
from veille.sources.gmail import authentique, collecter, fiche_du_message, lien_gmail, utf7_imap

from .conftest import MAINTENANT, courriel


def test_utf7_imap():
    assert utf7_imap("Veille numérique") == "Veille num&AOk-rique"
    assert utf7_imap("A&B") == "A&-B"
    assert utf7_imap("Veille emploi") == "Veille emploi"


def test_lettre_gardee(cfg):
    fiche, motif = fiche_du_message(courriel(), cfg, MAINTENANT)
    assert motif == "" and fiche is not None
    assert fiche.source == "Localtis" and fiche.canal is Canal.LETTRE
    assert "Bonjour" in fiche.texte
    assert fiche.liens_cites == ("https://www.banquedesterritoires.fr/ia",)  # pistage retiré, désabonnement exclu
    assert fiche.lien == lien_gmail("abc123@exemple")
    assert fiche.cle == "mail:abc123@exemple"


def test_expediteur_non_liste(cfg):
    assert fiche_du_message(courriel(expediteur="pub@inconnu.fr"), cfg, MAINTENANT) == (None, "expéditeur non listé")


def test_faux_expediteur_refuse(cfg):
    usurpe = courriel(authentification="mx.google.com; dkim=fail; spf=softfail; dmarc=fail")
    assert fiche_du_message(usurpe, cfg, MAINTENANT)[1] == "authenticité non confirmée"
    sans_entete = courriel(authentification=None)
    assert fiche_du_message(sans_entete, cfg, MAINTENANT)[1] == "authenticité non confirmée"


def test_entete_forge_ignore():
    """Seul le premier en-tête (posé par Gmail) compte ; un en-tête ajouté plus bas par l'expéditeur est ignoré."""
    import email
    from email import policy

    brut = courriel(authentification="mx.google.com; dkim=fail; spf=fail; dmarc=fail")
    message = email.message_from_bytes(brut, policy=policy.default)
    message["Authentication-Results"] = "mx.google.com; dkim=pass; spf=pass; dmarc=pass"  # ajouté APRÈS
    assert not authentique(message)
    autre = email.message_from_bytes(courriel(authentification="pirate.example; dkim=pass"), policy=policy.default)
    assert not authentique(autre)


def test_emails_de_service_ignores(cfg):
    for sujet in (
        "Confirmation de votre inscription à la newsletter",
        "Votre inscription est confirmée !",
        "Bienvenue Mme Martinez sur Acteurs publics !",
        "Welcome to Import AI",
    ):
        assert fiche_du_message(courriel(sujet=sujet), cfg, MAINTENANT)[1] == "e-mail de service"
    # un vrai contenu qui parle d'inscription reste gardé
    assert fiche_du_message(courriel(sujet="Inscriptions ouvertes au salon IA"), cfg, MAINTENANT)[1] == ""


def test_adresse_exacte_pour_substack(cfg):
    assert fiche_du_message(courriel(expediteur="importai@substack.com", sujet="Import AI 481"), cfg, MAINTENANT)[0]
    assert fiche_du_message(courriel(expediteur="autre@substack.com"), cfg, MAINTENANT)[1] == "expéditeur non listé"


def test_collecter_bilan(cfg):
    messages = [courriel(), courriel(expediteur="pub@inconnu.fr"), courriel(sujet="Bienvenue !")]
    fiches, sante = collecter(cfg, MAINTENANT, lire=lambda libelle, jours: messages)
    assert len(fiches) == 1
    assert sante["Lettre · Localtis"] == "1 lettre(s)"
    assert "1 expéditeur non listé" in sante["Gmail · libellé"] and "1 e-mail de service" in sante["Gmail · libellé"]


def test_panne_gmail_non_bloquante(cfg, monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "motdepasse-secret")

    def panne(libelle, jours):
        raise RuntimeError("mot de passe motdepasse-secret refusé")

    fiches, sante = collecter(cfg, MAINTENANT, lire=panne)
    assert fiches == [] and sante["Gmail"].startswith("ERREUR") and "motdepasse-secret" not in sante["Gmail"]


def test_gmail_non_configure(cfg, monkeypatch):
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert collecter(cfg, MAINTENANT) == ([], {"Gmail": "non configuré (GMAIL_USER / GMAIL_APP_PASSWORD absents)"})


def test_lignes_de_service_retirees(cfg):
    html = "<p>Si vous ne visualisez pas correctement ce message, cliquez-ici.</p><p>Édito : l'IA arrive en mairie.</p>"
    fiche, _ = fiche_du_message(courriel(html=html), cfg, MAINTENANT)
    assert fiche is not None and fiche.extrait == "Édito : l'IA arrive en mairie."
