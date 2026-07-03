"""
Energen Solar Deal Snapshot
A standalone deal-screening tool. Run with:
    streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from snapshot_calc import (
    SnapshotInputs,
    calculate_snapshot,
    solve_rate_for_irr,
    solve_rate_for_payback,
    solve_cost_for_irr,
    solve_cost_for_payback,
    build_itc_pct,
    DEFAULT_YIELDS,
    DEFAULT_OM,
)
from pdf_export import build_deal_pdf


# ---------- Brand palette (matched to logo) ----------
NAVY = "#0b1a2e"
NAVY_LIGHT = "#1a2a45"
GOLD = "#c9a96e"
CREAM = "#d4cfc5"
TAN = "#8a8679"
SAND = "#f1ede2"
PARCHMENT = "#fbfaf6"

st.set_page_config(
    page_title="Energen Solar Deal Snapshot",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------- Header banner (text-only Energen brand) ----------
def render_header():
    st.markdown(
        f"""
        <style>
          .brand-banner {{
              background: {NAVY};
              padding: 18px 28px;
              margin: -1rem -1rem 1.5rem -1rem;
              display: flex;
              align-items: center;
              justify-content: space-between;
              border-bottom: 3px solid {GOLD};
          }}
          .brand-mark {{
              display: flex;
              align-items: center;
          }}
          .brand-mark .accent-bar {{
              width: 2px;
              height: 44px;
              background: {GOLD};
              margin-right: 14px;
          }}
          .brand-mark .wordmark {{
              color: {CREAM};
              font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
              font-size: 26px;
              font-weight: 600;
              letter-spacing: 0.14em;
              line-height: 1.0;
          }}
          .brand-mark .submark {{
              color: {TAN};
              font-family: Georgia, 'Times New Roman', serif;
              font-size: 10px;
              font-weight: 400;
              letter-spacing: 0.18em;
              margin-top: 3px;
          }}
          .brand-banner .tagline {{
              color: {CREAM};
              font-size: 1.0rem;
              letter-spacing: 0.04em;
              text-align: right;
              line-height: 1.3;
          }}
          .brand-banner .tagline .small {{
              color: {TAN};
              font-size: 0.78rem;
              letter-spacing: 0.10em;
              text-transform: uppercase;
              margin-top: 2px;
          }}
          .verdict-strong {{
              background: #e8f5e9;
              border-left: 4px solid #2e7d32;
              padding: 12px 18px;
              border-radius: 4px;
              color: {NAVY};
              font-weight: 500;
          }}
          .verdict-decent {{
              background: {SAND};
              border-left: 4px solid {GOLD};
              padding: 12px 18px;
              border-radius: 4px;
              color: {NAVY};
              font-weight: 500;
          }}
          .verdict-weak {{
              background: #fce8e6;
              border-left: 4px solid #b71c1c;
              padding: 12px 18px;
              border-radius: 4px;
              color: {NAVY};
              font-weight: 500;
          }}
          h1, h2, h3 {{
              color: {NAVY};
          }}
          hr {{ border-color: {SAND}; }}
        </style>
        <div class="brand-banner">
          <div class="brand-mark">
            <div class="accent-bar"></div>
            <div>
              <div class="wordmark">ENERGEN</div>
              <div class="submark">CONSULTING</div>
            </div>
          </div>
          <div class="tagline">
            <div>Solar Deal Snapshot</div>
            <div class="small">Quick screen for commercial solar projects</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


render_header()


# ---------- Helpers ----------
def _fmt_money(v):
    if v is None:
        return "N/M"
    if abs(v) >= 1e6:
        return f"${v/1e6:,.2f}M"
    return f"${v:,.0f}"


def _fmt_pct(v, d=1):
    return "N/M" if v is None else f"{v*100:.{d}f}%"


def _fmt_x(v):
    return "N/M" if v is None else f"{v:.2f}x"


# ---------- Inputs ----------
if "snap" not in st.session_state:
    # Default to the Energen primary deal profile. The dataclass already carries
    # the same defaults, but we instantiate explicitly here so the loaded case is
    # transparent and easy to swap on a per-deal basis.
    st.session_state.snap = SnapshotInputs()
if "itc_q" not in st.session_state:
    # Default ITC stack: 30% base + PWA + Energy Community = 40%.
    # Energy Community (Option B) is used as the +10pp adder because it's the
    # more common Energen deal pathway. If a project has verified Domestic Content
    # instead, the user can toggle DC on and EC off in the credit Q&A section.
    st.session_state.itc_q = {
        "obbba": True, "under_1mw": False, "pwa_direct": True,
        "ec": True, "dc": False, "li": "None",
    }

f: SnapshotInputs = st.session_state.snap
q = st.session_state.itc_q


# ---------- Save / load deal (JSON) ----------
with st.expander("Save or load a deal", expanded=False):
    import json as _json
    from dataclasses import asdict as _asdict

    st.caption("Save your current inputs to a JSON file, or load a previously-saved deal.")
    c1, c2 = st.columns(2)

    # Save button
    _serial = _asdict(f)
    _serial["_itc_questions"] = q  # persist the tax-credit Q&A too
    _json_bytes = _json.dumps(_serial, indent=2).encode("utf-8")
    project_slug = f"{f.project_type}_{f.size_kw_dc:.0f}kW".replace(" ", "_").replace("(", "").replace(")", "")
    c1.download_button(
        label="Save this deal as JSON",
        data=_json_bytes,
        file_name=f"Energen_deal_{project_slug}.json",
        mime="application/json",
        width="stretch",
    )

    # Load uploader — apply each uploaded file exactly ONCE. Without the signature
    # guard, the uploader stays "full" across reruns and would silently re-load the
    # JSON on every subsequent input change, overwriting the user's edits.
    upl = c2.file_uploader("Load a saved deal", type=["json"], label_visibility="visible")
    if upl is not None:
        _raw = upl.read()
        import hashlib as _hashlib
        _sig = _hashlib.md5(_raw).hexdigest()
        if st.session_state.get("_loaded_deal_sig") != _sig:
            try:
                loaded = _json.loads(_raw.decode("utf-8"))
                loaded_itc = loaded.pop("_itc_questions", None)
                # Filter to fields SnapshotInputs actually accepts
                valid_fields = set(SnapshotInputs.__dataclass_fields__.keys())
                filtered = {k: v for k, v in loaded.items() if k in valid_fields}
                st.session_state.snap = SnapshotInputs(**filtered)
                if loaded_itc:
                    st.session_state.itc_q = loaded_itc
                # Sync the depreciation radio to the loaded deal
                _s = st.session_state.snap
                st.session_state["dep_radio"] = "Yes" if (_s.bonus_depreciation_pct > 0 or _s.tax_rate > 0) else "No"
                st.session_state["_loaded_deal_sig"] = _sig
                st.success("Deal loaded.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not load JSON file: {e}")


