import io
import json
import math
from typing import List

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


# 2024 Federal tax parameters (Canada-wide)
FEDERAL_2024_BRACKETS = [
    (0.0, 55_867.0, 0.15),
    (55_867.0, 111_733.0, 0.205),
    (111_733.0, 173_205.0, 0.26),
    (173_205.0, 246_752.0, 0.29),
    (246_752.0, math.inf, 0.33),
]
FEDERAL_2024_BASIC_PERSONAL = 15_705.0
FEDERAL_2024_LOWEST_RATE = 0.15

# 2024 Alberta provincial tax parameters
ALBERTA_2024_BRACKETS = [
    (0.0, 148_269.0, 0.10),
    (148_269.0, 177_922.0, 0.12),
    (177_922.0, 237_230.0, 0.13),
    (237_230.0, 355_845.0, 0.14),
    (355_845.0, math.inf, 0.15),
]
ALBERTA_2024_BASIC_PERSONAL = 21_885.0
ALBERTA_2024_LOWEST_RATE = 0.10


class TaxBreakdown(BaseModel):
    taxable_income: float
    federal_tax: float
    alberta_tax: float
    total_tax: float
    net_after_tax: float
    average_rate_percent: float
    combined_marginal_rate_percent: float


class RRSPOptimizationResult(BaseModel):
    deduct_now: float
    deduct_next: float
    savings_year0: float
    savings_year1: float
    end_value: float
    advantage_vs_save: float


def tax_from_brackets(taxable_income: float, brackets) -> float:
    """Compute tax using marginal rate brackets."""
    if taxable_income <= 0:
        return 0.0

    tax = 0.0
    for lower, upper, rate in brackets:
        if taxable_income <= lower:
            break
        amount_in_bracket = min(taxable_income, upper) - lower
        if amount_in_bracket > 0:
            tax += amount_in_bracket * rate
    return tax


def marginal_rate(taxable_income: float, brackets) -> float:
    """Return marginal tax rate (as a fraction) for a given income."""
    if taxable_income <= 0:
        return 0.0
    for lower, upper, rate in brackets:
        if lower < taxable_income <= upper:
            return rate
    # If income exceeds the last finite bracket, use the last rate
    return brackets[-1][2]


def compute_tax_breakdown(gross_income: float, total_deductions: float) -> TaxBreakdown:
    """Return a breakdown of tax and net income for a given income and deductions."""
    taxable_income = max(0.0, gross_income - total_deductions)

    federal_before_credits = tax_from_brackets(
        taxable_income, FEDERAL_2024_BRACKETS
    )
    federal_bpa_credit = FEDERAL_2024_BASIC_PERSONAL * FEDERAL_2024_LOWEST_RATE
    federal_tax = max(0.0, federal_before_credits - federal_bpa_credit)

    alberta_before_credits = tax_from_brackets(
        taxable_income, ALBERTA_2024_BRACKETS
    )
    alberta_bpa_credit = ALBERTA_2024_BASIC_PERSONAL * ALBERTA_2024_LOWEST_RATE
    alberta_tax = max(0.0, alberta_before_credits - alberta_bpa_credit)

    total_tax = federal_tax + alberta_tax
    net_after_tax = gross_income - total_tax

    avg_rate_percent = (total_tax / gross_income * 100.0) if gross_income > 0 else 0.0
    combined_marginal_rate_percent = (
        marginal_rate(taxable_income, FEDERAL_2024_BRACKETS)
        + marginal_rate(taxable_income, ALBERTA_2024_BRACKETS)
    ) * 100.0

    return TaxBreakdown(
        taxable_income=taxable_income,
        federal_tax=federal_tax,
        alberta_tax=alberta_tax,
        total_tax=total_tax,
        net_after_tax=net_after_tax,
        average_rate_percent=avg_rate_percent,
        combined_marginal_rate_percent=combined_marginal_rate_percent,
    )


