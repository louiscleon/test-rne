from __future__ import annotations

import json
from typing import Any, Dict

import pandas as pd
import streamlit as st

try:
    # When running from repo root
    from instructions.pappers_client import PappersClient
    from instructions.legalmap_client import LegalMapClient
    from instructions.agents import summarize_company
    from instructions.perplexity_client import summarize_company_perplexity, research_company_perplexity
except Exception:
    # When running the file directly or depending on Streamlit's sys.path
    import os
    import sys

    sys.path.append(os.path.dirname(__file__))
    from pappers_client import PappersClient
    from legalmap_client import LegalMapClient
    from agents import summarize_company
    from perplexity_client import summarize_company_perplexity, research_company_perplexity


def is_valid_siren(value: str) -> bool:
    s = (value or "").strip().replace(" ", "")
    return len(s) == 9 and s.isdigit()


def flatten(obj: Any, parent_key: str = "") -> Dict[str, Any]:
    items: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}.{k}" if parent_key else str(k)
            items.update(flatten(v, new_key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_key = f"{parent_key}[{i}]" if parent_key else f"[{i}]"
            items.update(flatten(v, new_key))
    else:
        items[parent_key] = obj
    return items


def to_display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            text = str(value)
    else:
        text = str(value)
    # Optional truncation to keep the table light
    if len(text) > 2000:
        return text[:2000] + " …"
    return text


st.set_page_config(page_title="Comparaison LEGALMAP vs PAPPERS", layout="wide")
st.title("Comparaison LEGALMAP vs PAPPERS")
st.markdown("Entrez un SIREN (9 chiffres) puis cliquez sur Comparer.")

siren_input = st.text_input("SIREN", placeholder="ex: 552100554")
compare_clicked = st.button("Comparer")

if compare_clicked:
    siren = (siren_input or "").strip().replace(" ", "")
    if not is_valid_siren(siren):
        st.error("SIREN invalide. Il doit contenir exactement 9 chiffres.")
    else:
        st.info("Interrogation des APIs…")

        legalmap_data: Dict[str, Any]
        pappers_data: Dict[str, Any]

        with st.spinner("LegalMap…"):
            try:
                legalmap = LegalMapClient()
                # limiter l'enrichissement PDF pour réduire la latence
                legalmap_data = legalmap.get_bundle_for_siren(siren, fetch_pdf_details_top=0)
            except Exception as exc:
                legalmap_data = {"error": str(exc)}

        with st.spinner("Pappers…"):
            try:
                pappers = PappersClient()
                pappers_data = pappers.get_entreprise_by_siren(siren)
            except Exception as exc:
                pappers_data = {"error": str(exc)}

        flat_lm = flatten(legalmap_data) if isinstance(legalmap_data, dict) else {"": legalmap_data}
        flat_pp = flatten(pappers_data) if isinstance(pappers_data, dict) else {"": pappers_data}

        # Diagnostics & raw views
        with st.expander("Détails LegalMap (réponse brute)", expanded=False):
            if isinstance(legalmap_data, dict) and "error" in legalmap_data:
                st.error(legalmap_data["error"]) 
            st.json(legalmap_data)

        with st.expander("Détails Pappers (réponse brute)", expanded=False):
            if isinstance(pappers_data, dict) and "error" in pappers_data:
                st.error(pappers_data["error"]) 
            st.json(pappers_data)

        all_keys = sorted(set(flat_lm.keys()) | set(flat_pp.keys()))
        rows = []
        for key in all_keys:
            rows.append(
                {
                    "champ": key,
                    "legalmap": to_display_value(flat_lm.get(key)),
                    "pappers": to_display_value(flat_pp.get(key)),
                }
            )

        df = pd.DataFrame(rows, columns=["champ", "legalmap", "pappers"])  # order
        st.dataframe(df, use_container_width=True)

        # Optional: download
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Télécharger CSV",
            data=csv_bytes,
            file_name=f"comparaison_{siren}.csv",
            mime="text/csv",
        )

        # Coût & couverture
        st.subheader("Coût & Couverture")
        st.markdown("- Pappers: **1 crédit** par requête (ex: 40€ pour 500 crédits)")
        lm_used = ["rne/{siren}", "search", "search/count_results"]
        st.markdown("- LegalMap: endpoints utilisés → " + ", ".join(f"`{e}`" for e in lm_used))

        # Agent summaries (isolation stricte)
        st.subheader("Synthèses par Agent (isolation stricte)")
        col_s_lm, col_s_pp = st.columns(2)
        with col_s_lm:
            st.caption("Synthèse à partir de LegalMap uniquement")
            with st.spinner("OpenAI/AG2…"):
                try:
                    summary_lm = summarize_company(legalmap_data)
                except Exception as exc:
                    summary_lm = f"Erreur de synthèse: {exc}"
            st.write(summary_lm)
        with col_s_pp:
            st.caption("Synthèse à partir de Pappers uniquement")
            with st.spinner("OpenAI/AG2…"):
                try:
                    summary_pp = summarize_company(pappers_data)
                except Exception as exc:
                    summary_pp = f"Erreur de synthèse: {exc}"
            st.write(summary_pp)

        # Perplexity research-only (pas de JSON fourni), comparable
        st.subheader("Recherche Perplexity (web) – rapport indépendant")
        with st.spinner("Perplexity…"):
            try:
                # hint: try to pass denomination if present from LegalMap RNE
                denom_hint = None
                try:
                    denom_hint = (
                        ((legalmap_data or {}).get("rne", {}) or {})
                        .get("formality", {})
                        .get("content", {})
                        .get("personneMorale", {})
                        .get("identite", {})
                        .get("entreprise", {})
                        .get("denomination")
                    )
                except Exception:
                    denom_hint = None
                px_research = research_company_perplexity(siren=siren, denomination=denom_hint)
            except Exception as exc:
                px_research = f"Erreur Perplexity (recherche): {exc}"
        st.write(px_research)

        # ---------------- Coût estimé -----------------
        st.subheader("Estimation des coûts")

        def approx_tokens(text: str) -> int:
            if not isinstance(text, str):
                text = str(text)
            # approximation grossière: ~4 caractères par token
            return max(1, int(len(text) / 4))

        # Pappers coût fixe
        pappers_cost_eur = 40.0 / 500.0  # 0,08 € par requête

        # Perplexity (sonar/sonar-pro…) coûts par défaut (USD) → on affiche en USD par prudence
        # barème simplifié; adapter selon PERPLEXITY_MODEL / PERPLEXITY_MODEL_RESEARCH si défini
        import os as _os
        px_model = _os.getenv("PERPLEXITY_MODEL_RESEARCH") or _os.getenv("PERPLEXITY_MODEL") or "sonar-pro"
        px_pricing = {
            "sonar": {"in": 1.0, "out": 1.0},
            "sonar-pro": {"in": 3.0, "out": 15.0},
            "sonar-reasoning": {"in": 1.0, "out": 5.0},
            "sonar-reasoning-pro": {"in": 2.0, "out": 8.0},
            "sonar-deep-research": {"in": 2.0, "out": 8.0, "search": 5.0, "cit": 2.0, "query": 3.0},
        }
        px_cost_in = px_pricing.get(px_model, px_pricing["sonar-pro"]).get("in", 3.0)
        px_cost_out = px_pricing.get(px_model, px_pricing["sonar-pro"]).get("out", 15.0)
        # tokens
        openai_lm_tokens_out = approx_tokens(summary_lm)
        openai_pp_tokens_out = approx_tokens(summary_pp)
        px_tokens_in = approx_tokens(str(siren)) + approx_tokens("""Identification; Activité; Dirigeants/Associés; Capital/Finances; Établissements/Adresse; Documents/Actes marquants; Dates clés; Alertes/Points sensibles.""")
        px_tokens_out = approx_tokens(px_research)
        # coût Perplexity en USD
        px_cost_usd = (px_tokens_in / 1_000_000) * px_cost_in + (px_tokens_out / 1_000_000) * px_cost_out

        # OpenAI: coûts non affichés sans conf explicite
        st.markdown("- **Pappers** (fixe): ~{:0.2f} € / requête".format(pappers_cost_eur))
        st.markdown("- **Perplexity** ({}): ~{:0.4f} $ (estim.)".format(px_model, px_cost_usd))
        st.caption("Pour OpenAI/AG2, renseignez vos tarifs dans l'environnement si vous souhaitez une estimation précise.")