# ---------- 1. Owner mode + project type ----------
st.markdown("### Project basics")
c1, c2, c3 = st.columns([1.2, 1.2, 1])
f.owner_mode = c1.radio(
    "Who owns the system?",
    ["Customer-owned", "Developer-PPA"],
    index=["Customer-owned", "Developer-PPA"].index(f.owner_mode),
    horizontal=True,
)
f.project_type = c2.selectbox(
    "Project type",
    list(DEFAULT_YIELDS.keys()),
    index=list(DEFAULT_YIELDS.keys()).index(f.project_type),
)
f.yield_kwh_per_kw = c3.number_input(
    "Yield (kWh/kWdc-yr)",
    value=float(f.yield_kwh_per_kw),
    step=50.0,
    min_value=100.0,
    help="Defaults: Carport 1,300 / Rooftop 1,400 / Ground-fixed 1,500 / Ground-tracking 1,800",
)

c1, c2, c3 = st.columns(3)
f.size_kw_dc = c1.number_input("System size (kWdc)", value=float(f.size_kw_dc), step=50.0,
                                min_value=1.0,
                                help="Typical Energen deal: 750 kW – 60 MW.")
f.cost_per_watt = c2.number_input("Cost per watt ($/Wdc)", value=float(f.cost_per_watt), step=0.05,
                                   min_value=0.01,
                                   help="Module + BOS + soft costs. Interconnection is entered separately below.")
f.interconnection_cost = c3.number_input(
    "Interconnection cost ($)", value=float(f.interconnection_cost), step=25_000.0,
    min_value=0.0,
    help="Lump-sum for interconnection facilities, upgrades, PJM/CAISO/ERCOT costs. Adds to Total CapEx.",
)

# Fixed O&M — user can enter as $/kWdc-yr (industry benchmark) OR as a total $/yr lump sum
st.markdown("##### Fixed O&M")
c1, c2 = st.columns([1, 2])
f.fixed_om_entry_mode = c1.radio(
    "Entry mode", ["$/kWdc-yr", "$/yr"],
    index=["$/kWdc-yr", "$/yr"].index(f.fixed_om_entry_mode),
    horizontal=True,
)
if f.fixed_om_entry_mode == "$/kWdc-yr":
    f.fixed_om_per_kw_year = c2.number_input(
        "Fixed O&M ($/kWdc-yr)", value=float(f.fixed_om_per_kw_year), step=0.10,
        help=f"At {f.size_kw_dc:,.0f} kWdc, this is ${f.size_kw_dc * f.fixed_om_per_kw_year:,.0f}/yr total.",
    )
else:
    f.fixed_om_annual = c2.number_input(
        "Fixed O&M ($/yr)", value=float(f.fixed_om_annual), step=5_000.0,
        help=f"At {f.size_kw_dc:,.0f} kWdc, this implies ${(f.fixed_om_annual/max(f.size_kw_dc,1)):.2f}/kWdc-yr.",
    )

# Additional operating expenses, broken out (all annual dollar amounts)
st.markdown("##### Other annual operating expenses")
c1, c2, c3 = st.columns(3)
f.land_lease_annual = c1.number_input(
    "Land lease ($/yr)", value=float(f.land_lease_annual), step=1000.0,
    help="Typical: $0 for rooftop, $500–$2,000/acre/yr for ground-mount.",
)
f.property_tax_annual = c2.number_input(
    "Property tax ($/yr)", value=float(f.property_tax_annual), step=1000.0,
    help="State / local dependent. Many states exempt or partially exempt solar.",
)
f.other_opex_annual = c3.number_input(
    "Other expenses ($/yr)", value=float(f.other_opex_annual), step=1000.0,
    help="Insurance, asset management, monitoring, environmental compliance, misc.",
)


# ---------- 2. Revenue ----------
st.markdown("### Revenue side")
c1, c2, c3, c4 = st.columns(4)
if f.owner_mode == "Customer-owned":
    f.customer_current_rate = c1.number_input(
        "Customer's current utility rate ($/kWh)",
        value=float(f.customer_current_rate), step=0.005, format="%.4f",
    )
    c2.write("")
else:
    f.ppa_rate_to_customer = c1.number_input(
        "PPA rate charged to customer ($/kWh)",
        value=float(f.ppa_rate_to_customer), step=0.005, format="%.4f",
    )
    f.customer_current_rate = c2.number_input(
        "Customer's current rate ($/kWh, for context)",
        value=float(f.customer_current_rate), step=0.005, format="%.4f",
    )

esc_pct = c3.number_input(
    "Annual escalator (%)",
    value=float(f.rate_escalator) * 100.0,
    step=0.01,
    format="%.4f",
    help="Free-form decimal. e.g. 2.27 means 2.27%/yr.",
)
f.rate_escalator = esc_pct / 100.0

f.term_years = c4.number_input(
    "Analysis term (years)",
    value=int(f.term_years), step=1, min_value=5, max_value=40,
    help="Typical PPA/ESA terms: 15-25 years. Federal ESPC ESA max = 20.",
)


