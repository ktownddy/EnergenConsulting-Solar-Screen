"""
Energen Solar Deal Snapshot — calculation engine.

A standalone screening calc for small commercial solar (typically 750 kW – 10 MW).
Supports two ownership modes (customer-owned vs developer-PPA) and an optional
senior debt layer that, when enabled, drives DSCR and levered IRR outputs.

Designed to be:
  - Self-contained (no dependencies on the full Solar Deal Screener)
  - Robust (safe IRR wrapper, graceful debt-off path)
  - Transparent (every output traceable to the input that drove it)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from finance_math import safe_irr, equity_multiple, payback_year, amortization_payment, pv_annuity


# Default specific yield (kWh per kWdc-year) by project type.
DEFAULT_YIELDS = {
    "Carport":              1300,
    "Rooftop":              1400,
    "Ground (fixed-tilt)":  1500,
    "Ground (tracking)":    1800,
}

# Default fixed O&M ($/kWdc-yr) by project type.
DEFAULT_OM = {
    "Carport":              15.0,
    "Rooftop":              12.0,
    "Ground (fixed-tilt)":  15.0,
    "Ground (tracking)":    18.0,
}


# ---------- ITC stack helper ----------

def build_itc_pct(
    obbba_eligible: bool,
    under_1_mwac: bool,
    pwa_directly_met: bool,
    energy_community: bool,
    domestic_content: bool,
    low_income: str = "None",  # "None" | "10pp" | "20pp"
) -> Tuple[float, dict, List[str]]:
    """
    Build §48E applicable percentage from compliance answers.
    Labels are written so each component clearly identifies its own source —
    the +24pp can come from either PWA compliance OR the small-project exemption,
    and the +10pp adders are always labeled with the actual qualifying category.
    """
    components: dict = {}
    warnings: List[str] = []

    if not obbba_eligible:
        warnings.append(
            "OBBBA construction safe-harbor NOT met (BOC after July 4, 2026 and "
            "PIS after Dec 31, 2027). Section 48E credit unavailable for solar. "
            "ITC = 0%."
        )
        return 0.0, {"No credit (OBBBA cutoff)": 0.0}, warnings

    components["Base 48E credit"] = 0.06

    # The +24pp uplift can come from EITHER the small-project exemption OR PWA.
    # Check the small-project exemption FIRST — when both are true, "exempt under 1 MWac"
    # is the operative legal label (PWA isn't actually required for the system to qualify).
    pwa_effective = under_1_mwac or pwa_directly_met
    if under_1_mwac:
        components["Small project exemption (<1 MWac)"] = 0.24
    elif pwa_directly_met:
        components["PWA compliance"] = 0.24
    else:
        warnings.append("PWA not met and project is >=1 MWac — credit base is 6%, not 30%.")

    if energy_community:
        components["Energy Community"] = 0.10 if pwa_effective else 0.02
    if domestic_content:
        components["Domestic Content"] = 0.10 if pwa_effective else 0.02
    if low_income == "10pp":
        components["Low-Income (+10pp)"] = 0.10
        warnings.append("Low-Income +10pp requires DOE Capacity Limitation allocation.")
    elif low_income == "20pp":
        components["Low-Income (+20pp)"] = 0.20
        warnings.append("Low-Income +20pp requires qualifying residential/economic-benefit status AND DOE allocation.")

    return sum(components.values()), components, warnings


# ---------- Snapshot inputs ----------

@dataclass
class SnapshotInputs:
    """
    Default values reflect Energen's primary deal profile:
    a ~59 MWdc ground-mount with a bundled energy+REC offtake at $67/MWh.
    Adjust per-deal in the UI; these are just the loaded starting case.
    """
    # Project basics
    project_type: str = "Ground (fixed-tilt)"
    owner_mode: str = "Developer-PPA"              # "Customer-owned" | "Developer-PPA"
    size_kw_dc: float = 58850.0
    cost_per_watt: float = 1.84                    # module/BOS/soft-cost stack, $/Wdc
    interconnection_cost: float = 0.0              # separate lump-sum add-on
    yield_kwh_per_kw: float = 1433.0

    # Revenue (bundled energy + REC rate — do not double-count RECs separately)
    customer_current_rate: float = 0.0670
    ppa_rate_to_customer: float = 0.0670
    rate_escalator: float = 0.0125                  # 1.25% / yr

    # Operating — broken out for transparency
    # Fixed O&M can be entered either as $/kWdc-yr (industry-standard benchmark)
    # OR as a total $/yr lump sum. `fixed_om_entry_mode` toggles which field is used.
    fixed_om_entry_mode: str = "$/kWdc-yr"          # "$/kWdc-yr" | "$/yr"
    fixed_om_per_kw_year: float = 6.38              # used when mode == "$/kWdc-yr"
    fixed_om_annual: float = 0.0                    # used when mode == "$/yr"
    land_lease_annual: float = 203_626.0
    property_tax_annual: float = 148_609.0
    other_opex_annual: float = 262_364.0
    opex_escalation: float = 0.025
    degradation_pct: float = 0.005
    term_years: int = 25

    # Terminal / residual value at end of analysis term (rule of thumb: 5–15% of CapEx
    # for 20-yr operating solar; 0 = conservative screen).
    terminal_value: float = 0.0

    # Sponsor / developer contribution to the equity check (rest goes to outside LP).
    # Two entry modes:
    #   "% of equity" — LP convention: sponsor holds a skin-in-the-game share (typ. 10-20%)
    #   "$ amount"    — developer reality: sponsor brings what he has; LP ask = the gap
    sponsor_equity_entry_mode: str = "% of equity"   # "% of equity" | "$ amount"
    sponsor_equity_pct: float = 0.20
    sponsor_equity_amount: float = 0.0               # used when mode == "$ amount"

    # Tax & credit
    itc_pct: float = 0.40                           # 30% base + 10pp from Energy Community
    tax_rate: float = 0.27
    bonus_depreciation_pct: float = 1.0

    # Transferability — user's preferred screening assumption is unencumbered
    # net proceeds (no holdback, no txn cost). Real deals will have both;
    # adjust on a per-deal basis.
    transfer_sale_price: float = 0.92
    transfer_transaction_cost_pct: float = 0.00
    recapture_reserve_pct: float = 0.00

    # Senior debt — DSCR-sized by default, 1.25x floor, 75% LTC cap, 15-yr amort
    debt_enabled: bool = True
    debt_pct_of_cost: float = 0.50                  # only used when debt_sizing_method = "Percent of cost"
    interest_rate: float = 0.0825
    amortization_years: int = 15
    min_dscr_requirement: float = 1.25
    debt_sizing_method: str = "DSCR-sized"          # "Percent of cost" | "DSCR-sized"
    max_ltc_cap: float = 0.75


@dataclass
class SnapshotOutputs:
    total_capex: float
    year1_production_kwh: float
    year1_revenue_or_savings: float

    annual_revenue: List[float]
    annual_opex: List[float]
    annual_ebitda: List[float]
    opex_year1_breakdown: dict

    # Tax credit
    itc_cash_year1: float
    bonus_dep_shield_year1: float

    # Cash flows
    unlevered_cash_flow: List[float]
    cumulative_unlevered_cf: List[float]

    # Optional debt
    debt_amount: float
    annual_debt_service: List[float]
    annual_interest: List[float]
    annual_principal: List[float]
    annual_dscr: List[Optional[float]]
    min_dscr: Optional[float]
    avg_dscr: Optional[float]
    levered_cash_flow: List[float]
    cumulative_levered_cf: List[float]

    # Headlines (no debt = unlevered; with debt = levered)
    simple_payback_year: Optional[int]
    after_tc_payback_year: Optional[int]
    unlevered_irr: Optional[float]
    levered_irr: Optional[float]
    lcoe: float
    revenue_avg: float

    # Equity split + operating-year cash yield
    sponsor_cash: float                # dollars the developer/sponsor writes
    outside_lp_equity: float           # dollars the outside LP needs to write
    cash_on_cash_yield: Optional[float]  # avg operating-year distribution / equity at close

    verdict: str
    warnings: List[str] = field(default_factory=list)


# ---------- Main calc ----------

def calculate_snapshot(inp: SnapshotInputs) -> SnapshotOutputs:
    warnings: List[str] = []

    # Total CapEx = system cost + interconnection add-on. cost_per_watt is the
    # $/Wdc benchmark for modules/BOS/soft costs (not including interconnection).
    total_capex = inp.size_kw_dc * 1000.0 * inp.cost_per_watt + inp.interconnection_cost
    year1_production = inp.size_kw_dc * inp.yield_kwh_per_kw

    # ---- Revenue ----
    rate_yr1 = inp.customer_current_rate if inp.owner_mode == "Customer-owned" else inp.ppa_rate_to_customer

    # Year-1 OpEx breakdown — useful for the dashboard and PDF.
    # Fixed O&M is entered either per-kW or as a lump sum; use whichever mode is active.
    if inp.fixed_om_entry_mode == "$/yr":
        fixed_om = inp.fixed_om_annual
    else:  # default "$/kWdc-yr"
        fixed_om = inp.size_kw_dc * inp.fixed_om_per_kw_year
    opex_year1_breakdown = {
        "Fixed O&M": fixed_om,
        "Land lease": inp.land_lease_annual,
        "Property tax": inp.property_tax_annual,
        "Other (insurance / asset mgmt / misc)": inp.other_opex_annual,
    }
    opex_year1_total = sum(opex_year1_breakdown.values())

    annual_revenue, annual_opex, annual_ebitda = [], [], []
    for y in range(inp.term_years):
        production = year1_production * ((1.0 - inp.degradation_pct) ** y)
        rate = rate_yr1 * ((1.0 + inp.rate_escalator) ** y)
        rev = production * rate
        opex = opex_year1_total * ((1.0 + inp.opex_escalation) ** y)
        annual_revenue.append(rev)
        annual_opex.append(opex)
        annual_ebitda.append(rev - opex)

    # ---- Tax credit & dep shield ----
    itc_cash_year1 = total_capex * inp.itc_pct
    if inp.owner_mode == "Developer-PPA":
        # Developer monetizes via transferability: gross × price × (1 - txn - holdback)
        itc_cash_year1 = (
            total_capex * inp.itc_pct
            * inp.transfer_sale_price
            * (1 - inp.transfer_transaction_cost_pct - inp.recapture_reserve_pct)
        )
    depreciable_basis = total_capex * (1.0 - 0.5 * inp.itc_pct)
    bonus_dep_year1 = depreciable_basis * inp.bonus_depreciation_pct
    bonus_dep_shield_year1 = bonus_dep_year1 * inp.tax_rate

    # ---- Optional debt sizing ----
    debt_amount = 0.0
    balloon_payoff_final = 0.0
    annual_interest = [0.0] * inp.term_years
    annual_principal = [0.0] * inp.term_years
    annual_debt_service = [0.0] * inp.term_years
    annual_dscr: List[Optional[float]] = [None] * inp.term_years

    if inp.debt_enabled:
        if inp.debt_sizing_method == "DSCR-sized":
            # Worst-CFADS year over the amortization period sets max debt
            amortizing_cfads = annual_ebitda[:inp.amortization_years]
            if amortizing_cfads and min(amortizing_cfads) > 0:
                max_annual_ds = min(amortizing_cfads) / inp.min_dscr_requirement
                debt_capacity = pv_annuity(max_annual_ds, inp.interest_rate, inp.amortization_years)
                ltc_cap = total_capex * inp.max_ltc_cap
                if debt_capacity > ltc_cap:
                    debt_amount = ltc_cap
                    warnings.append(
                        f"DSCR-sized debt (${debt_capacity/1e6:.2f}M) exceeded LTC cap "
                        f"({inp.max_ltc_cap*100:.0f}% of cost = ${ltc_cap/1e6:.2f}M). Sized to cap."
                    )
                else:
                    debt_amount = debt_capacity
            else:
                warnings.append("Project EBITDA cannot support senior debt under chosen DSCR floor.")
        else:
            debt_amount = total_capex * inp.debt_pct_of_cost

        # Build amortization schedule
        balance = debt_amount
        for y in range(inp.term_years):
            if balance <= 0.01:
                continue
            interest = balance * inp.interest_rate
            if y < inp.amortization_years:
                remaining_periods = inp.amortization_years - y
                level_payment = amortization_payment(balance, inp.interest_rate, remaining_periods)
                principal = max(0.0, min(level_payment - interest, balance))
            else:
                principal = balance
            annual_interest[y] = interest
            annual_principal[y] = principal
            annual_debt_service[y] = interest + principal
            balance -= principal

        # If the amortization term runs past the analysis term, a balance remains at
        # the end. Treat it as a balloon payoff deducted from the final-year levered
        # cash flow (kept OUT of the DSCR arrays — it's a refinance/payoff event, not
        # an operating coverage burden) so levered returns aren't overstated.
        balloon_payoff_final = balance if balance > 0.01 else 0.0
        if balloon_payoff_final > 0:
            warnings.append(
                f"Amortization ({inp.amortization_years} yr) extends beyond the analysis term "
                f"({inp.term_years} yr). Remaining balance of ${balloon_payoff_final/1e6:.2f}M is "
                "deducted from the final year as a balloon payoff."
            )

        # DSCR per year
        for y in range(inp.term_years):
            if annual_debt_service[y] > 0:
                annual_dscr[y] = annual_ebitda[y] / annual_debt_service[y]
            else:
                annual_dscr[y] = None

        valid_dscr = [d for d in annual_dscr if d is not None and d > 0]
        if valid_dscr:
            min_dscr = min(valid_dscr)
            avg_dscr = sum(valid_dscr) / len(valid_dscr)
            if min_dscr < inp.min_dscr_requirement and inp.debt_sizing_method == "Percent of cost":
                warnings.append(
                    f"Min DSCR {min_dscr:.2f}x is below the required {inp.min_dscr_requirement:.2f}x floor. "
                    "Debt is oversized for this revenue stream — lender would resize down."
                )
        else:
            min_dscr = None
            avg_dscr = None
    else:
        min_dscr = None
        avg_dscr = None

    # ---- Cash flows ----
    # Unlevered (all-equity): -CapEx at t=0, then EBITDA - tax (with Y1 ITC + dep shield)
    #
    # Tax-appetite note: when the user has tax appetite, the Year-1 depreciation
    # shield is assumed to fully offset external income (or be carried forward),
    # so the shield is realized as cash benefit even when it exceeds operating tax.
    # That's why we do NOT clamp tax at zero. A negative `tax` value here is the
    # shield's net cash boost. (Treats the project as part of a taxpayer's broader
    # return — standard assumption for a face-test screen.)
    unlevered_cf = [-total_capex]
    for y in range(inp.term_years):
        operating = annual_ebitda[y]
        if y == 0:
            tax = operating * inp.tax_rate - bonus_dep_shield_year1
            after_tax = operating - tax + itc_cash_year1
        else:
            tax = operating * inp.tax_rate
            after_tax = operating - tax
        unlevered_cf.append(after_tax)

    # Levered: -(CapEx - debt_amount) at t=0, then EBITDA - debt service - tax (incl shields)
    # Interest is tax-deductible. Same tax-appetite logic: full shield realized in Y1.
    if inp.debt_enabled and debt_amount > 0:
        levered_cf = [-(total_capex - debt_amount)]
        for y in range(inp.term_years):
            operating = annual_ebitda[y]
            ds = annual_debt_service[y]
            interest_paid = annual_interest[y]
            if y == 0:
                tax = (operating - interest_paid) * inp.tax_rate - bonus_dep_shield_year1
                after_tax = operating - ds - tax + itc_cash_year1
            else:
                tax = (operating - interest_paid) * inp.tax_rate
                after_tax = operating - ds - tax
            levered_cf.append(after_tax)
        # Balloon payoff of any balance remaining past the analysis term
        if balloon_payoff_final > 0:
            levered_cf[-1] -= balloon_payoff_final
    else:
        levered_cf = list(unlevered_cf)

    # Terminal / residual value at end of analysis term.
    # Added to the final year of both unlevered and levered streams (post-tax simplification —
    # for a screening tool, we treat terminal value as an after-tax cash number the user has
    # already scoped for themselves).
    if inp.terminal_value > 0 and len(unlevered_cf) > 1:
        unlevered_cf[-1] += inp.terminal_value
        if len(levered_cf) > 1:
            levered_cf[-1] += inp.terminal_value

    # Cumulative
    cum_unlev = []
    r = 0.0
    for v in unlevered_cf:
        r += v
        cum_unlev.append(r)
    cum_lev = []
    r = 0.0
    for v in levered_cf:
        r += v
        cum_lev.append(r)

    # ---- Headlines ----
    headline_cf = levered_cf if inp.debt_enabled and debt_amount > 0 else unlevered_cf
    headline_cum = cum_lev if inp.debt_enabled and debt_amount > 0 else cum_unlev

    # Simple payback (no tax-credit benefits, no debt) — useful baseline
    simple_cf = [-total_capex] + [annual_ebitda[y] for y in range(inp.term_years)]
    simple_cum = []
    rr = 0.0
    for c in simple_cf:
        rr += c
        simple_cum.append(rr)

    simple_pb = payback_year(simple_cf)
    after_tc_pb = payback_year(headline_cf)
    unlev_irr = safe_irr(unlevered_cf)
    lev_irr = safe_irr(levered_cf) if (inp.debt_enabled and debt_amount > 0) else None

    # LCOE (simple, undiscounted)
    total_kwh = sum(year1_production * ((1 - inp.degradation_pct) ** y) for y in range(inp.term_years))
    total_cost_for_lcoe = total_capex + sum(annual_opex)
    lcoe = total_cost_for_lcoe / total_kwh if total_kwh > 0 else 0.0
    revenue_avg = sum(annual_revenue) / inp.term_years if annual_revenue else 0.0

    # ---- Sponsor / outside LP equity split ----
    equity_at_close = total_capex - (debt_amount if inp.debt_enabled else 0.0)
    if inp.sponsor_equity_entry_mode == "$ amount":
        # Developer brings a fixed dollar amount; the LP ask is the remaining gap.
        sponsor_cash = max(0.0, min(inp.sponsor_equity_amount, equity_at_close))
        if inp.sponsor_equity_amount > equity_at_close > 0:
            warnings.append(
                f"Sponsor contribution (${inp.sponsor_equity_amount/1e6:.2f}M) exceeds the full equity "
                f"check (${equity_at_close/1e6:.2f}M). Sponsor covers all equity; no outside LP needed. "
                "Sponsor cash capped at the equity requirement."
            )
    else:
        sponsor_share = max(0.0, min(1.0, inp.sponsor_equity_pct))
        sponsor_cash = equity_at_close * sponsor_share
    outside_lp_equity = max(0.0, equity_at_close - sponsor_cash)

    # ---- Cash-on-cash yield (operating years) ----
    # Average of Years 2..N distributions divided by the equity at close. Year 1 is
    # excluded because it contains the outsized ITC + depreciation shield receipts —
    # for a yield metric, we want the steady-state operating distribution level.
    hl_cf = levered_cf if (inp.debt_enabled and debt_amount > 0) else unlevered_cf
    if len(hl_cf) > 2 and equity_at_close > 0:
        # hl_cf[0] = -equity at close; hl_cf[1] = Year 1 (has ITC + dep bump); we skip both
        # for the yield calc unless there are only a couple of years total.
        operating_flows = hl_cf[2:]
        # If a terminal value was tacked onto the last year, strip it out for yield purposes
        # so it doesn't inflate the average.
        if inp.terminal_value > 0 and operating_flows:
            operating_flows = operating_flows[:-1] + [operating_flows[-1] - inp.terminal_value]
        cash_on_cash_yield = (sum(operating_flows) / len(operating_flows)) / equity_at_close
    else:
        cash_on_cash_yield = None

    # ---- Verdict ----
    bits: List[str] = []
    if after_tc_pb is not None and after_tc_pb <= 7:
        bits.append("Strong screen")
    elif after_tc_pb is not None and after_tc_pb <= 10:
        bits.append("Decent screen")
    elif after_tc_pb is not None:
        bits.append(f"Marginal — payback {after_tc_pb}yr")
    else:
        bits.append("Project does not pay back within term")

    headline_irr = lev_irr if lev_irr is not None else unlev_irr
    if headline_irr is not None and headline_irr > 0.15:
        bits.append(f"IRR {headline_irr*100:.0f}%")
    elif headline_irr is not None and headline_irr > 0.08:
        bits.append(f"IRR {headline_irr*100:.0f}%")
    elif headline_irr is not None:
        bits.append(f"IRR only {headline_irr*100:.0f}%")

    if inp.owner_mode == "Customer-owned":
        savings = rate_yr1 - lcoe
        if savings > 0.02:
            bits.append(f"saving {savings*100:.1f}c/kWh vs current rate")
        elif savings > 0:
            bits.append(f"thin savings ({savings*100:.1f}c/kWh)")
        else:
            bits.append("LCOE exceeds current rate (deal relies on tax benefits)")
    else:
        spread = rate_yr1 - lcoe
        if spread > 0.02:
            bits.append(f"PPA margin {spread*100:.1f}c/kWh above LCOE")
        elif spread > 0:
            bits.append(f"thin PPA margin {spread*100:.1f}c/kWh")
        else:
            bits.append("PPA rate is below LCOE (deal relies on tax benefits)")

    if inp.debt_enabled and min_dscr is not None:
        if min_dscr >= inp.min_dscr_requirement:
            bits.append(f"min DSCR {min_dscr:.2f}x (bankable)")
        else:
            bits.append(f"min DSCR {min_dscr:.2f}x (below {inp.min_dscr_requirement:.2f}x — needs resize)")

    verdict = " — ".join(bits) + "."

    # ---- Sanity warnings ----
    if inp.cost_per_watt > 5.0:
        warnings.append(f"Cost/Watt of ${inp.cost_per_watt:.2f} is very high — double-check assumptions.")
    if inp.yield_kwh_per_kw < 900 or inp.yield_kwh_per_kw > 2200:
        warnings.append(f"Specific yield {inp.yield_kwh_per_kw} kWh/kWdc-yr is outside typical 1,000–2,000 range.")

    # PPA / customer rate vs simple LCOE — flag if the revenue rate is below project LCOE.
    # Note: an apparent below-LCOE rate can still pencil thanks to ITC + depreciation,
    # so the warning is informational, not a kill signal.
    rate_for_compare = inp.customer_current_rate if inp.owner_mode == "Customer-owned" else inp.ppa_rate_to_customer
    if rate_for_compare < lcoe:
        warnings.append(
            f"PPA rate is below simple LCOE (${rate_for_compare:.4f}/kWh vs ${lcoe:.4f}/kWh); "
            "project does not recover all-in cost at this revenue rate. Tax credits and "
            "depreciation can still close the gap, but operating economics are sub-LCOE."
        )

    # ITC sell price sanity (Developer-PPA only — Customer-owned uses credit directly)
    if inp.owner_mode == "Developer-PPA":
        if inp.transfer_sale_price < 0.50 or inp.transfer_sale_price > 1.10:
            warnings.append(
                f"ITC sell price of {inp.transfer_sale_price:.2f} is implausible — typical mid-2026 "
                "market range is 0.82–0.96. Check the input."
            )

    # Depreciation shield assumes tax appetite — flag clearly when shield is non-zero
    if inp.bonus_depreciation_pct > 0 and inp.tax_rate > 0 and bonus_dep_shield_year1 > 0:
        warnings.append(
            "Depreciation tax shield is counted in cash flows. This assumes the owner has "
            "sufficient tax appetite to use it (full external income offset). For tax-exempt "
            "or low-appetite owners, switch the depreciation toggle to No."
        )

    # Debt sizing source flag — useful for the screener
    if inp.debt_enabled and debt_amount > 0:
        if inp.debt_sizing_method == "DSCR-sized":
            ltc_cap_dollars = total_capex * inp.max_ltc_cap
            if abs(debt_amount - ltc_cap_dollars) < 1.0:
                warnings.append(
                    f"Debt is capped by the {inp.max_ltc_cap*100:.0f}% LTC ceiling, not by DSCR. "
                    "Project could in theory support more debt under the chosen DSCR floor."
                )
            else:
                warnings.append(
                    f"Debt is sized by the {inp.min_dscr_requirement:.2f}x DSCR floor (LTC not binding)."
                )

    return SnapshotOutputs(
        total_capex=total_capex,
        year1_production_kwh=year1_production,
        year1_revenue_or_savings=annual_revenue[0] if annual_revenue else 0.0,
        annual_revenue=annual_revenue,
        annual_opex=annual_opex,
        annual_ebitda=annual_ebitda,
        opex_year1_breakdown=opex_year1_breakdown,
        itc_cash_year1=itc_cash_year1,
        bonus_dep_shield_year1=bonus_dep_shield_year1,
        unlevered_cash_flow=unlevered_cf,
        cumulative_unlevered_cf=cum_unlev,
        debt_amount=debt_amount,
        annual_debt_service=annual_debt_service,
        annual_interest=annual_interest,
        annual_principal=annual_principal,
        annual_dscr=annual_dscr,
        min_dscr=min_dscr,
        avg_dscr=avg_dscr,
        levered_cash_flow=levered_cf,
        cumulative_levered_cf=cum_lev,
        simple_payback_year=simple_pb,
        after_tc_payback_year=after_tc_pb,
        unlevered_irr=unlev_irr,
        levered_irr=lev_irr,
        lcoe=lcoe,
        revenue_avg=revenue_avg,
        sponsor_cash=sponsor_cash,
        outside_lp_equity=outside_lp_equity,
        cash_on_cash_yield=cash_on_cash_yield,
        verdict=verdict,
        warnings=warnings,
    )


# ---------- Solvers ----------

def _set_rate(inp: SnapshotInputs, rate: float) -> SnapshotInputs:
    import copy
    c = copy.copy(inp)
    if inp.owner_mode == "Customer-owned":
        c.customer_current_rate = rate
    else:
        c.ppa_rate_to_customer = rate
    return c


def _eff_irr(out: SnapshotOutputs) -> float:
    headline = out.levered_irr if out.levered_irr is not None else out.unlevered_irr
    return headline if headline is not None else -0.99


def solve_rate_for_irr(inp: SnapshotInputs, target_irr: float,
                        low: float = 0.001, high: float = 0.50,
                        tol: float = 1e-4, max_iter: int = 80) -> Optional[float]:
    out_lo = calculate_snapshot(_set_rate(inp, low))
    out_hi = calculate_snapshot(_set_rate(inp, high))
    irr_lo, irr_hi = _eff_irr(out_lo), _eff_irr(out_hi)
    if irr_hi < target_irr:
        return None
    if irr_lo >= target_irr:
        return low
    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        out_mid = calculate_snapshot(_set_rate(inp, mid))
        irr_mid = _eff_irr(out_mid)
        if abs(irr_mid - target_irr) < tol:
            return mid
        if irr_mid < target_irr:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def _set_cost(inp: SnapshotInputs, cost_per_watt: float) -> SnapshotInputs:
    import copy
    c = copy.copy(inp)
    c.cost_per_watt = cost_per_watt
    return c


def solve_cost_for_irr(
    inp: SnapshotInputs,
    target_irr: float,
    low: float = 0.50,
    high: float = 5.00,
    tol: float = 1e-4,
    max_iter: int = 80,
) -> Optional[float]:
    """
    Find the maximum cost-per-watt that still clears the target IRR.

    Lower cost -> higher IRR; higher cost -> lower IRR. Binary search.
    Returns None if even the cheapest cost in range fails to clear the target
    (i.e., the deal is fundamentally broken regardless of CapEx).
    """
    out_lo = calculate_snapshot(_set_cost(inp, low))
    out_hi = calculate_snapshot(_set_cost(inp, high))
    irr_lo, irr_hi = _eff_irr(out_lo), _eff_irr(out_hi)

    if irr_lo < target_irr:
        return None
    if irr_hi >= target_irr:
        return high  # cost is not binding

    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        out_mid = calculate_snapshot(_set_cost(inp, mid))
        irr_mid = _eff_irr(out_mid)
        if abs(irr_mid - target_irr) < tol:
            return mid
        if irr_mid >= target_irr:
            low = mid          # mid still works, try higher cost
        else:
            high = mid         # mid too expensive
    return 0.5 * (low + high)


def solve_cost_for_payback(
    inp: SnapshotInputs,
    target_year: int,
    low: float = 0.50,
    high: float = 5.00,
    max_iter: int = 60,
) -> Optional[float]:
    """
    Find the maximum cost-per-watt that still pays back by target_year.
    Lower cost -> faster payback; higher cost -> slower payback.
    """
    out_lo = calculate_snapshot(_set_cost(inp, low))
    pb_lo = out_lo.after_tc_payback_year
    if pb_lo is None or pb_lo > target_year:
        return None

    out_hi = calculate_snapshot(_set_cost(inp, high))
    pb_hi = out_hi.after_tc_payback_year
    if pb_hi is not None and pb_hi <= target_year:
        return high

    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        out_mid = calculate_snapshot(_set_cost(inp, mid))
        pb = out_mid.after_tc_payback_year
        if pb is None or pb > target_year:
            high = mid
        else:
            low = mid
        if abs(high - low) < 1e-4:
            break
    return low


def solve_rate_for_payback(inp: SnapshotInputs, target_year: int,
                            low: float = 0.001, high: float = 0.50,
                            max_iter: int = 60) -> Optional[float]:
    out_hi = calculate_snapshot(_set_rate(inp, high))
    if out_hi.after_tc_payback_year is None or out_hi.after_tc_payback_year > target_year:
        return None
    out_lo = calculate_snapshot(_set_rate(inp, low))
    if out_lo.after_tc_payback_year is not None and out_lo.after_tc_payback_year <= target_year:
        return low
    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        out_mid = calculate_snapshot(_set_rate(inp, mid))
        pb = out_mid.after_tc_payback_year
        if pb is None or pb > target_year:
            low = mid
        else:
            high = mid
        if abs(high - low) < 1e-5:
            break
    return high
