"""
Consolidateur de Mémoire - Phase 2
------------------------------------
Rôle : Détecter les fichiers thématiquement proches dans memory/,
       proposer des fusions, et les exécuter après validation humaine.

Workflow :
  1. Scan de tous les fichiers .md de memory/
  2. Calcul de similarité par tags et mots-clés communs
  3. Affichage des paires candidates à la fusion
  4. Décision humaine : f (fusionner) / s (skip) / q (quitter)
  5. Si fusion validée :
     - Appel LLM pour générer un nom de fichier consolidé
     - Concaténation du contenu des deux fichiers
     - Suppression des fichiers sources
     - Log de session

Usage :
  docker exec -it cognition_phase1 python src/consolidate.py
  docker exec -it cognition_phase1 python src/consolidate.py --threshold 0.4
"""

import os
import re
import json
import shutil
import argparse
import datetime
from collections import Counter

# Chemins internes Docker
WORKSPACE = "/workspace"
MEMORY_DIR = f"{WORKSPACE}/assistant/memory"
LOGS_DIR = f"{WORKSPACE}/assistant/logs"

# Dossiers à exclure
DIRS_TO_IGNORE = ['proposals', 'approved', 'rejected', 'skipped']

# Seuil de similarité par défaut (0.0 → 1.0)
DEFAULT_THRESHOLD = 0.35

# Mots vides à ignorer dans l'analyse de similarité
STOPWORDS = {
    'le', 'la', 'les', 'de', 'du', 'des', 'un', 'une', 'et', 'en',
    'est', 'pour', 'dans', 'sur', 'avec', 'par', 'the', 'a', 'an',
    'of', 'to', 'in', 'and', 'or', 'for', 'is', 'are', 'this', 'that',
    'it', 'as', 'at', 'be', 'has', 'have', 'was', 'were', 'but', 'not',
    'from', 'by', 'which', 'when', 'all', 'also', 'its', 'can', 'will',
    'ce', 'qui', 'que', 'se', 'si', 'au', 'aux', 'il', 'elle', 'ils',
    'nous', 'vous', 'leur', 'leurs', 'on', 'ou', 'ne', 'pas', 'plus',
}


def get_all_memory_files():
    """Retourne tous les fichiers .md de memory/ hors dossiers de gouvernance."""
    files = []
    if not os.path.exists(MEMORY_DIR):
        return files
    for root, dirs, filenames in os.walk(MEMORY_DIR):
        dirs[:] = [d for d in dirs if d not in DIRS_TO_IGNORE]
        for f in filenames:
            if f.endswith(".md") and f != "inbox.md":
                files.append(os.path.join(root, f))
    return sorted(files)


def get_relative_path(full_path):
    return os.path.relpath(full_path, MEMORY_DIR)


def extract_tags(content):
    """Extrait tous les #tags du contenu."""
    return set(re.findall(r'#[\w]+', content, re.IGNORECASE))


def extract_keywords(content):
    """Extrait les mots significatifs du contenu (hors stopwords, hors markdown)."""
    # Supprime les blocs de code
    content = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
    # Supprime les URLs
    content = re.sub(r'https?://\S+', '', content)
    # Supprime la ponctuation markdown
    content = re.sub(r'[#*`_\[\]()>\-|]', ' ', content)
    # Tokenise
    words = re.findall(r'\b[a-zA-ZÀ-ÿ]{4,}\b', content.lower())
    return Counter(w for w in words if w not in STOPWORDS)