# ---------- 3. Tax credit Q&A ----------
st.markdown("### Tax credit (Section 48E)")

q["obbba"] = st.radio(
    "Did the project safe-harbor under OBBBA — start of construction by July 4, 2026, OR placed in service by Dec 31, 2027?",
    ["Yes", "No"], index=0 if q["obbba"] else 1, horizontal=True,
    help=("OBBBA terminates Section 48E for solar unless one of these dates is hit. "
          "If No, there is no federal tax credit."),
) == "Yes"

if not q["obbba"]:
    f.itc_pct = 0.0
    st.error(
        "No Section 48E tax credit available under the OBBBA cutoff. ITC = 0%. "
        "Project economics will rely entirely on revenue, depreciation, and any state incentives."
    )
else:
    c1, c2, c3 = st.columns(3)
    q["under_1mw"] = c1.radio(
        "Is the system under 1 MWac?",
        ["No", "Yes"], index=1 if q["under_1mw"] else 0, horizontal=True,
        help="Projects under 1 MWac are exempt from PWA. 30% credit applies without proving PWA.",
    ) == "Yes"
    if q["under_1mw"]:
        c2.success("PWA exempt (<1 MWac)")
        q["pwa_direct"] = True
    else:
        # Helpful nudge: at a typical ~1.25 DC/AC ratio, systems under ~1,250 kWdc
        # are likely under 1 MWac and may qualify for the small-project exemption.
        if f.size_kw_dc < 1250:
            c1.caption(
                "This system may be under 1 MWac (at a typical 1.25 DC/AC ratio) — "
                "check the inverter nameplate; the small-project exemption may apply."
            )
        q["pwa_direct"] = c2.radio(
            "Is PWA compliance met?",
            ["Yes", "No"], index=0 if q["pwa_direct"] else 1, horizontal=True,
        ) == "Yes"
    q["li"] = c3.selectbox(
        "Low-Income allocation?",
        ["None", "10pp", "20pp"],
        index=["None", "10pp", "20pp"].index(q["li"]),
    )

    c1, c2 = st.columns(2)
    q["ec"] = c1.radio("Energy Community?", ["No", "Yes"], index=1 if q["ec"] else 0, horizontal=True) == "Yes"
    q["dc"] = c2.radio("Domestic Content?", ["No", "Yes"], index=1 if q["dc"] else 0, horizontal=True) == "Yes"

    itc_pct, components, itc_warnings = build_itc_pct(
        obbba_eligible=True,
        under_1_mwac=q["under_1mw"],
        pwa_directly_met=q["pwa_direct"],
        energy_community=q["ec"],
        domestic_content=q["dc"],
        low_income=q["li"],
    )
    f.itc_pct = itc_pct
    pieces = " + ".join(f"{name} {v*100:.0f}%" for name, v in components.items())
    st.info(f"**Applicable Section 48E credit: {itc_pct*100:.1f}%** ({pieces})")

    # ---- ITC monetization (transferability sell price) ----
    if f.owner_mode == "Developer-PPA":
        st.markdown("##### How is the ITC monetized?")
        c1, c2, c3 = st.columns(3)
        sell_pct = c1.number_input(
            "ITC sell price (¢ per $1 of credit)",
            value=float(f.transfer_sale_price) * 100.0,
            step=0.5, format="%.2f",
            help=("Mid-2026 IG benchmark per Crux: ~93¢. Non-IG ~$82-90. "
                  "FEOC-clean projects price ~$0.02-0.03 above market."),
        )
        f.transfer_sale_price = sell_pct / 100.0
        txn_pct = c2.number_input(
            "Transaction cost (%)",
            value=float(f.transfer_transaction_cost_pct) * 100.0,
            step=0.5, format="%.2f",
            help="Legal, insurance, broker fee. Typical 1-3%.",
        )
        f.transfer_transaction_cost_pct = txn_pct / 100.0
        recapture_pct = c3.number_input(
            "Recapture reserve / holdback (%)",
            value=float(f.recapture_reserve_pct) * 100.0,
            step=0.5, format="%.2f",
            help="Buyer holdback against 5-yr recapture risk. Typical 5-10%.",
        )
        f.recapture_reserve_pct = recapture_pct / 100.0
        # Match the calc engine's basis: system cost PLUS interconnection.
        gross_credit = (f.size_kw_dc * 1000 * f.cost_per_watt + f.interconnection_cost) * f.itc_pct
        net_proceeds = gross_credit * f.transfer_sale_price * (1 - f.transfer_transaction_cost_pct - f.recapture_reserve_pct)
        st.caption(
            f"Gross §48E credit: **{_fmt_money(gross_credit)}**  →  "
            f"sold at {f.transfer_sale_price*100:.1f}¢  →  "
            f"less {(f.transfer_transaction_cost_pct + f.recapture_reserve_pct)*100:.1f}% costs/holdback  "
            f"=  **net cash {_fmt_money(net_proceeds)}**"
        )


# ---------- 4. Depreciation ----------
st.markdown("### Depreciation")
who = "the customer" if f.owner_mode == "Customer-owned" else "the developer entity"
c1, c2 = st.columns(2)
# Remember the last non-zero tax rate so toggling No -> Yes restores it instead of 0%.
if f.tax_rate > 0:
    st.session_state["_last_tax_rate"] = f.tax_rate
# Stable-keyed radio: initialize once from state (so a loaded "no depreciation" deal
# restores correctly — the JSON loader sets this key), then let the widget own it.
if "dep_radio" not in st.session_state:
    st.session_state["dep_radio"] = "Yes" if (f.bonus_depreciation_pct > 0 or f.tax_rate > 0) else "No"
