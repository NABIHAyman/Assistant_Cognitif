# 🧠 Assistant Cognitif Personnel

> Un système de gestion de connaissances piloté par l'IA, conçu pour capturer, structurer et retrouver l'information à partir de captures d'écran mobiles.

---

## Vue d'ensemble

Ce projet transforme des captures d'écran (cours, posts techniques, recommandations culturelles) en une base de connaissances Markdown structurée, consultable et pérenne.

**Le principe** : tu glisses des images dans un dossier `inbox/`. L'orchestrateur les analyse via l'API Gemini, génère des propositions JSON. Tu valides chaque proposition via l'exécuteur interactif. Le contenu est fusionné dans ta mémoire Markdown.

```
images/inbox/  →  orchestrator  →  proposals/*.json  →  executor  →  memory/**/*.md
```

---

## Architecture

```
Assistant/
├── src/
│   ├── orchestrator_gemini.py   # Analyse les images via Gemini API
│   ├── executor.py              # Valide et fusionne les propositions
│   ├── search.py                # Recherche full-text dans memory/
│   ├── consolidate.py           # Détecte et fusionne les fichiers proches
│   └── list_models.py           # Utilitaire — liste les modèles disponibles
│
├── assistant/
│   ├── core/
│   │   └── instructions.md      # Configuration unique du LLM
│   ├── memory/
│   │   ├── inbox.md             # Fallback et triage
│   │   ├── culture/
│   │   │   └── watchlist.md     # Films, séries, animes
│   │   ├── tech/                # Notes techniques (code, frameworks)
│   │   ├── ai/                  # Architecture d'agents, outils IA
│   │   ├── proposals/           # JSON en attente de validation
│   │   ├── approved/            # JSON validés (archive)
│   │   ├── rejected/            # JSON rejetés (archive)
│   │   └── skipped/             # JSON reportés
│   ├── logs/                    # Journaux de session Markdown
│   └── prompts/                 # Audit des prompts générés
│
├── images/
│   ├── inbox/                   # 📥 Dépôt des images à traiter
│   ├── archive/                 # Images traitées
│   └── trash/                   # Images ignorées (bruit)
│
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env
```

---

## Stack technique

| Composant | Technologie |
|---|---|
| Runtime | Python 3.11 |
| Conteneur | Docker |
| LLM | Google Gemini (`gemini-2.5-flash-lite` recommandé) |
| SDK | `google-genai` 1.65.0 |
| Traitement image | Pillow |
| Config | python-dotenv |

---

## Installation

### Prérequis

- Docker Desktop installé
- Clé API Gemini ([obtenir ici](https://aistudio.google.com/))

### Setup

```bash
# 1. Cloner le repo
git clone https://github.com/ton-user/assistant-cognitif.git
cd assistant-cognitif

# 2. Configurer l'environnement
cp .env.example .env
# Éditer .env : renseigner GEMINI_API_KEY

# 3. Build et lancement
docker compose build
docker compose up -d
```

### `.env`

```env
GEMINI_API_KEY=ta_cle_api
GEMINI_MODEL=gemini-2.5-flash-lite
DRY_RUN=true
```

> ⚠️ Commence toujours avec `DRY_RUN=true` pour auditer les prompts avant tout appel API payant.

---

## Utilisation

### 1. Analyser les images

```bash
# Glisser les images dans images/inbox/, puis :
docker exec -it cognition_phase1 python src/orchestrator_gemini.py
```

Les propositions JSON sont générées dans `memory/proposals/`.

### 2. Valider les propositions

```bash
docker exec -it cognition_phase1 python src/executor.py
```

Commandes interactives : `[o]` Approuver · `[n]` Rejeter · `[s]` Skip · `[q]` Quitter

### 3. Rechercher dans la mémoire

```bash
# Recherche texte libre
docker exec -it cognition_phase1 python src/search.py "microservices"

# Recherche par tag
docker exec -it cognition_phase1 python src/search.py "python" --tags

# Lister tous les fichiers avec stats
docker exec -it cognition_phase1 python src/search.py --list
```

### 4. Consolider la mémoire

```bash
# Voir les candidats à la fusion (sans modifier)
docker exec -it cognition_phase1 python src/consolidate.py --dry-run

# Lancer la consolidation interactive
docker exec -it cognition_phase1 python src/consolidate.py
```

### 5. Diagnostiquer les modèles disponibles

```bash
docker exec -it cognition_phase1 python src/list_models.py
```

---

## Modèles Gemini recommandés

| Modèle | Usage | Quota free tier |
|---|---|---|
| `gemini-2.5-flash-lite` | Production — batches quotidiens | Généreux |
| `gemini-2.0-flash` | Fallback volumétrie | ~1500 req/jour |
| `gemini-2.5-flash` | Images difficiles ponctuelles | ~20 req/jour |

Pour les batches de 100+ images, le throttle proactif est intégré (4s entre chaque requête) — lance le script le soir, tout est prêt le lendemain matin.

---

## Configuration du LLM — `instructions.md`

Le comportement du système est entièrement piloté par `assistant/core/instructions.md`. C'est le seul fichier à modifier pour ajuster la classification, le nommage, ou le style de rédaction.

**Règles principales :**
- Ignore uniquement les erreurs manifestes (écran noir, flou illisible)
- `append` si le sujet existe déjà, `create` si 100% inédit
- Films/séries/animes → toujours `culture/watchlist.md`
- Nommage : `[domaine]_[concept]_[précision].md` (3 à 5 mots)
- Format watchlist : une ligne par entrée `- **Titre (Année)** — *Genre* : Raison. #tags`

---

## Workflow complet

```
┌─────────────────────────────────────────────────────────┐
│  1. Captures mobiles  →  images/inbox/                  │
│                                                         │
│  2. orchestrator_gemini.py                              │
│     ├── Optimise l'image (resize 1200px, WebP)          │
│     ├── Construit le prompt (instructions + fichiers)   │
│     ├── Appel Gemini API avec retry + throttle          │
│     └── Génère proposals/*.json                         │
│                                                         │
│  3. executor.py  (validation humaine)                   │
│     ├── [o] → fusionne dans memory/**/*.md              │
│     ├── [n] → archive dans rejected/                    │
│     └── [s] → reporte dans skipped/                     │
│                                                         │
│  4. search.py  →  retrouve n'importe quelle note        │
│  5. consolidate.py  →  fusionne les doublons            │
└─────────────────────────────────────────────────────────┘
```

---

## Roadmap

- [x] **Phase 1** — Pipeline orchestrator → proposals → executor
- [x] **Phase 2** — Recherche full-text (`search.py`) + consolidation (`consolidate.py`)
- [ ] **Phase 3** — Vector Search / RAG (quand memory/ dépasse ~50 fichiers)
- [ ] **Phase 4** — Interface web de consultation et validation

---

## Licence

MIT