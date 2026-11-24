"""Le bilan de santé d'un passage : quelles sources ont répondu, combien d'infos, quelles erreurs.

Il est affiché dans le journal, écrit dans donnees/bilan.md et, sur GitHub,
ajouté au résumé de l'exécution (onglet Actions, visible sans rien ouvrir).
Règle : une source en panne devient une ligne du bilan, jamais un arrêt du passage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class Ligne:
    source: str
    etat: str  # « ok », « rien de neuf », « erreur », « info »
    detail: str = ""


@dataclass(slots=True)
class Bilan:
    debut: datetime
    essai: bool = False
    lignes: list[Ligne] = field(default_factory=list)
    nouvelles: int = 0
    rangees: int = 0
    doublons: int = 0
    erreur_rangement: str = ""

    def noter(self, source: str, etat: str, detail: str = "") -> None:
        self.lignes.append(Ligne(source, etat, detail))

    @property
    def sources_en_erreur(self) -> list[Ligne]:
        return [ligne for ligne in self.lignes if ligne.etat == "erreur"]

    @property
    def echec(self) -> bool:
        """Échec franc : rangement impossible, ou aucune source n'a répondu."""
        sources = [ligne for ligne in self.lignes if ligne.etat != "info"]
        return bool(self.erreur_rangement) or (bool(sources) and len(self.sources_en_erreur) == len(sources))

    def markdown(self) -> str:
        titre = "Passage d'essai (rien n'est envoyé)" if self.essai else "Passage du robot"
        lignes = [
            f"## {titre} du {self.debut:%d/%m/%Y à %H:%M} UTC",
            "",
            f"- Infos nouvelles : **{self.nouvelles}**",
            f"- Rangées dans Notion : **{self.rangees}**",
            f"- Doublons écartés : **{self.doublons}**",
            f"- Sources en erreur : **{len(self.sources_en_erreur)}**",
        ]
        if self.erreur_rangement:
            lignes.append(f"- ⚠️ Rangement interrompu : {self.erreur_rangement}")
        lignes += ["", "| Source | État | Détail |", "|---|---|---|"]
        for ligne in self.lignes:
            detail = ligne.detail.replace("|", "/").replace("\n", " ")
            lignes.append(f"| {ligne.source} | {ligne.etat} | {detail} |")
        return "\n".join(lignes) + "\n"

    def publier(self, dossier: Path) -> None:
        texte = self.markdown()
        print(texte)
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / "bilan.md").write_text(texte, encoding="utf-8")
        resume = os.environ.get("GITHUB_STEP_SUMMARY")
        if resume:
            with open(resume, "a", encoding="utf-8") as fichier:
                fichier.write(texte)
