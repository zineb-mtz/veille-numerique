"""La mémoire du robot : un petit fichier SQLite.

Elle retient :
  - les infos déjà rangées dans Notion, pour ne jamais les envoyer deux fois ;
  - pour chaque flux, ce que le site a répondu la dernière fois (ETag,
    Last-Modified), pour lui demander ensuite « quoi de neuf depuis ? ».

Bases techniques :
  - SQLite est une base de données tenue dans un seul fichier, sans serveur.
    Python la sait lire et écrire sans bibliothèque supplémentaire.
  - Sur GitHub, ce fichier est gardé d'un passage à l'autre par le cache des
    Actions (voir .github/workflows/veille.yml).

Deux filtres de doublons, dans l'ordre :
  1. même identifiant (lien nettoyé, ou identifiant de l'e-mail) ;
  2. même titre normalisé vu dans les 30 derniers jours, pour les flux et
     vidéos seulement (le même article repris par deux sites). Les lettres ne
     sont pas comparées sur leur titre : « La lettre de la semaine » revient
     chaque semaine avec un contenu différent.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .modeles import Canal, Fiche
from .texte import normaliser_titre

FENETRE_TITRE_JOURS = 30
TITRE_MIN = 20  # un titre très court (« Édito ») n'est pas assez distinctif pour dédoublonner
OUBLI_JOURS = 365


class Memoire:
    def __init__(self, chemin: Path | str = ":memory:") -> None:
        if str(chemin) != ":memory:":
            Path(chemin).parent.mkdir(parents=True, exist_ok=True)
        self.base = sqlite3.connect(str(chemin))
        self.base.executescript(
            """
            CREATE TABLE IF NOT EXISTS vues (
                identifiant TEXT PRIMARY KEY, titre TEXT NOT NULL, source TEXT NOT NULL,
                canal TEXT NOT NULL, vue_le TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS vues_titre ON vues (titre);
            CREATE TABLE IF NOT EXISTS http (
                url TEXT PRIMARY KEY, etag TEXT NOT NULL, modifie_le TEXT NOT NULL);
            """
        )

    def fermer(self) -> None:
        self.base.close()

    def deja_vue(self, fiche: Fiche) -> bool:
        if self.base.execute("SELECT 1 FROM vues WHERE identifiant = ?", (fiche.identifiant,)).fetchone():
            return True
        titre = normaliser_titre(fiche.titre)
        if fiche.canal is Canal.LETTRE or len(titre) < TITRE_MIN:
            return False
        depuis = (datetime.now(UTC) - timedelta(days=FENETRE_TITRE_JOURS)).isoformat()
        return (
            self.base.execute(
                "SELECT 1 FROM vues WHERE titre = ? AND canal != ? AND vue_le >= ?",
                (titre, Canal.LETTRE.value, depuis),
            ).fetchone()
            is not None
        )

    def retenir(self, fiche: Fiche) -> None:
        """À appeler SEULEMENT après un envoi réussi : en cas d'échec, l'info sera retentée au passage suivant."""
        self.base.execute(
            "INSERT OR REPLACE INTO vues VALUES (?, ?, ?, ?, ?)",
            (
                fiche.identifiant,
                normaliser_titre(fiche.titre),
                fiche.source,
                fiche.canal.value,
                datetime.now(UTC).isoformat(),
            ),
        )
        self.base.commit()

    def validateurs(self, url: str) -> tuple[str, str]:
        ligne = self.base.execute("SELECT etag, modifie_le FROM http WHERE url = ?", (url,)).fetchone()
        return (ligne[0], ligne[1]) if ligne else ("", "")

    def noter_validateurs(self, url: str, etag: str, modifie_le: str) -> None:
        self.base.execute("INSERT OR REPLACE INTO http VALUES (?, ?, ?)", (url, etag, modifie_le))
        self.base.commit()

    def oublier_validateurs(self, url: str) -> None:
        self.base.execute("DELETE FROM http WHERE url = ?", (url,))
        self.base.commit()

    def menage(self) -> int:
        """Oublie les infos de plus d'un an (la base reste petite). Renvoie le nombre de lignes retirées."""
        limite = (datetime.now(UTC) - timedelta(days=OUBLI_JOURS)).isoformat()
        retirees = self.base.execute("DELETE FROM vues WHERE vue_le < ?", (limite,)).rowcount
        self.base.commit()
        return retirees
