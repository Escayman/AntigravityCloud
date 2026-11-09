"""
Point d'entrée principal pour le Bot ETF Trading 212 (Stratégie Hybride Lumibot)

Commandes disponibles :
  python main.py --status      : Affiche l'état du compte T212 et les signaux de marché sans rien exécuter.
  python main.py --execute     : Évalue et passe réellement les ordres sur Trading 212 (Démo ou Live selon config).
  python main.py --daemon      : Exécute le bot en continu selon l'intervalle configuré (ex: 1 fois par jour).
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict

from t212_client import Trading212Client, Trading212Error
from strategy_hybrid import HybridETFStrategy, MarketSignal, ProposedOrder

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ETFRunner")


def load_config(config_path: str = "config_etf.json") -> Dict[str, Any]:
    """Charge le fichier de configuration JSON."""
    if not os.path.exists(config_path):
        # Tenter depuis le dossier courant ou relatif au script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        alt_path = os.path.join(script_dir, config_path)
        if os.path.exists(alt_path):
            config_path = alt_path
        else:
            logger.error(f"Fichier de configuration introuvable : {config_path}")
            sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_banner(env: str, mode: str) -> None:
    print("\n" + "=" * 70)
    print("      ANTIGRAVITY CLOUD - BOT ETF TRADING 212 (LUMIBOT HYBRIDE)      ")
    print(f"      Environnement : {env.upper()} | Stratégie : {mode.upper()}")
    print("=" * 70 + "\n")


def display_status(
    client: Trading212Client,
    strategy: HybridETFStrategy,
    config: Dict[str, Any],
) -> None:
    """Affiche un tableau de bord complet de l'état du compte et des marchés."""
    print("📡 Récupération des données Trading 212 et analyse de marché...\n")

    # 1. Données du compte
    try:
        cash = client.get_account_cash()
        portfolio = client.get_portfolio()
    except Trading212Error as e:
        logger.warning(f"Impossible de contacter Trading 212 : {e}")
        cash = {"free": 0.0, "total": 0.0, "ppl": 0.0}
        portfolio = []

    free_cash = cash.get("free", 0.0)
    total_val = cash.get("total", free_cash)
    ppl = cash.get("ppl", 0.0)

    print("💼 --- ÉTAT DU COMPTE TRADING 212 ---")
    print(f"  • Valeur totale du compte : {total_val:,.2f} €")
    print(f"  • Liquidités disponibles   : {free_cash:,.2f} €")
    print(f"  • Profit / Perte latente   : {ppl:+,.2f} €")
    print("-" * 50)

    # 2. Positions actuelles
    print("\n📦 --- POSITIONS EN PORTEFEUILLE ---")
    if not portfolio:
        print("  Aucune position actuellement ouverte.")
    else:
        for pos in portfolio:
            ticker = pos.get("ticker", "N/A")
            qty = pos.get("quantity", 0.0)
            avg_p = pos.get("averagePrice", 0.0)
            cur_p = pos.get("currentPrice", 0.0)
            pos_ppl = pos.get("ppl", 0.0)
            val = qty * cur_p
            print(f"  • {ticker:<12} | {qty:,.4f} parts | Valeur: {val:,.2f} € | PRU: {avg_p:.2f} € | Cours: {cur_p:.2f} € | PnL: {pos_ppl:+,.2f} €")
    print("-" * 50)

    # 3. Analyse technique des ETF configurés
    print("\n📈 --- SIGNAUX DE TENDANCE (ANALYSE TECHNIQUE SMA 200) ---")
    signals = []
    portfolio_cfg = config.get("portfolio", {})
    for yf_ticker, etf_data in portfolio_cfg.items():
        t212_ticker = etf_data.get("t212_ticker")
        name = etf_data.get("name")
        target_alloc = etf_data.get("target_allocation", 0.5)
        yf_symbol = etf_data.get("yfinance_ticker", yf_ticker)

        sig = strategy.analyze_etf(yf_symbol, t212_ticker, name, target_alloc)
        signals.append(sig)

        badge = "🟢 HAUSSIER (BULL)" if sig.trend == "BULLISH" else ("🟡 REPLI FAVORABLE (DIP)" if sig.trend == "DIP_BUY" else "🔴 BAISSIER (BEAR)")
        dist_sma200 = ((sig.current_price - sig.sma_200) / sig.sma_200) * 100

        print(f"  • {sig.name} ({sig.ticker_yf}) :")
        print(f"      Cours actuel  : {sig.current_price:.2f} € | SMA 200 : {sig.sma_200:.2f} € (Écart: {dist_sma200:+.2f}%)")
        print(f"      RSI 14 jours  : {sig.rsi_14:.1f} | Statut : {badge}")
        print(f"      Allocation    : Cible {sig.target_allocation*100:.0f}% -> Ajustée {sig.adjusted_allocation*100:.0f}%")
        print(f"      Diagnostic    : {sig.rationale}\n")
    print("-" * 50)

    # 4. Ordres proposés
    proposed_orders = strategy.evaluate_portfolio(signals, cash, portfolio)
    print("\n🎯 --- DÉCISIONS & ORDRES PROPOSÉS DU BOT ---")
    if not proposed_orders:
        print("  ✅ Aucune action requise. Le portefeuille est déjà parfaitement aligné et sécurisé !")
    else:
        for idx, o in enumerate(proposed_orders, 1):
            action_badge = "🟩 ACHAT" if o.action == "BUY" else "🟥 VENTE"
            print(f"  {idx}. {action_badge} : {abs(o.shares):.4f} parts de {o.name} ({o.ticker_t212})")
            print(f"     Montant estimé : ~{o.estimated_total_eur:.2f} € (Cours: {o.estimated_price:.2f} €)")
            print(f"     Raison         : {o.reason}")
    print("=" * 70 + "\n")