def jaccard_similarity(set_a, set_b):
    """Similarité de Jaccard entre deux ensembles."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def compute_similarity(content_a, content_b):
    """
    Score de similarité composite :
    - 60% similarité des tags
    - 40% similarité des mots-clés (top 30)
    """
    tags_a = extract_tags(content_a)
    tags_b = extract_tags(content_b)
    tag_score = jaccard_similarity(tags_a, tags_b)

    kw_a = set(k for k, _ in extract_keywords(content_a).most_common(30))
    kw_b = set(k for k, _ in extract_keywords(content_b).most_common(30))
    kw_score = jaccard_similarity(kw_a, kw_b)

    return round(0.6 * tag_score + 0.4 * kw_score, 3)


def generate_merged_filename(path_a, path_b):
    """
    Génère un nom de fichier fusionné à partir des deux noms sources.
    Convention : [concept_a]_and_[concept_b].md (max 5 mots, underscores)
    """
    def stem(path):
        return os.path.splitext(os.path.basename(path))[0]

    name_a = stem(path_a)
    name_b = stem(path_b)

    # Si même dossier, on combine les noms
    dir_a = os.path.dirname(get_relative_path(path_a))
    dir_b = os.path.dirname(get_relative_path(path_b))

    # Extraction des mots uniques de chaque nom
    words_a = name_a.split('_')
    words_b = name_b.split('_')

    # Mots communs → préfixe, mots distincts → suffixe
    common = [w for w in words_a if w in words_b]
    unique_a = [w for w in words_a if w not in words_b]
    unique_b = [w for w in words_b if w not in words_a]

    if common:
        merged_words = common + unique_a[:2] + unique_b[:2]
    else:
        merged_words = words_a[:3] + words_b[:2]

    # Limite à 5 mots
    merged_name = '_'.join(merged_words[:5]) + '.md'

    # Dossier cible : dossier commun ou dossier de a
    target_dir = dir_a if dir_a == dir_b else dir_a
    return os.path.join(target_dir, merged_name) if target_dir != '.' else merged_name


def find_candidates(files, threshold):
    """Trouve toutes les paires de fichiers dépassant le seuil de similarité."""
    candidates = []
    contents = {}

    for f in files:
        try:
            with open(f, encoding='utf-8') as fh:
                contents[f] = fh.read()
        except Exception:
            contents[f] = ""

    for i in range(len(files)):
        for j in range(i + 1, len(files)):
            score = compute_similarity(contents[files[i]], contents[files[j]])
            if score >= threshold:
                candidates.append((score, files[i], files[j]))

    # Tri par score décroissant
    return sorted(candidates, key=lambda x: x[0], reverse=True)


def display_candidate(score, path_a, path_b, contents):
    """Affiche une paire candidate de manière lisible."""
    rel_a = get_relative_path(path_a)
    rel_b = get_relative_path(path_b)

    tags_a = extract_tags(contents[path_a])
    tags_b = extract_tags(contents[path_b])
    common_tags = tags_a & tags_b

    size_a = len(contents[path_a])
    size_b = len(contents[path_b])

    print(f"\n{'=' * 60}")
    print(f"🔗 PAIRE CANDIDATE — Score : {score:.1%}")
    print(f"{'=' * 60}")
    print(f"  A : {rel_a}  ({size_a} chars)")
    print(f"  B : {rel_b}  ({size_b} chars)")
    if common_tags:
        print(f"  Tags communs : {' '.join(sorted(common_tags))}")
    else:
        print(f"  Tags A : {' '.join(sorted(tags_a)) or 'aucun'}")
        print(f"  Tags B : {' '.join(sorted(tags_b)) or 'aucun'}")

    merged_name = generate_merged_filename(path_a, path_b)
    print(f"  Nom fusionné proposé : {merged_name}")
    print(f"{'─' * 60}")

    # Aperçu du contenu A
    lines_a = contents[path_a].split('\n')
    preview_a = '\n'.join(lines_a[:5]).strip()
    print(f"\n  📄 Aperçu A :\n  {preview_a[:200]}")

    # Aperçu du contenu B
    lines_b = contents[path_b].split('\n')
    preview_b = '\n'.join(lines_b[:5]).strip()
    print(f"\n  📄 Aperçu B :\n  {preview_b[:200]}")

    print(f"\n{'=' * 60}")
    return merged_name


def execute_merge(path_a, path_b, merged_rel_path, contents):
    """
    Fusionne les deux fichiers en un seul.
    - Crée le fichier fusionné avec en-tête + contenu A + séparateur + contenu B
    - Supprime les fichiers sources
    """
    merged_full_path = os.path.join(MEMORY_DIR, merged_rel_path)
    os.makedirs(os.path.dirname(merged_full_path), exist_ok=True)

    rel_a = get_relative_path(path_a)
    rel_b = get_relative_path(path_b)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    title = os.path.splitext(os.path.basename(merged_full_path))[0].replace('_', ' ').title()

    with open(merged_full_path, 'w', encoding='utf-8') as f:
        f.write(f"# {title}\n\n")
        f.write(f"*Consolidé le {timestamp} — Fusion de `{rel_a}` et `{rel_b}`*\n\n")
        f.write("---\n\n")
        # Contenu A (sans le titre H1 s'il existe)
        content_a = re.sub(r'^#\s+.+\n', '', contents[path_a], count=1).strip()
        f.write(content_a)
        f.write(f"\n\n---\n*Contenu fusionné depuis `{rel_b}`*\n\n")
        # Contenu B (sans le titre H1 s'il existe)
        content_b = re.sub(r'^#\s+.+\n', '', contents[path_b], count=1).strip()
        f.write(content_b)
        f.write("\n")

    # Suppression des fichiers sources
    os.remove(path_a)
    os.remove(path_b)

    print(f"✅ Fusionné → {merged_rel_path}")
    print(f"   Supprimé : {rel_a}")
    print(f"   Supprimé : {rel_b}")

    return merged_full_path


def write_consolidation_log(stats):
    """Log de session du consolidateur."""
    if os.path.exists(LOGS_DIR) and not os.path.isdir(LOGS_DIR):
        os.remove(LOGS_DIR)
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_filename = f"{LOGS_DIR}/session_{datetime.datetime.now().strftime('%Y%m%d')}.md"

    with open(log_filename, 'a', encoding='utf-8') as f:
        f.write(f"## Consolidation du {timestamp}\n")
        f.write(f"- **Paires analysées :** {stats['analysees']}\n")
        f.write(f"- **Fusions effectuées :** {stats['fusionnees']}\n")
        f.write(f"- **Skippées :** {stats['skippees']}\n")
        f.write("---\n")


def main():
    parser = argparse.ArgumentParser(
        description="Détecte et fusionne les fichiers thématiquement proches.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python src/consolidate.py
  python src/consolidate.py --threshold 0.4
  python src/consolidate.py --dry-run
        """
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"Seuil de similarité (défaut : {DEFAULT_THRESHOLD}). Plus élevé = moins de candidats."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche les candidats sans demander de validation."
    )
    args = parser.parse_args()

    print("====================================")
    print("🔗 CONSOLIDATEUR DE MÉMOIRE - Phase 2")
    print(f"   Seuil de similarité : {args.threshold:.0%}")
    if args.dry_run:
        print("   Mode DRY-RUN — aucune modification.")
    print("====================================\n")

    files = get_all_memory_files()

    if len(files) < 2:
        print("📭 Moins de 2 fichiers dans memory/ — rien à consolider.")
        return

    print(f"📚 {len(files)} fichier(s) scanné(s)...")

    # Chargement des contenus
    contents = {}
    for f in files:
        try:
            with open(f, encoding='utf-8') as fh:
                contents[f] = fh.read()
        except Exception:
            contents[f] = ""

    candidates = find_candidates(files, args.threshold)

    if not candidates:
        print(f"\n✅ Aucune paire similaire trouvée au-dessus de {args.threshold:.0%}.")
        print("   Ta mémoire est bien fragmentée — pas de consolidation nécessaire.")
        return

    print(f"\n🔍 {len(candidates)} paire(s) candidate(s) trouvée(s).\n")

    if args.dry_run:
        for score, path_a, path_b in candidates:
            display_candidate(score, path_a, path_b, contents)
        return

    print("Commandes : [f] Fusionner  [s] Skip  [r] Renommer  [q] Quitter\n")

    stats = {"analysees": 0, "fusionnees": 0, "skippees": 0}
    processed = 0

    # Fichiers déjà supprimés (après fusion) — à ignorer dans les paires suivantes
    deleted = set()

    for score, path_a, path_b in candidates:
        # Skip si l'un des fichiers a déjà été fusionné
        if path_a in deleted or path_b in deleted:
            continue

        merged_name = display_candidate(score, path_a, path_b, contents)
        processed += 1
        remaining = len(candidates) - processed
        print(f"[{processed}/{len(candidates)}] — {remaining} restante(s).")

        while True:
            choix = input("\n👉 Action [f/s/r/q] : ").strip().lower()
            if choix in ('f', 's', 'r', 'q'):
                break
            print("   Commande invalide. Tape 'f', 's', 'r' ou 'q'.")

        if choix == 'q':
            print("\n⏹️  Session interrompue.")
            break

        elif choix == 'f':
            execute_merge(path_a, path_b, merged_name, contents)
            deleted.add(path_a)
            deleted.add(path_b)
            stats["fusionnees"] += 1

        elif choix == 'r':
            custom = input("   Nouveau nom (chemin relatif depuis memory/, ex: tech/mon_fichier.md) : ").strip()
            if custom:
                merged_name = custom
            execute_merge(path_a, path_b, merged_name, contents)
            deleted.add(path_a)
            deleted.add(path_b)
            stats["fusionnees"] += 1

        elif choix == 's':
            print("⏭️  Paire ignorée.")
            stats["skippees"] += 1

        stats["analysees"] += 1

    write_consolidation_log(stats)
    print(f"\n🏁 Session terminée.")
    print(f"   Fusions : {stats['fusionnees']} | Skippées : {stats['skippees']}")


if __name__ == "__main__":
    main()