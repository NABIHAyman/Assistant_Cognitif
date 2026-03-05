"""
Orchestrateur Cognitif - Phase 1 (V1.2 - Version Ultra-Blindée)
---------------------------------------------------------------
Améliorations :
- V1.1 : Scan profond (os.walk), Trash, Logging.
- V1.2 : Extraction JSON défensive (Regex + Fallback manuel anti-gourmandise).
"""

import os
import re
import json
import base64
import shutil
import datetime
from anthropic import Anthropic
from dotenv import load_dotenv

# Chargement sécurisé de la configuration
load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Modèle dynamique
MODEL_NAME = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

# Chemins internes
WORKSPACE = "/workspace"
IMAGES_INBOX = f"{WORKSPACE}/images/inbox"
IMAGES_ARCHIVE = f"{WORKSPACE}/images/archive"
IMAGES_TRASH = f"{WORKSPACE}/images/trash"
CORE_DIR = f"{WORKSPACE}/assistant/core"
MEMORY_DIR = f"{WORKSPACE}/assistant/memory"
PROPOSALS_DIR = f"{MEMORY_DIR}/proposals"
LOGS_DIR = f"{WORKSPACE}/assistant/logs"

def read_file(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def get_existing_categories():
    """Scanne récursivement la mémoire pour trouver les fichiers .md."""
    categories = []
    dirs_to_ignore = ['proposals', 'approved', 'rejected']
    
    if os.path.exists(MEMORY_DIR):
        for root, dirs, files in os.walk(MEMORY_DIR):
            dirs[:] = [d for d in dirs if d not in dirs_to_ignore]
            for f in files:
                if f.endswith(".md") and f != "inbox.md":
                    rel_dir = os.path.relpath(root, MEMORY_DIR)
                    if rel_dir == ".":
                        categories.append(f)
                    else:
                        categories.append(f"{rel_dir}/{f}")
    return categories

def extract_json_safely(text):
    """V1.2 : Regex défensive anti-gourmandise avec fallback manuel."""
    # Nettoyage basique des balises markdown si le LLM en génère
    text = text.replace("```json\n", "").replace("```", "").strip()
    
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if not match:
        # Fallback de sécurité : on cherche la première et dernière accolade manuellement
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise ValueError("Aucun objet JSON valide trouvé dans la réponse.")
    
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        # Si la regex échoue à cause d'une imbrication complexe, le fallback manuel sauve la mise
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise ValueError("Le JSON extrait est invalide.")

def build_system_prompt():
    identity = read_file(f"{CORE_DIR}/identity.md")
    rules = read_file(f"{CORE_DIR}/rules.md")
    approval = read_file(f"{CORE_DIR}/approval.md")

    existing_files = get_existing_categories()
    files_str = "\n- ".join(existing_files) if existing_files else "Aucun fichier existant. Tu devras proposer 'create'."

    return f"""
    {identity}
    {rules}
    {approval}

    MISSION :
    Tu es le Routeur Sémantique et le Filtre Anti-Bruit de ce système de gestion de connaissances. Tu vas recevoir une image (photo ou capture d'écran).
    Tu dois l'analyser, en extraire la valeur PROFONDE, et proposer une classification.

    DIRECTIVES D'ANALYSE :
    1. Cherche au-delà de l'évidence : Sur une capture de réseau social, ignore l'image principale si elle est inutile, et concentre-toi sur les textes, commentaires, noms d'outils ou technos mentionnés.
    2. Identifie le contexte : Si c'est une photo de tableau blanc, déduis qu'il s'agit de cours ou de brainstorming technique.
    3. Filtre le bruit : Les écrans noirs, les blagues/memes, ou l'art purement visuel sans information textuelle ou architecturale doivent être classés comme inutiles pour la base de connaissances.

    LISTE DES FICHIERS EXISTANTS (Chemins relatifs) :
    - {files_str}
    
    Règle : Tu DOIS utiliser un fichier de cette liste si le thème correspond (action: 'append'). Tu ne proposes 'create' que si le sujet est radicalement nouveau.

    CONTRAINTE ABSOLUE :
    Tu ne dois répondre QUE par un objet JSON valide. Format strict attendu :
    {{
      "analyse_visuelle": "Description brève de l'image ET de ce qui s'y cache.",
      "valeur_extraite": "Quelle est l'information utile ici ? (Outils, concepts, reco film, etc.). Mettre 'Aucune' si c'est du bruit.",
      "action_proposee": "append | create | ignore",
      "fichier_cible": "dossier/nom_du_fichier.md (mettre null si action est 'ignore')",
      "tags": ["#tag1", "#tag2"],
      "justification": "Pourquoi ce choix de fichier ou pourquoi l'ignorer ?",
      "contenu_markdown": "Le texte extrait, structuré, nettoyé et formaté en markdown. (Mettre null si action est 'ignore')"
    }}
    """

def process_image(filename, stats):
    image_path = os.path.join(IMAGES_INBOX, filename)
    print(f"\n🔄 Analyse de : {filename}...")

    base64_image = encode_image_to_base64(image_path)
    media_type = "image/png" if filename.lower().endswith("png") else "image/jpeg"
    system_prompt = build_system_prompt()

    try:
        response = client.messages.create(
            model=MODEL_NAME, 
            max_tokens=1500,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": base64_image},
                        },
                        {"type": "text", "text": "Analyse cette image selon tes directives et fournis le JSON."}
                    ],
                }
            ],
        )
        
        data = extract_json_safely(response.content[0].text)

    except Exception as e:
        print(f"❌ Erreur sur {filename} : {e}")
        stats["erreurs"] += 1
        return

    action = data.get('action_proposee', '').lower()
    
    if action == "ignore":
        print(f"🗑️ BRUIT DÉTECTÉ : L'image a été ignorée.")
        shutil.move(image_path, os.path.join(IMAGES_TRASH, filename))
        stats["ignorees"] += 1
        return

    fichier_cible = data.get('fichier_cible') or "inbox.md"
    safe_target_name = fichier_cible.replace("/", "_")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    proposal_filename = f"proposal_{timestamp}_{safe_target_name}"
    proposal_path = os.path.join(PROPOSALS_DIR, proposal_filename)

    with open(proposal_path, "w", encoding="utf-8") as f:
        f.write(f"# 📝 Proposition d'intégration\n")
        f.write(f"**Source :** `{filename}`\n")
        f.write(f"**Date :** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("---\n")
        f.write(f"### 🧠 Analyse\n")
        f.write(f"- **Type de visuel :** {data.get('analyse_visuelle')}\n")
        f.write(f"- **Valeur extraite :** {data.get('valeur_extraite')}\n")
        f.write(f"- **Tags :** {', '.join(data.get('tags', []))}\n")
        f.write(f"- **Action requise :** `{action.upper()}` sur `{fichier_cible}`\n")
        f.write(f"- **Justification :** {data.get('justification')}\n")
        f.write("---\n")
        f.write(f"### 📄 Contenu à insérer\n\n")
        f.write(str(data.get('contenu_markdown', '')))

    print(f"✅ Artefact généré : {proposal_filename}")
    shutil.move(image_path, os.path.join(IMAGES_ARCHIVE, filename))
    stats["traitees"] += 1

def write_session_log(stats):
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_filename = f"{LOGS_DIR}/session_{datetime.datetime.now().strftime('%Y%m%d')}.md"
    
    total = stats["traitees"] + stats["ignorees"] + stats["erreurs"]
    
    with open(log_filename, "a", encoding="utf-8") as f:
        f.write(f"## Session du {timestamp}\n")
        f.write(f"- **Total d'images scannées :** {total}\n")
        f.write(f"- **Propositions générées :** {stats['traitees']}\n")
        f.write(f"- **Bruit filtré (ignorées) :** {stats['ignorees']}\n")
        if stats["erreurs"] > 0:
            f.write(f"- **Erreurs rencontrées :** {stats['erreurs']}\n")
        f.write("---\n")

def main():
    print("====================================")
    print("🧠 ASSISTANT COGNITIF - V1.2")
    print("====================================\n")

    os.makedirs(PROPOSALS_DIR, exist_ok=True)
    os.makedirs(IMAGES_ARCHIVE, exist_ok=True)
    os.makedirs(IMAGES_TRASH, exist_ok=True)
    
    stats = {"traitees": 0, "ignorees": 0, "erreurs": 0}

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