can_use_dep = c1.radio(
    f"Can {who} use the depreciation (sufficient tax appetite)?",
    ["Yes", "No"], horizontal=True, key="dep_radio",
    help=("Yes = 100% bonus depreciation Year 1 + tax on operating income. "
          "No = no depreciation shield, no operating tax (tax-exempt owner)."),
) == "Yes"
if can_use_dep:
    _tax_default = f.tax_rate if f.tax_rate > 0 else st.session_state.get("_last_tax_rate", 0.27)
    tax_pct = c2.number_input(
        "Combined tax rate (%)",
        value=float(_tax_default) * 100.0,
        step=0.01,
        format="%.4f",
    )
    f.tax_rate = tax_pct / 100.0
    f.bonus_depreciation_pct = 1.0
else:
    f.tax_rate = 0.0
    f.bonus_depreciation_pct = 0.0
    c2.warning("No depreciation shield, no operating-income tax.")


# ---------- 5. Optional senior debt ----------
st.markdown("### Senior debt (optional)")
f.debt_enabled = st.toggle(
    "Add senior debt to the screen",
    value=f.debt_enabled,
    help="Default is all-equity. Turn on to layer in senior debt and see DSCR + levered IRR.",
)
if f.debt_enabled:
    c1, c2, c3, c4 = st.columns(4)
    f.debt_sizing_method = c1.radio(
        "Sizing method",
        ["Percent of cost", "DSCR-sized"],
        index=["Percent of cost", "DSCR-sized"].index(f.debt_sizing_method),
        horizontal=True,
        help=("Percent of cost: you specify leverage directly. "
              "DSCR-sized: lender constraints drive the debt amount."),
    )
    if f.debt_sizing_method == "Percent of cost":
        debt_pct = c2.number_input(
            "Debt % of cost",
            value=float(f.debt_pct_of_cost) * 100.0,
            step=0.5, format="%.2f",
        )
        f.debt_pct_of_cost = debt_pct / 100.0
    else:
        max_ltc = c2.number_input(
            "Max LTC cap (%)",
            value=float(f.max_ltc_cap) * 100.0,
            step=1.0, format="%.1f",
            help="Lender hard ceiling on debt as % of project cost.",
        )
        f.max_ltc_cap = max_ltc / 100.0
    int_rate = c3.number_input(
        "Interest rate (%)",
        value=float(f.interest_rate) * 100.0,
        step=0.05, format="%.4f", min_value=0.0,
    )
    f.interest_rate = int_rate / 100.0
    c4_a, c4_b = c4.columns(2)
    f.amortization_years = c4_a.number_input("Amort (yr)", value=int(f.amortization_years), step=1, min_value=1, max_value=40)
    dscr_floor = c4_b.number_input(
        "Min DSCR",
        value=float(f.min_dscr_requirement),
        step=0.05, format="%.2f",
    )
    f.min_dscr_requirement = dscr_floor


# ---------- 6. Equity structure and terminal value ----------
st.markdown("### Equity structure and terminal value")
c1, c2 = st.columns(2)
with c1:
    f.sponsor_equity_entry_mode = st.radio(
        "How do you want to set the sponsor / developer contribution?",
        ["% of equity", "$ amount"],
        index=["% of equity", "$ amount"].index(f.sponsor_equity_entry_mode),
        horizontal=True,
        help=("% of equity — LP convention: the investor requires the sponsor to hold a "
              "skin-in-the-game share (typically 10–20%) of the equity check. "
              "$ amount — developer reality: the sponsor brings a fixed dollar amount "
              "(cash, rolled dev fee, land value) and the outside-LP ask is whatever gap remains "
              "after debt. Either way the TOTAL equity check is CapEx minus senior debt — "
              "this input only splits it."),
    )
    if f.sponsor_equity_entry_mode == "$ amount":
        f.sponsor_equity_amount = st.number_input(
            "Sponsor / developer contribution ($)",
            value=float(f.sponsor_equity_amount), step=250_000.0, min_value=0.0,
            help="What the developer actually brings. Outside-LP ask = equity check minus this.",
        )
    else:
        sponsor_pct = st.number_input(
            "Sponsor / developer equity share (%)",
            value=float(f.sponsor_equity_pct) * 100.0,
            step=1.0, format="%.1f", min_value=0.0, max_value=100.0,
            help=("What share of the equity check the developer / sponsor covers. Balance is outside-LP equity. "
                  "Splits the equity number pro-rata; does not model pref or promote."),
        )
        f.sponsor_equity_pct = sponsor_pct / 100.0

f.terminal_value = c2.number_input(
    "Terminal / residual value at end of term ($)",
    value=float(f.terminal_value), step=100_000.0, min_value=0.0,
    help=("Residual PPA-extension value, land sale, or asset resale. Set 0 for conservative screen. "
          "Rule of thumb for 20-yr operating solar: 5–15% of original CapEx."),
)


# ---------- Calculate ----------
out = calculate_snapshot(f)


# ---------- Verdict banner ----------
st.divider()

verdict_class = "verdict-decent"
if out.after_tc_payback_year is not None and out.after_tc_payback_year <= 7:
    verdict_class = "verdict-strong"
elif out.after_tc_payback_year is None or out.after_tc_payback_year > 10:
    verdict_class = "verdict-weak"

st.markdown(
    f'<div class="{verdict_class}">Verdict: {out.verdict}</div>',
    unsafe_allow_html=True,
)
if out.warnings:
    st.caption(
        f"⚠ {len(out.warnings)} sanity {'warning' if len(out.warnings) == 1 else 'warnings'} "
        "flagged — full detail in the Sanity Warnings section near the bottom of the page."
    )


# ---------- Headline cards ----------
# ITC cash is real money. Depreciation shield is a tax benefit (only real if the owner
# has tax appetite). We surface them separately so a user can't accidentally treat the
# dep shield as project cash.
equity_at_close = out.total_capex - (out.debt_amount if f.debt_enabled else 0.0)
itc_cash_yr1 = out.itc_cash_year1
dep_shield_yr1 = out.bonus_dep_shield_year1
net_cash_after_itc = equity_at_close - itc_cash_yr1                    # cash residual
net_exposure_after_all = equity_at_close - itc_cash_yr1 - dep_shield_yr1  # economic residual

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total CapEx", _fmt_money(out.total_capex))
c2.metric("Equity at close", _fmt_money(equity_at_close),
          help="What you or your investor write at financial close. CapEx minus senior debt.")
