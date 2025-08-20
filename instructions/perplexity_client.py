from __future__ import annotations

import json
import os
from typing import Any, Optional

import requests
from dotenv import load_dotenv


PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
DEFAULT_MODEL = "sonar-pro"


def _compact_json(data: Any, limit: int = 15000) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(data)
    if len(text) > limit:
        return text[:limit] + " …"
    return text


def summarize_company_perplexity(data: Any, *, model: Optional[str] = None, timeout_seconds: float = 45.0) -> str:
    load_dotenv(override=False)
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        raise RuntimeError("PERPLEXITY_API_KEY manquant dans votre .env")

    chosen_model = model or os.getenv("PERPLEXITY_MODEL", DEFAULT_MODEL)
    payload = _compact_json(data)

    system_msg = (
        "Tu es un analyste légal. Tu produis une synthèse claire et LA PLUS détaillée POSSIBLE d'une société à partir EXCLUSIVEMENT du JSON fourni. "
        "N'invente rien. Si une information n'est pas présente, indique 'Non disponible'. "
        "Ne fais AUCUNE référence à d'autres API, sources, ou contextes. "
        "Structure recommandée: Identification; Activité; Dirigeants/Associés; Capital/Finances; Établissements/Adresse; Documents/Actes marquants; Dates clés; Alertes/Points sensibles."
    )
    user_msg = (
        "Voici les données JSON (exclusives à cette synthèse). Analyse et synthétise en français, sans redondance et sans spéculation.\n\n"
        + payload
    )

    url = f"{PERPLEXITY_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
    }
    resp = requests.post(url, headers=headers, json=body, timeout=timeout_seconds)
    data = resp.json()
    if resp.status_code >= 400:
        raise requests.HTTPError(f"Perplexity HTTP {resp.status_code}: {json.dumps(data, ensure_ascii=False)}", response=resp)
    try:
        return data["choices"][0]["message"]["content"] or ""
    except Exception:
        return ""


def research_company_perplexity(*, siren: str, denomination: Optional[str] = None,
                                model: Optional[str] = None, timeout_seconds: float = 60.0,
                                return_citations: bool = False) -> str:
    """Launch a web-backed Perplexity research using only public info (SIREN and optional denomination).

    Produces a structured French summary comparable to other agents, without using provided JSON.
    """
    load_dotenv(override=False)
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        raise RuntimeError("PERPLEXITY_API_KEY manquant dans votre .env")

    chosen_model = model or os.getenv("PERPLEXITY_MODEL_RESEARCH") or os.getenv("PERPLEXITY_MODEL") or DEFAULT_MODEL

    system_msg = (
        "Tu es un analyste légal. Recherche sur le web pour établir un profil d'entreprise français. "
        "Travaille uniquement à partir des informations publiques retournées par la recherche. "
        "Ne fabrique pas d'information. "
        "Structure recommandée: Identification; Activité; Dirigeants/Associés; Capital/Finances; Établissements/Adresse; Documents/Actes marquants; Dates clés; Alertes/Points sensibles."
    )

    hints = []
    hints.append(f"SIREN: {siren}")
    if denomination:
        hints.append(f"Dénomination: {denomination}")
    user_msg = (
        "Effectue une recherche web (France) pour retrouver et synthétiser les informations clés sur une société à partir des indices suivants. "
        "Fournis une synthèse en français, la plus détaillée possible, comparable aux autres rapports.\n\n"
        + "\n".join(hints)
    )

    url = f"{PERPLEXITY_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
    }
    if return_citations:
        body["return_citations"] = True
    resp = requests.post(url, headers=headers, json=body, timeout=timeout_seconds)
    data = resp.json()
    if resp.status_code >= 400:
        raise requests.HTTPError(f"Perplexity HTTP {resp.status_code}: {json.dumps(data, ensure_ascii=False)}", response=resp)
    try:
        return data["choices"][0]["message"]["content"] or ""
    except Exception:
        return ""


