"""
Client Trading 212 Public API (v0)
Fournit une interface Python simple, robuste et sécurisée pour interagir avec Trading 212.
Supporte le compte Démo (papier) et Réel (Live).
"""

import base64
import logging
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger("Trading212Client")


class Trading212Error(Exception):
    """Exception levée en cas d'erreur de l'API Trading 212."""
    pass


class Trading212Client:
    DEMO_URL = "https://demo.trading212.com/api/v0"
    LIVE_URL = "https://live.trading212.com/api/v0"

    def __init__(
        self,
        api_key: str,
        api_secret: Optional[str] = None,
        environment: str = "demo",
        timeout: int = 15,
    ):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip() if api_secret else None
        self.environment = environment.lower()
        self.timeout = timeout

        if self.environment == "live":
            self.base_url = self.LIVE_URL
        else:
            self.base_url = self.DEMO_URL

        self.session = requests.Session()
        self._setup_headers()

    def _setup_headers(self) -> None:
        """Configure les en-têtes d'authentification."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Antigravity-ETF-Bot/1.0",
        }

        # Trading 212 supporte l'authentification Basic (Key:Secret) ou l'API Key directe
        if self.api_secret and self.api_secret != "VOTRE_SECRET_API_TRADING_212":
            auth_string = f"{self.api_key}:{self.api_secret}"
            b64_auth = base64.b64encode(auth_string.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {b64_auth}"
        else:
            headers["Authorization"] = self.api_key

        self.session.headers.update(headers)

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            if response.status_code == 401:
                raise Trading212Error("Erreur 401 : Clé API Trading 212 invalide ou expirée.")
            elif response.status_code == 403:
                raise Trading212Error("Erreur 403 : Accès interdit. Vérifiez les permissions de votre clé API et la restriction d'adresse IP.")
            elif response.status_code == 429:
                reset_time = response.headers.get("x-ratelimit-reset", "quelques secondes")
                raise Trading212Error(f"Erreur 429 : Limite de requêtes dépassée. Réessayez dans {reset_time}.")
            
            response.raise_for_status()

            if response.content:
                return response.json()
            return {}
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur réseau Trading 212 ({url}) : {e}")
            raise Trading212Error(f"Erreur de communication avec Trading 212 : {e}")

    # ==========================
    # Compte & Liquidités (Cash)
    # ==========================
    def get_account_cash(self) -> Dict[str, Any]:
        """
        Récupère les liquidités du compte (en EUR).
        Retourne : free (cash disponible), total (valeur totale), ppl (profit/perte latent), etc.
        """
        return self._request("GET", "/equity/account/cash")

    def get_account_info(self) -> Dict[str, Any]:
        """Récupère les informations générales du compte (devise, ID...)."""
        return self._request("GET", "/equity/account/info")

    # ==========================
    # Portefeuille (Portfolio)
    # ==========================
    def get_portfolio(self) -> List[Dict[str, Any]]:
        """
        Récupère toutes les positions ouvertes en portefeuille.
        Chaque position contient : ticker, quantity, averagePrice, currentPrice, ppl...
        """
        return self._request("GET", "/equity/portfolio")

    def get_position(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Récupère une position spécifique par son ticker T212 (ex: 'VUAA_DE_EQ')."""
        try:
            return self._request("GET", f"/equity/portfolio/{ticker}")
        except Trading212Error as e:
            if "404" in str(e):
                return None
            raise

    # ==========================
    # Ordres de bourse (Orders)
    # ==========================
    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Récupère la liste des ordres en attente d'exécution."""
        return self._request("GET", "/equity/orders")

    def place_market_order(self, ticker: str, quantity: float) -> Dict[str, Any]:
        """
        Place un ordre au marché sur un ETF / action.
        - quantity > 0 pour ACHETER (ex: +2.5 parts)
        - quantity < 0 pour VENDRE (ex: -1.0 part)
        """
        if quantity == 0:
            raise ValueError("La quantité d'un ordre ne peut pas être égale à 0.")

        payload = {
            "ticker": ticker,
            "quantity": quantity
        }
        logger.info(f"Envoi ordre marché T212 : {ticker} (quantité={quantity})")
        return self._request("POST", "/equity/orders/market", json=payload)

    def cancel_order(self, order_id: int) -> Dict[str, Any]:
        """Annule un ordre en attente par son ID."""
        return self._request("DELETE", f"/equity/orders/{order_id}")

    # ==========================
    # Métadonnées & Instruments
    # ==========================
    def get_instruments(self) -> List[Dict[str, Any]]:
        """Récupère la liste des instruments disponibles sur Trading 212."""
        return self._request("GET", "/equity/metadata/instruments")
