"""
Antigravity Cloud - ETF Trading Web Dashboard
Interface Web interactive, moderne et temps réel pour piloter la stratégie hybride Trading 212.
Fonctionne sans dépendance externe lourde (serveur HTTP Python standard multithreadé).
Port par défaut : 8085
"""

import datetime
import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from t212_client import Trading212Client, Trading212Error
from strategy_hybrid import HybridETFStrategy

logger = logging.getLogger("ETFWebDashboard")


def load_config(config_path: str = "config_etf.json") -> Dict[str, Any]:
    if not os.path.exists(config_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        alt_path = os.path.join(script_dir, config_path)
        if os.path.exists(alt_path):
            config_path = alt_path
        else:
            raise FileNotFoundError(f"Config non trouvee : {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


class ETFTradingState:
    """Conserve l'état en cache pour des réponses ultra-rapides du tableau de bord."""
    def __init__(self, config_path: str = "config_etf.json"):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.lock = threading.Lock()
        self.last_update = None
        self.cached_status = {}
        self.init_clients()
        self.refresh()

    def init_clients(self):
        t212_cfg = self.config.get("trading212", {})
        self.client = Trading212Client(
            api_key=t212_cfg.get("api_key", ""),
            api_secret=t212_cfg.get("api_secret", ""),
            environment=t212_cfg.get("environment", "demo")
        )
        self.strategy = HybridETFStrategy(self.config)

    def refresh(self) -> Dict[str, Any]:
        with self.lock:
            # Recharger la config au cas où elle a été éditée
            try:
                self.config = load_config(self.config_path)
                self.init_clients()
            except Exception as e:
                logger.warning(f"Erreur rechargement config: {e}")

            env = self.config.get("trading212", {}).get("environment", "demo")
            t212_connected = True
            t212_error = None
            cash = {"free": 0.0, "total": 0.0, "ppl": 0.0}
            portfolio = []

            # 1. Contact T212
            try:
                cash = self.client.get_account_cash()
                portfolio = self.client.get_portfolio()
            except Trading212Error as e:
                t212_connected = False
                t212_error = str(e)

            # 2. Analyse technique des ETFs
            signals_data = []
            portfolio_cfg = self.config.get("portfolio", {})
            for key, etf_data in portfolio_cfg.items():
                yf_symbol = etf_data.get("yfinance_ticker", key)
                t212_ticker = etf_data.get("t212_ticker")
                name = etf_data.get("name")
                target_alloc = etf_data.get("target_allocation", 0.5)

                sig = self.strategy.analyze_etf(yf_symbol, t212_ticker, name, target_alloc)
                dist_pct = ((sig.current_price - sig.sma_200) / sig.sma_200) * 100 if sig.sma_200 else 0.0

                signals_data.append({
                    "ticker_yf": sig.ticker_yf,
                    "ticker_t212": sig.ticker_t212,
                    "name": sig.name,
                    "current_price": round(sig.current_price, 2),
                    "sma_200": round(sig.sma_200, 2),
                    "sma_50": round(sig.sma_50, 2),
                    "dist_sma200_pct": round(dist_pct, 2),
                    "rsi_14": round(sig.rsi_14, 1),
                    "trend": sig.trend,
                    "target_allocation": sig.target_allocation,
                    "adjusted_allocation": sig.adjusted_allocation,
                    "rationale": sig.rationale
                })

            # 3. Évaluation des ordres
            # Conversion dataclass pour la stratégie
            from strategy_hybrid import MarketSignal
            obj_signals = [
                MarketSignal(
                    ticker_yf=s["ticker_yf"],
                    ticker_t212=s["ticker_t212"],
                    name=s["name"],
                    current_price=s["current_price"],
                    sma_200=s["sma_200"],
                    sma_50=s["sma_50"],
                    rsi_14=s["rsi_14"],
                    trend=s["trend"],
                    target_allocation=s["target_allocation"],
                    adjusted_allocation=s["adjusted_allocation"],
                    rationale=s["rationale"]
                ) for s in signals_data
            ]
            proposed_orders = self.strategy.evaluate_portfolio(obj_signals, cash, portfolio)
            orders_data = [
                {
                    "ticker": o.ticker_t212,
                    "name": o.name,
                    "action": o.action,
                    "shares": round(o.shares, 4),
                    "estimated_price": round(o.estimated_price, 2),
                    "total_eur": round(o.estimated_total_eur, 2),
                    "reason": o.reason
                } for o in proposed_orders
            ]

            self.cached_status = {
                "environment": env.upper(),
                "mode": self.config.get("strategy", {}).get("mode", "hybrid").upper(),
                "t212_connected": t212_connected,
                "t212_error": t212_error,
                "cash": {
                    "free": round(cash.get("free", 0.0), 2),
                    "total": round(cash.get("total", cash.get("free", 0.0)), 2),
                    "ppl": round(cash.get("ppl", 0.0), 2)
                },
                "portfolio": portfolio,
                "signals": signals_data,
                "orders": orders_data,
                "last_update": datetime.datetime.now().strftime("%H:%M:%S")
            }
            return self.cached_status

    def execute_orders(self) -> Dict[str, Any]:
        with self.lock:
            # Réactualise d'abord
            self.refresh()
            if not self.cached_status["t212_connected"]:
                return {"status": "error", "message": "Impossible d'exécuter: Trading 212 non connecté."}
            
            orders = self.cached_status["orders"]
            if not orders:
                return {"status": "ok", "message": "Aucun ordre nécessaire. Portefeuille équilibré."}

            executed = []
            for o in orders:
                qty = o["shares"] if o["action"] == "BUY" else -abs(o["shares"])
                try:
                    res = self.client.place_market_order(o["ticker"], qty)
                    executed.append({"ticker": o["ticker"], "qty": qty, "result": res})
                except Exception as e:
                    executed.append({"ticker": o["ticker"], "qty": qty, "error": str(e)})

            self.refresh()
            return {"status": "ok", "executed": executed}


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Antigravity Cloud - Bot ETF Trading 212</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        darkbg: '#0B0F19',
                        cardbg: '#111827',
                        cardborder: '#1F2937',
                        accent: '#3B82F6',
                        emerald: '#10B981',
                        amber: '#F59E0B',
                        rose: '#EF4444'
                    }
                }
            }
        }
    </script>
    <style>
        body { background-color: #0B0F19; color: #F3F4F6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .glass-card { background: rgba(17, 24, 39, 0.85); backdrop-filter: blur(10px); border: 1px solid #1F2937; }
        .pulse-live { animation: pulse 2s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.4; } 100% { opacity: 1; } }
    </style>
