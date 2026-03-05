"""
Moteur de Recherche - Phase 2
------------------------------
Rôle : Recherche full-text dans tous les fichiers .md de memory/.
       Affiche les extraits pertinents avec contexte et chemin de fichier.

Usage :
  docker exec -it cognition_phase1 python src/search.py "mot clé"
  docker exec -it cognition_phase1 python src/search.py "jwt auth" --tags
  docker exec -it cognition_phase1 python src/search.py "clean code" --file tech/clean_code.md
"""

import os
import re
import sys
import argparse
import datetime

# Chemins internes Docker
WORKSPACE = "/workspace"
MEMORY_DIR = f"{WORKSPACE}/assistant/memory"

# Dossiers à exclure de la recherche (gouvernance, pas mémoire)
DIRS_TO_IGNORE = ['proposals', 'approved', 'rejected', 'skipped']

# Nombre de lignes de contexte autour d'un match
CONTEXT_LINES = 3


def get_all_memory_files():
    """Retourne tous les fichiers .md de memory/ hors dossiers de gouvernance."""
    files = []
    if not os.path.exists(MEMORY_DIR):
        return files
    for root, dirs, filenames in os.walk(MEMORY_DIR):
        dirs[:] = [d for d in dirs if d not in DIRS_TO_IGNORE]
        for f in filenames:
            if f.endswith(".md"):
                files.append(os.path.join(root, f))
    return sorted(files)


def get_relative_path(full_path):
    """Retourne le chemin relatif depuis memory/."""
    return os.path.relpath(full_path, MEMORY_DIR)


def search_in_file(filepath, query, case_sensitive=False):
    """
    Cherche query dans le fichier.
    Retourne une liste de matches : (line_number, line, context_before, context_after).
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []

    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(re.escape(query), flags)

    matches = []
    for i, line in enumerate(lines):
        if pattern.search(line):
            start = max(0, i - CONTEXT_LINES)
            end = min(len(lines), i + CONTEXT_LINES + 1)
            context_before = lines[start:i]
            context_after = lines[i+1:end]
            matches.append({
                "line_number": i + 1,
                "line": line.rstrip(),
                "context_before": [l.rstrip() for l in context_before],
                "context_after": [l.rstrip() for l in context_after],
            })
    return matches


def search_by_tags(query):
    """
    Recherche par tag (#tag) dans tous les fichiers.
    Normalise la query en tag si besoin (ex: 'python' → '#python').
    """
    tag = query if query.startswith("#") else f"#{query}"
    return tag


def highlight(text, query, case_sensitive=False):
    """Entoure les occurrences de query avec des marqueurs visuels."""
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.sub(
        f"({re.escape(query)})",
        r">>> \1 <<<",
        text,
        flags=flags
    )


def display_results(results, query, total_files_searched):
    """Affiche les résultats de manière lisible."""
    total_matches = sum(len(m) for m in results.values())

    print(f"\n{'=' * 60}")
    print(f"🔍 Recherche : \"{query}\"")
    print(f"   {total_matches} occurrence(s) dans {len(results)} fichier(s) / {total_files_searched} scannés")
    print(f"{'=' * 60}")

    if not results:
        print("\n📭 Aucun résultat trouvé.")
        return

    for filepath, matches in results.items():
        rel_path = get_relative_path(filepath)
        print(f"\n📄 {rel_path}  ({len(matches)} match(es))")
        print(f"   {'─' * 50}")

        for match in matches:
            print(f"\n   Ligne {match['line_number']} :")

            # Contexte avant
            for ctx_line in match['context_before']:
                print(f"   │  {ctx_line}")

            # Ligne matchée avec highlight
            highlighted = highlight(match['line'], query)
            print(f"   ▶  {highlighted}")

            # Contexte après
            for ctx_line in match['context_after']:
                print(f"   │  {ctx_line}")

    print(f"\n{'=' * 60}")
    print(f"💡 Pour ouvrir un fichier : code {MEMORY_DIR}/<chemin>")
    print(f"{'=' * 60}\n")


def display_file_list(files):
    """Affiche la liste de tous les fichiers de la mémoire."""
    print(f"\n{'=' * 60}")
    print(f"📚 MÉMOIRE — {len(files)} fichier(s) indexé(s)")
    print(f"{'=' * 60}\n")

    # Grouper par dossier
    by_dir = {}
    for f in files:
        rel = get_relative_path(f)
        parts = rel.split(os.sep)
        folder = parts[0] if len(parts) > 1 else "."
        by_dir.setdefault(folder, []).append(rel)

    for folder, file_list in sorted(by_dir.items()):
        print(f"  📁 {folder}/")
        for f in sorted(file_list):
            # Compter les entrées (séparateurs ---) comme indicateur de richesse
            try:
                content = open(os.path.join(MEMORY_DIR, f), encoding="utf-8").read()
                entries = content.count("\n---\n")
                size = len(content)
                print(f"     - {os.path.basename(f)}  ({entries} entrée(s), {size} chars)")
            except Exception:
                print(f"     - {f}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Recherche full-text dans la mémoire de l'assistant.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python src/search.py "jwt"
  python src/search.py "#python" --tags
  python src/search.py "clean code" --case-sensitive
  python src/search.py --list
        """
    )
    parser.add_argument("query", nargs="?", help="Texte ou tag à rechercher")
    parser.add_argument("--tags", action="store_true", help="Recherche par tag (#tag)")
    parser.add_argument("--case-sensitive", action="store_true", help="Recherche sensible à la casse")
    parser.add_argument("--list", action="store_true", help="Affiche tous les fichiers de la mémoire")
    parser.add_argument("--file", help="Limite la recherche à un fichier spécifique (chemin relatif depuis memory/)")

    args = parser.parse_args()

    # Mode liste
    if args.list:
        files = get_all_memory_files()
        display_file_list(files)
        return

    # Query obligatoire hors mode --list
    if not args.query:
        parser.print_help()
        return

    query = args.query

    # Mode tag : normalise la query
    if args.tags:
        query = search_by_tags(query)
        print(f"🏷️  Mode tag — recherche de : {query}")

    # Sélection des fichiers à scanner
    if args.file:
        target = os.path.join(MEMORY_DIR, args.file)
        if not os.path.exists(target):
            print(f"❌ Fichier introuvable : {args.file}")
            return
        files = [target]
    else:
        files = get_all_memory_files()

    if not files:
        print("📭 Aucun fichier trouvé dans memory/.")
        return

    # Recherche
    results = {}
    for filepath in files:
        matches = search_in_file(filepath, query, args.case_sensitive)
        if matches:
            results[filepath] = matches

    display_results(results, query, len(files))


if __name__ == "__main__":
    main()