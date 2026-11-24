"""Lettres d'information : lire le libellé Gmail « Veille numérique ».

Même boîte et même mot de passe d'application que la veille emploi (variables
GMAIL_USER et GMAIL_APP_PASSWORD), mais le robot ne lit QUE ce libellé.

Bases techniques :
  - IMAP est le protocole standard pour lire une boîte e-mail à distance. Gmail
    y présente chaque libellé comme un dossier. Connexion chiffrée (SSL).
  - IMAP écrit les noms de dossiers non anglais dans un codage particulier,
    « UTF-7 modifié » : « Veille numérique » devient « Veille num&AOk-rique ».
  - La boîte est ouverte en lecture seule : rien n'est marqué comme lu,
    déplacé ou supprimé.

Règles de sécurité :
  - seuls les expéditeurs listés dans sources.toml sont lus ;
  - un e-mail dont l'authenticité n'est pas confirmée par Gmail (SPF/DKIM,
    DMARC) est ignoré : une fausse « lettre de la CNIL » ne passe pas ;
  - le robot ne clique JAMAIS sur un lien d'une lettre (liens pistés, liens de
    désabonnement en un clic) : il garde le texte et relève les adresses.
"""

from __future__ import annotations

import base64
import contextlib
import email
import imaplib
import os
import re
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import quote

from ..config import Config
from ..modeles import Canal, Fiche, extrait
from ..texte import en_date, html_vers_texte, masquer, nettoyer_lien

HOTE = "imap.gmail.com"
TAILLE_MAX = 2_000_000  # un e-mail de plus de 2 Mo est ignoré (pièce jointe, pas une lettre)
MAX_LIENS = 40
MOIS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Sujets d'e-mails de service, pas de contenu : confirmation d'inscription, bienvenue…
_SERVICE = re.compile(
    r"\bconfirm|\bvalidation de votre|\bvalidez\b|\bbienvenue\b|\bwelcome\b|votre (?:inscription|abonnement) est|"
    r"\bactiv(?:ez|ation) (?:de )?votre|\bverify your",
    re.I,
)
# Liens sans intérêt éditorial : désabonnement, préférences, version en ligne, réseaux sociaux.
_LIEN_INUTILE = re.compile(
    r"d[ée]sabonn|unsubscribe|desinscri|preferences|pr[ée]f[ée]rences|optout|opt-out|view-in-browser|"
    r"version-en-ligne|webversion|facebook\.com|twitter\.com|x\.com/|linkedin\.com/(?:company|shareArticle)|"
    r"instagram\.com|youtube\.com/(?:@|channel|user)|apps\.apple\.com|play\.google\.com",
    re.I,
)

# Lignes de service en tête de lettre (« Si vous ne visualisez pas correctement ce message… »).
_LIGNE_SERVICE = re.compile(
    r"visualis|version en ligne|view (?:this email )?in (?:your )?browser|afficher dans le navigateur|"
    r"cliquez[- ]ici|lire en ligne",
    re.I,
)

LireBoite = Callable[[str, int], list[bytes]]