c3.metric("After-TC payback", f"Yr {out.after_tc_payback_year}" if out.after_tc_payback_year else "Never")
headline_irr = out.levered_irr if out.levered_irr is not None else out.unlevered_irr
irr_label = "Levered IRR" if f.debt_enabled and out.debt_amount > 0 else "IRR (post-tax-credit)"
c4.metric(irr_label, _fmt_pct(headline_irr))

c1, c2, c3, c4 = st.columns(4)
c1.metric("ITC cash received Yr 1", _fmt_money(itc_cash_yr1),
          help="Real cash. Either used directly by an owner with tax appetite, or proceeds from a §6418 transfer sale.")
c2.metric("Depreciation tax shield Yr 1", _fmt_money(dep_shield_yr1),
          help="Tax benefit (not project cash). Assumes the owner has tax appetite to offset other income.")
c3.metric(
    "Net cash equity after ITC",
    _fmt_money(net_cash_after_itc),
    help="Equity at close minus the ITC cash. This is the true residual cash exposure of the equity check.",
)
c4.metric(
    "Net exposure after ITC + dep shield",
    _fmt_money(net_exposure_after_all),
    help="Further reduced by the depreciation tax shield. Economic residual — only valid if the owner uses the shield against other income.",
)

# Production and revenue detail row
c1, c2, c3, c4 = st.columns(4)
c1.metric("Year-1 production", f"{out.year1_production_kwh/1000:,.0f} MWh")
c2.metric("Year-1 revenue/savings", _fmt_money(out.year1_revenue_or_savings))
c3.metric("Yr-1 tax benefits", _fmt_money(itc_cash_yr1 + dep_shield_yr1),
          help="ITC cash + depreciation tax shield combined. The cash piece is the ITC; the dep shield is tax-only.")
c4.metric("LCOE (simple)", f"${out.lcoe:.4f}/kWh")

# Sponsor split + operating yield row
c1, c2, c3, c4 = st.columns(4)
_eff_sponsor_pct = (out.sponsor_cash / equity_at_close * 100.0) if equity_at_close > 0 else 0.0
c1.metric(
    "Sponsor cash (skin-in-the-game)",
    _fmt_money(out.sponsor_cash),
    help=f"{_eff_sponsor_pct:.0f}% of the equity check. This is what the developer / sponsor writes.",
)
c2.metric(
    "Outside LP equity to raise",
    _fmt_money(out.outside_lp_equity),
    help=f"The remaining {100 - _eff_sponsor_pct:.0f}% of the equity check — the gap after debt and sponsor cash. This is the outside raise.",
)
c3.metric(
    "Cash-on-cash yield (operating avg)",
    _fmt_pct(out.cash_on_cash_yield),
    help=("Average annual distribution during operating years (excludes Year 1's ITC + dep bump) "
          "divided by equity at close. Key metric for yield-oriented LPs like family offices."),
)
c4.metric("Simple payback (no TC)", f"Yr {out.simple_payback_year}" if out.simple_payback_year else "Never")

# Debt row, only when debt is on
if f.debt_enabled and out.debt_amount > 0:
    c1, c2, c3, c4 = st.columns(4)
    leverage = out.debt_amount / out.total_capex if out.total_capex else 0
    c1.metric("Senior debt", _fmt_money(out.debt_amount))
    c2.metric("Implied leverage", f"{leverage*100:.1f}%")
    c3.metric("Min DSCR", _fmt_x(out.min_dscr))
    c4.metric("Avg DSCR", _fmt_x(out.avg_dscr))


# ---------- Spread context ----------
st.markdown("### Spread context")
rate_ref = f.customer_current_rate if f.owner_mode == "Customer-owned" else f.ppa_rate_to_customer
if f.owner_mode == "Customer-owned":
    savings = f.customer_current_rate - out.lcoe
    st.markdown(
        f"- Customer pays **${f.customer_current_rate:.4f}/kWh** today\n"
        f"- Project LCOE is **${out.lcoe:.4f}/kWh**\n"
        f"- Customer saves **{savings*100:.2f}c/kWh** "
        f"(= **{savings/f.customer_current_rate*100:.1f}%** off current rate)"
    )
else:
    spread = f.ppa_rate_to_customer - out.lcoe
    ppa_vs_util = f.customer_current_rate - f.ppa_rate_to_customer
    st.markdown(
        f"- Developer charges **${f.ppa_rate_to_customer:.4f}/kWh** under PPA\n"
        f"- Project LCOE is **${out.lcoe:.4f}/kWh** → margin **{spread*100:.2f}c/kWh**\n"
        f"- Customer's PPA discount vs ${f.customer_current_rate:.4f}/kWh utility rate: "
        f"**{ppa_vs_util/f.customer_current_rate*100:.1f}%**"
    )


# ---------- Capital stack + tax-benefit bridge waterfall ----------
st.markdown("### Capital stack and Year-1 tax benefits")
st.caption(
    "Senior debt and ITC transfer proceeds are real cash sources. "
    "The depreciation shield is a tax benefit, not project cash — it assumes the owner has sufficient tax appetite. "
    "The bar on the right is the residual economic exposure once both are applied."
)

# Waterfall components — positive contributors that fund the CapEx
funding_labels = ["Total CapEx"]
funding_values = [out.total_capex]
funding_measures = ["absolute"]

if f.debt_enabled and out.debt_amount > 0:
    funding_labels.append("Senior debt")
    funding_values.append(-out.debt_amount)
    funding_measures.append("relative")

