# Alberta Income Tax Tools (FastAPI)

Overview

This application helps users estimate their personal income tax in Alberta and understand when it makes sense to claim RRSP deductions. It provides an easy-to-use web interface where users can input their income and deduction details to see estimated federal and provincial tax, take-home income, and marginal tax rates.

The RRSP optimizer is useful for people whose income changes from year to year and want to explore whether claiming RRSP deductions now, later, or partially can lead to better after-tax outcomes. The tool compares different strategies and presents the results visually and in a downloadable PDF summary.

This project is intended for students, early-career professionals, and anyone interested in learning how Canadian income tax and RRSP deductions work. It is designed for educational and planning insight only and does not provide tax or financial advice.

Web-based tools (FastAPI + Jinja2) to estimate 2024 Federal + Alberta personal income tax and explore RRSP deduction timing strategies.

This is an educational tool only and not tax or financial advice.

## Requirements

- Python 3.10+ installed
- The following Python packages (installed via `requirements.txt`):
  - `fastapi`
  - `uvicorn`
  - `pydantic`
  - `jinja2`
  - `reportlab`

## Setup

From `c:\Users\rpara\OneDrive\Documents\TaxApp`:

1. (Optional) Create a virtual environment:
   - PowerShell: `python -m venv .venv`
2. Activate the virtual environment:
   - PowerShell: `.\.venv\Scripts\Activate.ps1`
3. Install dependencies:
   - `pip install -r requirements.txt`

## Running the app

With your virtual environment activated and from the `TaxApp` folder:

```bash
uvicorn tax_app:app --reload
```

Then open your browser at `http://127.0.0.1:8000/tax-estimator` or just visit `http://127.0.0.1:8000` (which redirects to the tax estimator).

### Tax estimator

- Enter:
  - Employment income (T4)
  - Other taxable income
  - RRSP contributions
  - Other deductions
- The page shows estimated federal and Alberta tax, total tax, net income, and average/marginal tax rates.

### RRSP deduction optimizer

- Go to `http://127.0.0.1:8000/rrsp-optimizer`.
- Enter:
  - Current year taxable income
  - Next year expected taxable income
  - RRSP deduction amount to allocate
  - Expected annual investment return (%)
- You’ll see:
  - A comparison table for:
    - Saving the deduction
    - Claiming it fully this year
    - (If beneficial) an optimized partial-claim strategy
  - A line chart showing **advantage vs. deduction this year**, with the peak at the optimized split.
  - A link to download a simple PDF summary of the recommended strategy.
