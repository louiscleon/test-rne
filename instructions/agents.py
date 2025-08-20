from __future__ import annotations

import json
import os
from typing import Any, Optional

from dotenv import load_dotenv


def _compact_json(data: Any, limit: int = 15000) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(data)
    if len(text) > limit:
        return text[:limit] + " …"
    return text


def _summarize_with_openai(payload: str, *, model: Optional[str] = None) -> str:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("Le package 'openai' est requis pour la synthèse.") from exc

    load_dotenv(override=False)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY manquant dans l'environnement (.env)")

    client = OpenAI(api_key=api_key)
    chosen_model = model or os.getenv("OPENAI_MODEL", "gpt-4o")

    system_msg = (
        "Tu es un analyste légal. Tu produis une synthèse claire et LA PLUS détaillée POSSIBLE d'une société à partir EXCLUSIVEMENT du JSON fourni. "
        "N'invente rien. Si une information n'est pas présente, indique 'Non disponible'. "
        "Ne fais AUCUNE référence à d'autres API, sources, ou contextes. "
        "Structure recommandée: Identification; Activité; Dirigeants/Associés; Capital/Finances; Établissements/Adresse; Documents/Actes marquants; Dates clés; Alertes/Points sensibles."
    )
    user_msg = (
        "Voici les données JSON (exclusives à cette synthèse). Analyse et synthétise en français, sans redondance et sans spéculation.\n\n" + payload
    )

    completion = client.chat.completions.create(
        model=chosen_model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        top_p=0.9,
    )
    return completion.choices[0].message.content or ""


def _summarize_with_ag2(payload: str, *, model: Optional[str] = None) -> str:
    # Appel AG2 en un seul tour; fallback OpenAI si non dispo
    try:
        from autogen import AssistantAgent  # type: ignore
    except Exception:
        return _summarize_with_openai(payload, model=model)

    load_dotenv(override=False)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY manquant dans l'environnement (.env)")

    chosen_model = model or os.getenv("OPENAI_MODEL", "gpt-4o")

    system_msg = (
        "Tu es un analyste légal. Tu produis une synthèse claire et LA PLUS détaillée POSSIBLE d'une société à partir EXCLUSIVEMENT du JSON fourni. "
        "N'invente rien. Si une information n'est pas présente, indique 'Non disponible'. "
        "Ne fais AUCUNE référence à d'autres API, sources, ou contextes. "
        "Structure recommandée: Identification; Activité; Dirigeants/Associés; Capital/Finances; Établissements/Adresse; Documents/Actes marquants; Dates clés; Alertes/Points sensibles."
    )

    config_list = [{"model": chosen_model, "api_key": api_key}]
    llm_config = {"config_list": config_list, "temperature": 0.2}

    assistant = AssistantAgent(
        name="summarizer",
        system_message=system_msg,
        llm_config=llm_config,
    )
    user_msg = (
        "Voici les données JSON (exclusives à cette synthèse). Analyse et synthétise en français, sans redondance et sans spéculation.\n\n"
        + payload
    )
    reply = assistant.generate_reply(messages=[{"role": "user", "content": user_msg}])
    if isinstance(reply, dict):
        return reply.get("content", "")
    return str(reply or "")


def summarize_company(data: Any, *, model: Optional[str] = None) -> str:
    payload = _compact_json(data)
    # Préférer AG2 si dispo, fallback OpenAI
    return _summarize_with_ag2(payload, model=model)


