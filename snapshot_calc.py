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
    """Build §48E applicable percentage from compliance answers."""
    components: dict = {}
    warnings: List[str] = []

    if not obbba_eligible:
        warnings.append(
            "OBBBA construction safe-harbor NOT met (BOC after July 4, 2026 and "
            "PIS after Dec 31, 2027). Section 48E credit unavailable for solar. "
            "ITC = 0%."
        )
        return 0.0, {"No credit (OBBBA cutoff)": 0.0}, warnings

    pwa_effective = under_1_mwac or pwa_directly_met
    components["Base 48E credit"] = 0.06
    if pwa_effective:
        components["PWA (+24pp)"] = 0.24
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
    # Project basics
    project_type: str = "Rooftop"
    owner_mode: str = "Customer-owned"       # "Customer-owned" | "Developer-PPA"
    size_kw_dc: float = 1000.0
    cost_per_watt: float = 2.50
    yield_kwh_per_kw: float = 1400.0

    # Revenue
    customer_current_rate: float = 0.12
    ppa_rate_to_customer: float = 0.085
    rate_escalator: float = 0.0250

    # Operating
    fixed_om_per_kw_year: float = 12.0
    degradation_pct: float = 0.005
    term_years: int = 25

    # Tax & credit
    itc_pct: float = 0.30
    tax_rate: float = 0.27
    bonus_depreciation_pct: float = 1.0
    transfer_sale_price: float = 0.93        # mid-2026 IG benchmark
    transfer_transaction_cost_pct: float = 0.02
    recapture_reserve_pct: float = 0.05

    # OPTIONAL senior debt layer
    debt_enabled: bool = False
    debt_pct_of_cost: float = 0.50
    interest_rate: float = 0.0825
    amortization_years: int = 15
    min_dscr_requirement: float = 1.30
    debt_sizing_method: str = "Percent of cost"   # "Percent of cost" | "DSCR-sized"
    max_ltc_cap: float = 0.75


@dataclass
class SnapshotOutputs:
    total_capex: float
    year1_production_kwh: float
    year1_revenue_or_savings: float

    annual_revenue: List[float]
    annual_opex: List[float]
    annual_ebitda: List[float]

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

    verdict: str
    warnings: List[str] = field(default_factory=list)


# ---------- Main calc ----------

def calculate_snapshot(inp: SnapshotInputs) -> SnapshotOutputs:
    warnings: List[str] = []

    total_capex = inp.size_kw_dc * 1000.0 * inp.cost_per_watt
    year1_production = inp.size_kw_dc * inp.yield_kwh_per_kw

    # ---- Revenue ----
    rate_yr1 = inp.customer_current_rate if inp.owner_mode == "Customer-owned" else inp.ppa_rate_to_customer

    annual_revenue, annual_opex, annual_ebitda = [], [], []
    for y in range(inp.term_years):
        production = year1_production * ((1.0 - inp.degradation_pct) ** y)
        rate = rate_yr1 * ((1.0 + inp.rate_escalator) ** y)
        rev = production * rate
        opex = inp.size_kw_dc * inp.fixed_om_per_kw_year * ((1.0 + 0.025) ** y)
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
    else:
        levered_cf = list(unlevered_cf)

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
            bits.append("LCOE exceeds current rate — does not save customer money")
    else:
        spread = rate_yr1 - lcoe
        if spread > 0.02:
            bits.append(f"PPA margin {spread*100:.1f}c/kWh above LCOE")
        elif spread > 0:
            bits.append(f"thin PPA margin {spread*100:.1f}c/kWh")
        else:
            bits.append("PPA rate is below LCOE — losing money on each kWh")

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

    return SnapshotOutputs(
        total_capex=total_capex,
        year1_production_kwh=year1_production,
        year1_revenue_or_savings=annual_revenue[0] if annual_revenue else 0.0,
        annual_revenue=annual_revenue,
        annual_opex=annual_opex,
        annual_ebitda=annual_ebitda,
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
