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
    build_itc_pct,
    DEFAULT_YIELDS,
    DEFAULT_OM,
)


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
    page_icon=None,
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
    st.session_state.snap = SnapshotInputs(
        project_type="Rooftop",
        size_kw_dc=1000.0,
        cost_per_watt=2.50,
        yield_kwh_per_kw=1400.0,
        customer_current_rate=0.12,
        ppa_rate_to_customer=0.085,
        fixed_om_per_kw_year=12.0,
    )
if "itc_q" not in st.session_state:
    st.session_state.itc_q = {
        "obbba": True, "under_1mw": False, "pwa_direct": True,
        "ec": False, "dc": False, "li": "None",
    }

f: SnapshotInputs = st.session_state.snap
q = st.session_state.itc_q


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
    help="Defaults: Carport 1,300 / Rooftop 1,400 / Ground-fixed 1,500 / Ground-tracking 1,800",
)

c1, c2, c3 = st.columns(3)
f.size_kw_dc = c1.number_input("System size (kWdc)", value=float(f.size_kw_dc), step=50.0,
                                help="Typical Energen deal: 750 kW – 10 MW.")
f.cost_per_watt = c2.number_input("Cost per watt ($/Wdc)", value=float(f.cost_per_watt), step=0.10)
f.fixed_om_per_kw_year = c3.number_input("Fixed O&M ($/kWdc-yr)", value=float(f.fixed_om_per_kw_year), step=1.0)


# ---------- 2. Revenue ----------
st.markdown("### Revenue side")
c1, c2, c3 = st.columns(3)
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


# ---------- 4. Depreciation ----------
st.markdown("### Depreciation")
who = "the customer" if f.owner_mode == "Customer-owned" else "the developer entity"
c1, c2 = st.columns(2)
can_use_dep = c1.radio(
    f"Can {who} use the depreciation (sufficient tax appetite)?",
    ["Yes", "No"], index=0, horizontal=True,
    help=("Yes = 100% bonus depreciation Year 1 + tax on operating income. "
          "No = no depreciation shield, no operating tax (tax-exempt owner)."),
) == "Yes"
if can_use_dep:
    tax_pct = c2.number_input(
        "Combined tax rate (%)",
        value=float(f.tax_rate) * 100.0,
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
        step=0.05, format="%.4f",
    )
    f.interest_rate = int_rate / 100.0
    c4_a, c4_b = c4.columns(2)
    f.amortization_years = c4_a.number_input("Amort (yr)", value=int(f.amortization_years), step=1)
    dscr_floor = c4_b.number_input(
        "Min DSCR",
        value=float(f.min_dscr_requirement),
        step=0.05, format="%.2f",
    )
    f.min_dscr_requirement = dscr_floor


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


# ---------- Headline cards ----------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total CapEx", _fmt_money(out.total_capex))
c2.metric("Simple payback", f"Yr {out.simple_payback_year}" if out.simple_payback_year else "Never")
c3.metric("After-TC payback", f"Yr {out.after_tc_payback_year}" if out.after_tc_payback_year else "Never")
headline_irr = out.levered_irr if out.levered_irr is not None else out.unlevered_irr
irr_label = "Levered IRR" if f.debt_enabled and out.debt_amount > 0 else "IRR (post-tax-credit)"
c4.metric(irr_label, _fmt_pct(headline_irr))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Year-1 production", f"{out.year1_production_kwh/1000:,.0f} MWh")
c2.metric("Year-1 revenue/savings", _fmt_money(out.year1_revenue_or_savings))
c3.metric("LCOE (simple)", f"${out.lcoe:.4f}/kWh")
c4.metric("ITC + dep shield Yr 1", _fmt_money(out.itc_cash_year1 + out.bonus_dep_shield_year1))

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
st.plotly_chart(fig, use_container_width=True)


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
    st.plotly_chart(fig2, use_container_width=True)


# ---------- Warnings ----------
if out.warnings:
    with st.expander(f"{len(out.warnings)} sanity warnings"):
        for w in out.warnings:
            st.warning(w)


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
