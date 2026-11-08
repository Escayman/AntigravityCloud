# 📊 Bot ETF Trading 212 — Stratégie Hybride Lumibot

Ce bot gère l'investissement automatisé sur ETF via l'**API officielle Trading 212 (v0)** avec une approche quantitative **Hybride**.

---

## 🧠 Principe de la Stratégie Hybride

La plupart des investisseurs font du DCA "aveugle" : ils continuent d'acheter même en plein krach boursier et subissent des pertes de -30% à -50% pendant des mois.

La stratégie **Hybride** résout ce problème en combinant deux moteurs :

1. **Moteur d'Accumulation (DCA Intelligent) :**
   - Vous définissez vos ETF cibles (ex: **60% S&P 500** et **40% Nasdaq 100**).
   - En marché normal (haussier), le bot investit régulièrement et rééquilibre le portefeuille automatiquement.

2. **Bouclier Anti-Krach (Filtre SMA 200) :**
   - Toutes les 24h, le bot vérifie la Moyenne Mobile à 200 jours (`SMA 200`) sur chaque ETF.
   - 🟢 **Cours > SMA 200 (Marché haussier) :** Le bot achète et fait fructifier le capital.
   - 🟡 **Cours > SMA 200 + RSI < 42 (Repli sain) :** Opportunité d'achat sur repli ("Buy the Dip").
   - 🔴 **Cours < SMA 200 (Marché baissier / Risque de krach) :** Le bot coupe la position et place l'argent en **Cash (EUR)** sur votre compte pour préserver votre capital. Dès que le marché repasse au-dessus de la SMA 200, il réinvestit !

---

## 🔑 Obtenir votre clé API Trading 212

1. Ouvrez l'application **Trading 212** (ou connectez-vous sur le site web).
2. Allez dans **Paramètres** > **API (Bêta)**.
3. Cochez l'acceptation des risques et cliquez sur **Générer une clé API**.
4. Configurez :
   - **Nom :** `Antigravity-ETF-Bot`
   - **Restrictions IP :** Indiquez votre adresse IP publique (celle de votre gros PC).
   - **Permissions :** Activez la lecture du compte et les ordres de bourse.
5. Copiez votre **API Key** (et votre **API Secret** si affiché).

---

## ⚙️ Configuration (`config_etf.json`)

Ouvrez le fichier [`config_etf.json`](file:///home/antigravity/Escayman/AntigravityCloud/etf_trading/config_etf.json) pour ajuster vos paramètres :

```json
{
    "trading212": {
        "api_key": "VOTRE_CLE_API_ICI",
        "api_secret": "VOTRE_SECRET_API_ICI",
        "environment": "demo"
    },
    "strategy": {
        "mode": "hybrid",
        "sma_period": 200,
        "bearish_action": "exit_to_cash",
        "rebalance_threshold_percent": 5.0,
        "cash_reserve_percent": 2.0,
        "check_interval_hours": 24
    },
    "portfolio": {
        "VUAA.DE": {
            "t212_ticker": "VUAA_DE_EQ",
            "name": "Vanguard S&P 500 UCITS ETF (EUR)",
            "target_allocation": 0.60
        },
        "EQAC.DE": {
            "t212_ticker": "EQAC_DE_EQ",
            "name": "Invesco EQQQ Nasdaq 100 UCITS ETF (EUR)",
            "target_allocation": 0.40
        }
    }
}
```

> [!TIP]
> Laissez `"environment": "demo"` au début pour observer les ordres virtuels sur votre compte d'entraînement Trading 212 sans risquer le moindre centime !

---

## 🚀 Lancement

### Option A : En Python direct

```powershell
# 1. Aller dans le dossier
cd $HOME\Documents\AntigravityCloud\etf_trading

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Voir l'état du compte et les signaux de marché (sans rien acheter)
python main.py --status

# 4. Exécuter un cycle réel (passe les ordres sur T212)
python main.py --execute

# 5. Laisser tourner en continu (surveillance quotidienne)
python main.py --daemon
```

### Option B : Avec Docker (sans rien installer)

```powershell
cd $HOME\Documents\AntigravityCloud\etf_trading
docker compose up -d
```
