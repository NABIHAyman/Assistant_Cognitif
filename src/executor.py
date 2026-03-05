"""
Exécuteur Cognitif - Phase 1 (V2.1 - Fusion Optimale)
------------------------------------------------------
Rôle : Lire les propositions .json dans memory/proposals/,
       les présenter une par une, et exécuter l'action validée.

Workflow :
  1. Scan de memory/proposals/*.json
  2. Validation de cohérence interne (contrat approval.md)
  3. Affichage de chaque proposition dans le terminal
  4. Décision humaine : o (approuver) / n (rejeter) / s (skip) / q (quitter)
  5. Si approuvé → write_to_memory() (create ou append, logique unifiée)
     - Déplace la proposition vers memory/approved/
  6. Si rejeté  → memory/rejected/
  7. Si skip    → memory/skipped/
  8. Log de session mis à jour
"""

import os
import json
import shutil
import datetime

# Chemins internes Docker
WORKSPACE = "/workspace"
MEMORY_DIR = f"{WORKSPACE}/assistant/memory"
PROPOSALS_DIR = f"{MEMORY_DIR}/proposals"
APPROVED_DIR = f"{MEMORY_DIR}/approved"
REJECTED_DIR = f"{MEMORY_DIR}/rejected"
SKIPPED_DIR = f"{MEMORY_DIR}/skipped"
LOGS_DIR = f"{WORKSPACE}/assistant/logs"


def validate_proposal(data):
    """Vérifie la complétude du contrat de données (règles approval.md)."""
    required = ["action_proposee", "fichier_cible", "contenu_markdown", "tags",
                "analyse_visuelle", "valeur_extraite", "justification"]
    for field in required:
        if field not in data:
            return False, f"Champ manquant : '{field}'"

    action = data["action_proposee"]
    if action in ["append", "create"]:
        if not data["fichier_cible"]:
            return False, "fichier_cible est null pour une action positive."
        if not data["contenu_markdown"]:
            return False, "contenu_markdown est null pour une action positive."
        if not data["tags"]:
            return False, "tags est vide pour une action positive."

    return True, "OK"


def display_proposal(filename, data):
    """Affiche la proposition de manière lisible dans le terminal."""
    meta = data.get("_meta", {})
    print("\n" + "=" * 60)
    print(f"📄 PROPOSITION : {filename}")
    print("=" * 60)
    print(f"  Source       : {meta.get('source_image', 'N/A')}")
    print(f"  Traité le    : {meta.get('processed_at', 'N/A')}")
    print(f"  Modèle       : {meta.get('model', 'N/A')}")
    print(f"  Action       : {data.get('action_proposee', 'N/A').upper()}")
    print(f"  Fichier cible: {data.get('fichier_cible', 'N/A')}")
    print(f"  Tags         : {' '.join(data.get('tags', []))}")
    print(f"  Analyse      : {data.get('analyse_visuelle', 'N/A')}")
    print(f"  Valeur       : {data.get('valeur_extraite', 'N/A')}")
    print(f"  Justification: {data.get('justification', 'N/A')}")
    print("-" * 60)
    print("📄 CONTENU À INSÉRER :")
    print("-" * 60)
    contenu = data.get("contenu_markdown") or "(aucun contenu)"
    lines = contenu.split("\n")
    if len(lines) > 20:
        print("\n".join(lines[:20]))
        print(f"\n... [{len(lines) - 20} lignes supplémentaires non affichées]")
    else:
        print(contenu)
    print("=" * 60)


def write_to_memory(data):
    """
    Fonction unifiée create + append.
    - Si le fichier n'existe pas : mode 'w' avec en-tête automatique (create).
    - Si le fichier existe       : mode 'a' sous séparateur --- horodaté (append).
    Retourne True si le fichier existait déjà (append), False si créé.
    """
    fichier_cible = data["fichier_cible"]
    full_path = os.path.join(MEMORY_DIR, fichier_cible)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    exists = os.path.exists(full_path)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tags_str = " ".join(data.get("tags", []))

    meta = data.get("_meta", {})
    source = meta.get("source_image", "N/A")

    entry = (
        f"\n\n---\n"
        f"### 📅 Intégré le {timestamp}\n"
        f"*Source : `{source}` | Tags : {tags_str}*  \n"
        f"**Justification :** {data.get('justification', 'N/A')}\n\n"
        f"{data['contenu_markdown']}\n"
    )

    with open(full_path, "a" if exists else "w", encoding="utf-8") as f:
        if not exists:
            # En-tête automatique pour les nouveaux fichiers
            title = os.path.splitext(os.path.basename(fichier_cible))[0].replace("_", " ").title()
            f.write(f"# {title}\n")
        f.write(entry)

    action_label = "Fusionné dans" if exists else "Créé"
    print(f"✅ {action_label} : {fichier_cible}")
    return exists