if out.itc_cash_year1 > 0:
    funding_labels.append("ITC cash (Yr 1)")
    funding_values.append(-out.itc_cash_year1)
    funding_measures.append("relative")

if out.bonus_dep_shield_year1 > 0:
    funding_labels.append("Depreciation tax shield (Yr 1)")
    funding_values.append(-out.bonus_dep_shield_year1)
    funding_measures.append("relative")

# What's left = the net residual equity exposure
residual = out.total_capex - (out.debt_amount if f.debt_enabled else 0) - out.itc_cash_year1 - out.bonus_dep_shield_year1
funding_labels.append("Net equity at risk")
funding_values.append(residual)
funding_measures.append("total")

waterfall = go.Figure(go.Waterfall(
    name="Funding stack",
    orientation="v",
    measure=funding_measures,
    x=funding_labels,
    y=funding_values,
    text=[f"${v/1e6:,.2f}M" for v in funding_values],
    textposition="outside",
    connector={"line": {"color": TAN}},
    decreasing={"marker": {"color": GOLD}},
    increasing={"marker": {"color": NAVY}},
    totals={"marker": {"color": NAVY_LIGHT}},
))
waterfall.update_layout(
    height=380,
    margin=dict(l=10, r=10, t=20, b=20),
    plot_bgcolor=PARCHMENT, paper_bgcolor=PARCHMENT,
    yaxis_title="$",
    showlegend=False,
)
st.plotly_chart(waterfall, width="stretch")


# ---------- Cumulative cash chart ----------
headline_cum = out.cumulative_levered_cf if (f.debt_enabled and out.debt_amount > 0) else out.cumulative_unlevered_cf
years_axis = list(range(0, len(headline_cum)))
fig = go.Figure()
fig.add_scatter(
    x=years_axis, y=headline_cum, mode="lines+markers",
    line=dict(color=NAVY, width=3),
    fill="tozeroy", fillcolor=f"rgba(11,26,46,0.15)",
    name="Cumulative cash",
)
fig.add_hline(y=0, line_dash="dash", line_color=TAN)
if out.after_tc_payback_year is not None:
    fig.add_vline(
        x=out.after_tc_payback_year, line_dash="dot", line_color=GOLD,
        annotation_text=f"Payback yr {out.after_tc_payback_year}",
        annotation_position="top",
    )
fig.update_layout(
    title="Cumulative cash position (after ITC + depreciation shield)",
    xaxis_title="Year", yaxis_title="Cumulative cash ($)",
    height=380, margin=dict(l=10, r=10, t=40, b=10),
    plot_bgcolor=PARCHMENT, paper_bgcolor=PARCHMENT,
)
st.plotly_chart(fig, width="stretch")


# ---------- DSCR chart (only if debt is on) ----------
if f.debt_enabled and out.debt_amount > 0:
    st.markdown("### Debt service coverage by year")
    years_d = list(range(1, len(out.annual_dscr) + 1))
    dscr_vals = [d if d is not None else 0 for d in out.annual_dscr]
    colors = []
    for d in out.annual_dscr:
        if d is None or d <= 0:
            colors.append(TAN)
        elif d < f.min_dscr_requirement:
            colors.append("#b71c1c")
        else:
            colors.append(NAVY)
    fig2 = go.Figure()
    fig2.add_bar(
        x=years_d, y=dscr_vals,
        marker_color=colors,
        text=[f"{d:.2f}x" if d is not None else "" for d in out.annual_dscr],
        textposition="auto",
        name="DSCR",
    )
    fig2.add_hline(
        y=f.min_dscr_requirement, line_dash="dash", line_color=GOLD,
        annotation_text=f"Min req {f.min_dscr_requirement:.2f}x",
        annotation_position="top right",
    )
    fig2.update_layout(
        title="Annual DSCR (debt amortization period)",
        xaxis_title="Year", yaxis_title="DSCR (x)",
        height=320, margin=dict(l=10, r=10, t=40, b=10),
        plot_bgcolor=PARCHMENT, paper_bgcolor=PARCHMENT,
    )
    st.plotly_chart(fig2, width="stretch")


# Warnings are surfaced in a dedicated section below the scenario comparison.


# ---------- Solve-for-PPA ----------
st.divider()
rate_label = "customer rate" if f.owner_mode == "Customer-owned" else "PPA rate"
st.markdown(f"### What {rate_label} hits the target?")
st.caption(
    f"Back-solves the {rate_label} that delivers your target IRR or payback, "
    "holding all other assumptions constant."
)
c1, c2 = st.columns(2)
target_irr_pct = c1.number_input(
    "Target IRR (%)", value=10.0, step=0.5, format="%.2f",
    help="e.g. 10 = 10% IRR (levered if debt is on, otherwise all-equity).",
)
target_payback = c2.number_input(
    "Target payback (years)", value=7, step=1, min_value=2, max_value=30,
)

rate_for_irr = solve_rate_for_irr(f, target_irr=target_irr_pct / 100.0)
rate_for_pb = solve_rate_for_payback(f, target_year=int(target_payback))
current_rate = f.customer_current_rate if f.owner_mode == "Customer-owned" else f.ppa_rate_to_customer

c1, c2, c3 = st.columns(3)
c1.metric(
    f"{rate_label.title()} at {target_irr_pct:.1f}% IRR",
    f"${rate_for_irr:.4f}/kWh" if rate_for_irr is not None else "N/M",
    delta=(f"{(rate_for_irr - current_rate)*100:+.2f}c vs. current" if rate_for_irr is not None else None),
    delta_color="inverse",
)
c2.metric(
    f"{rate_label.title()} at {target_payback}-yr payback",
    f"${rate_for_pb:.4f}/kWh" if rate_for_pb is not None else "N/M",
    delta=(f"{(rate_for_pb - current_rate)*100:+.2f}c vs. current" if rate_for_pb is not None else None),
    delta_color="inverse",
)
c3.metric(f"Current {rate_label}", f"${current_rate:.4f}/kWh")

