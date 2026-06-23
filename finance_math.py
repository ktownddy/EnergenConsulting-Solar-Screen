"""
Robust financial helpers.

safe_irr wraps numpy_financial.irr and falls back to bracketed bisection on
failure. Never crashes the UI on a problematic cash-flow stream.
"""
from __future__ import annotations

import math
from typing import Sequence, Optional

try:
    import numpy_financial as npf  # type: ignore
    _HAS_NPF = True
except Exception:
    _HAS_NPF = False


def npv(rate: float, cash_flows: Sequence[float]) -> float:
    return sum(cf / ((1.0 + rate) ** t) for t, cf in enumerate(cash_flows))


def _bisect_irr(cf, low=-0.99, high=10.0, tol=1e-7, max_iter=200):
    f_low = npv(low, cf)
    f_high = npv(high, cf)
    if math.isnan(f_low) or math.isnan(f_high) or f_low * f_high > 0:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        f_mid = npv(mid, cf)
        if abs(f_mid) < tol or (high - low) < tol:
            return mid
        if f_low * f_mid < 0:
            high = mid
            f_high = f_mid
        else:
            low = mid
            f_low = f_mid
    return 0.5 * (low + high)


def safe_irr(cash_flows: Sequence[float]) -> Optional[float]:
    cf = list(cash_flows)
    if len(cf) < 2:
        return None
    if not (any(c > 0 for c in cf) and any(c < 0 for c in cf)):
        return None
    if _HAS_NPF:
        try:
            r = npf.irr(cf)
            if r is not None and not math.isnan(float(r)) and not math.isinf(float(r)):
                if abs(npv(float(r), cf)) < 1e-3 * max(abs(c) for c in cf):
                    return float(r)
        except Exception:
            pass
    for high in (1.0, 3.0, 10.0, 50.0):
        r = _bisect_irr(cf, low=-0.95, high=high)
        if r is not None:
            return r
    return None


def equity_multiple(cf):
    inflows = sum(c for c in cf if c > 0)
    outflows = -sum(c for c in cf if c < 0)
    return inflows / outflows if outflows > 0 else None


def payback_year(cf):
    cum = 0.0
    for t, c in enumerate(cf):
        cum += c
        if cum >= 0:
            return t
    return None


def amortization_payment(principal, rate, n):
    if n <= 0:
        return 0.0
    if rate == 0:
        return principal / n
    return principal * rate / (1.0 - (1.0 + rate) ** (-n))


def pv_annuity(payment, rate, n):
    if n <= 0:
        return 0.0
    if rate == 0:
        return payment * n
    return payment * (1.0 - (1.0 + rate) ** (-n)) / rate
