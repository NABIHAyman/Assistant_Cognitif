"""
Orchestrateur Cognitif - Phase 1 (V2.3 - Retry Backoff)
--------------------------------------------------------
Moteur : Google Gen AI SDK (Unifié - google-genai 1.65.0)
Modèles : gemini-2.0-flash / gemini-2.5-flash
Changements V2.3 :
- Retry automatique avec backoff sur erreur 429 (RESOURCE_EXHAUSTED).
- Suppression du JSON dupliqué dans le prompt (~150 tokens économisés).
  Le format JSON est uniquement dans build_system_prompt() / CONTRAINTE ABSOLUE.
  instructions.md ne doit plus contenir de section FORMAT DE SORTIE.
"""

import os
import re
import io
import json
import time
import shutil
import datetime
from google import genai
from google.genai import types
import PIL.Image
from dotenv import load_dotenv

# Chargement de la configuration
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Mode Audit (Dry Run) - Par défaut à True pour la sécurité
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 60  # secondes — plancher si retryDelay absent de la réponse

# Chemins internes Docker
WORKSPACE = "/workspace"
IMAGES_INBOX = f"{WORKSPACE}/images/inbox"
IMAGES_ARCHIVE = f"{WORKSPACE}/images/archive"
IMAGES_TRASH = f"{WORKSPACE}/images/trash"
CORE_DIR = f"{WORKSPACE}/assistant/core"
MEMORY_DIR = f"{WORKSPACE}/assistant/memory"
PROPOSALS_DIR = f"{MEMORY_DIR}/proposals"
LOGS_DIR = f"{WORKSPACE}/assistant/logs"
PROMPTS_DIR = f"{WORKSPACE}/assistant/prompts"


def read_file(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_existing_categories():
    categories = []
    dirs_to_ignore = ['proposals', 'approved', 'rejected', 'skipped']
    if os.path.exists(MEMORY_DIR):
        for root, dirs, files in os.walk(MEMORY_DIR):
            dirs[:] = [d for d in dirs if d not in dirs_to_ignore]
            for f in files:
                if f.endswith(".md") and f != "inbox.md":
                    rel_dir = os.path.relpath(root, MEMORY_DIR)
                    categories.append(f if rel_dir == "." else f"{rel_dir}/{f}")
    return categories


def sanitize_filename(name):
    name = name.replace("/", "_").replace("\\", "_")
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name)


def extract_json_safely(text):
    text = text.replace("```json\n", "").replace("```", "").strip()
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if not match:
        start, end = text.find('{'), text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise ValueError("Aucun objet JSON valide trouvé dans la réponse.")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        start, end = text.find('{'), text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise ValueError("Le JSON extrait est invalide.")


def extract_retry_delay(error_str):
    """Extrait le retryDelay en secondes depuis le message d'erreur 429."""
    match = re.search(r'retryDelay.*?(\d+)s', error_str)
    if match:
        return int(match.group(1)) + 5  # +5s de marge
    return RETRY_BASE_DELAY


def build_system_prompt():
    """
    Charge uniquement instructions.md.
    IMPORTANT : instructions.md ne doit PAS contenir de section FORMAT DE SORTIE —
    le format JSON est défini ici dans CONTRAINTE ABSOLUE pour éviter la duplication.
    """
    rules = read_file(f"{CORE_DIR}/instructions.md")

    existing_files = get_existing_categories()
    files_str = "\n- ".join(existing_files) if existing_files else "Aucun fichier existant."

    return f"""
{rules}

LISTE DES FICHIERS EXISTANTS (Chemins relatifs) :
- {files_str}

CONTRAINTE ABSOLUE :
Réponds EXCLUSIVEMENT avec un objet JSON valide, sans texte avant ou après :
{{
  "analyse_visuelle": "Description brève.",
  "valeur_extraite": "L'info utile.",
  "action_proposee": "append | create | ignore",
  "fichier_cible": "dossier/fichier.md (null si ignore)",
  "tags": ["#tag1", "#tag2"],
  "justification": "Pourquoi ce choix ?",
  "contenu_markdown": "Le texte extrait et formaté en Markdown propre (null si ignore)"
}}
    """


def log_prompt(prompt, filename):
    """Sauvegarde le prompt généré pour audit. Zéro appel réseau en DRY_RUN."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_file = os.path.join(PROMPTS_DIR, f"prompt_{timestamp}_{sanitize_filename(filename)}.md")

    if not DRY_RUN:
        try:
            count = client.models.count_tokens(model=MODEL_NAME, contents=prompt)
            token_info = f"{count.total_tokens} tokens (Compte exact API)"
        except Exception:
            approx_tokens = int(len(prompt.split()) * 1.3)
            token_info = f"~{approx_tokens} tokens (Estimation locale, API injoignable)"
    else:
        approx_tokens = int(len(prompt.split()) * 1.3)
        token_info = f"~{approx_tokens} tokens (Estimation locale, Mode Audit Offline)"

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"# 🧪 Audit du Prompt\n\n")
        f.write(f"**Image source :** `{filename}`\n")
        f.write(f"**Taille du prompt :** {token_info}\n\n")
        f.write("---\n```text\n")
        f.write(prompt)
        f.write("\n```\n")

    print(f"🧾 Prompt loggé : {log_file} | {token_info}")


def call_api_with_retry(system_prompt, optimized_img):
    """
    Appel API avec retry automatique sur 429.
    Lit le retryDelay dans le message d'erreur et attend ce délai avant de retenter.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=["Analyse cette image et génère le JSON.", optimized_img],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json"
                )
            )
            return response

        except Exception as e:
            error_str = str(e)
            is_quota = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str

            if is_quota and attempt < MAX_RETRIES:
                delay = extract_retry_delay(error_str)
                print(f"   ⏳ Quota atteint (tentative {attempt}/{MAX_RETRIES}). Attente {delay}s...")
                time.sleep(delay)
                continue

            # Erreur non-quota ou dernière tentative
            raise


