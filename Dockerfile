# Image slim pour la sécurité et la légèreté
FROM python:3.11-slim

# Empêche Python de bufferiser les logs (affichage immédiat dans le terminal)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Dossier racine interne
WORKDIR /workspace

# Utilitaires de base (au cas où on ajoute n8n/scraping plus tard)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc \
    && rm -rf /var/lib/apt/lists/*

# On copie uniquement les requirements d'abord pour optimiser le cache Docker
COPY src/requirements.txt /workspace/src/

RUN pip install --no-cache-dir -r /workspace/src/requirements.txt

# NOTE : On ne fait pas de COPY du script Python ici !
# Il sera injecté dynamiquement par le volume de docker-compose.
# Cela te permet de modifier ton code sans jamais taper "docker build".