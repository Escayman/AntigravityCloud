FROM python:3.11-slim

WORKDIR /app

# Installation des dépendances système légères
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Par défaut, on lance le bot en mode statut/surveillance
CMD ["python", "main.py", "--daemon"]
