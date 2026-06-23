# Energen Solar Deal Snapshot

A standalone quick-screen tool for commercial solar projects (typically 750 kW – 10 MW).
Built for the first 30 seconds of a deal conversation: does this pencil?

Branded for Energen Consulting. Independent of the larger Solar Deal Screener — own folder, own dependencies, deploys on its own.

## How to launch (Mac)

1. Open Finder, navigate to the `energen_solar_deal_snapshot` folder.
2. Double-click `start_mac.command`.
3. Browser opens to `http://localhost:8501`.

First-run takes ~1 minute (installs dependencies into a local environment). Subsequent launches are instant. To stop, close the Terminal window that opened.

## What it does

- Choose **Customer-owned** vs **Developer-PPA** mode
- Pick project type (Carport, Rooftop, Ground fixed-tilt, Ground tracking)
- Enter system size, cost/W, yield, customer rate, escalator, O&M
- Answer the **Section 48E tax credit Q&A** (OBBBA gate, PWA, EC, DC, Low-Income)
- Confirm depreciation tax appetite Yes/No
- **Optional: add senior debt** to see DSCR, debt service, levered IRR
- Read the verdict + four headline metrics
- Use the **Solve-for-PPA** section to back-solve the rate needed for a target IRR or payback

## Web deployment paths

The app is web-ready. Three options once you decide:

1. **Streamlit Community Cloud** (free, public): push the folder to a GitHub repo, connect at streamlit.io, get a URL like `energen-snapshot.streamlit.app`.
2. **Render or Fly.io with your domain** (~$5–10/mo): host at a URL like `tools.energenconsulting.com/snapshot`.
3. **Embed in your existing website**: once hosted, drop an iframe on a page of energenconsulting.com.

No code changes needed for any of these — the same app runs locally, on Streamlit Cloud, or on a paid host.

## Folder structure

```
energen_solar_deal_snapshot/
├── app.py                  Streamlit app (single page, branded)
├── requirements.txt
├── start_mac.command       Mac launcher
├── README.md
├── .streamlit/
│   └── config.toml         Brand theme (palette derived from logo)
├── assets/
│   └── logo.svg            Energen logo
├── src/
│   ├── snapshot_calc.py    Calculation engine (with optional DSCR debt layer)
│   └── finance_math.py     Robust IRR + amortization helpers
└── exports/                (Empty — reserved for future PDF/Excel exports)
```

## Disclaimer

Preliminary deal screening only. Not tax, legal, accounting, investment, or engineering advice. Verify tax-credit eligibility, depreciation treatment, transferability, and regulatory assumptions with qualified tax counsel and CPA before relying on any output.
