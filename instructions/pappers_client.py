"""
Pappers API client to fetch full company data by SIREN.

Environment variables used:
- PAPPERS_API_TOKEN or PAPPERS_API_KEY: your API token
- PAPPERS_BASE_URL (optional, default: https://api.pappers.fr/v2)

Programmatic usage:
    from instructions.pappers_client import PappersClient
    client = PappersClient()
    data = client.get_entreprise_by_siren("552100554")
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_BASE_URL = "https://api.pappers.fr/v2"


def _validate_siren(siren: str) -> str:
    s = (siren or "").strip()
    if not (len(s) == 9 and s.isdigit()):
        raise ValueError("SIREN invalide: doit contenir exactement 9 chiffres")
    return s


def _build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "test-rne-pappers-client/1.0"})
    return session


@dataclass
class PappersClient:
    api_token: str | None = None
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        load_dotenv(override=False)
        if self.api_token is None:
            self.api_token = (
                os.getenv("PAPPERS_API_TOKEN")
                or os.getenv("PAPPERS_API_KEY")
                or ""
            )
        env_base = os.getenv("PAPPERS_BASE_URL")
        if env_base:
            self.base_url = env_base.rstrip("/")
        if not self.api_token:
            raise RuntimeError(
                "Pappers: API token manquant. Définissez PAPPERS_API_TOKEN (ou PAPPERS_API_KEY) dans votre .env"
            )
        self._session = _build_session()

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        query = {"api_token": self.api_token}
        if params:
            query.update(params)
        resp = self._session.get(url, params=query, timeout=self.timeout_seconds)
        try:
            data = resp.json()
        except Exception:
            resp.raise_for_status()
            return {}
        if resp.status_code >= 400:
            raise requests.HTTPError(
                f"Pappers HTTP {resp.status_code}: {json.dumps(data, ensure_ascii=False)}",
                response=resp,
            )
        return data

    def get_entreprise_by_siren(self, siren: str, **extra_params: Any) -> Dict[str, Any]:
        s = _validate_siren(siren)
        params = {"siren": s}
        if extra_params:
            params.update(extra_params)
        return self._request("/entreprise", params=params)

 