if rate_for_irr is not None:
    if rate_for_irr <= current_rate:
        st.markdown(
            f"Your current {rate_label} **already clears** the {target_irr_pct:.1f}% IRR hurdle "
            f"by **{(current_rate - rate_for_irr)*100:.2f}c/kWh**."
        )
    else:
        st.markdown(
            f"To hit {target_irr_pct:.1f}% IRR, the {rate_label} needs to **rise "
            f"{(rate_for_irr - current_rate)*100:.2f}c/kWh** from today's ${current_rate:.4f}."
        )
else:
    st.warning(
        f"No {rate_label} in the 0c–50c/kWh range delivers {target_irr_pct:.1f}% IRR "
        "at these CapEx + opex assumptions. CapEx or yield needs to move."
    )


# ============================================================
# Solve for max supportable cost  (the inverse view — PPA is fixed, cost is the variable)
# ============================================================
st.divider()
st.markdown("### What project cost can this PPA support?")
st.caption(
    "Holds the revenue rate, yield, ITC, and debt assumptions constant, and back-solves "
    "the maximum cost-per-watt that still clears your IRR and payback targets. Useful when "
    "the PPA rate is fixed by the offtaker and you need to push CapEx down to clear hurdles."
)

c1, c2, c3 = st.columns(3)
cost_target_irr_pct = c1.number_input(
    "Target IRR (%)", value=10.0, step=0.5, format="%.2f", key="cost_irr",
    help="Levered IRR if debt is on, otherwise unlevered.",
)
cost_min_dscr = c2.number_input(
    "Min DSCR", value=float(f.min_dscr_requirement), step=0.05, format="%.2f", key="cost_dscr",
    help="Drives the DSCR floor when re-sizing debt across the search range. Only binds when debt is on with DSCR-sized sizing.",
)
cost_target_payback = c3.number_input(
    "Min acceptable payback (years)", value=10, step=1, min_value=2, max_value=30, key="cost_pb",
)
c1, c2, c3 = st.columns(3)
cost_low = c1.number_input("Cost search range — low ($/Wdc)", value=0.50, step=0.05, format="%.2f", key="c_low")
cost_high = c2.number_input("Cost search range — high ($/Wdc)", value=5.00, step=0.05, format="%.2f", key="c_high")
cost_max_ltc_pct = c3.number_input(
    "Max LTC cap (%)", value=float(f.max_ltc_cap) * 100.0, step=1.0, format="%.1f", key="c_ltc",
    help="Optional ceiling on leverage when debt is on. Lower than the DSCR-implied debt → LTC binds; higher → DSCR binds.",
)

# Build a solver-scoped copy of the inputs so the user's DSCR/LTC override on this
# section drives the solver without mutating state elsewhere on the page.
import copy as _copy
cost_case = _copy.copy(f)
cost_case.min_dscr_requirement = cost_min_dscr
cost_case.max_ltc_cap = cost_max_ltc_pct / 100.0

max_cost_irr = solve_cost_for_irr(cost_case, target_irr=cost_target_irr_pct/100.0, low=cost_low, high=cost_high)
max_cost_pb = solve_cost_for_payback(cost_case, target_year=int(cost_target_payback), low=cost_low, high=cost_high)

# Binding constraint = whichever target is more demanding (lower max cost)
candidates = [c for c in (max_cost_irr, max_cost_pb) if c is not None]
max_cost = min(candidates) if candidates else None
binding = None
if max_cost is not None:
    if max_cost_irr is not None and abs(max_cost - max_cost_irr) < 1e-3:
        binding = f"{cost_target_irr_pct:.1f}% IRR"
    else:
        binding = f"{cost_target_payback}-yr payback"

# Display
c1, c2, c3 = st.columns(3)
c1.metric(
    "Max cost at target IRR",
    f"${max_cost_irr:.3f}/Wdc" if max_cost_irr is not None else "N/M",
    help=f"Highest cost/Wdc that still clears {cost_target_irr_pct:.1f}% IRR. N/M = deal broken even at cheapest cost.",
)
c2.metric(
    "Max cost at target payback",
    f"${max_cost_pb:.3f}/Wdc" if max_cost_pb is not None else "N/M",
    help=f"Highest cost/Wdc that still pays back within {cost_target_payback} years.",
)
c3.metric(
    "Binding max supportable cost",
    f"${max_cost:.3f}/Wdc" if max_cost is not None else "N/M",
    help=f"Stricter of the two constraints. Currently bound by: {binding}." if binding else "Deal does not work at any cost in the search range.",
)

if max_cost is not None:
    current_cost = f.cost_per_watt
    current_total = f.size_kw_dc * 1000 * current_cost
    max_total = f.size_kw_dc * 1000 * max_cost
    diff_per_w = current_cost - max_cost
    diff_total = current_total - max_total
    diff_pct = (diff_per_w / current_cost) * 100.0 if current_cost > 0 else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Current cost/Wdc", f"${current_cost:.3f}/Wdc")
    c2.metric("Max supportable cost", f"${max_cost:.3f}/Wdc")
    c3.metric(
        "Required reduction",
        f"${diff_per_w:.3f}/Wdc" if diff_per_w > 0 else "$0.000/Wdc",
        delta=f"−{diff_pct:.1f}%" if diff_per_w > 0 else "in the clear",
        delta_color="off" if diff_per_w <= 0 else "inverse",
    )

    if diff_per_w <= 0:
        st.success(
            f"**Current cost works.** Current ${current_cost:.3f}/Wdc is at or below the "
            f"max supportable ${max_cost:.3f}/Wdc — deal clears the {binding} hurdle by "
            f"${-diff_per_w:.3f}/Wdc of headroom."
        )
    else:
        st.error(
            f"**Current cost too high.** Need to drop "
            f"${diff_per_w:.3f}/Wdc (≈ ${diff_total/1e6:.2f}M of total CapEx, {diff_pct:.1f}%) "
            f"to clear the {binding} hurdle."
        )
