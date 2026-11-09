"""
Stratégie ETF Hybride (DCA Intelligent + Filtre de Tendance SMA 200)
Combine la puissance de l'accumulation passive avec la protection contre les krachs majeurs.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger("HybridETFStrategy")


@dataclass
class MarketSignal:
    ticker_yf: str
    ticker_t212: str
    name: str
    current_price: float
    sma_200: float
    sma_50: float
    rsi_14: float
    trend: str  # "BULLISH", "BEARISH", "DIP_BUY"
    target_allocation: float
    adjusted_allocation: float
    rationale: str


@dataclass
class ProposedOrder:
    ticker_t212: str
    name: str
    action: str  # "BUY" ou "SELL"
    shares: float
    estimated_price: float
    estimated_total_eur: float
    reason: str


class HybridETFStrategy:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.strategy_cfg = config.get("strategy", {})
        self.portfolio_cfg = config.get("portfolio", {})

        self.sma_period = self.strategy_cfg.get("sma_period", 200)
        self.sma_fast_period = self.strategy_cfg.get("sma_fast_period", 50)
        self.bearish_action = self.strategy_cfg.get("bearish_action", "exit_to_cash")
        self.rebalance_threshold = self.strategy_cfg.get("rebalance_threshold_percent", 5.0) / 100.0
        self.cash_reserve = self.strategy_cfg.get("cash_reserve_percent", 2.0) / 100.0

    def compute_rsi(self, series: pd.Series, period: int = 14) -> float:
        """Calcule le RSI (Relative Strength Index) sur une série de clôtures."""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else 50.0

    def analyze_etf(self, ticker_yf: str, ticker_t212: str, name: str, target_alloc: float) -> MarketSignal:
        """
        Télécharge les données historiques récentes via Yahoo Finance et calcule
        les indicateurs techniques fondamentaux (SMA 200, SMA 50, RSI).
        """
        logger.info(f"Analyse de tendance pour {name} ({ticker_yf})...")
        
        # Correspondances de secours Yahoo Finance pour les ETFs européens
        FALLBACK_MAP = {
            "EQAC.DE": "EQQQ.DE",
            "EQAC": "EQQQ.DE",
            "VUAA": "VUAA.DE",
        }

        # Récupération de l'historique pour calculer la SMA 200 proprement
        df = yf.download(ticker_yf, period="2y", interval="1d", progress=False)
        
        if (df.empty or len(df) < self.sma_period) and ticker_yf in FALLBACK_MAP:
            alt_ticker = FALLBACK_MAP[ticker_yf]
            logger.info(f"Symbole alternatif testé pour {ticker_yf} -> {alt_ticker}")
            df = yf.download(alt_ticker, period="2y", interval="1d", progress=False)
            if not df.empty:
                ticker_yf = alt_ticker

        if df.empty or len(df) < self.sma_period:
            logger.warning(f"Données insuffisantes pour {ticker_yf}, utilisation du dernier cours disponible.")
            current_price = float(df["Close"].iloc[-1]) if not df.empty else 100.0
            return MarketSignal(
                ticker_yf=ticker_yf,
                ticker_t212=ticker_t212,
                name=name,
                current_price=current_price,
                sma_200=current_price,
                sma_50=current_price,
                rsi_14=50.0,
                trend="BULLISH",
                target_allocation=target_alloc,
                adjusted_allocation=target_alloc,
                rationale="Données historiques limitées, maintien de l'allocation cible."
            )

        close = df["Close"].squeeze()
        current_price = float(close.iloc[-1])
        sma_200 = float(close.rolling(window=self.sma_period).mean().iloc[-1])
        sma_50 = float(close.rolling(window=self.sma_fast_period).mean().iloc[-1])
        rsi_14 = self.compute_rsi(close, period=14)

        # Logique de décision Hybride
        if current_price >= sma_200:
            if rsi_14 <= 42.0:
                trend = "DIP_BUY"
                rationale = f"Tendance haussière saine (Cours {current_price:.2f}€ > SMA200 {sma_200:.2f}€) + repli attractif (RSI {rsi_14:.1f}). Opportunité d'achat !"
            else:
                trend = "BULLISH"
                rationale = f"Tendance haussière confirmée (Cours {current_price:.2f}€ > SMA200 {sma_200:.2f}€). Marché favorable à l'accumulation."
            adjusted_alloc = target_alloc
        else:
            trend = "BEARISH"
            if self.bearish_action == "exit_to_cash":
                adjusted_alloc = 0.0
                rationale = f"Alerte krach / tendance baissière (Cours {current_price:.2f}€ < SMA200 {sma_200:.2f}€). Sécurisation en cash pour préserver le capital."
            else:
                adjusted_alloc = target_alloc
                rationale = f"Tendance baissière (Cours < SMA200). Maintien des parts actuelles mais suspension des nouveaux achats."

        return MarketSignal(
            ticker_yf=ticker_yf,
            ticker_t212=ticker_t212,
            name=name,
            current_price=current_price,
            sma_200=sma_200,
            sma_50=sma_50,
            rsi_14=rsi_14,
            trend=trend,
            target_allocation=target_alloc,
            adjusted_allocation=adjusted_alloc,
            rationale=rationale
        )

    def evaluate_portfolio(
        self,
        signals: List[MarketSignal],
        cash_data: Dict[str, Any],
        portfolio_positions: List[Dict[str, Any]],
    ) -> List[ProposedOrder]:
        """
        Compare les allocations cibles ajustées avec l'état réel du portefeuille sur Trading 212
        et génère les ordres nécessaires (Achats DCA ou Ventes de protection).
        """
        free_cash = float(cash_data.get("free", 0.0))
        total_account_value = float(cash_data.get("total", free_cash))

        # Valeur nette utilisable (on garde une petite marge de sécurité de 2%)
        investable_total = total_account_value * (1.0 - self.cash_reserve)

        # Mapper les positions actuelles par ticker T212
        positions_by_ticker = {
            pos["ticker"]: {
                "quantity": float(pos.get("quantity", 0.0)),
                "currentPrice": float(pos.get("currentPrice", 0.0)),
                "totalValue": float(pos.get("quantity", 0.0)) * float(pos.get("currentPrice", 0.0))
            }
            for pos in portfolio_positions
        }

        orders: List[ProposedOrder] = []

        # 1. D'abord vérifier les ventes de protection (exit_to_cash pour les ETF baissiers)
        for sig in signals:
            current_pos = positions_by_ticker.get(sig.ticker_t212, {"quantity": 0.0, "totalValue": 0.0})
            qty_held = current_pos["quantity"]

            if sig.trend == "BEARISH" and self.bearish_action == "exit_to_cash" and qty_held > 0.001:
                orders.append(
                    ProposedOrder(
                        ticker_t212=sig.ticker_t212,
                        name=sig.name,
                        action="SELL",
                        shares=-qty_held,  # Quantité négative pour vente T212
                        estimated_price=sig.current_price,
                        estimated_total_eur=qty_held * sig.current_price,
                        reason=f"Protection Krach : Cours sous la SMA200 ({sig.current_price:.2f}€ < {sig.sma_200:.2f}€)."
                    )
                )

        # 2. Calculer les achats d'accumulation (DCA) sur les ETF haussiers
        for sig in signals:
            if sig.trend in ("BULLISH", "DIP_BUY"):
                target_value = investable_total * sig.adjusted_allocation
                current_pos = positions_by_ticker.get(sig.ticker_t212, {"quantity": 0.0, "totalValue": 0.0})
                current_value = current_pos["totalValue"]

                delta_eur = target_value - current_value

                # Si l'écart dépasse le seuil de tolérance (ex: 5%) et qu'il y a du cash disponible
                if delta_eur > (target_value * self.rebalance_threshold) and delta_eur >= 1.0 and free_cash >= 1.0:
                    amount_to_spend = min(delta_eur, free_cash)
                    shares_to_buy = round(amount_to_spend / sig.current_price, 4)

                    if shares_to_buy > 0.0001:
                        orders.append(
                            ProposedOrder(
                                ticker_t212=sig.ticker_t212,
                                name=sig.name,
                                action="BUY",
                                shares=shares_to_buy,
                                estimated_price=sig.current_price,
                                estimated_total_eur=shares_to_buy * sig.current_price,
                                reason=f"DCA & Rééquilibrage ({sig.trend}) : objectif={sig.adjusted_allocation*100:.0f}%, actuel={(current_value/total_account_value)*100 if total_account_value>0 else 0:.1f}%."
                            )
                        )
                        free_cash -= (shares_to_buy * sig.current_price)

        return orders
