# Secure Maritime Project Finance Engine

Hello everyone, this is a deterministic project-finance underwriting model I made for a hypothetical **$2.5bn secure deepwater maritime logistics hub**.

The model treats the asset like a real credit-sizing problem, namely construction funding first, then operating CFADS, senior debt service, the mezzanine PIK mechanics, covenant testing, and then sponsor distributions. It avoids stochastic noise because this kind of first-pass underwriting usually starts with a deterministic case pack before anyone gets cute with Monte Carlo!!! (important to note).

## The transaction context

| Item | Assumption |
|---|---:|
| Asset | Secure Deepwater Maritime Logistics Hub |
| Total CAPEX | $2.5bn |
| Construction period | Years 1-3 |
| Operating period | Years 4-23 |
| Year 4 revenue | $375.0m |
| Revenue escalation | 2.5% per year |
| Base OPEX | 35.0% of revenue |
| Senior debt tenor | 15-year straight-line amortization |
| Senior debt coupon | 5.0% fixed |
| DSCR sizing floor | 1.30x |
| Mezzanine debt | 15.0% of CAPEX |
| Mezzanine coupon | 7.5%, PIK when cash chokes |
| First-loss guarantee | 10.0% of senior debt in the protected stress case |

## What my model does

The engine sizes senior debt off the binding DSCR year, then pushes the same capital stack through three deterministic cases:

1. **Base Case**: normal operating ramp, senior debt sized against the 1.30x DSCR covenant floor.
2. **Supply Chain Margin Compression Shock**: Years 6-9 take a 25% revenue hit and OPEX jumps to 45% of revenue.
3. **First-Loss Multilateral Guarantee Frame**: same stress case, but a 10% first-loss support pool covers senior debt service shortfalls and lowers the senior risk spread.

The output is a terminal report with annual construction draws, operating cash flow, debt service, PIK accretion, DSCR, LLCR, overcollateralization ratio, guarantee draws, and breach logs.

## Layout of my work

```text
TransactionConfig
    |
    v
OperatingCaseBuilder
    |---- base revenue / OPEX / CFADS curve
    |---- stress revenue and margin overrides
    |
    v
SeniorDebtSizer
    |---- iterative DSCR sizing solver
    |---- annual DSCR and LLCR vector
    |
    v
ProjectFinanceWaterfall
    |---- construction funding ledger
    |---- senior interest / principal
    |---- mezzanine interest / PIK / final repayment
    |---- first-loss guarantee draw logic
    |---- sponsor equity dividends
    |
    v
ScenarioRunner + TerminalReport
    |---- Base Case
    |---- Margin Compression Shock
    |---- First-Loss Guarantee Frame
```

## The main model logic

### Senior debt sizing

Senior debt is sized so the minimum annual DSCR over the amortization period stays at or above 1.30x:

```text
DSCR_t = CFADS_t / (Senior Interest_t + Senior Principal_t)
```

The solver uses bisection. It keeps increasing senior principal until the binding year just touches the covenant floor. That is closer to how debt capacity is usually backed into in a project finance model.

### LLCR

LLCR is calculated each operating year while senior debt is outstanding:

```text
LLCR_t = NPV(remaining CFADS through senior maturity, discounted at senior debt rate)
         / senior opening balance_t
```

DSCR tells you if the year can pay, and LLCR tells you whether the remaining loan life still has enough cash depth.

### Waterfall

The annual operating waterfall is strict:

```text
Revenue
- OPEX
= CFADS
- maintenance capex
- working capital reserve
= cash available after Tier 1
- senior interest
- senior principal
- mezzanine interest, or PIK if cash is short
- mezzanine final repayment in Year 23
= sponsor equity dividend
```

If the guarantee case is active, the support pool is drawn only when available cash cannot fully cover senior debt service. It does not rescue mezzanine or equity.

## Repo layout

```text
secure_maritime_project_finance_engine/
├── README.md
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── docs/
│   ├── model_framework.md
│   └── transaction_notes.md
├── examples/
│   └── run_project_finance.py
├── outputs/
│   └── sample_terminal_report.txt
├── src/
│   ├── __init__.py
│   └── project_finance_engine.py
└── tests/
    └── test_project_finance_engine.py
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## How to run the model

```bash
python examples/run_project_finance.py
```

Or run the source file directly:

```bash
python src/project_finance_engine.py
```

## Run tests

```bash
pytest
```

The tests check senior debt sizing, base-case senior repayment, stress-case covenant breaches, and the first-loss guarantee mechanics.

## Notes on scope of my work

This is a deterministic underwriting engine. It is not trying to be a live bank model, and it does not pull market data! The point is to make the credit math explicit in how much senior debt fits, where the stress breaks and how PIK moves risk down the stack, and what a first-loss support layer actually changes. Enjoy!