def write_executor_log(stats):
    """Log de session de l'exécuteur."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_filename = f"{LOGS_DIR}/session_{datetime.datetime.now().strftime('%Y%m%d')}.md"

    total = stats["approuvees"] + stats["rejetees"] + stats["skippees"] + stats["invalides"]

    with open(log_filename, "a", encoding="utf-8") as f:
        f.write(f"## Exécution du {timestamp}\n")
        f.write(f"- **Total de propositions traitées :** {total}\n")
        f.write(f"- **Approuvées et intégrées :** {stats['approuvees']}\n")
        f.write(f"- **Rejetées :** {stats['rejetees']}\n")
        if stats["skippees"] > 0:
            f.write(f"- **Skippées (reportées) :** {stats['skippees']}\n")
        if stats["invalides"] > 0:
            f.write(f"- **Invalides (rejetées auto) :** {stats['invalides']}\n")
        if stats["interrompue"] > 0:
            f.write(f"- **Session interrompue (quit) :** {stats['interrompue']} non traitées\n")
        f.write("---\n")


def main():
    print("====================================")
    print("✅ EXÉCUTEUR COGNITIF - V2.1")
    print("====================================\n")

    for d in [APPROVED_DIR, REJECTED_DIR, SKIPPED_DIR]:
        os.makedirs(d, exist_ok=True)

    proposals = sorted([
        f for f in os.listdir(PROPOSALS_DIR)
        if f.endswith(".json") and f.startswith("proposal_")
    ])

    if not proposals:
        print("📭 Aucune proposition JSON en attente dans memory/proposals/.")
        return

    total = len(proposals)
    print(f"📬 {total} proposition(s) en attente.\n")
    print("Commandes : [o] Approuver  [n] Rejeter  [s] Skip  [q] Quitter\n")

    stats = {"approuvees": 0, "rejetees": 0, "skippees": 0, "invalides": 0, "interrompue": 0}
    processed = 0

    for proposal_file in proposals:
        proposal_path = os.path.join(PROPOSALS_DIR, proposal_file)

        # Lecture JSON
        try:
            with open(proposal_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"\n❌ Erreur lecture {proposal_file} : {e}")
            shutil.move(proposal_path, os.path.join(REJECTED_DIR, proposal_file))
            stats["invalides"] += 1
            processed += 1
            continue

        # Validation du contrat
        is_valid, msg = validate_proposal(data)
        if not is_valid:
            print(f"\n⚠️  Proposition invalide ({proposal_file}) : {msg} → Rejet automatique.")
            shutil.move(proposal_path, os.path.join(REJECTED_DIR, proposal_file))
            stats["invalides"] += 1
            processed += 1
            continue

        # Alerte create → fichier existe déjà
        if data["action_proposee"] == "create":
            target_path = os.path.join(MEMORY_DIR, data["fichier_cible"])
            if os.path.exists(target_path):
                print(f"\n❗ ATTENTION : Action 'create' mais '{data['fichier_cible']}' existe déjà. Ce sera un APPEND.")

        display_proposal(proposal_file, data)
        remaining = total - processed - 1
        print(f"[{processed + 1}/{total}] — {remaining} restante(s) après celle-ci.")

        # Boucle de décision
        while True:
            choix = input("\n👉 Décision [o/n/s/q] : ").strip().lower()
            if choix in ("o", "n", "s", "q"):
                break
            print("   Commande invalide. Tape 'o', 'n', 's' ou 'q'.")

        if choix == "q":
            remaining_after = total - processed - 1
            stats["interrompue"] = remaining_after
            print(f"\n⏹️  Session interrompue. {remaining_after} proposition(s) non traitée(s).")
            break

        elif choix == "o":
            action = data["action_proposee"]
            if action in ("append", "create"):
                write_to_memory(data)
            else:
                print(f"⚠️  Action inconnue '{action}'. Proposition rejetée.")
                shutil.move(proposal_path, os.path.join(REJECTED_DIR, proposal_file))
                stats["rejetees"] += 1
                processed += 1
                continue

            shutil.move(proposal_path, os.path.join(APPROVED_DIR, proposal_file))
            stats["approuvees"] += 1

        elif choix == "n":
            shutil.move(proposal_path, os.path.join(REJECTED_DIR, proposal_file))
            stats["rejetees"] += 1
            print("🗑️  Proposition rejetée.")

        elif choix == "s":
            shutil.move(proposal_path, os.path.join(SKIPPED_DIR, proposal_file))
            stats["skippees"] += 1
            print("⏭️  Mis de côté (skipped) — disponible pour une prochaine session.")

        processed += 1

    write_executor_log(stats)
    print(f"\n🏁 Session terminée.")
    print(f"   Approuvées : {stats['approuvees']} | Rejetées : {stats['rejetees']} | Skippées : {stats['skippees']}")


if __name__ == "__main__":
    main()