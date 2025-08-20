"""
LegalMap API client to fetch company data by SIREN.

Defaults match the notebook configuration you provided:
- Base URL: https://7agsqhzcd0.execute-api.eu-west-3.amazonaws.com/master-api/
- Route: rne/{siren}
- Auth header: x-api-key: <token>

Env overrides (optional):
- LEGALMAP_API_TOKEN or LEGALMAP_API_KEY
- LEGALMAP_API_BASE_URL (default provided above)
- LEGALMAP_COMPANY_URL_TEMPLATE (e.g. https://.../v1/companies/{siren})
- LEGALMAP_COMPANY_PATH (e.g. rne/{siren})

CLI:
    python -m instructions.legalmap_client 552100554
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib.parse import urljoin
DEFAULT_BASE_URL = "https://7agsqhzcd0.execute-api.eu-west-3.amazonaws.com/master-api/"
DEFAULT_RNE_ROUTE = "rne/{siren}"

from urllib3.util.retry import Retry


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
    session.headers.update({"User-Agent": "test-rne-legalmap-client/1.0"})
    return session


@dataclass
class LegalMapClient:
    api_token: str | None = None
    company_url_template: str | None = None
    base_url: str | None = None
    company_path: str | None = None
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        load_dotenv(override=False)
        if self.api_token is None:
            self.api_token = (
                os.getenv("LEGALMAP_API_TOKEN")
                or os.getenv("LEGALMAP_API_KEY")
                or ""
            )
        self.company_url_template = self.company_url_template or os.getenv("LEGALMAP_COMPANY_URL_TEMPLATE")
        # Defaults from notebook if not provided
        self.base_url = (self.base_url or os.getenv("LEGALMAP_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.company_path = (self.company_path or os.getenv("LEGALMAP_COMPANY_PATH") or DEFAULT_RNE_ROUTE)
        if not self.api_token:
            raise RuntimeError(
                "LegalMap: API token manquant. Définissez LEGALMAP_API_TOKEN dans votre .env"
            )
        self._session = _build_session()

    def _headers(self) -> Dict[str, str]:
        return {
            # Notebook uses x-api-key
            "x-api-key": self.api_token,
            "Accept": "application/json",
        }

    def _get_url_and_params(self, siren: str) -> tuple[str, Dict[str, Any]]:
        if self.company_url_template:
            return self.company_url_template.format(siren=siren), {}
        # Format path with {siren} placeholder if present
        formatted_path = self.company_path.format(siren=siren) if "{siren}" in self.company_path else self.company_path
        # Ensure single slash between base and path
        url = urljoin(self.base_url + "/", formatted_path.lstrip("/"))
        return url, {}

    def _request(self, route_or_url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # route_or_url can be an absolute URL or a route relative to base_url
        if route_or_url.startswith("http://") or route_or_url.startswith("https://"):
            url = route_or_url
        else:
            url = urljoin(self.base_url + "/", route_or_url.lstrip("/"))
        resp = self._session.get(url, headers=self._headers(), params=params or {}, timeout=self.timeout_seconds)
        try:
            data = resp.json()
        except Exception:
            content_type = resp.headers.get("Content-Type", "")
            if resp.ok:
                result: Dict[str, Any] = {
                    "_status_code": resp.status_code,
                    "_content_type": content_type,
                }
                if "pdf" in content_type or "octet-stream" in content_type:
                    result["_note"] = "Réponse binaire (probablement un PDF ou un flux)."
                    try:
                        result["_bytes_length"] = len(resp.content)
                    except Exception:
                        pass
                else:
                    try:
                        text = resp.text
                    except Exception:
                        text = "<non-décodable>"
                    result["_text_preview"] = text[:2000]
                return result
            resp.raise_for_status()
            return {"_status_code": resp.status_code}
        if resp.status_code >= 400:
            raise requests.HTTPError(
                f"LegalMap HTTP {resp.status_code}: {json.dumps(data, ensure_ascii=False)}",
                response=resp,
            )
        return data

    def get_company_by_siren(self, siren: str, **extra_params: Any) -> Dict[str, Any]:
        s = _validate_siren(siren)
        url, params = self._get_url_and_params(s)
        if extra_params:
            params.update(extra_params)
        return self._request(url, params=params)

    def search_documents(self, *, search_date_from: str, search_date_to: str, qe: Optional[str] = None,
                          results_group_by: str = "COMPANIES", results_sort_by: str = "SCORES",
                          skip: int = 0, limit: int = 50) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "search_date_from": search_date_from,
            "search_date_to": search_date_to,
            "results_group_by": results_group_by,
            "results_sort_by": results_sort_by,
            "sk": skip,
            "lm": limit,
        }
        if qe:
            params["qe"] = qe
        return self._request("search", params=params)

    def search_all_documents(self, *, search_date_from: str, search_date_to: str, qe: str,
                              results_group_by: str = "COMPANIES", results_sort_by: str = "SCORES",
                              page_size: int = 100, max_results: int = 1000) -> Dict[str, Any]:
        """Paginate over search to aggregate more results.

        Returns a merged structure similar to one page of search but with concatenated search_results.
        """
        aggregated: Dict[str, Any] = {}
        all_results: list[dict] = []
        sk = 0
        while sk < max_results:
            page = self.search_documents(
                search_date_from=search_date_from,
                search_date_to=search_date_to,
                qe=qe,
                results_group_by=results_group_by,
                results_sort_by=results_sort_by,
                skip=sk,
                limit=page_size,
            )
            if not aggregated:
                aggregated = page
            # extract results
            page_results = ((page.get("legalmap", {}) or {}).get("search_results", []) or [])
            if not page_results:
                break
            all_results.extend(page_results)
            if len(page_results) < page_size:
                break
            sk += page_size
        # put back aggregated results
        if "legalmap" not in aggregated:
            aggregated["legalmap"] = {}
        aggregated["legalmap"]["search_results"] = all_results
        return aggregated

    def count_results(self, *, search_date_from: str, search_date_to: str, qe: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "search_date_from": search_date_from,
            "search_date_to": search_date_to,
            "qe": qe,
        }
        return self._request("search/count_results", params=params)

    def get_pdf_details(self, pdf_id: str, *, pages: str = "all", highlight: Optional[str] = None) -> Dict[str, Any]:
        route = f"pdfs/{pdf_id}"
        params: Dict[str, Any] = {"pages": pages}
        if highlight:
            params["highlight"] = highlight
        return self._request(route, params=params)

    def get_bundle_for_siren(self, siren: str, *, days: int = 365, fetch_pdf_details_top: int = 3) -> Dict[str, Any]:
        s = _validate_siren(siren)
        # RNE details
        rne = self.get_company_by_siren(s)
        # Build a default query expression (qe) from denomination or fallback to SIREN
        qe: Optional[str] = None
        try:
            denom = (
                (rne or {})
                .get("formality", {})
                .get("content", {})
                .get("personneMorale", {})
                .get("identite", {})
                .get("entreprise", {})
                .get("denomination")
            )
            if isinstance(denom, str) and denom.strip():
                # Exact phrase to improve precision
                qe = f'"{denom.strip()}"'
        except Exception:
            pass
        if not qe:
            qe = s  # fallback: search by SIREN digits present in many filings

        # Broad search over recent period, then filter by SIREN
        end = datetime.today().strftime("%d/%m/%Y")
        start_dt = datetime.today().replace(year=datetime.today().year - 1) if days >= 365 else datetime.today()
        try:
            start = start_dt.strftime("%d/%m/%Y")
        except Exception:
            start = "01/01/2000"
        search = self.search_all_documents(search_date_from=start, search_date_to=end, qe=qe, page_size=100, max_results=1000)
        # Count results for completeness (as in notebook examples)
        try:
            count = self.count_results(search_date_from=start, search_date_to=end, qe=qe)
        except Exception as _:
            count = {"error": "count_results failed"}
        company_results: list[dict] = []
        try:
            for res in (search.get("legalmap", {}) or {}).get("search_results", []) or []:
                if str(res.get("rne", {}).get("siren", "")).zfill(9) == s:
                    company_results.append(res)
        except Exception:
            pass
        # Optionally enrich with PDF details for top documents
        pdf_details: list[dict] = []
        try:
            for doc in company_results[:fetch_pdf_details_top]:
                pdf_id = doc.get("acte_id") or doc.get("inpi_id")
                if not pdf_id:
                    continue
                try:
                    pdf_details.append(self.get_pdf_details(pdf_id, pages="all", highlight=qe))
                except Exception:
                    continue
        except Exception:
            pass
        return {
            "rne": rne,
            "search_company_results": company_results,
            "_search_raw": search,
            "_count_results": count,
            "_pdf_details_top": pdf_details,
        }


def _main_cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Récupère les données LegalMap d'une entreprise par SIREN")
    parser.add_argument("siren", type=str, help="SIREN (9 chiffres)")
    parser.add_argument("--template", dest="template", type=str, default=None, help="URL template avec {siren}")
    parser.add_argument("--base-url", dest="base_url", type=str, default=None, help="Base URL si mode query param")
    parser.add_argument("--path", dest="path", type=str, default=None, help="Chemin endpoint si mode query param")
    args = parser.parse_args()

    client = LegalMapClient(
        company_url_template=args.template,
        base_url=args.base_url,
        company_path=args.path,
    )
    data = client.get_company_by_siren(args.siren)
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main_cli()


