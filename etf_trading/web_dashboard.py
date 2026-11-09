"""
Antigravity Cloud - ETF Trading Web Dashboard
Interface Web interactive, moderne et temps réel pour piloter la stratégie hybride Trading 212.
Pré-remplissage instantané des données côté serveur (rendu en 0 ms garanti).
Port par défaut : 8085
"""

import datetime
import json
import logging
import math
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import urlparse

from t212_client import Trading212Client, Trading212Error
from strategy_hybrid import HybridETFStrategy, MarketSignal

logger = logging.getLogger("ETFWebDashboard")


def safe_num(val: Any, default: float = 0.0) -> float:
    """Garantit qu'aucun NaN ou Inf ne casse la sérialisation JSON."""
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def load_config(config_path: str = "config_etf.json") -> Dict[str, Any]:
    if not os.path.exists(config_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        alt_path = os.path.join(script_dir, config_path)
        if os.path.exists(alt_path):
            config_path = alt_path
        else:
            raise FileNotFoundError(f"Config non trouvée : {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


class ETFTradingState:
    """Gère l'état et le cache pour une réponse instantanée (<1ms) du tableau de bord."""
    def __init__(self, config_path: str = "config_etf.json"):
        self.config_path = config_path
        self.lock = threading.Lock()
        self.config = {}
        self.is_refreshing = False
        self.cached_status = {
            "environment": "DEMO",
            "mode": "HYBRID",
            "t212_connected": False,
            "t212_error": "Initialisation en cours...",
            "cash": {"free": 0.0, "total": 0.0, "ppl": 0.0},
            "portfolio": [],
            "signals": [],
            "orders": [],
            "last_update": "--:--:--",
            "is_loading": True
        }
        self.reload_config()
        self.refresh()

    def reload_config(self):
        try:
            self.config = load_config(self.config_path)
            t212_cfg = self.config.get("trading212", {})
            self.client = Trading212Client(
                api_key=t212_cfg.get("api_key", ""),
                api_secret=t212_cfg.get("api_secret", ""),
                environment=t212_cfg.get("environment", "demo")
            )
            self.strategy = HybridETFStrategy(self.config)
        except Exception as e:
            logger.error(f"Erreur chargement config : {e}")

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.cached_status)

    def refresh(self) -> Dict[str, Any]:
        with self.lock:
            if self.is_refreshing:
                return self.cached_status
            self.is_refreshing = True

        try:
            self.reload_config()
            env = self.config.get("trading212", {}).get("environment", "demo").upper()
            mode = self.config.get("strategy", {}).get("mode", "hybrid").upper()
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
            except Exception as e:
                t212_connected = False
                t212_error = f"Erreur inattendue Trading 212 : {e}"

            # 2. Analyse technique des ETFs
            signals_data = []
            portfolio_cfg = self.config.get("portfolio", {})
            for key, etf_data in portfolio_cfg.items():
                yf_symbol = etf_data.get("yfinance_ticker", key)
                t212_ticker = etf_data.get("t212_ticker")
                name = etf_data.get("name")
                target_alloc = safe_num(etf_data.get("target_allocation", 0.5), 0.5)

                try:
                    sig = self.strategy.analyze_etf(yf_symbol, t212_ticker, name, target_alloc)
                    cur_p = safe_num(sig.current_price, 100.0)
                    sma_200 = safe_num(sig.sma_200, cur_p)
                    sma_50 = safe_num(sig.sma_50, cur_p)
                    rsi = safe_num(sig.rsi_14, 50.0)
                    dist_pct = ((cur_p - sma_200) / sma_200) * 100 if sma_200 > 0 else 0.0

                    signals_data.append({
                        "ticker_yf": sig.ticker_yf,
                        "ticker_t212": sig.ticker_t212,
                        "name": sig.name,
                        "current_price": round(cur_p, 2),
                        "sma_200": round(sma_200, 2),
                        "sma_50": round(sma_50, 2),
                        "dist_sma200_pct": round(safe_num(dist_pct), 2),
                        "rsi_14": round(rsi, 1),
                        "trend": sig.trend,
                        "target_allocation": sig.target_allocation,
                        "adjusted_allocation": sig.adjusted_allocation,
                        "rationale": sig.rationale
                    })
                except Exception as e:
                    logger.error(f"Erreur analyse ETF {key} : {e}")

            # 3. Évaluation des ordres
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
                    "shares": round(safe_num(o.shares), 4),
                    "estimated_price": round(safe_num(o.estimated_price), 2),
                    "total_eur": round(safe_num(o.estimated_total_eur), 2),
                    "reason": o.reason
                } for o in proposed_orders
            ]

            now_str = datetime.datetime.now().strftime("%H:%M:%S")

            with self.lock:
                self.cached_status = {
                    "environment": env,
                    "mode": mode,
                    "t212_connected": t212_connected,
                    "t212_error": t212_error,
                    "cash": {
                        "free": round(safe_num(cash.get("free", 0.0)), 2),
                        "total": round(safe_num(cash.get("total", cash.get("free", 0.0))), 2),
                        "ppl": round(safe_num(cash.get("ppl", 0.0)), 2)
                    },
                    "portfolio": portfolio,
                    "signals": signals_data,
                    "orders": orders_data,
                    "last_update": now_str,
                    "is_loading": False
                }
                logger.info(f"Actualisation terminée à {now_str}. T212 connecté : {t212_connected}")
                return self.cached_status
        except Exception as e:
            logger.error(f"Erreur critique lors de refresh() : {e}", exc_info=True)
            with self.lock:
                self.cached_status["is_loading"] = False
                self.cached_status["server_error"] = str(e)
                return self.cached_status
        finally:
            with self.lock:
                self.is_refreshing = False

    def execute_orders(self) -> Dict[str, Any]:
        with self.lock:
            if not self.cached_status["t212_connected"]:
                return {"status": "error", "message": "Impossible d'exécuter: Trading 212 non connecté."}
            
            orders = self.cached_status.get("orders", [])
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

        threading.Thread(target=self.refresh, daemon=True).start()
        return {"status": "ok", "executed": executed}


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Antigravity Cloud - Bot ETF Trading 212</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #0B0F19; color: #F3F4F6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .glass-card { background: rgba(17, 24, 39, 0.85); border: 1px solid #1F2937; }
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
                    📈
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
                    <span class="w-2 h-2 rounded-full bg-yellow-400 pulse-live"></span> Initialisation...
                </span>
                <button onclick="triggerRefresh()" id="btn-refresh" class="px-4 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs font-medium text-gray-200 transition flex items-center gap-2">
                    🔄 Actualiser (<span id="last-update">--:--:--</span>)
                </button>
            </div>
        </header>

        <!-- ALERTE ERREUR T212 (si présente) -->
        <div id="alert-banner" class="hidden mt-6 p-4 rounded-xl bg-red-950/60 border border-red-800/80 text-red-200 text-sm">
            <div class="flex items-start gap-3">
                <span class="text-red-400 text-lg">⚠️</span>
                <div class="flex-1">
                    <h3 class="font-bold text-red-300">Statut Trading 212</h3>
                    <p id="alert-message" class="text-xs mt-1 text-red-300/90 whitespace-pre-line"></p>
                </div>
            </div>
        </div>

        <!-- STATS CARDS -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-6">
            <div class="glass-card p-5 rounded-2xl">
                <div class="flex items-center justify-between text-gray-400 text-xs font-medium">
                    <span>VALEUR TOTALE DU COMPTE</span>
                    <span>💼</span>
                </div>
                <div id="val-total" class="text-2xl font-black text-white mt-2">0.00 €</div>
                <div class="text-[11px] text-gray-400 mt-1">Positions + Liquidités</div>
            </div>

            <div class="glass-card p-5 rounded-2xl">
                <div class="flex items-center justify-between text-gray-400 text-xs font-medium">
                    <span>LIQUIDITÉS DISPONIBLES</span>
                    <span>💶</span>
                </div>
                <div id="val-cash" class="text-2xl font-black text-emerald-400 mt-2">0.00 €</div>
                <div class="text-[11px] text-gray-400 mt-1">Prêt pour les futurs achats DCA</div>
            </div>

            <div class="glass-card p-5 rounded-2xl">
                <div class="flex items-center justify-between text-gray-400 text-xs font-medium">
                    <span>PROFIT / PERTE LATENTE</span>
                    <span>📊</span>
                </div>
                <div id="val-ppl" class="text-2xl font-black text-gray-300 mt-2">+0.00 €</div>
                <div class="text-[11px] text-gray-400 mt-1">Performance globale non réalisée</div>
            </div>

            <div class="glass-card p-5 rounded-2xl">
                <div class="flex items-center justify-between text-gray-400 text-xs font-medium">
                    <span>BOUCLIER ANTI-KRACH</span>
                    <span>🛡️</span>
                </div>
                <div id="shield-status" class="text-xl font-bold text-emerald-400 mt-2">🟢 ACTIF</div>
                <div class="text-[11px] text-gray-400 mt-1">Surveillance SMA 200 en direct</div>
            </div>
        </div>

        <!-- GRILLE PRINCIPALE (SIGNAUX & ALLOCATION) -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
            <!-- COLONNE 1 & 2 : SIGNAUX DE TENDANCE DES ETFS -->
            <div class="lg:col-span-2 space-y-4">
                <div class="flex items-center justify-between">
                    <h2 class="text-sm font-bold tracking-wider text-gray-300 uppercase flex items-center gap-2">
                        📡 Signaux Techniques & Tendance (SMA 200)
                    </h2>
                    <span class="text-xs text-gray-500">Source : Yahoo Finance Live</span>
                </div>

                <div id="signals-container" class="space-y-4">
                    <!-- Rempli en direct -->
                </div>

                <!-- TABLEAU DES POSITIONS TRADING 212 -->
                <div class="glass-card p-5 rounded-2xl mt-6">
                    <h3 class="text-xs font-bold uppercase text-gray-400 tracking-wider mb-4 flex items-center gap-2">
                        📦 Portefeuille Détenu sur Trading 212
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
                <!-- ALLOCATION -->
                <div class="glass-card p-5 rounded-2xl">
                    <h2 class="text-sm font-bold tracking-wider text-gray-300 uppercase flex items-center gap-2 mb-4">
                        🎯 Répartition Cible
                    </h2>
                    <div class="space-y-4">
                        <div>
                            <div class="flex justify-between text-xs mb-1">
                                <span class="font-bold text-blue-400">Vanguard S&P 500 (VUAA)</span>
                                <span class="font-mono text-gray-300">60%</span>
                            </div>
                            <div class="w-full bg-gray-800 h-3 rounded-full overflow-hidden">
                                <div class="bg-blue-500 h-full rounded-full" style="width: 60%"></div>
                            </div>
                        </div>
                        <div>
                            <div class="flex justify-between text-xs mb-1">
                                <span class="font-bold text-purple-400">Invesco Nasdaq 100 (EQAC)</span>
                                <span class="font-mono text-gray-300">40%</span>
                            </div>
                            <div class="w-full bg-gray-800 h-3 rounded-full overflow-hidden">
                                <div class="bg-purple-500 h-full rounded-full" style="width: 40%"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- ORDRES PROPOSÉS PAR LE BOT -->
                <div class="glass-card p-5 rounded-2xl">
                    <div class="flex items-center justify-between mb-4">
                        <h2 class="text-sm font-bold tracking-wider text-gray-300 uppercase flex items-center gap-2">
                            🤖 Décisions du Bot
                        </h2>
                        <button onclick="executeBotOrders()" id="btn-exec" class="px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white transition disabled:opacity-50 flex items-center gap-1.5">
                            ⚡ Exécuter
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
        // DONNÉES PRÉ-CHARGÉES CÔTÉ SERVEUR (0 milliseconde de latence)
        const SERVER_DATA = __INITIAL_DATA__;

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                if (!res.ok) throw new Error("HTTP " + res.status);
                const data = await res.json();
                renderUI(data);
            } catch (err) {
                console.error("Erreur fetchStatus :", err);
            }
        }

        async function triggerRefresh() {
            const btn = document.getElementById('btn-refresh');
            btn.disabled = true;
            try {
                const res = await fetch('/api/refresh', { method: 'POST' });
                const data = await res.json();
                renderUI(data);
            } catch (err) {
                console.error("Erreur triggerRefresh :", err);
                await fetchStatus();
            } finally {
                btn.disabled = false;
            }
        }

        function renderUI(data) {
            if (!data) return;

            document.getElementById('last-update').innerText = data.last_update || '--:--:--';
            document.getElementById('env-badge').innerText = 'ENVIRONNEMENT : ' + (data.environment || 'DEMO');

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
            const cash = data.cash || { total: 0, free: 0, ppl: 0 };
            document.getElementById('val-total').innerText = Number(cash.total || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2 }) + ' €';
            document.getElementById('val-cash').innerText = Number(cash.free || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2 }) + ' €';
            
            const pplVal = Number(cash.ppl || 0);
            const pplEl = document.getElementById('val-ppl');
            pplEl.innerText = (pplVal >= 0 ? '+' : '') + pplVal.toLocaleString('fr-FR', { minimumFractionDigits: 2 }) + ' €';
            pplEl.className = pplVal >= 0 ? 'text-2xl font-black text-emerald-400 mt-2' : 'text-2xl font-black text-red-400 mt-2';

            // Signaux
            const sigContainer = document.getElementById('signals-container');
            const signals = data.signals || [];
            
            if (signals.length > 0) {
                sigContainer.innerHTML = '';
                let allBullish = true;
                signals.forEach(sig => {
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
                                <span class="text-base font-bold text-white">${Number(sig.current_price).toFixed(2)} €</span>
                            </div>
                            <div>
                                <span class="text-[10px] text-gray-500 uppercase block">SMA 200 Jours</span>
                                <span class="text-base font-bold text-gray-300">${Number(sig.sma_200).toFixed(2)} €</span>
                                <span class="text-[10px] ${sig.dist_sma200_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}">
                                    (${sig.dist_sma200_pct >= 0 ? '+' : ''}${Number(sig.dist_sma200_pct).toFixed(2)}%)
                                </span>
                            </div>
                            <div>
                                <span class="text-[10px] text-gray-500 uppercase block">SMA 50 Jours</span>
                                <span class="text-base font-bold text-gray-300">${Number(sig.sma_50).toFixed(2)} €</span>
                            </div>
                            <div>
                                <span class="text-[10px] text-gray-500 uppercase block">RSI 14 Jours</span>
                                <span class="text-base font-bold text-white">${Number(sig.rsi_14).toFixed(1)}</span>
                                <div class="w-full bg-gray-800 h-1.5 rounded-full mt-1 overflow-hidden">
                                    <div class="${rsiColor} h-full" style="width: ${Math.min(sig.rsi_14, 100)}%"></div>
                                </div>
                            </div>
                        </div>

                        <div class="p-3 rounded-xl bg-gray-900/60 border border-gray-800 text-xs text-gray-300">
                            ℹ️ <span class="ml-1">${sig.rationale}</span>
                        </div>
                    `;
                    sigContainer.appendChild(card);
                });
                document.getElementById('shield-status').innerText = allBullish ? '🟢 MARCHÉ NORMAL' : '🔴 BOUCLIER KRACH (CASH)';
            }

            // Portefeuille
            const pbody = document.getElementById('portfolio-tbody');
            const portfolio = data.portfolio || [];
            pbody.innerHTML = '';
            if (portfolio.length === 0) {
                pbody.innerHTML = '<tr><td colspan="6" class="py-4 text-center text-gray-500">Aucune position ouverte sur Trading 212.</td></tr>';
            } else {
                portfolio.forEach(pos => {
                    const tr = document.createElement('tr');
                    const qty = Number(pos.quantity || 0);
                    const curP = Number(pos.currentPrice || 0);
                    const avgP = Number(pos.averagePrice || 0);
                    const val = qty * curP;
                    const posPpl = Number(pos.ppl || 0);
                    tr.innerHTML = `
                        <td class="py-2.5 font-bold text-white">${pos.ticker}</td>
                        <td class="py-2.5">${qty.toFixed(4)}</td>
                        <td class="py-2.5">${avgP.toFixed(2)} €</td>
                        <td class="py-2.5 text-blue-400">${curP.toFixed(2)} €</td>
                        <td class="py-2.5 text-white">${val.toFixed(2)} €</td>
                        <td class="py-2.5 ${posPpl >= 0 ? 'text-emerald-400' : 'text-red-400'}">${posPpl >= 0 ? '+' : ''}${posPpl.toFixed(2)} €</td>
                    `;
                    pbody.appendChild(tr);
                });
            }

            // Ordres
            const oContainer = document.getElementById('orders-container');
            const orders = data.orders || [];
            oContainer.innerHTML = '';
            if (orders.length === 0) {
                oContainer.innerHTML = `
                    <div class="p-3 rounded-xl bg-emerald-950/40 border border-emerald-800/40 text-xs text-emerald-300 flex items-center gap-2">
                        <span>✅ Portefeuille parfaitement aligné. Aucun ordre nécessaire !</span>
                    </div>
                `;
            } else {
                orders.forEach(o => {
                    const isBuy = o.action === 'BUY';
                    const div = document.createElement('div');
                    div.className = `p-3 rounded-xl border ${isBuy ? 'bg-emerald-950/40 border-emerald-800/60' : 'bg-red-950/40 border-red-800/60'} text-xs`;
                    div.innerHTML = `
                        <div class="flex items-center justify-between font-bold">
                            <span class="${isBuy ? 'text-emerald-400' : 'text-red-400'}">${isBuy ? 'ACHAT' : 'VENTE'} ${o.ticker}</span>
                            <span class="text-white font-mono">${Number(o.total_eur).toFixed(2)} €</span>
                        </div>
                        <div class="text-gray-400 text-[11px] mt-1 font-mono">${Number(o.shares).toFixed(4)} parts @ env. ${Number(o.estimated_price).toFixed(2)} €</div>
                        <div class="text-gray-300 text-[11px] mt-1 italic">${o.reason}</div>
                    `;
                    oContainer.appendChild(div);
                });
            }
        }

        async function executeBotOrders() {
            const btn = document.getElementById('btn-exec');
            btn.disabled = true;
            btn.innerHTML = '⏳ Exécution...';
            try {
                const res = await fetch('/api/execute', { method: 'POST' });
                const result = await res.json();
                alert(result.message || 'Cycle exécuté avec succès !');
                await triggerRefresh();
            } catch (err) {
                alert('Erreur lors de l\'exécution : ' + err);
            } finally {
                btn.disabled = false;
                btn.innerHTML = '⚡ Exécuter';
            }
        }

        // RENDU IMMÉDIAT (sans attendre d'appel réseau)
        if (SERVER_DATA && !SERVER_DATA.is_loading) {
            renderUI(SERVER_DATA);
        } else {
            fetchStatus();
        }

        // Polling en arrière-plan toutes les 15 secondes
        setInterval(fetchStatus, 15000);
    </script>
</body>
</html>
"""


class ETFRequestHandler(BaseHTTPRequestHandler):
    state: ETFTradingState = None

    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            data = self.state.get_status()
            # Injection immédiate des données dans le HTML
            html = HTML_TEMPLATE.replace("__INITIAL_DATA__", json.dumps(data, ensure_ascii=False))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        elif parsed.path == "/api/status":
            data = self.state.get_status()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        elif parsed.path == "/api/refresh":
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
        if parsed.path in ("/api/execute",):
            res = self.state.execute_orders()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
        elif parsed.path in ("/api/refresh",):
            data = self.state.refresh()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def start_server(config_path: str = "config_etf.json", port: int = 8085, host: str = "0.0.0.0"):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info(f"Démarrage du Web Dashboard ETF Antigravity sur http://localhost:{port}...")
    
    state = ETFTradingState(config_path=config_path)
    ETFRequestHandler.state = state

    # Tâche de fond pour rafraîchir les données toutes les 60 secondes
    def background_loop():
        while True:
            time.sleep(60)
            try:
                state.refresh()
            except Exception as e:
                logger.error(f"Erreur actualisation automatique : {e}")

    threading.Thread(target=background_loop, daemon=True).start()

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
