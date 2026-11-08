# AntigravityCloud - Freqtrade & FreqAI avec Docker Desktop

Ce projet est configuré pour lancer facilement **Freqtrade** avec son module de machine learning **FreqAI** et son interface web **FreqUI** sur votre machine locale via **Docker Desktop**.

---

## 🚀 Prérequis

* Avoir [Docker Desktop](https://www.docker.com/products/docker-desktop/) installé et démarré sur votre ordinateur (Windows, macOS ou Linux).

---

## 📁 Structure du projet

```text
AntigravityCloud/
├── docker-compose.yml           # Configuration Docker (image stable_freqai)
├── .gitignore                   # Ignore les logs, données et modèles lourds
├── README.md                    # Guide d'utilisation
└── user_data/
    ├── config.json              # Configuration Freqtrade + FreqAI + FreqUI
    ├── strategies/
    │   └── FreqaiExampleStrategy.py # Stratégie d'exemple avec FreqAI
    ├── data/                    # Données de marché téléchargées
    ├── logs/                    # Journaux d'exécution
    └── models/                  # Modèles de machine learning entraînés
```

---

## ⚡ Démarrage rapide

### 1. Télécharger des données historiques de marché (pour FreqAI)
Avant de lancer le bot ou un backtest, téléchargez les données Binance pour les paires sélectionnées :
```bash
docker compose run --rm freqtrade download-data --pairs BTC/USDT ETH/USDT SOL/USDT ADA/USDT --timeframes 5m 15m 1h --days 30 --exchange binance
```

### 2. Démarrer le bot (Dry-Run / Simulation FreqAI)
Lancez le bot en tâche de fond :
```bash
docker compose up -d
```
> Le bot démarre par défaut en mode **Dry-Run** (simulation sans argent réel, capital virtuel de 1000 USDT avec les cours Binance en direct).

### 3. Accéder à l'interface web (FreqUI)
Ouvrez votre navigateur sur :
👉 [http://localhost:8080](http://localhost:8080)

* **Utilisateur :** `freqtrader`
* **Mot de passe :** `SuperSecurePassword123!` *(modifiable dans `user_data/config.json`)*

---

## 🛠️ Commandes utiles

* **Voir les logs en direct :**
  ```bash
  docker compose logs -f
  ```

* **Lancer un backtest avec FreqAI :**
  ```bash
  docker compose run --rm freqtrade backtesting --config user_data/config.json --strategy FreqaiExampleStrategy --freqaimodel LightGBMRegressor --timerange 20240101-20240201
  ```

* **Arrêter le bot :**
  ```bash
  docker compose down
  ```

* **Mettre à jour l'image Docker :**
  ```bash
  docker compose pull
  docker compose up -d
  ```

---

## 🐙 Connexion à Kraken

### Mode Simulation (Dry-Run - Recommandé pour commencer)
Dans `user_data/config.json`, `"dry_run": true` :
* Aucun compte Kraken ni clé API n'est requis.
* Le bot se connecte à l'API publique de Kraken pour lire les prix et simuler les achats/ventes avec un portefeuille fictif de 1000 EUR.

### Mode Réel (Live Trading)
Pour passer en argent réel avec votre compte Kraken :
1. Créez une clé API sur votre compte Kraken (**Settings > API**).
   > ⚠️ **Sécurité cruciale :** Cochez uniquement les permissions **Query Funds**, **Query Open Orders & Trades**, **Query Closed Orders & Trades**, **Create & Modify Orders**, et **Cancel/Close Orders**. Ne cochez **JAMAIS** les droits de **Withdrawal / Retrait** !
2. Ouvrez `user_data/config.json` et configurez vos clés :
   ```json
   "dry_run": false,
   "exchange": {
       "name": "kraken",
       "key": "VOTRE_CLE_API_KRAKEN",
       "secret": "VOTRE_SECRET_KRAKEN",
   ...
   ```
3. Redémarrez le bot avec `docker compose restart`.

---

## ⚙️ Personnalisation de FreqAI
FreqAI utilise par défaut le modèle **LightGBMRegressor**.
Pour changer de modèle ou ajuster les paramètres (indicateurs, fenêtres d'entraînement, etc.), éditez la section `"freqai"` dans `user_data/config.json`.

