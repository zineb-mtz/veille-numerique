# Veille sur le numérique (robot de collecte)

Un robot gratuit qui suit chaque jour l'actualité de l'IA et du numérique public :
il lit des flux RSS, des chaînes YouTube et des lettres d'information reçues dans
Gmail, écarte les doublons et range le reste dans une base Notion. En option, il
ajoute à chaque info une phrase « À retenir » écrite par Mistral. Il ne publie
rien : la lecture et la décision restent humaines.

C'est le lot 1 (collecte) du projet « Veille sur le numérique ». Le tri, l'analyse
(fiches inspirées de la méthode de Romy Alula) et la publication viendront ensuite.
Les choix et leurs raisons sont tenus dans [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Le principe en une image

```
flux RSS ──────────┐
chaînes YouTube ───┼──> LIRE ──> MÊME FORMAT ──> DOUBLONS ──> Notion « Veille numérique » ──> toi
lettres (Gmail) ───┘    (une source       (fiche brute)    (mémoire       (statut « À lire »)
                         à la fois)                          SQLite)
                                  └──> bilan de santé (journal + résumé GitHub)
```

- **IA en option, au bout de la chaîne** : la collecte n'appelle aucune IA ; seule la
  phrase « À retenir » (facultative) fait appel à Mistral, offre gratuite.
- **Une panne n'arrête rien** : chaque source est lue séparément ; une source qui
  échoue devient une ligne du bilan de santé.
- **Rien n'est perdu** : une info n'est marquée « déjà vue » qu'après son
  rangement réussi dans Notion ; si Notion refuse, elle revient au passage suivant.
- **Relançable sans risque** : deux passages de suite ne créent aucun doublon.

## Essayer en 3 minutes

Il faut Python 3.12 ou plus récent.

```bash
python -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements.txt -r requirements-dev.txt
python -m pytest                    # vérifie que tout fonctionne (aucun appel réseau)
python -m veille.robot --essai      # passage d'essai : rien n'est envoyé ni retenu
```

## Le mettre en service

1. **Base Notion** nommée « Veille numérique », avec ces colonnes (noms exacts) :

   | Colonne | Type | Contenu |
   |---|---|---|
   | Titre | Titre | titre de l'info |
   | Lien | URL | article, vidéo, ou e-mail d'origine dans Gmail |
   | Source | Sélection | Mistral AI, Localtis… |
   | Canal | Sélection | RSS, YouTube, Lettre d'info |
   | Axe | Sélection | IA et innovation, Numérique public, Confiance et cadre |
   | Publié le | Date | date de publication |
   | Collecté le | Date | date du passage |
   | Extrait | Texte | 500 premiers caractères |
   | À retenir | Texte | facultatif : une phrase « le fait : ce que ça change pour le public » |
   | Statut | Sélection | À lire, Retenu, Écarté, Publié |
   | Identifiant | Texte | empreinte servant au dédoublonnage |

   Puis la partager avec l'intégration Notion (menu « … » → Connexions).

2. **Libellé Gmail** « Veille numérique » (nom exact), alimenté par un filtre par
   expéditeur. Le robot ne lit que ce libellé, en lecture seule.

3. **Secrets du dépôt** (Settings → Secrets and variables → Actions) :

   | Secret | Contenu |
   |---|---|
   | `NOTION_TOKEN` | clé de l'intégration Notion |
   | `NOTION_BASE_ID` | identifiant (ou adresse) de la base « Veille numérique » |
   | `GMAIL_USER` | adresse Gmail |
   | `GMAIL_APP_PASSWORD` | mot de passe d'application Google (pas le vrai mot de passe) |
   | `MISTRAL_API_KEY` | facultatif : clé de l'API Mistral, pour la phrase « À retenir » |
   | `SOURCES_TOML` | facultatif : liste privée des sources |

4. **Sources** : [`config.exemple/sources.toml`](config.exemple/sources.toml), commenté.
   Chaque source a un axe ; un expéditeur se déclare par domaine, ou par adresse
   exacte pour les domaines partagés (`importai@substack.com`).

Le passage tourne chaque jour vers 4 h 17 UTC (5 h 17 à Paris l'hiver) (onglet Actions) ; le bouton « Run workflow »
lance un passage à la main, en essai si besoin. Le bilan apparaît dans le résumé
de l'exécution.

## Sécurité

| Risque | Parade |
|---|---|
| Fuite d'une clé | secrets GitHub uniquement, donnés à la seule étape du robot ; masqués dans les messages ; scan gitleaks |
| Flux XML piégé | lecture par defusedxml (DTD refusées) ; taille maximale vérifiée après décompression ; délai maximal |
| Lien dangereux | seuls http(s) sont gardés ; paramètres de pistage retirés |
| Fausse lettre d'info | expéditeurs listés seulement ; authenticité vérifiée par Gmail (DKIM/SPF, DMARC) |
| Liens pistés, désabonnement en un clic | le robot ne clique jamais sur un lien d'une lettre |
| Dépendance compromise | versions figées avec empreintes (`--require-hashes`), pip-audit, Dependabot |
| Action GitHub détournée | actions épinglées par empreinte (SHA), jeton GitHub en lecture seule |
| Contenu piégé pour une IA | la collecte n'appelle aucune IA ; pour « À retenir », le texte est encadré comme une donnée, la consigne interdit d'en suivre les instructions, la réponse est réduite à une ligne affichée, jamais exécutée |
| Droits d'auteur | texte des lettres gardé en privé dans Notion, jamais republié |

## Organisation du code

```
veille/
├── modeles.py      la fiche brute, format commun à toutes les sources
├── config.py       lecture et vérification de sources.toml
├── reseau.py       requêtes polies et sûres
├── sources/
│   ├── flux.py     flux RSS et Atom (dont YouTube)
│   └── gmail.py    lettres d'information du libellé Gmail
├── memoire.py      déjà-vus et réponses des sites (SQLite)
├── notion.py       rangement dans Notion (seul module à changer pour Obsidian)
├── sante.py        bilan de santé
└── robot.py        chef d'orchestre
```

Inspirations : [Latest-developments](https://github.com/davidamitchell/Latest-developments-),
[radar](https://github.com/Samdev2420/radar-ai), [veilleur](https://github.com/allienna/veilleur),
astuces de [tech-news-digest](https://github.com/draco-agent/tech-news-digest), et la
veille emploi du même auteur.

## Licence

MIT : réutilisation libre, avec mention de l'auteure. Voir [`LICENSE`](LICENSE).