def process_image(filename, stats):
    image_path = os.path.join(IMAGES_INBOX, filename)
    print(f"\n🔄 Analyse de : {filename}...")

    system_prompt = build_system_prompt()
    log_prompt(system_prompt, filename)

    if DRY_RUN:
        print("🧪 Mode DRY_RUN actif — Appel API ignoré. L'image reste dans l'inbox.")
        stats["dry_runs"] += 1
        return

    try:
        with PIL.Image.open(image_path) as img:
            # Optimisation image avant envoi à l'API
            max_size = 1200
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size), PIL.Image.Resampling.LANCZOS)
                print(f"   📐 Image redimensionnée : {img.size}")

            buffer = io.BytesIO()
            img.save(buffer, format="WEBP", quality=80)
            buffer.seek(0)
            optimized_img = PIL.Image.open(buffer)

            response = call_api_with_retry(system_prompt, optimized_img)

        data = extract_json_safely(response.text)

    except Exception as e:
        print(f"❌ Erreur sur {filename} : {e}")
        stats["erreurs"] += 1
        return

    action = data.get('action_proposee', '').lower()
    tags = data.get('tags', [])

    # Bloc ignore
    if action == "ignore":
        print(f"🗑️ BRUIT DÉTECTÉ : L'image a été ignorée.")
        print(f"   Justification : {data.get('justification')}")
        shutil.move(image_path, os.path.join(IMAGES_TRASH, filename))
        stats["ignorees"] += 1
        return

    # Bouclier Anti-Tags-Vides
    if action in ["append", "create"] and not tags:
        print(f"⚠️ AVERTISSEMENT : Tags vides. Injection du tag fallback '#a_classifier'.")
        tags = ["#a_classifier"]
        data["tags"] = tags

    # Enrichissement avec métadonnées de traçabilité
    data["_meta"] = {
        "source_image": filename,
        "processed_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": MODEL_NAME
    }

    # Sauvegarde en .json (transport pur pour l'executor)
    fichier_cible = data.get('fichier_cible') or "inbox.md"
    safe_target_name = sanitize_filename(fichier_cible)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    proposal_filename = f"proposal_{timestamp}_{safe_target_name}.json"
    proposal_path = os.path.join(PROPOSALS_DIR, proposal_filename)

    with open(proposal_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"✅ Proposition JSON générée : {proposal_filename}")
    shutil.move(image_path, os.path.join(IMAGES_ARCHIVE, filename))
    stats["traitees"] += 1


def write_session_log(stats):
    """Formatage markdown complet de la session."""
    # Défensif : si 'logs' existe en tant que fichier (collision), on le supprime
    if os.path.exists(LOGS_DIR) and not os.path.isdir(LOGS_DIR):
        os.remove(LOGS_DIR)
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_filename = f"{LOGS_DIR}/session_{datetime.datetime.now().strftime('%Y%m%d')}.md"

    total = stats["traitees"] + stats["ignorees"] + stats["erreurs"] + stats["dry_runs"]

    with open(log_filename, "a", encoding="utf-8") as f:
        f.write(f"## Session du {timestamp}\n")
        f.write(f"- **Total d'images scannées :** {total}\n")
        if stats["dry_runs"] > 0:
            f.write(f"- **Mode Audit (Dry Runs) :** {stats['dry_runs']}\n")
        f.write(f"- **Propositions générées :** {stats['traitees']}\n")
        f.write(f"- **Bruit filtré (ignorées) :** {stats['ignorees']}\n")
        if stats["erreurs"] > 0:
            f.write(f"- **Erreurs rencontrées :** {stats['erreurs']}\n")
        f.write("---\n")


def main():
    print("====================================")
    print("🧠 ASSISTANT COGNITIF - V2.3 (Retry Backoff)")
    if DRY_RUN:
        print("⚠️  MODE AUDIT ACTIF (DRY_RUN=true) - 100% Hors-ligne.")
    print("====================================\n")

    os.makedirs(PROPOSALS_DIR, exist_ok=True)
    os.makedirs(IMAGES_ARCHIVE, exist_ok=True)
    os.makedirs(IMAGES_TRASH, exist_ok=True)
    os.makedirs(PROMPTS_DIR, exist_ok=True)

    stats = {"traitees": 0, "ignorees": 0, "erreurs": 0, "dry_runs": 0}

    images = [f for f in os.listdir(IMAGES_INBOX) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]

    if not images:
        print("📭 Aucune image en attente dans /images/inbox/.")
        return

    for image in images:
        process_image(image, stats)

    write_session_log(stats)
    print("\n🏁 Batch terminé. Journal de session mis à jour.")


if __name__ == "__main__":
    main()