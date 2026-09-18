"""Layer 4: valuation. Two independent, cross-checking methods rather than
one black-boxed number:

1. A Damodaran-style DCF - assumptions computed from the company's own
   data and always logged in the output, never hidden inside a single
   opaque "fair value" figure. This is a deliberately simplified model
   (fixed discount rate, flat stage-1 growth, no CAPM/WACC build - this
   pipeline has no reliable beta/cost-of-debt source), and says so in its
   own output rather than presenting false precision.
2. A relative-multiple check (P/E, EV/EBITDA vs. the sector median among
   the OTHER tracked companies in the same sector this run) as a sanity
   cross-check against the DCF, computed the same way
   pipeline.main.apply_sector_relative_momentum() already computes a
   sector-relative signal for price momentum.

FMP's own DCF endpoint (dcf_upside_pct, computed in fundamentals.py) and
the Graham Number remain available as further cross-checks; this module
doesn't replace them.
"""

# Fixed, documented simplifications - see module docstring. Not tuned per
# company; the growth-rate assumption below is the one input that does vary
# by company.
_DISCOUNT_RATE_PCT = 9.0
_TERMINAL_GROWTH_RATE_PCT = 2.5
_PROJECTION_YEARS = 5
_DEFAULT_GROWTH_RATE_PCT = 3.0  # used only when no trailing revenue CAGR is available at all
_GROWTH_RATE_CLAMP = (-10.0, 20.0)  # avoid extrapolating an outlier year's growth indefinitely


def _first_of(row: dict, *keys: str):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _base_fcf(raw: dict) -> float | None:
    cashflow_stmts = raw.get("cashflow_stmts") or []
    if not cashflow_stmts:
        return None
    row = cashflow_stmts[0]
    fcf = _first_of(row, "freeCashFlow")
    if fcf is not None:
        return fcf
    ocf = _first_of(row, "operatingCashFlow")
    capex = _first_of(row, "capitalExpenditure")
    if ocf is not None and capex is not None:
        return ocf - abs(capex)
    return None


def _growth_assumption(metrics: dict) -> tuple[float, str]:
    for key, source in (
        ("revenue_cagr_5yr_pct", "trailing_5yr_revenue_cagr"),
        ("revenue_cagr_3yr_pct", "trailing_3yr_revenue_cagr"),
    ):
        value = metrics.get(key)
        if value is not None:
            clamped = max(_GROWTH_RATE_CLAMP[0], min(_GROWTH_RATE_CLAMP[1], value))
            return clamped, source
    return _DEFAULT_GROWTH_RATE_PCT, "default_conservative"


def build_dcf(metrics: dict, raw: dict, shares_outstanding: float | None, price: float | None) -> dict:
    base_fcf = _base_fcf(raw)
    growth_rate_pct, growth_source = _growth_assumption(metrics)
    assumptions = {
        "base_fcf": base_fcf,
        "growth_rate_pct": growth_rate_pct,
        "growth_rate_source": growth_source,
        "projection_years": _PROJECTION_YEARS,
        "discount_rate_pct": _DISCOUNT_RATE_PCT,
        "terminal_growth_rate_pct": _TERMINAL_GROWTH_RATE_PCT,
        "note": (
            "Simplified 2-stage DCF: flat growth_rate_pct for projection_years, "
            "then a Gordon-growth terminal value at terminal_growth_rate_pct, "
            "discounted at a single fixed discount_rate_pct (not a full CAPM/WACC "
            "build). Treats free cash flow as equity-available cash flow directly. "
            "A deliberately transparent estimate, not a precise fair value."
        ),
    }

    if base_fcf is None or base_fcf <= 0 or not shares_outstanding or not price:
        return {"assumptions": assumptions, "intrinsic_value_per_share": None, "margin_of_safety_pct": None}

    discount_rate = _DISCOUNT_RATE_PCT / 100
    terminal_growth = _TERMINAL_GROWTH_RATE_PCT / 100
    growth = growth_rate_pct / 100

    if discount_rate <= terminal_growth:
        # Guard against an undefined/negative Gordon-growth denominator -
        # shouldn't happen with the fixed defaults above, but stays safe if
        # they're ever tuned.
        return {"assumptions": assumptions, "intrinsic_value_per_share": None, "margin_of_safety_pct": None}

    pv_sum = 0.0
    fcf_year = base_fcf
    for year in range(1, _PROJECTION_YEARS + 1):
        fcf_year = fcf_year * (1 + growth)
        pv_sum += fcf_year / (1 + discount_rate) ** year

    terminal_value = fcf_year * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / (1 + discount_rate) ** _PROJECTION_YEARS

    intrinsic_value_total = pv_sum + pv_terminal
    intrinsic_value_per_share = intrinsic_value_total / shares_outstanding
    margin_of_safety_pct = (intrinsic_value_per_share - price) / price * 100

    return {
        "assumptions": assumptions,
        "intrinsic_value_per_share": intrinsic_value_per_share,
        "margin_of_safety_pct": margin_of_safety_pct,
    }


def build_relative_multiples(metrics: dict, sector_medians: dict | None) -> dict:
    """sector_medians: {"pe_ttm": float|None, "ev_ebitda": float|None} computed
    across the OTHER tracked companies in the same sector this run (see
    pipeline.main.apply_sector_relative_valuation) - None if this company has
    no sector peers with data this run."""
    sector_medians = sector_medians or {}
    pe_ttm = metrics.get("pe_ttm")
    ev_ebitda = metrics.get("ev_ebitda")
    sector_median_pe = sector_medians.get("pe_ttm")
    sector_median_ev_ebitda = sector_medians.get("ev_ebitda")

    return {
        "pe_ttm": pe_ttm,
        "sector_median_pe_ttm": sector_median_pe,
        "pe_vs_sector_median_pct": (
            (pe_ttm - sector_median_pe) / sector_median_pe * 100
            if pe_ttm is not None and sector_median_pe
            else None
        ),
        "ev_ebitda": ev_ebitda,
        "sector_median_ev_ebitda": sector_median_ev_ebitda,
        "ev_ebitda_vs_sector_median_pct": (
            (ev_ebitda - sector_median_ev_ebitda) / sector_median_ev_ebitda * 100
            if ev_ebitda is not None and sector_median_ev_ebitda
            else None
        ),
    }


def build_valuation(
    metrics: dict,
    raw: dict,
    shares_outstanding: float | None,
    price: float | None,
    sector_medians: dict | None = None,
) -> dict:
    dcf = build_dcf(metrics, raw, shares_outstanding, price)
    relative = build_relative_multiples(metrics, sector_medians)
    return {
        "dcf": dcf,
        "relative": relative,
        # The valuation gate other layers read (see pipeline/scoring/aggregation.py) -
        # this module's own DCF, not FMP's black-box one (metrics["dcf_upside_pct"],
        # which remains available separately as a further cross-check).
        "margin_of_safety_pct": dcf["margin_of_safety_pct"],
    }
