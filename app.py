"""PowerGuard — Streamlit UI.

Reads customer addresses (manual or CSV), checks power-outage risk using an
offline heuristic model fed by live weather, and predicts recovery times.
"""
from __future__ import annotations

import io
import os
from typing import List

import pandas as pd
import streamlit as st

from powerguard.service import Assessment, AssessmentInput, assess

st.set_page_config(page_title="PowerGuard ⚡", page_icon="⚡", layout="wide")

BAND_COLORS = {
    "Low": "#2e7d32",
    "Moderate": "#f9a825",
    "High": "#ef6c00",
    "Severe": "#c62828",
}


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
st.sidebar.title("⚡ PowerGuard")
st.sidebar.caption("Outage-risk & recovery-time estimates")

offline = st.sidebar.toggle(
    "Offline mode",
    value=os.environ.get("POWERGUARD_OFFLINE") == "1",
    help="Skip all network calls (geocoding + live weather) and use bundled "
    "fallback data. Predictions are flagged as degraded.",
)

st.sidebar.markdown(
    "- **Model:** offline heuristic (deterministic)\n"
    "- **Weather:** Open-Meteo (live) + seasonal fallback\n"
    "- **Geocoding:** Nominatim (cached)"
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _opt_float(value) -> float | None:
    """Parse an optional lat/lon cell to float, tolerating blanks/NaN."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def run_assessments(items: List[AssessmentInput]) -> List[Assessment]:
    results: List[Assessment] = []
    progress = st.progress(0.0, text="Assessing addresses…")
    for i, item in enumerate(items, start=1):
        results.append(assess(item, offline=offline))
        progress.progress(i / len(items), text=f"Assessed {i}/{len(items)}")
    progress.empty()
    return results


def band_tag(band: str) -> str:
    color = BAND_COLORS.get(band, "#555")
    return (
        f"<span style='background:{color};color:#fff;padding:2px 10px;"
        f"border-radius:12px;font-weight:600'>{band}</span>"
    )


def results_dataframe(results: List[Assessment]) -> pd.DataFrame:
    rows = []
    for a in results:
        p = a.prediction
        rows.append(
            {
                "Name": a.name,
                "Address": a.address,
                "Region": a.region_name,
                "Risk score": p.risk_score,
                "Risk band": p.risk_band,
                "Est. recovery (h)": p.estimated_recovery_hours,
                "Degraded": "⚠️" if p.degraded else "",
                "lat": a.lat,
                "lon": a.lon,
            }
        )
    return pd.DataFrame(rows)


def render_results(results: List[Assessment]) -> None:
    df = results_dataframe(results)

    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Addresses", len(results))
    c2.metric("Avg risk score", f"{df['Risk score'].mean():.1f}")
    high = int((df["Risk band"].isin(["High", "Severe"])).sum())
    c3.metric("High / Severe", high)
    c4.metric("Avg recovery (h)", f"{df['Est. recovery (h)'].mean():.1f}")

    st.subheader("Results")
    st.dataframe(
        df.drop(columns=["lat", "lon"]),
        use_container_width=True,
        hide_index=True,
    )

    # Download
    csv_buf = io.StringIO()
    df.drop(columns=["lat", "lon"]).to_csv(csv_buf, index=False)
    st.download_button(
        "⬇️ Download results (CSV)",
        csv_buf.getvalue(),
        file_name="powerguard_results.csv",
        mime="text/csv",
    )

    # Map (only points with coordinates)
    map_df = df.dropna(subset=["lat", "lon"])[["lat", "lon"]]
    if not map_df.empty:
        st.subheader("Map")
        st.map(map_df, use_container_width=True)

    # Per-address detail
    st.subheader("Details")
    for a in results:
        p = a.prediction
        header = f"{a.name} — {p.risk_band} ({p.risk_score})"
        with st.expander(header):
            if a.error:
                st.warning(a.error)
            st.markdown(band_tag(p.risk_band), unsafe_allow_html=True)

            d1, d2 = st.columns(2)
            with d1:
                st.markdown("**Risk factor contributions (points)**")
                contrib = pd.DataFrame(
                    {"points": p.contributions}
                ).sort_values("points", ascending=False)
                st.bar_chart(contrib)
            with d2:
                w = a.weather
                st.markdown("**Weather inputs**")
                st.write(
                    {
                        "Wind (km/h)": w.wind_speed_kmh,
                        "Gusts (km/h)": w.wind_gust_kmh,
                        "Precip (mm)": w.precip_mm,
                        "Snow (cm)": w.snowfall_cm,
                        "Temp (°C)": w.temperature_c,
                        "Thunderstorm": w.thunderstorm,
                        "Source": "fallback" if w.is_fallback else "live",
                    }
                )
                st.metric("Estimated recovery", f"{p.estimated_recovery_hours} h")

            if p.notes:
                st.markdown("**Notes**")
                for note in p.notes:
                    st.markdown(f"- {note}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
st.title("PowerGuard ⚡")
st.caption(
    "Read customer addresses, check power-outage risk, and estimate recovery "
    "times. The scoring model runs fully offline; weather is pulled live with a "
    "fallback to bundled seasonal data."
)

tab_manual, tab_csv = st.tabs(["🏠 Manual entry", "📄 CSV upload"])

with tab_manual:
    with st.form("manual"):
        name = st.text_input("Name / label (optional)", placeholder="Downtown Office")
        address = st.text_input(
            "Address", placeholder="1600 Amphitheatre Parkway, Mountain View, CA"
        )
        submitted = st.form_submit_button("Assess")
    if submitted:
        if not address.strip():
            st.error("Please enter an address.")
        else:
            results = run_assessments(
                [AssessmentInput(name=name.strip(), address=address.strip())]
            )
            render_results(results)

with tab_csv:
    st.write(
        "Upload a CSV with an **`address`** column. Optional columns: "
        "`name`, `lat`, `lon` (if `lat`/`lon` are present, geocoding is skipped)."
    )
    uploaded = st.file_uploader("CSV file", type=["csv"])
    use_sample = st.checkbox("Use the bundled sample file instead")

    df_in = None
    if use_sample:
        df_in = pd.read_csv("data/sample_addresses.csv")
    elif uploaded is not None:
        df_in = pd.read_csv(uploaded)

    if df_in is not None:
        df_in.columns = [c.strip().lower() for c in df_in.columns]
        if "address" not in df_in.columns:
            st.error("CSV must contain an 'address' column.")
        else:
            st.write("Preview:")
            st.dataframe(df_in.head(20), use_container_width=True, hide_index=True)
            if st.button("Assess all", type="primary"):
                items = [
                    AssessmentInput(
                        name=str(row.get("name", "") or "").strip(),
                        address=str(row["address"]).strip(),
                        lat=_opt_float(row.get("lat")),
                        lon=_opt_float(row.get("lon")),
                    )
                    for _, row in df_in.iterrows()
                    if str(row.get("address", "")).strip()
                ]
                results = run_assessments(items)
                render_results(results)