else:
    st.error(
        "No cost in the search range delivers both hurdles. This means the deal is broken "
        "even at the cheapest cost — revenue, yield, or ITC stack need to improve before cost is "
        "the lever."
    )


# ============================================================
# Three-case scenario comparison
# ============================================================
st.divider()
st.markdown("### Scenario comparison")
st.caption("Run three quick cases at different cost/Wdc points. Useful for stress-testing where the deal needs to land on CapEx.")
c1, c2, c3 = st.columns(3)
sc_current = c1.number_input("Current case ($/Wdc)", value=float(f.cost_per_watt), step=0.05, format="%.2f", key="sc_curr")
sc_target = c2.number_input("Target case ($/Wdc)", value=1.53, step=0.05, format="%.2f", key="sc_tgt")
sc_low = c3.number_input("Low-cost case ($/Wdc)", value=1.46, step=0.05, format="%.2f", key="sc_low")

def _run_case(cost_per_w: float):
    """Run snapshot with one cost-override; return a compact dict of headline metrics."""
    import copy as _copy
    g = _copy.copy(f)
    g.cost_per_watt = cost_per_w
    o = calculate_snapshot(g)
    eq_close = o.total_capex - (o.debt_amount if g.debt_enabled else 0.0)
    net_cash_eq = eq_close - o.itc_cash_year1
    headline_irr_v = o.levered_irr if o.levered_irr is not None else o.unlevered_irr
    return {
        "Cost/Wdc": f"${cost_per_w:.2f}",
        "Total CapEx": _fmt_money(o.total_capex),
        "Senior debt": _fmt_money(o.debt_amount) if g.debt_enabled and o.debt_amount > 0 else "—",
        "ITC cash (Yr 1)": _fmt_money(o.itc_cash_year1),
        "Equity at close": _fmt_money(eq_close),
        "Net cash equity after ITC": _fmt_money(net_cash_eq),
        "Levered IRR": _fmt_pct(headline_irr_v),
        "Min DSCR": _fmt_x(o.min_dscr) if g.debt_enabled else "—",
        "Payback": f"Yr {o.after_tc_payback_year}" if o.after_tc_payback_year else "Never",
        "Verdict": (
            "Strong" if (o.after_tc_payback_year is not None and o.after_tc_payback_year <= 7)
            else "Decent" if (o.after_tc_payback_year is not None and o.after_tc_payback_year <= 10)
            else "Marginal" if o.after_tc_payback_year is not None
            else "Doesn't pay back"
        ),
    }

scenario_df = pd.DataFrame({
    "Current": _run_case(sc_current),
    f"Target (${sc_target:.2f}/W)": _run_case(sc_target),
    f"Low-cost (${sc_low:.2f}/W)": _run_case(sc_low),
})
st.dataframe(scenario_df, width="stretch")


# ============================================================
# Cross-cut sanity warnings (in addition to calc-engine warnings)
# ============================================================
st.divider()
st.markdown("### Sanity warnings")

cross_warnings = []
# Levered IRR below target IRR (using the cost section's target as the reference)
hl_irr = out.levered_irr if out.levered_irr is not None else out.unlevered_irr
if hl_irr is not None and hl_irr < cost_target_irr_pct / 100.0:
    cross_warnings.append(
        f"Levered IRR ({hl_irr*100:.1f}%) is below your target ({cost_target_irr_pct:.1f}%). "
        "Either raise the revenue rate, drop CapEx, or layer in more credit/bonuses."
    )
# Current cost above solved max supportable cost
if max_cost is not None and f.cost_per_watt > max_cost:
    cross_warnings.append(
        f"Current cost/Wdc (${f.cost_per_watt:.3f}) exceeds the max supportable "
        f"(${max_cost:.3f}) for your {cost_target_irr_pct:.1f}% IRR + {cost_target_payback}-yr payback hurdles."
    )
# Domestic Content selected without explicit verification
if q.get("dc"):
    cross_warnings.append(
        "Domestic Content +10pp selected. Confirm Adjusted Percentage Rule (50% for 2026 BOC) "
        "or Notice 2025-08 safe harbor evidence is in hand BEFORE relying on this credit."
    )
# Energy Community selected without explicit verification
if q.get("ec"):
    cross_warnings.append(
        "Energy Community +10pp selected. Confirm site qualifies per IRS Notice 2026-39 (June 2026) "
        "as of the placed-in-service date. EC status is PIS-date-determined for ITC."
    )

# Stack calc-engine + cross-cut warnings together
all_warnings = list(out.warnings) + cross_warnings
if all_warnings:
    for w in all_warnings:
        st.warning(w)
else:
    st.success("No sanity warnings flagged.")


# ---------- PDF deal-analysis export ----------
st.divider()
st.markdown("### Export deal analysis")
st.caption("Generate a single-page PDF deal sheet with all the inputs, outputs, and tax-credit stack. Use to share with investors, lenders, or internal review.")

try:
    pdf_bytes = build_deal_pdf(f, out, q)
    project_label = f"{f.project_type}_{f.size_kw_dc:.0f}kW".replace(" ", "_").replace("(", "").replace(")", "")
    st.download_button(
        label="Download deal analysis PDF",
        data=pdf_bytes,
        file_name=f"Energen_Solar_Deal_Snapshot_{project_label}.pdf",
        mime="application/pdf",
        width="stretch",
    )
except Exception as e:
    st.warning(f"PDF generation failed: {e}. Refresh the page; if it persists, let us know.")


# ---------- Footer ----------
st.divider()
st.markdown(
    f"""
    <div style="text-align:center; color:{TAN}; font-size: 0.8rem; padding: 12px 0;">
      Energen Consulting — Solar Deal Snapshot · Preliminary screening only ·
      Not tax, legal, accounting, investment, or engineering advice.
    </div>
    """,
    unsafe_allow_html=True,
)