</head>
<body class="min-h-screen p-4 md:p-8 flex flex-col justify-between">
    <div class="max-w-7xl mx-auto w-full">
        <!-- HEADER -->
        <header class="flex flex-col md:flex-row md:items-center md:justify-between pb-6 border-b border-gray-800 gap-4">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-blue-600/20 border border-blue-500/40 flex items-center justify-center text-blue-400 text-xl font-bold">
                    <i class="fa-solid fa-chart-line"></i>
                </div>
                <div>
                    <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
                        Antigravity Cloud <span class="text-xs px-2.5 py-0.5 rounded-full bg-blue-900/50 text-blue-400 border border-blue-700/50">ETF HYBRIDE</span>
                    </h1>
                    <p class="text-xs text-gray-400">Stratégie Dual-Shield (DCA Automatique + Filtre Krach SMA 200)</p>
                </div>
            </div>

            <div class="flex items-center gap-3 flex-wrap">
                <span id="env-badge" class="px-3 py-1 rounded-full text-xs font-semibold bg-gray-800 text-gray-300 border border-gray-700">
                    ENVIRONNEMENT : DEMO
                </span>
                <span id="conn-badge" class="px-3 py-1 rounded-full text-xs font-semibold flex items-center gap-1.5 bg-yellow-900/40 text-yellow-400 border border-yellow-700/50">
                    <span class="w-2 h-2 rounded-full bg-yellow-400 pulse-live"></span> Connexion T212...
                </span>
                <button onclick="refreshData()" class="px-4 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs font-medium text-gray-200 transition flex items-center gap-2">
                    <i class="fa-solid fa-rotate"></i> Actualiser (<span id="last-update">--:--:--</span>)
                </button>
            </div>
        </header>

        <!-- ALERTE ERREUR T212 (si présente) -->
        <div id="alert-banner" class="hidden mt-6 p-4 rounded-xl bg-red-950/60 border border-red-800/80 text-red-200 text-sm">
            <div class="flex items-start gap-3">
                <i class="fa-solid fa-triangle-exclamation text-red-400 text-lg mt-0.5"></i>
                <div class="flex-1">
                    <h3 class="font-bold text-red-300">Alerte Authentification Trading 212</h3>
                    <p id="alert-message" class="text-xs mt-1 text-red-300/90 whitespace-pre-line"></p>
                </div>
            </div>
        </div>

        <!-- STATS CARDS -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-6">
            <div class="glass-card p-5 rounded-2xl">
                <div class="flex items-center justify-between text-gray-400 text-xs font-medium">
                    <span>VALEUR TOTALE DU COMPTE</span>
                    <i class="fa-solid fa-wallet text-gray-500"></i>
                </div>
                <div id="val-total" class="text-2xl font-black text-white mt-2">0.00 €</div>
                <div class="text-[11px] text-gray-400 mt-1 flex items-center gap-1">
                    <span>Positions + Liquidités</span>
                </div>
            </div>

            <div class="glass-card p-5 rounded-2xl">
                <div class="flex items-center justify-between text-gray-400 text-xs font-medium">
                    <span>LIQUIDITÉS DISPONIBLES</span>
                    <i class="fa-solid fa-euro-sign text-emerald-400"></i>
                </div>
                <div id="val-cash" class="text-2xl font-black text-emerald-400 mt-2">0.00 €</div>
                <div class="text-[11px] text-gray-400 mt-1">Prêt pour les futurs achats DCA</div>
            </div>

            <div class="glass-card p-5 rounded-2xl">
                <div class="flex items-center justify-between text-gray-400 text-xs font-medium">
                    <span>PROFIT / PERTE LATENTE</span>
                    <i class="fa-solid fa-arrow-trend-up text-blue-400"></i>
                </div>
                <div id="val-ppl" class="text-2xl font-black text-gray-300 mt-2">+0.00 €</div>
                <div class="text-[11px] text-gray-400 mt-1">Performance globale non réalisée</div>
            </div>

            <div class="glass-card p-5 rounded-2xl">
                <div class="flex items-center justify-between text-gray-400 text-xs font-medium">
                    <span>BOUCLIER ANTI-KRACH</span>
                    <i class="fa-solid fa-shield-halved text-blue-400"></i>
                </div>
                <div id="shield-status" class="text-xl font-bold text-emerald-400 mt-2">🟢 ACTIF (100%)</div>
                <div class="text-[11px] text-gray-400 mt-1">Surveillance SMA 200 en direct</div>
            </div>
        </div>

        <!-- GRILLE PRINCIPALE (SIGNAUX & ALLOCATION) -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
            <!-- COLONNE 1 & 2 : SIGNAUX DE TENDANCE DES ETFS -->
            <div class="lg:col-span-2 space-y-4">
                <div class="flex items-center justify-between">
                    <h2 class="text-sm font-bold tracking-wider text-gray-300 uppercase flex items-center gap-2">
                        <i class="fa-solid fa-radar text-blue-400"></i> Signaux Techniques & Tendance (SMA 200)
                    </h2>
                    <span class="text-xs text-gray-500">Source : Yahoo Finance Live</span>
                </div>

                <div id="signals-container" class="space-y-4">
                    <div class="glass-card p-6 rounded-2xl text-center text-gray-400 text-sm">
                        <i class="fa-solid fa-spinner fa-spin text-blue-400 text-xl mb-2"></i><br>
                        Calcul des moyennes mobiles 200 jours et RSI...
                    </div>
                </div>

                <!-- TABLEAU DES POSITIONS TRADING 212 -->
                <div class="glass-card p-5 rounded-2xl mt-6">
                    <h3 class="text-xs font-bold uppercase text-gray-400 tracking-wider mb-4 flex items-center gap-2">
                        <i class="fa-solid fa-layer-group text-purple-400"></i> Portefeuille Détenu sur Trading 212
                    </h3>
                    <div class="overflow-x-auto">
                        <table class="w-full text-left text-xs text-gray-300">
                            <thead class="text-gray-500 uppercase border-b border-gray-800 text-[10px]">
                                <tr>
                                    <th class="py-2">Actif</th>
                                    <th class="py-2">Parts</th>
                                    <th class="py-2">PRU</th>
                                    <th class="py-2">Cours</th>
                                    <th class="py-2">Valeur</th>
                                    <th class="py-2">PnL</th>
                                </tr>
                            </thead>
                            <tbody id="portfolio-tbody" class="divide-y divide-gray-800/60 font-mono">
                                <tr>
                                    <td colspan="6" class="py-4 text-center text-gray-500">Aucune position ouverte sur Trading 212.</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- COLONNE 3 : ALLOCATION & ORDRES PROPOSÉS -->
            <div class="space-y-6">
                <!-- ALLOCATION DONUT -->
                <div class="glass-card p-5 rounded-2xl">
                    <h2 class="text-sm font-bold tracking-wider text-gray-300 uppercase flex items-center gap-2 mb-4">
                        <i class="fa-solid fa-pie-chart text-emerald-400"></i> Répartition Cible
                    </h2>
                    <div class="h-44 flex items-center justify-center">
                        <canvas id="allocationChart"></canvas>
                    </div>
                    <div class="mt-4 space-y-2 text-xs">
                        <div class="flex items-center justify-between text-gray-300">
                            <span class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-blue-500"></span> Vanguard S&P 500 (VUAA)</span>
                            <span class="font-bold">60%</span>
                        </div>
                        <div class="flex items-center justify-between text-gray-300">
                            <span class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full bg-purple-500"></span> Invesco Nasdaq 100 (EQAC)</span>
                            <span class="font-bold">40%</span>
                        </div>
                    </div>
                </div>

                <!-- ORDRES PROPOSÉS PAR LE BOT -->
                <div class="glass-card p-5 rounded-2xl">
                    <div class="flex items-center justify-between mb-4">
                        <h2 class="text-sm font-bold tracking-wider text-gray-300 uppercase flex items-center gap-2">
                            <i class="fa-solid fa-robot text-blue-400"></i> Décisions du Bot
                        </h2>
                        <button onclick="executeBotOrders()" id="btn-exec" class="px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white transition disabled:opacity-50 flex items-center gap-1.5">
                            <i class="fa-solid fa-bolt"></i> Exécuter
                        </button>
                    </div>

                    <div id="orders-container" class="space-y-3">
                        <div class="p-3 rounded-xl bg-gray-900/60 border border-gray-800 text-xs text-gray-400 text-center">
                            Chargement des décisions...
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- FOOTER -->
    <footer class="mt-8 text-center text-xs text-gray-500 border-t border-gray-800 pt-4">
        Antigravity Cloud • Freqtrade + FreqAI & Trading 212 Hybrid ETF Bot • Monnaie : EUR (€)
    </footer>

    <script>
        let allocChart = null;

        function initChart() {
            const ctx = document.getElementById('allocationChart').getContext('2d');
            allocChart = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: ['S&P 500 (VUAA)', 'Nasdaq 100 (EQAC)'],
                    datasets: [{
                        data: [60, 40],
                        backgroundColor: ['#3B82F6', '#A855F7'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    cutout: '72%'
                }
            });
        }

        async function refreshData() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                renderUI(data);
            } catch (err) {
                console.error("Erreur actualisation :", err);
            }
        }

        function renderUI(data) {
            document.getElementById('last-update').innerText = data.last_update || '--:--:--';
            document.getElementById('env-badge').innerText = 'ENVIRONNEMENT : ' + data.environment;

            const connBadge = document.getElementById('conn-badge');
            const alertBanner = document.getElementById('alert-banner');
            const alertMsg = document.getElementById('alert-message');

            if (data.t212_connected) {
                connBadge.className = 'px-3 py-1 rounded-full text-xs font-semibold flex items-center gap-1.5 bg-emerald-950/60 text-emerald-400 border border-emerald-700/50';
                connBadge.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-400 pulse-live"></span> Trading 212 Connecté';
                alertBanner.classList.add('hidden');
            } else {
                connBadge.className = 'px-3 py-1 rounded-full text-xs font-semibold flex items-center gap-1.5 bg-red-950/60 text-red-400 border border-red-700/50';
                connBadge.innerHTML = '<span class="w-2 h-2 rounded-full bg-red-400"></span> Déconnecté';
                alertBanner.classList.remove('hidden');
                alertMsg.innerText = data.t212_error || "Impossible de contacter Trading 212.";
            }

            // Stats
            document.getElementById('val-total').innerText = (data.cash.total || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2 }) + ' €';
            document.getElementById('val-cash').innerText = (data.cash.free || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2 }) + ' €';
            
            const pplVal = data.cash.ppl || 0;
            const pplEl = document.getElementById('val-ppl');
            pplEl.innerText = (pplVal >= 0 ? '+' : '') + pplVal.toLocaleString('fr-FR', { minimumFractionDigits: 2 }) + ' €';
            pplEl.className = pplVal >= 0 ? 'text-2xl font-black text-emerald-400 mt-2' : 'text-2xl font-black text-red-400 mt-2';

            // Signaux
            const sigContainer = document.getElementById('signals-container');
            sigContainer.innerHTML = '';

            let allBullish = true;
            data.signals.forEach(sig => {
                const isBull = sig.trend === 'BULLISH';
                const isDip = sig.trend === 'DIP_BUY';
                if (!isBull && !isDip) allBullish = false;

                const badgeBg = isBull ? 'bg-emerald-950/60 text-emerald-400 border-emerald-700/50' : 
                                (isDip ? 'bg-amber-950/60 text-amber-400 border-amber-700/50' : 'bg-red-950/60 text-red-400 border-red-700/50');
                const badgeText = isBull ? '🟢 HAUSSIER (BULL)' : (isDip ? '🟡 REPLI FAVORABLE (DIP)' : '🔴 KRACH SÉCURISÉ (BEAR)');

                const rsiColor = sig.rsi_14 < 40 ? 'bg-amber-400' : (sig.rsi_14 > 70 ? 'bg-red-400' : 'bg-emerald-400');

                const card = document.createElement('div');
                card.className = 'glass-card p-5 rounded-2xl border border-gray-800';
                card.innerHTML = `
                    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-3 border-b border-gray-800/80">
                        <div>
                            <div class="font-bold text-white text-base">${sig.name}</div>
                            <div class="text-xs text-gray-400 font-mono">${sig.ticker_yf} • T212: ${sig.ticker_t212}</div>
                        </div>
                        <span class="px-2.5 py-1 rounded-full text-xs font-semibold border ${badgeBg} w-fit">
                            ${badgeText}
                        </span>
                    </div>

                    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 my-4 font-mono">
                        <div>
                            <span class="text-[10px] text-gray-500 uppercase block">Cours Actuel</span>
                            <span class="text-base font-bold text-white">${sig.current_price.toFixed(2)} €</span>
                        </div>
                        <div>
                            <span class="text-[10px] text-gray-500 uppercase block">SMA 200 Jours</span>
                            <span class="text-base font-bold text-gray-300">${sig.sma_200.toFixed(2)} €</span>
                            <span class="text-[10px] ${sig.dist_sma200_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}">
                                (${sig.dist_sma200_pct >= 0 ? '+' : ''}${sig.dist_sma200_pct.toFixed(2)}%)
                            </span>
                        </div>
                        <div>
                            <span class="text-[10px] text-gray-500 uppercase block">SMA 50 Jours</span>
                            <span class="text-base font-bold text-gray-300">${sig.sma_50.toFixed(2)} €</span>
                        </div>
                        <div>
                            <span class="text-[10px] text-gray-500 uppercase block">RSI 14 Jours</span>
                            <span class="text-base font-bold text-white">${sig.rsi_14.toFixed(1)}</span>
                            <div class="w-full bg-gray-800 h-1.5 rounded-full mt-1 overflow-hidden">
                                <div class="${rsiColor} h-full" style="width: ${Math.min(sig.rsi_14, 100)}%"></div>
                            </div>
                        </div>
                    </div>

                    <div class="p-3 rounded-xl bg-gray-900/60 border border-gray-800 text-xs text-gray-300">
                        <i class="fa-solid fa-circle-info text-blue-400 mr-1.5"></i>
                        <span>${sig.rationale}</span>
                    </div>
                `;
                sigContainer.appendChild(card);
            });

            document.getElementById('shield-status').innerText = allBullish ? '🟢 SÉCURISÉ (100% MARCHÉ)' : '🔴 PROTECTION KRACH ACTIVÉE';

            // Portefeuille
            const pbody = document.getElementById('portfolio-tbody');
            pbody.innerHTML = '';
            if (!data.portfolio || data.portfolio.length === 0) {
                pbody.innerHTML = '<tr><td colspan="6" class="py-4 text-center text-gray-500">Aucune position ouverte sur Trading 212.</td></tr>';
            } else {
                data.portfolio.forEach(pos => {
                    const tr = document.createElement('tr');
                    const val = pos.quantity * pos.currentPrice;
                    const posPpl = pos.ppl || 0;
                    tr.innerHTML = `
                        <td class="py-2.5 font-bold text-white">${pos.ticker}</td>
                        <td class="py-2.5">${pos.quantity.toFixed(4)}</td>
                        <td class="py-2.5">${(pos.averagePrice || 0).toFixed(2)} €</td>
                        <td class="py-2.5 text-blue-400">${(pos.currentPrice || 0).toFixed(2)} €</td>
                        <td class="py-2.5 text-white">${val.toFixed(2)} €</td>
                        <td class="py-2.5 ${posPpl >= 0 ? 'text-emerald-400' : 'text-red-400'}">${posPpl >= 0 ? '+' : ''}${posPpl.toFixed(2)} €</td>
                    `;
                    pbody.appendChild(tr);
                });
            }

            // Ordres
            const oContainer = document.getElementById('orders-container');
            oContainer.innerHTML = '';
            if (!data.orders || data.orders.length === 0) {
                oContainer.innerHTML = `
                    <div class="p-3 rounded-xl bg-emerald-950/40 border border-emerald-800/40 text-xs text-emerald-300 flex items-center gap-2">
                        <i class="fa-solid fa-check-circle text-emerald-400"></i>
                        <span>Portefeuille parfaitement aligné. Aucun ordre nécessaire !</span>
                    </div>
                `;
            } else {
                data.orders.forEach(o => {
                    const isBuy = o.action === 'BUY';
                    const div = document.createElement('div');
                    div.className = `p-3 rounded-xl border ${isBuy ? 'bg-emerald-950/40 border-emerald-800/60' : 'bg-red-950/40 border-red-800/60'} text-xs`;
                    div.innerHTML = `
                        <div class="flex items-center justify-between font-bold">
                            <span class="${isBuy ? 'text-emerald-400' : 'text-red-400'}">${isBuy ? 'ACHAT' : 'VENTE'} ${o.ticker}</span>
                            <span class="text-white font-mono">${o.total_eur.toFixed(2)} €</span>
                        </div>
                        <div class="text-gray-400 text-[11px] mt-1 font-mono">${o.shares.toFixed(4)} parts @ env. ${o.estimated_price.toFixed(2)} €</div>
                        <div class="text-gray-300 text-[11px] mt-1 italic">${o.reason}</div>
                    `;
                    oContainer.appendChild(div);
                });
            }
        }

        async function executeBotOrders() {
            const btn = document.getElementById('btn-exec');
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Exécution...';
            try {
                const res = await fetch('/api/execute', { method: 'POST' });
                const result = await res.json();
                alert(result.message || 'Cycle exécuté avec succès !');
                await refreshData();
            } catch (err) {
                alert('Erreur lors de l\'exécution : ' + err);
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Exécuter';
            }
        }

        window.onload = () => {
            initChart();
            refreshData();
            setInterval(refreshData, 30000); // Rafraîchissement automatique toutes les 30s
        };
    </script>
</body>
</html>
"""


class ETFRequestHandler(BaseHTTPRequestHandler):
    state: ETFTradingState = None

    def log_message(self, format, *args):
        # Réduire le bruit dans le terminal
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif parsed.path == "/api/status":
            data = self.state.refresh()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/execute":
            res = self.state.execute_orders()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def start_server(config_path: str = "config_etf.json", port: int = 8085, host: str = "0.0.0.0"):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info(f"Initialisation du Web Dashboard ETF sur http://localhost:{port}...")
    state = ETFTradingState(config_path=config_path)
    ETFRequestHandler.state = state

    server = ThreadingHTTPServer((host, port), ETFRequestHandler)
    print("\n" + "=" * 70)
    print("      ANTIGRAVITY CLOUD - DASHBOARD WEB ETF TRADING 212")
    print(f"      Interface accessible sur : http://localhost:{port}")
    print("      Appuyez sur Ctrl+C pour arrêter le serveur.")
    print("=" * 70 + "\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du Web Dashboard ETF.")
        server.server_close()


if __name__ == "__main__":
    start_server()
