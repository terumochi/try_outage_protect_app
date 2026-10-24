# PowerGuard ⚡

Predict power-outage risk and estimate recovery times from customer addresses.

PowerGuard reads customer addresses (one at a time or in bulk via CSV), geocodes
them, pulls **live weather** for each location, and runs a **fully offline
heuristic model** to produce:

- an **outage-risk score** (0–100) and risk band (Low / Moderate / High / Severe), and
- an **estimated recovery time** (hours) if an outage occurs.

## Architecture: offline model, online inference

The scoring logic is pure Python and runs entirely offline and deterministically.
It only needs *input values*. Weather is the one input fetched live — with a
graceful fallback to bundled seasonal/historical averages when the network is
unavailable.

```
Address
   │
   ▼
[Geocode → lat/lon]        ◄── online (Nominatim) + local cache
   │
   ▼
[Fetch current weather]    ◄── online (Open-Meteo) + local cache + offline fallback
   │
   ▼
[Bundled dataset]          ◄── offline: regional risk, grid reliability, history
   │
   ▼
[HEURISTIC MODEL]          ◄── offline, pure Python, deterministic
   │
   ▼
Risk score + predicted recovery time
```

| Component                        | Offline?                      | Source                         |
|----------------------------------|-------------------------------|--------------------------------|
| Heuristic model (scoring)        | ✅ Fully offline              | `powerguard/model.py`          |
| Regional / grid / history data   | ✅ Fully offline              | `data/regions.csv`             |
| Weather                          | 🌐 Online, offline fallback   | Open-Meteo + cache + seasonal  |
| Geocoding (address → lat/lon)    | 🌐 Online, cached             | Nominatim + cache              |
| SMS notifications                | 🌐 Online (Twilio) / offline mock | `powerguard/notifier.py`   |

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (default http://localhost:8501).

## Input modes

- **Manual entry** — type a single address (with optional phone + "outage
  reported" flag).
- **CSV upload** — upload a file with an `address` column. Optional columns:
  `name`, `lat`, `lon` (used directly if present, skipping geocoding), `phone`
  (for SMS), and `outage_reported` (true/false).

A sample file lives at `data/sample_addresses.csv`.

## Customer notifications (SMS)

After an assessment, PowerGuard can notify customers when their outage status
**changes** vs. the previous run. It only sends on a real change:

- risk **band** change (e.g., Moderate → Severe),
- risk **score** crossing your configured threshold,
- a **significant** recovery-time shift (> 2h), or
- an **outage newly reported** / restoration estimate updated.

Two message templates are used:

- **Pre-storm alert** — elevated predicted risk, no confirmed outage. Includes
  risk factors, preparation steps, and an update source, and makes clear it is a
  *prediction*.
- **Outage notification** — sent once an outage is reported (manual checkbox or
  the `outage_reported` CSV column). Restoration-focused: estimated restoration
  window, current status, and restoration factors.

Change detection is backed by a small persisted store at
`.cache/status_store.json`.

### SMS channel

- **Mock sender (default)** — logs messages, needs no account, runs fully
  offline. Great for demos.
- **Twilio (opt-in)** — enable in the sidebar and set `TWILIO_ACCOUNT_SID`,
  `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM_NUMBER`. Requires `pip install twilio`.

Use the sidebar "Preview only" toggle to render messages and decisions without
sending or advancing the change-detection store.

## Deployment

The code lives on GitHub; to run it live, deploy to a Python host. The easiest
free path is **Streamlit Community Cloud** — point it at this repo and it runs.
(GitHub itself only hosts the code; GitHub Pages cannot run a Python app.)

## Offline mode

Set the toggle in the sidebar (or env var `POWERGUARD_OFFLINE=1`) to skip all
network calls and use bundled fallback data only. Predictions are still produced,
flagged as `degraded`.