def execute_cycle(
    client: Trading212Client,
    strategy: HybridETFStrategy,
    config: Dict[str, Any],
    dry_run: bool = True,
) -> None:
    """Exécute un cycle complet : Analyse + Envoi des ordres réels si dry_run=False."""
    logger.info("Démarrage du cycle d'évaluation ETF...")

    try:
        cash = client.get_account_cash()
        portfolio = client.get_portfolio()
    except Trading212Error as e:
        logger.error(f"Échec de connexion à Trading 212 : {e}")
        return

    signals = []
    portfolio_cfg = config.get("portfolio", {})
    for yf_ticker, etf_data in portfolio_cfg.items():
        yf_symbol = etf_data.get("yfinance_ticker", yf_ticker)
        sig = strategy.analyze_etf(
            yf_symbol,
            etf_data.get("t212_ticker"),
            etf_data.get("name"),
            etf_data.get("target_allocation", 0.5)
        )
        signals.append(sig)

    orders = strategy.evaluate_portfolio(signals, cash, portfolio)

    if not orders:
        logger.info("Aucun ordre à exécuter. Portefeuille équilibré.")
        return

    logger.info(f"{len(orders)} ordre(s) généré(s) par la stratégie Hybride :")
    for o in orders:
        if dry_run:
            logger.info(f"[SIMULATION / DRY-RUN] Ordre non envoyé : {o.action} {abs(o.shares):.4f} {o.ticker_t212} (~{o.estimated_total_eur:.2f} €)")
        else:
            try:
                logger.info(f"[EXÉCUTION RÉELLE] Envoi de l'ordre : {o.action} {o.shares:.4f} {o.ticker_t212}")
                resp = client.place_market_order(o.ticker_t212, o.shares)
                logger.info(f"Ordre validé avec succès sur T212 (ID: {resp.get('id', 'N/A')})")
            except Trading212Error as e:
                logger.error(f"Erreur lors du passage de l'ordre {o.ticker_t212} : {e}")


def main():
    parser = argparse.ArgumentParser(description="Bot ETF Trading 212 avec Stratégie Hybride Lumibot")
    parser.add_argument("--status", action="store_true", help="Affiche l'état du compte et les signaux de marché sans rien modifier.")
    parser.add_argument("--execute", action="store_true", help="Passe réellement les ordres calculés sur Trading 212.")
    parser.add_argument("--daemon", action="store_true", help="Fait tourner le bot en continu selon l'intervalle configuré.")
    parser.add_argument("--web", action="store_true", help="Lance le Dashboard Web interactif sur http://localhost:8085.")
    parser.add_argument("--port", type=int, default=8085, help="Port d'écoute du serveur Web (défaut : 8085).")
    parser.add_argument("--config", default="config_etf.json", help="Chemin vers le fichier config_etf.json.")

    args = parser.parse_args()

    if args.web:
        from web_dashboard import start_server
        start_server(config_path=args.config, port=args.port)
        return

    config = load_config(args.config)

    t212_cfg = config.get("trading212", {})
    env = t212_cfg.get("environment", "demo")
    mode = config.get("strategy", {}).get("mode", "hybrid")

    client = Trading212Client(
        api_key=t212_cfg.get("api_key", ""),
        api_secret=t212_cfg.get("api_secret", ""),
        environment=env
    )
    strategy = HybridETFStrategy(config)

    print_banner(env, mode)

    if args.status:
        display_status(client, strategy, config)
    elif args.execute and not args.daemon:
        logger.info(f"Mode exécution directe activé sur l'environnement {env.upper()}.")
        execute_cycle(client, strategy, config, dry_run=False)
    elif args.daemon:
        interval_hours = config.get("strategy", {}).get("check_interval_hours", 24)
        logger.info(f"Démarrage en mode démon. Vérification toutes les {interval_hours} heures.")
        while True:
            execute_cycle(client, strategy, config, dry_run=(not args.execute))
            logger.info(f"Prochain cycle dans {interval_hours} heures...")
            time.sleep(interval_hours * 3600)
    else:
        # Par défaut sans argument : affiche le statut
        display_status(client, strategy, config)


if __name__ == "__main__":
    main()