def configure() -> bool:
    return bool(os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD"))


def utf7_imap(nom: str) -> str:
    """Code un nom de dossier en « UTF-7 modifié » (RFC 3501, §5.1.3), comme IMAP l'exige."""
    sortie: list[str] = []
    a_coder: list[str] = []

    def vider() -> None:
        if a_coder:
            octets = "".join(a_coder).encode("utf-16-be")
            sortie.append("&" + base64.b64encode(octets).decode().rstrip("=").replace("/", ",") + "-")
            a_coder.clear()

    for caractere in nom:
        if 0x20 <= ord(caractere) <= 0x7E:
            vider()
            sortie.append("&-" if caractere == "&" else caractere)
        else:
            a_coder.append(caractere)
    vider()
    return "".join(sortie)


def lire_boite(libelle: str, jours: int) -> list[bytes]:
    """Télécharge les messages du libellé reçus depuis `jours` jours (lecture seule)."""
    depuis = date.today() - timedelta(days=jours)
    boite = imaplib.IMAP4_SSL(HOTE, timeout=30)
    try:
        boite.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"].replace(" ", ""))
        etat, _ = boite.select(f'"{utf7_imap(libelle)}"', readonly=True)
        if etat != "OK":
            raise RuntimeError(f"libellé « {libelle} » introuvable dans la boîte")
        _, numeros = boite.search(None, "SINCE", f"{depuis.day:02d}-{MOIS[depuis.month - 1]}-{depuis.year}")
        messages = []
        for numero in numeros[0].split():
            _, taille = boite.fetch(numero, "(RFC822.SIZE)")
            trouve = re.search(rb"RFC822\.SIZE (\d+)", taille[0] if isinstance(taille[0], bytes) else b"")
            if trouve and int(trouve.group(1)) > TAILLE_MAX:
                continue
            _, contenu = boite.fetch(numero, "(BODY.PEEK[])")  # PEEK : ne marque pas comme lu
            if contenu and isinstance(contenu[0], tuple):
                messages.append(contenu[0][1])
        return messages
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            boite.logout()


def authentique(message: EmailMessage) -> bool:
    """Vrai si Gmail a vérifié l'expéditeur : DKIM ou SPF valide, et DMARC pas en échec.

    On ne lit que le PREMIER en-tête « Authentication-Results » posé par Gmail
    (mx.google.com) : un expéditeur malveillant peut ajouter ses propres
    en-têtes plus bas, mais pas au-dessus de celui de Gmail.
    """
    resultats = message.get_all("Authentication-Results") or []
    if not resultats:
        return False
    premier = str(resultats[0]).lower()
    if not premier.strip().startswith("mx.google.com"):
        return False
    if "dmarc=fail" in premier:
        return False
    return "dkim=pass" in premier or "spf=pass" in premier


def _contenu(message: EmailMessage) -> tuple[str, list[str]]:
    for genre in ("html", "plain"):
        partie = message.get_body((genre,))
        if partie is None:
            continue
        try:
            brut = partie.get_content()
        except (LookupError, UnicodeError):
            continue
        if genre == "html":
            texte, liens = html_vers_texte(brut)
        else:
            texte, liens = brut.strip(), re.findall(r"https?://[^\s<>\"')\]]+", brut)
        lignes = [ligne for ligne in texte.splitlines() if not (len(ligne) < 200 and _LIGNE_SERVICE.search(ligne))]
        return "\n".join(lignes).strip(), liens
    return "", []


def _liens_utiles(liens: list[str]) -> tuple[str, ...]:
    vus: dict[str, None] = {}
    for lien in liens:
        propre = nettoyer_lien(lien)
        if propre and not _LIEN_INUTILE.search(propre):
            vus.setdefault(propre, None)
    return tuple(vus)[:MAX_LIENS]


def lien_gmail(message_id: str) -> str:
    """Lien qui retrouve l'e-mail dans Gmail (recherche par identifiant de message)."""
    return "https://mail.google.com/mail/u/0/#search/" + quote(f"rfc822msgid:{message_id}", safe=":")


def fiche_du_message(brut: bytes, config: Config, collecte_le: datetime) -> tuple[Fiche | None, str]:
    """(fiche, motif). Motif vide si la fiche est gardée, sinon la raison de l'écart. Sans réseau."""
    # Avec policy.default, la bibliothèque renvoie un EmailMessage (API moderne).
    message = email.message_from_bytes(brut, policy=policy.default)
    expediteur = parseaddr(str(message["from"] or ""))[1].lower()
    connu = config.expediteur(expediteur)
    if connu is None:
        return None, "expéditeur non listé"
    if not authentique(message):
        return None, "authenticité non confirmée"
    sujet = " ".join(str(message["subject"] or "").split())
    if _SERVICE.search(sujet):
        return None, "e-mail de service"
    texte, liens = _contenu(message)
    if not texte:
        return None, "contenu illisible"
    identifiant = str(message["message-id"] or "").strip().strip("<>")
    return Fiche(
        titre=sujet or f"Lettre {connu.nom}",
        lien=lien_gmail(identifiant) if identifiant else "",
        source=connu.nom,
        canal=Canal.LETTRE,
        axe=connu.axe,
        publie_le=en_date(str(message["date"] or "")),
        collecte_le=collecte_le,
        extrait=extrait(texte),
        texte=texte,
        liens_cites=_liens_utiles(liens),
        cle=f"mail:{identifiant}" if identifiant else f"mail:{connu.nom}|{sujet}",
    ), ""


def collecter(
    config: Config, collecte_le: datetime, lire: LireBoite | None = None
) -> tuple[list[Fiche], dict[str, str]]:
    """Fiches des lettres reçues et état de santé. `lire` remplace la vraie boîte dans les tests."""
    if not config.expediteurs:
        return [], {}
    if lire is None and not configure():
        return [], {"Gmail": "non configuré (GMAIL_USER / GMAIL_APP_PASSWORD absents)"}
    reglages = config.reglages
    try:
        messages = (lire or lire_boite)(reglages.gmail_libelle, reglages.gmail_jours)
    except Exception as erreur:  # mot de passe refusé, libellé absent, panne réseau : signalé, pas bloquant
        return [], {"Gmail": masquer(f"ERREUR : {type(erreur).__name__} {erreur}")[:200]}

    fiches: list[Fiche] = []
    ecarts: Counter[str] = Counter()
    for brut in messages:
        fiche, motif = fiche_du_message(brut, config, collecte_le)
        if fiche:
            fiches.append(fiche)
        else:
            ecarts[motif] += 1
    par_source = Counter(f.source for f in fiches)
    sante = {f"Lettre · {e.nom}": f"{par_source[e.nom]} lettre(s)" for e in config.expediteurs}
    detail = ", ".join(f"{n} {motif}" for motif, n in ecarts.most_common())
    sante["Gmail · libellé"] = f"{len(messages)} message(s) sur {reglages.gmail_jours} jour(s)" + (
        f" ; écartés : {detail}" if detail else ""
    )
    return fiches, sante
