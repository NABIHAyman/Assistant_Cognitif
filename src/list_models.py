"""
Utilitaire - Liste des modèles Gemini disponibles
--------------------------------------------------
Affiche uniquement les modèles supportant generateContent.
Usage : docker exec -it cognition_phase1 python src/list_models.py
"""
import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

def list_available_models():
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    print("====================================")
    print("📡 MODÈLES DISPONIBLES (generateContent)")
    print("====================================\n")

    try:
        for model in client.models.list():
            # Compatibilité selon version SDK
            methods = getattr(model, 'supported_actions', None) \
                   or getattr(model, 'supported_methods', None) \
                   or []
            if 'generateContent' in methods:
                print(f"- ID           : {model.name}")
                print(f"  Titre        : {model.display_name}")
                print(f"  Description  : {model.description}\n")

    except Exception as e:
        print(f"❌ Erreur : {e}")

if __name__ == "__main__":
    list_available_models()