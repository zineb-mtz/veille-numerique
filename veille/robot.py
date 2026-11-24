"""Le chef d'orchestre : un passage complet du robot de veille.

    python -m veille.robot           passage normal (range dans Notion)
    python -m veille.robot --essai   passage d'essai : rien n'est envoyé ni retenu

Déroulé :
  1. lire et vérifier la liste des sources (arrêt immédiat si elle est fausse) ;
  2. lire chaque flux RSS / YouTube, l'un après l'autre ;
  3. lire les lettres d'information du libellé Gmail ;
  4. écarter les doublons, ranger le reste dans Notion ;
  5. publier le bilan de santé.

Aucune IA ici : la collecte est mécanique et gratuite (décision D3).
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import httpx

from . import config as configuration
from . import notion, reseau
from .memoire import TITRE_MIN, Memoire
from .modeles import Canal, Fiche
from .sante import Bilan
from .sources import flux as lecteur_flux
from .sources import gmail
from .texte import maintenant, masquer, normaliser_titre

DONNEES = configuration.RACINE / "donnees"


def collecter_flux(
    cfg: configuration.Config, session: httpx.Client, memoire: Memoire, bilan: Bilan
) -> dict[str, tuple[list[Fiche], tuple[str, str]]]:
    """Lit chaque flux. Renvoie, par adresse de flux : (fiches, validateurs à retenir si tout est rangé)."""
    resultats: dict[str, tuple[list[Fiche], tuple[str, str]]] = {}
    reglages = cfg.reglages
    for source in cfg.flux:
        etag, modifie_le = memoire.validateurs(source.url)
        try:
            reponse = reseau.telecharger(
                session, source.url, etag=etag, modifie_le=modifie_le, taille_max=reglages.taille_max_octets
            )
            if reponse.inchangee:
                bilan.noter(source.nom, "rien de neuf", "le site confirme : aucune nouveauté (304)")
                continue
            fiches = lecteur_flux.lire(
                reponse.contenu,
                source,
                bilan.debut,
                reglages.fraicheur_jours,
                source.maximum or reglages.max_par_source,
            )
        except (reseau.ErreurReseau, lecteur_flux.FluxIllisible) as erreur:
            bilan.noter(source.nom, "erreur", masquer(str(erreur))[:200])
            continue
        except Exception as erreur:  # bug ou cas imprévu sur UNE source : signalé, le passage continue
            bilan.noter(source.nom, "erreur", masquer(f"{type(erreur).__name__} : {erreur}")[:200])
            continue
        bilan.noter(source.nom, "ok", f"{len(fiches)} info(s) récente(s) dans le flux")
        resultats[source.url] = (fiches, (reponse.etag, reponse.modifie_le))
    return resultats


def passage(
    cfg: configuration.Config,
    session: httpx.Client,
    memoire: Memoire,
    boite: notion.Boite | None,
    lire_boite: gmail.LireBoite | None = None,
) -> Bilan:
    """Un passage complet. `boite` vaut None en mode essai. Testable avec de faux sites et une fausse boîte."""
    bilan = Bilan(debut=maintenant(), essai=boite is None)
    par_flux = collecter_flux(cfg, session, memoire, bilan)
    lettres, sante_gmail = gmail.collecter(cfg, bilan.debut, lire_boite)
    for nom, detail in sante_gmail.items():
        etat = "erreur" if detail.startswith(("ERREUR", "non configuré")) else ("info" if "libellé" in nom else "ok")
        bilan.noter(nom, etat, detail)

    a_traiter: list[tuple[str, Fiche]] = [(url, f) for url, (fiches, _) in par_flux.items() for f in fiches]
    a_traiter += [("gmail", f) for f in lettres]
    incomplets: set[str] = set()  # flux dont une info n'a pas pu être rangée
    vus_ce_passage: set[str] = set()
    titres_ce_passage: set[str] = set()
    nouvelles_par_source: dict[str, int] = defaultdict(int)

    for origine, fiche in a_traiter:
        titre = normaliser_titre(fiche.titre)
        if (
            fiche.identifiant in vus_ce_passage
            or memoire.deja_vue(fiche)
            or (fiche.canal is not Canal.LETTRE and len(titre) >= TITRE_MIN and titre in titres_ce_passage)
        ):
            bilan.doublons += 1
            continue
        vus_ce_passage.add(fiche.identifiant)
        titres_ce_passage.add(titre)
        bilan.nouvelles += 1
        nouvelles_par_source[fiche.source] += 1
        if boite is None:
            print(f"[essai] {fiche.canal.value} · {fiche.source} · {fiche.titre}")
            continue
        if bilan.erreur_rangement:
            incomplets.add(origine)
            continue
        try:
            boite.ranger(fiche)
        except (notion.ErreurNotion, httpx.HTTPError) as erreur:
            bilan.erreur_rangement = masquer(str(erreur))[:300]
            incomplets.add(origine)
            continue
        memoire.retenir(fiche)  # seulement après un rangement réussi
        bilan.rangees += 1

    if boite is not None:
        # Un flux n'est marqué « lu jusqu'ici » que si toutes ses infos ont été rangées.
        # Sinon, au passage suivant, il sera relu en entier (les doublons seront écartés).
        for url, (_, (etag, modifie_le)) in par_flux.items():
            if url in incomplets:
                memoire.oublier_validateurs(url)
            elif etag or modifie_le:
                memoire.noter_validateurs(url, etag, modifie_le)
        memoire.menage()
    for ligne in bilan.lignes:
        if ligne.source in nouvelles_par_source:
            ligne.detail += f" · {nouvelles_par_source[ligne.source]} nouvelle(s)"
    return bilan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Robot de veille sur le numérique (collecte).")
    parser.add_argument("--essai", action="store_true", help="passage d'essai : rien n'est envoyé ni retenu")
    parser.add_argument("--sources", type=Path, help="fichier de sources (par défaut config/ puis config.exemple/)")
    args = parser.parse_args(argv)

    try:
        cfg = configuration.charger(args.sources)
    except configuration.ErreurConfig as erreur:
        print(f"ERREUR de configuration : {erreur}", file=sys.stderr)
        return 2

    essai = args.essai or not notion.configure()
    if essai and not args.essai:
        print("Notion non configuré (NOTION_TOKEN / NOTION_BASE_ID) : passage d'essai.")
    memoire = Memoire(":memory:" if essai else DONNEES / "memoire.sqlite")
    try:
        with reseau.client(cfg.reglages.delai_s) as session:
            boite = None if essai else notion.Boite(session)
            bilan = passage(cfg, session, memoire, boite)
    finally:
        memoire.fermer()
    bilan.publier(DONNEES)
    return 1 if bilan.echec else 0


if __name__ == "__main__":
    sys.exit(main())
