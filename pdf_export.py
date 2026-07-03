"""
Energen Solar Deal Snapshot — PDF deal-analysis export.

Single-page investor-ready deal sheet. Uses ReportLab Platypus (pure pip,
no system dependencies). Branded with Energen palette.
"""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)


# Energen brand palette
NAVY = colors.HexColor("#0b1a2e")
NAVY_LIGHT = colors.HexColor("#1a2a45")
GOLD = colors.HexColor("#c9a96e")
CREAM = colors.HexColor("#d4cfc5")
TAN = colors.HexColor("#8a8679")
SAND = colors.HexColor("#f1ede2")
PARCHMENT = colors.HexColor("#fbfaf6")
WHITE = colors.white
LIGHT_GREY = colors.HexColor("#EFEFEF")


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


def _draw_header_footer(canvas, doc):
    canvas.saveState()
    # Header banner
    canvas.setFillColor(NAVY)
    canvas.rect(0, doc.pagesize[1] - 0.7 * inch, doc.pagesize[0], 0.7 * inch, fill=1, stroke=0)
    canvas.setFillColor(GOLD)
    canvas.rect(0, doc.pagesize[1] - 0.72 * inch, doc.pagesize[0], 0.02 * inch, fill=1, stroke=0)
    # Wordmark
    canvas.setFillColor(CREAM)
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(0.5 * inch, doc.pagesize[1] - 0.42 * inch, "ENERGEN")
    canvas.setFillColor(TAN)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(0.5 * inch, doc.pagesize[1] - 0.56 * inch, "C O N S U L T I N G")
    # Tagline
    canvas.setFillColor(CREAM)
    canvas.setFont("Helvetica", 10)
    canvas.drawRightString(doc.pagesize[0] - 0.5 * inch, doc.pagesize[1] - 0.36 * inch, "Solar Deal Snapshot")
    canvas.setFillColor(TAN)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(doc.pagesize[0] - 0.5 * inch, doc.pagesize[1] - 0.5 * inch,
                            f"Generated {datetime.now().strftime('%B %d, %Y')}")

    # Footer
    canvas.setFillColor(TAN)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(
        0.5 * inch, 0.4 * inch,
        "Preliminary deal screening only. Not tax, legal, accounting, investment, or engineering advice.",
    )
    canvas.drawRightString(doc.pagesize[0] - 0.5 * inch, 0.4 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _make_table(data, col_widths, header=True, totals_row=False):
    t = Table(data, colWidths=col_widths)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, LIGHT_GREY),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (-1, 0), "RIGHT"),
        ]
        body_start = 1
    else:
        body_start = 0
    style += [("ROWBACKGROUNDS", (0, body_start), (-1, -1), [WHITE, LIGHT_GREY])]
    if totals_row:
        style += [
            ("BACKGROUND", (0, -1), (-1, -1), SAND),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(style))
    return t


