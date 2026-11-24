"""Outils partagés par les tests : faux flux, faux e-mails, faux sites. Aucun appel réseau."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime

import httpx
import pytest

from veille.config import Config, lire

MAINTENANT = datetime(2026, 11, 24, 6, 0, tzinfo=UTC)

RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Exemple</title>
<item><title>Nouveau mod\xc3\xa8le ouvert</title><link>https://exemple.fr/a?utm_source=rss&amp;id=3</link>
<pubDate>Mon, 23 Nov 2026 08:00:00 GMT</pubDate><description>&lt;p&gt;Un &lt;b&gt;r\xc3\xa9sum\xc3\xa9&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>Article ancien</title><link>https://exemple.fr/vieux</link><pubDate>Mon, 02 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>Lien pi\xc3\xa9g\xc3\xa9</title><link>javascript:alert(1)</link><pubDate>Mon, 23 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>Sans lien mais guid</title><guid>https://exemple.fr/guid-seul</guid><pubDate>Sun, 22 Nov 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""

YOUTUBE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>Cha\xc3\xaene</title>
 <entry><id>yt:video:abc</id><title>L'IA dans les collectivit\xc3\xa9s</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=abc"/>
  <published>2026-11-23T10:00:00+00:00</published>
  <media:group><media:title>L'IA dans les collectivit\xc3\xa9s</media:title><media:description>Description de la vid\xc3\xa9o</media:description></media:group>
 </entry>
</feed>"""

SOURCES = {
    "reglages": {"fraicheur_jours": 7},
    "flux": [{"nom": "Exemple", "url": "https://exemple.fr/flux.xml", "axe": "IA"}],
    "youtube": [{"nom": "Chaîne", "chaine_id": "UC" + "a" * 22, "axe": "PUBLIC", "sans_shorts": True}],
    "expediteurs": [
        {"nom": "Localtis", "domaine": "infos.banquedesterritoires.fr", "axe": "PUBLIC"},
        {"nom": "Import AI", "adresse": "importai@substack.com", "axe": "IA"},
    ],
}

AUTH_OK = "mx.google.com; dkim=pass header.i=@exemple; spf=pass smtp.mailfrom=exemple; dmarc=pass"


@pytest.fixture
def cfg() -> Config:
    return lire(SOURCES)


def courriel(
    expediteur: str = "lettre@infos.banquedesterritoires.fr",
    sujet: str = "La Quotidienne de Localtis",
    html: str = '<p>Bonjour</p><p>Article : <a href="https://www.banquedesterritoires.fr/ia?utm_campaign=x">IA</a></p>'
    '<a href="https://exemple.fr/desabonnement">Se désabonner</a>',
    authentification: str | None = AUTH_OK,
    identifiant: str = "<abc123@exemple>",
) -> bytes:
    message = EmailMessage()
    if authentification is not None:
        message["Authentication-Results"] = authentification
    message["From"] = f"Expéditeur <{expediteur}>"
    message["To"] = "moi@gmail.com"
    message["Subject"] = sujet
    message["Date"] = format_datetime(MAINTENANT)
    message["Message-ID"] = identifiant
    message.set_content("version texte")
    message.add_alternative(html, subtype="html")
    return message.as_bytes()


def faux_sites(pages: dict[str, httpx.Response | Callable[[httpx.Request], httpx.Response]]) -> httpx.Client:
    """Client httpx dont chaque adresse renvoie une réponse prévue (ou 404)."""

    def repondre(requete: httpx.Request) -> httpx.Response:
        prevu = pages.get(str(requete.url))
        if prevu is None:
            return httpx.Response(404)
        return prevu(requete) if callable(prevu) else prevu

    return httpx.Client(transport=httpx.MockTransport(repondre), follow_redirects=True)