def optimize_rrsp_split(
    current_income: float,
    next_income: float,
    rrsp_amount: float,
    expected_return_percent: float,
    steps: int = 100,
) -> tuple[RRSPOptimizationResult, List[RRSPOptimizationResult]]:
    """Return best RRSP deduction split and all evaluated points."""
    r = expected_return_percent / 100.0

    base_tax_year0 = compute_tax_breakdown(current_income, 0.0).total_tax
    base_tax_year1 = compute_tax_breakdown(next_income, 0.0).total_tax

    def evaluate_scenario(deduct_now: float) -> RRSPOptimizationResult:
        deduct_now = max(0.0, min(deduct_now, rrsp_amount))
        deduct_next = rrsp_amount - deduct_now

        tax_year0 = compute_tax_breakdown(current_income, deduct_now).total_tax
        tax_year1 = compute_tax_breakdown(next_income, deduct_next).total_tax

        savings_year0 = base_tax_year0 - tax_year0
        savings_year1 = base_tax_year1 - tax_year1

        end_value = savings_year0 * (1.0 + r) + savings_year1
        # advantage_vs_save is filled after baseline is known
        return RRSPOptimizationResult(
            deduct_now=deduct_now,
            deduct_next=deduct_next,
            savings_year0=savings_year0,
            savings_year1=savings_year1,
            end_value=end_value,
            advantage_vs_save=0.0,
        )

    save_deduction = evaluate_scenario(0.0)

    best: RRSPOptimizationResult | None = None
    points: List[RRSPOptimizationResult] = []

    if rrsp_amount > 0:
        for i in range(steps + 1):
            d0 = rrsp_amount * i / steps
            scenario = evaluate_scenario(d0)
            points.append(scenario)
            if best is None or scenario.end_value > best.end_value + 1e-6:
                best = scenario
    else:
        best = save_deduction
        points.append(save_deduction)

    baseline_value = save_deduction.end_value
    for scenario in points:
        scenario.advantage_vs_save = scenario.end_value - baseline_value

    return best, points


app = FastAPI(title="Alberta Tax Tools")
templates = Jinja2Templates(directory="templates")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/tax-estimator", status_code=307)


@app.get("/tax-estimator", response_class=HTMLResponse)
async def tax_estimator(
    request: Request,
    employment_income: float = Query(60_000.0, ge=0.0),
    other_income: float = Query(0.0, ge=0.0),
    rrsp: float = Query(5_000.0, ge=0.0),
    other_deductions: float = Query(0.0, ge=0.0),
) -> HTMLResponse:
    gross_income = employment_income + other_income
    total_deductions = rrsp + other_deductions

    breakdown = compute_tax_breakdown(gross_income, total_deductions)
    net_after_tax_and_deductions = breakdown.net_after_tax - total_deductions

    context = {
        "request": request,
        "employment_income": employment_income,
        "other_income": other_income,
        "rrsp": rrsp,
        "other_deductions": other_deductions,
        "gross_income": gross_income,
        "total_deductions": total_deductions,
        "breakdown": breakdown,
        "net_after_tax_and_deductions": net_after_tax_and_deductions,
    }
    return templates.TemplateResponse("tax_estimator.html", context)


@app.get("/rrsp-optimizer", response_class=HTMLResponse)
async def rrsp_optimizer(
    request: Request,
    current_income: float = Query(75_000.0, ge=0.0),
    next_income: float = Query(90_000.0, ge=0.0),
    rrsp_amount: float = Query(10_000.0, ge=0.0),
    expected_return_percent: float = Query(5.0, ge=0.0, le=30.0),
) -> HTMLResponse:
    has_valid_inputs = (
        current_income > 0 and next_income > 0 and rrsp_amount > 0
    )

    best = None
    save_deduction = None
    rows_display = []
    x_values: list[float] = []
    y_values: list[float] = []

    if has_valid_inputs:
        best, points = optimize_rrsp_split(
            current_income=current_income,
            next_income=next_income,
            rrsp_amount=rrsp_amount,
            expected_return_percent=expected_return_percent,
        )

        # Baseline is the "save the deduction" point (deduct_now = 0)
        save_deduction = next(
            (p for p in points if abs(p.deduct_now) < 1e-6),
            None,
        )
        if save_deduction is None:
            save_deduction = points[0]

        claim_now = next(
            (
                p
                for p in points
                if abs(p.deduct_now - rrsp_amount) < rrsp_amount / 100.0 + 1e-6
            ),
            None,
        )
        if claim_now is None:
            claim_now = points[-1]

        def row_dict(name: str, scenario: RRSPOptimizationResult) -> dict:
            return {
                "name": name,
                "deduct_now": f"${scenario.deduct_now:,.2f}",
                "deduct_next": f"${scenario.deduct_next:,.2f}",
                "savings_year0": f"${scenario.savings_year0:,.2f}",
                "savings_year1": f"${scenario.savings_year1:,.2f}",
                "end_value": f"${scenario.end_value:,.2f}",
                "advantage": f"${scenario.advantage_vs_save:,.2f}",
            }

        rows_display.append(
            row_dict("Save the deduction for next year", save_deduction)
        )
        rows_display.append(
            row_dict("Claim full deduction this year", claim_now)
        )

        is_distinct_from_endpoints = (
            abs(best.deduct_now - save_deduction.deduct_now) > 1e-2
            and abs(best.deduct_now - claim_now.deduct_now) > 1e-2
        )
        if is_distinct_from_endpoints:
            rows_display.append(
                row_dict("Optimized partial claim", best)
            )

        x_values = [p.deduct_now for p in points]
        y_values = [p.advantage_vs_save for p in points]

    context = {
        "request": request,
        "current_income": current_income,
        "next_income": next_income,
        "rrsp_amount": rrsp_amount,
        "expected_return_percent": expected_return_percent,
        "has_valid_inputs": has_valid_inputs,
        "rows": rows_display,
        "best": best,
        "save_deduction": save_deduction,
        "x_values_json": json.dumps(x_values),
        "y_values_json": json.dumps(y_values),
    }

    return templates.TemplateResponse("rrsp_optimizer.html", context)