def build_deal_pdf(inp, out, q: dict) -> bytes:
    """
    Generate a single-page deal snapshot PDF.

    `inp`   = SnapshotInputs
    `out`   = SnapshotOutputs (result of calculate_snapshot)
    `q`     = the ITC question dict (obbba, under_1mw, pwa_direct, ec, dc, li)

    Returns the PDF bytes for st.download_button.
    """
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        topMargin=0.95 * inch, bottomMargin=0.65 * inch,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="branded", frames=[frame], onPage=_draw_header_footer)])

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading2"], textColor=NAVY, fontSize=14, spaceAfter=4, spaceBefore=6)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=12, textColor=NAVY)
    italic = ParagraphStyle("italic", parent=body, textColor=TAN, fontName="Helvetica-Oblique")
    verdict_style = ParagraphStyle(
        "verdict", parent=body, fontSize=10.5, leading=14, leftIndent=10,
        borderColor=GOLD, borderWidth=1.5, borderPadding=8, backColor=SAND,
        spaceBefore=6, spaceAfter=10,
    )

    story = []

    # Project summary
    story.append(Paragraph("Project Summary", h1))
    summary_rows = [
        ["Field", "Value"],
        ["Project type", inp.project_type],
        ["Ownership / structure", inp.owner_mode],
        ["System size (DC)", f"{inp.size_kw_dc:,.0f} kWdc"],
        ["Cost per watt", f"${inp.cost_per_watt:,.2f}/Wdc"],
    ]
    if inp.interconnection_cost > 0:
        summary_rows.append(["Interconnection cost", _fmt_money(inp.interconnection_cost)])
    summary_rows += [
        ["Specific yield", f"{inp.yield_kwh_per_kw:,.0f} kWh/kWdc-yr"],
        ["Analysis term", f"{inp.term_years} years"],
        [
            "Revenue rate (Year 1)",
            f"${(inp.customer_current_rate if inp.owner_mode == 'Customer-owned' else inp.ppa_rate_to_customer):.4f}/kWh"
        ],
        ["Annual escalator", f"{inp.rate_escalator*100:.2f}%"],
    ]
    if inp.terminal_value > 0:
        summary_rows.append(["Terminal value at end of term", _fmt_money(inp.terminal_value)])
    story.append(_make_table(summary_rows, [2.5 * inch, 2.5 * inch]))
    story.append(Spacer(1, 8))

    # Verdict
    story.append(Paragraph("Verdict", h1))
    story.append(Paragraph(out.verdict, verdict_style))

    # Headline metrics — two-column grid
    story.append(Paragraph("Headline Metrics", h1))
    irr_label = "Levered IRR" if (inp.debt_enabled and out.debt_amount > 0) else "IRR (post-TC)"
    irr_value = out.levered_irr if out.levered_irr is not None else out.unlevered_irr
    equity_at_close = out.total_capex - (out.debt_amount if inp.debt_enabled else 0.0)
    yr1_tax_benefits = out.itc_cash_year1 + out.bonus_dep_shield_year1
    net_equity_after_yr1 = equity_at_close - yr1_tax_benefits

    # ITC cash and depreciation shield reported separately. ITC cash is real money
    # (either used directly or sold via §6418 transfer). Dep shield is a tax benefit
    # only — valid for owners with sufficient tax appetite. The two residual lines
    # below show the cash residual and the broader economic residual.
    net_cash_equity_after_itc = equity_at_close - out.itc_cash_year1
    net_exposure_after_all = equity_at_close - out.itc_cash_year1 - out.bonus_dep_shield_year1

    headline_rows = [
        ["Metric", "Value"],
        ["Total CapEx", _fmt_money(out.total_capex)],
        ["Equity at close", _fmt_money(equity_at_close)],
        [f"  Sponsor cash ({(out.sponsor_cash / equity_at_close * 100.0) if equity_at_close > 0 else 0:.0f}%)", _fmt_money(out.sponsor_cash)],
        [f"  Outside LP equity ({(out.outside_lp_equity / equity_at_close * 100.0) if equity_at_close > 0 else 0:.0f}%)", _fmt_money(out.outside_lp_equity)],
        ["ITC cash received Year 1 (real cash)", _fmt_money(out.itc_cash_year1)],
        ["Depreciation tax shield Year 1 (tax benefit, not cash)", _fmt_money(out.bonus_dep_shield_year1)],
        ["Net cash equity after ITC", _fmt_money(net_cash_equity_after_itc)],
        ["Net exposure after ITC + depreciation shield", _fmt_money(net_exposure_after_all)],
        ["After-TC payback", f"Year {out.after_tc_payback_year}" if out.after_tc_payback_year else "Never"],
        [irr_label, _fmt_pct(irr_value)],
        ["Cash-on-cash yield (operating avg)", _fmt_pct(out.cash_on_cash_yield)],
        ["Equity back by end of Year 1 (incl. ITC + dep shield)", _fmt_pct(out.equity_returned_yr1_pct, 0)],
        ["LCOE (simple)", f"${out.lcoe:.4f}/kWh"],
        ["Year-1 production", f"{out.year1_production_kwh/1000:,.0f} MWh"],
        ["Year-1 revenue / savings", _fmt_money(out.year1_revenue_or_savings)],
    ]
    if inp.debt_enabled and out.debt_amount > 0:
        leverage = out.debt_amount / out.total_capex if out.total_capex else 0
        headline_rows.append(["Senior debt", f"{_fmt_money(out.debt_amount)}  ({leverage*100:.1f}% LTC)"])
        headline_rows.append(["Min DSCR / Avg DSCR", f"{_fmt_x(out.min_dscr)}  /  {_fmt_x(out.avg_dscr)}"])
    story.append(_make_table(headline_rows, [3.0 * inch, 2.0 * inch]))
    story.append(Spacer(1, 6))

    # Tax credit stack — use the calc engine's own component labels so the PDF
    # always matches the app (including the small-project-exemption precedence
    # when both under-1MWac and PWA are true).
    story.append(Paragraph("Section 48E Tax Credit Stack", h1))
    if q and q.get("obbba"):
        from snapshot_calc import build_itc_pct
        _, components, _ = build_itc_pct(
            obbba_eligible=True,
            under_1_mwac=bool(q.get("under_1mw")),
            pwa_directly_met=bool(q.get("pwa_direct")),
            energy_community=bool(q.get("ec")),
            domestic_content=bool(q.get("dc")),
            low_income=q.get("li", "None"),
        )
        tc_rows = [["Component", "Adder"]]
        for name, val in components.items():
            tc_rows.append([name, f"{val*100:.0f}%"])
        tc_rows.append(["Applicable percentage", f"{inp.itc_pct*100:.1f}%"])
        story.append(_make_table(tc_rows, [3.5 * inch, 1.5 * inch], totals_row=True))
    else:
        story.append(Paragraph(
            "<b>No §48E credit available</b> — OBBBA construction safe-harbor cutoff not met. "
            "Project economics rely on revenue, depreciation, and any state incentives.",
            body,
        ))
    story.append(Spacer(1, 6))

    # OpEx breakdown
    story.append(Paragraph("Year-1 Operating Expense Breakdown", h1))
    opex_rows = [["Line item", "Year-1 cost"]]
    for k, v in out.opex_year1_breakdown.items():
        opex_rows.append([k, _fmt_money(v)])
    opex_rows.append(["Total Year-1 OpEx", _fmt_money(sum(out.opex_year1_breakdown.values()))])
    story.append(_make_table(opex_rows, [3.5 * inch, 1.5 * inch], totals_row=True))
    story.append(Spacer(1, 8))

    # Tax credit monetization (if Developer-PPA)
    if inp.owner_mode == "Developer-PPA":
        story.append(Paragraph("Tax Credit Monetization (§6418 Transferability)", h1))
        gross_credit = out.total_capex * inp.itc_pct
        tcm_rows = [
            ["Item", "Value"],
            ["Gross §48E credit", _fmt_money(gross_credit)],
            ["Transfer sale price per credit dollar", f"${inp.transfer_sale_price:.4f}"],
            ["Less: transaction cost", f"{inp.transfer_transaction_cost_pct*100:.1f}%"],
            ["Less: recapture reserve / holdback", f"{inp.recapture_reserve_pct*100:.1f}%"],
            ["Net cash to project (Year 1)", _fmt_money(out.itc_cash_year1)],
        ]
        story.append(_make_table(tcm_rows, [3.5 * inch, 1.5 * inch], totals_row=True))
        story.append(Spacer(1, 6))

    # Customer spread (Customer-owned) OR developer margin (Developer-PPA)
    story.append(Paragraph("Spread Context", h1))
    if inp.owner_mode == "Customer-owned":
        savings = inp.customer_current_rate - out.lcoe
        story.append(Paragraph(
            f"Customer current rate: <b>${inp.customer_current_rate:.4f}/kWh</b><br/>"
            f"Project LCOE: <b>${out.lcoe:.4f}/kWh</b><br/>"
            f"Year-1 savings vs current: <b>{savings*100:.2f}¢/kWh "
            f"({savings/inp.customer_current_rate*100:.1f}% off current rate)</b>",
            body,
        ))
    else:
        margin = inp.ppa_rate_to_customer - out.lcoe
        story.append(Paragraph(
            f"PPA rate charged to customer: <b>${inp.ppa_rate_to_customer:.4f}/kWh</b><br/>"
            f"Project LCOE: <b>${out.lcoe:.4f}/kWh</b><br/>"
            f"PPA margin over LCOE: <b>{margin*100:.2f}¢/kWh</b><br/>"
            f"Customer's PPA discount vs ${inp.customer_current_rate:.4f}/kWh utility rate: "
            f"<b>{(inp.customer_current_rate - inp.ppa_rate_to_customer)/inp.customer_current_rate*100:.1f}%</b>",
            body,
        ))
    story.append(Spacer(1, 8))

    # Warnings (if any)
    if out.warnings:
        story.append(Paragraph("Sanity Warnings", h1))
        for w in out.warnings[:8]:
            story.append(Paragraph(f"&bull; {w}", body))
        story.append(Spacer(1, 4))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
