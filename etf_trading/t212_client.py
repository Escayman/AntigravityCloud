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

        # Nettoyage des placeholders courants (ex: 'cle', 'secret', etc.)
        clean_secret = (self.api_secret or "").strip()
        if clean_secret.lower() in ["cle", "clé", "secret", "votre_secret_api_trading_212", "votre_secret_api_ici", "none", "null"]:
            clean_secret = ""
        self.api_secret = clean_secret if clean_secret else None

        # Trading 212 Public API (v0) utilise HTTP Basic Auth avec Key:Secret si secret disponible
        if self.api_secret:
            auth_string = f"{self.api_key}:{self.api_secret}"
            b64_auth = base64.b64encode(auth_string.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {b64_auth}"
        else:
            # Si pas de secret fourni, tenter avec la clé directe
            headers["Authorization"] = self.api_key

        self.session.headers.update(headers)

    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            
            # Si échec 401 et qu'on avait envoyé la clé brute sans secret, tenter avec Bearer
            if response.status_code == 401 and not self.api_secret:
                headers_alt = dict(self.session.headers)
                headers_alt["Authorization"] = f"Bearer {self.api_key}"
                retry_resp = requests.request(method, url, headers=headers_alt, timeout=self.timeout, **kwargs)
                if retry_resp.status_code == 200:
                    self.session.headers["Authorization"] = f"Bearer {self.api_key}"
                    if retry_resp.content:
                        return retry_resp.json()
                    return {}

            if response.status_code == 401:
                env_hint = "DEMO" if self.environment == "demo" else "LIVE (Réel)"
                extra_hint = ""
                # Si échec en mode démo, vérifier si la clé fonctionne sur le serveur Réel (Live)
                if self.environment == "demo":
                    try:
                        live_test_headers = dict(self.session.headers)
                        live_resp = requests.get(f"{self.LIVE_URL}/equity/account/cash", headers=live_test_headers, timeout=5)
                        if live_resp.status_code == 200:
                            extra_hint = "\n  👉 NOTE : Votre clé API est valide sur le compte RÉEL (Live) ! Changez 'environment': 'live' dans config_etf.json."
                    except Exception:
                        pass

                raise Trading212Error(
                    f"Erreur 401 : Clé API Trading 212 non reconnue par l'environnement {env_hint}.\n"
                    f"  1. 'api_secret' : Si Trading 212 ne vous a donné qu'une seule clé, laissez \"api_secret\": \"\".\n"
                    f"     (Ne mettez pas le mot 'cle' dedans, sinon T212 croit que votre mot de passe est 'cle').\n"
                    f"     Si T212 vous a affiché un 'API Secret' à la création, collez ce long code.\n"
                    f"  2. Votre clé a-t-elle été générée sur le compte {env_hint} ?{extra_hint}\n"
                    f"  3. Si la restriction IP est activée sur T212, assurez-vous que votre IP publique est autorisée."
                )
            elif response.status_code == 403:
                raise Trading212Error("Erreur 403 : Accès interdit. Vérifiez les permissions (scopes) de votre clé API.")
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