@app.get("/api/tax-breakdown", response_model=TaxBreakdown)
async def api_tax_breakdown(
    employment_income: float = Query(60_000.0, ge=0.0),
    other_income: float = Query(0.0, ge=0.0),
    rrsp: float = Query(5_000.0, ge=0.0),
    other_deductions: float = Query(0.0, ge=0.0),
) -> TaxBreakdown:
    gross_income = employment_income + other_income
    total_deductions = rrsp + other_deductions
    return compute_tax_breakdown(gross_income, total_deductions)


@app.get("/api/rrsp-optimizer", response_model=RRSPOptimizationResult)
async def api_rrsp_optimizer(
    current_income: float = Query(75_000.0, ge=0.0),
    next_income: float = Query(90_000.0, ge=0.0),
    rrsp_amount: float = Query(10_000.0, ge=0.0),
    expected_return_percent: float = Query(5.0, ge=0.0, le=30.0),
) -> RRSPOptimizationResult:
    best, _ = optimize_rrsp_split(
        current_income=current_income,
        next_income=next_income,
        rrsp_amount=rrsp_amount,
        expected_return_percent=expected_return_percent,
    )
    return best


@app.get("/rrsp-optimizer/report.pdf")
async def rrsp_report_pdf(
    current_income: float = Query(75_000.0, ge=0.0),
    next_income: float = Query(90_000.0, ge=0.0),
    rrsp_amount: float = Query(10_000.0, ge=0.0),
    expected_return_percent: float = Query(5.0, ge=0.0, le=30.0),
) -> StreamingResponse:
    best, _ = optimize_rrsp_split(
        current_income=current_income,
        next_income=next_income,
        rrsp_amount=rrsp_amount,
        expected_return_percent=expected_return_percent,
    )

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    y = height - 72
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(72, y, "RRSP Deduction Strategy Report")
    pdf.setFont("Helvetica", 11)
    y -= 32

    pdf.drawString(
        72,
        y,
        f"Current year taxable income: ${current_income:,.2f}",
    )
    y -= 16
    pdf.drawString(
        72,
        y,
        f"Next year expected taxable income: ${next_income:,.2f}",
    )
    y -= 16
    pdf.drawString(
        72,
        y,
        f"RRSP deduction amount: ${rrsp_amount:,.2f}",
    )
    y -= 16
    pdf.drawString(
        72,
        y,
        f"Expected annual investment return: {expected_return_percent:.2f}%",
    )

    y -= 32
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(72, y, "Recommended allocation")
    pdf.setFont("Helvetica", 11)
    y -= 18
    pdf.drawString(
        72,
        y,
        f"Deduct this year: ${best.deduct_now:,.2f}",
    )
    y -= 16
    pdf.drawString(
        72,
        y,
        f"Deduct next year: ${best.deduct_next:,.2f}",
    )
    y -= 16
    pdf.drawString(
        72,
        y,
        f"Tax savings this year (invested): ${best.savings_year0:,.2f}",
    )
    y -= 16
    pdf.drawString(
        72,
        y,
        f"Tax savings next year: ${best.savings_year1:,.2f}",
    )
    y -= 16
    pdf.drawString(
        72,
        y,
        f"Value at end of next year: ${best.end_value:,.2f}",
    )
    y -= 16
    pdf.drawString(
        72,
        y,
        f"Advantage vs saving deduction: ${best.advantage_vs_save:,.2f}",
    )

    y -= 32
    pdf.setFont("Helvetica-Oblique", 9)
    pdf.drawString(
        72,
        y,
        "Notes: This report is an educational estimate only and not financial advice.",
    )

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    headers = {
        "Content-Disposition": 'inline; filename="rrsp_strategy_report.pdf"'
    }
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)


if __name__ == "__main__":
    # For local debugging (uvicorn is the recommended entry point)
    import uvicorn

    uvicorn.run("tax_app:app", host="127.0.0.1", port=8000, reload=True)

