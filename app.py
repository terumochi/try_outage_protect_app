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

from powerguard import notifications
from powerguard.notifier import build_notifier
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

st.sidebar.divider()
st.sidebar.subheader("📣 Notifications (SMS)")
notify_enabled = st.sidebar.toggle(
    "Send customer notifications",
    value=False,
    help="After assessing, detect status changes vs. the last run and send SMS "
    "alerts to customers with a phone number on file.",
)
use_twilio = st.sidebar.toggle(
    "Use real Twilio SMS",
    value=False,
    help="Off = mock sender (logs messages, no account needed). On requires "
    "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER env vars.",
)
risk_threshold = st.sidebar.slider(
    "Pre-storm alert threshold (risk score)",
    min_value=0, max_value=100, value=50,
    help="Send a pre-storm alert when risk is High/Severe or the score crosses "
    "this threshold.",
)
dry_run = st.sidebar.toggle(
    "Preview only (don't send / don't save status)",
    value=False,
    help="Render the messages and decisions without sending or advancing the "
    "change-detection store.",
)

st.sidebar.divider()
st.sidebar.markdown(
    "- **Model:** offline heuristic (deterministic)\n"
    "- **Weather:** Open-Meteo (live) + seasonal fallback\n"
    "- **Geocoding:** Nominatim (cached)\n"
    "- **Notify:** SMS (mock by default, Twilio opt-in)"
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


def _opt_str(value) -> str | None:
    """Parse an optional text cell, tolerating blanks/NaN."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _opt_bool(value) -> bool:
    """Parse an optional boolean cell (true/yes/1/y)."""
    s = _opt_str(value)
    return s is not None and s.lower() in {"true", "yes", "1", "y", "t"}


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


def render_notifications(results: List[Assessment]) -> None:
    """Run change detection + send SMS, and display the outcome."""
    st.subheader("📣 Notifications")

    try:
        notifier = build_notifier(use_twilio=use_twilio)
    except ValueError as exc:
        st.error(f"Twilio is enabled but not configured: {exc}")
        st.info("Turn off 'Use real Twilio SMS' to use the mock sender instead.")
        return

    decisions = notifications.process(
        results,
        notifier,
        risk_threshold=float(risk_threshold),
        dry_run=dry_run,
    )

    sent = [d for d in decisions if d.should_notify and d.body]
    skipped = [d for d in decisions if not d.should_notify]

    mode = "Preview (nothing sent)" if dry_run else f"Sent via {notifier.channel}"
    st.caption(
        f"{mode} · {len(sent)} notification(s) triggered · {len(skipped)} no-change/skipped"
    )

    if sent:
        for d in sent:
            label = "Pre-storm alert" if d.template == "pre_storm" else "Outage notification"
            status = ""
            if d.send_result:
                status = " ✅" if d.send_result.success else f" ❌ {d.send_result.detail}"
            with st.expander(f"{label} → {d.name}{status}", expanded=False):
                st.caption(f"Reason: {d.reason}")
                st.code(d.body, language="text")
    if skipped:
        with st.expander(f"No notification for {len(skipped)} address(es)"):
            for d in skipped:
                st.markdown(f"- **{d.name}** — {d.reason}")


def handle(items: List[AssessmentInput]) -> None:
    """Assess, render results, and (optionally) run notifications."""
    results = run_assessments(items)
    render_results(results)
    if notify_enabled:
        render_notifications(results)


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
        phone = st.text_input(
            "Customer phone (for SMS, optional)",
            placeholder="+15551234567",
            help="Include country code (E.164). Required to receive SMS alerts.",
        )
        outage_reported = st.checkbox(
            "An outage has been reported for this address",
            help="Check this to send the restoration-focused outage notification "
            "instead of a pre-storm alert.",
        )
        submitted = st.form_submit_button("Assess")
    if submitted:
        if not address.strip():
            st.error("Please enter an address.")
        else:
            handle(
                [
                    AssessmentInput(
                        name=name.strip(),
                        address=address.strip(),
                        phone=phone.strip() or None,
                        outage_reported=outage_reported,
                    )
                ]
            )

with tab_csv:
    st.write(
        "Upload a CSV with an **`address`** column. Optional columns: "
        "`name`, `lat`, `lon` (if present, geocoding is skipped), `phone` "
        "(for SMS), and `outage_reported` (true/false)."
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
                        phone=_opt_str(row.get("phone")),
                        outage_reported=_opt_bool(row.get("outage_reported")),
                    )
                    for _, row in df_in.iterrows()
                    if str(row.get("address", "")).strip()
                ]
                handle(items)
