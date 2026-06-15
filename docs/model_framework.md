# Model Framework

This note lays out the math behind the deterministic underwriting engine. The model is deliberately mechanical: one asset, fixed transaction assumptions, three cases, and a hard covenant test.

## 1. Timeline

The horizon is 23 years.

- Years 1-3: construction
- Years 4-23: operations
- Years 4-18: senior debt amortization
- Year 23: final mezzanine bullet repayment if cash is available

Let \(t\) denote the model year.

## 2. CAPEX draw schedule

Total project cost is:

\[
C = 2{,}500{,}000{,}000
\]

Construction draw weights are:

\[
w_1 = 30\%, \quad w_2 = 40\%, \quad w_3 = 30\%
\]

Annual CAPEX outlay is:

\[
CAPEX_t = C \cdot w_t, \quad t \in \{1,2,3\}
\]

The capital stack is funded pro-rata during construction:

\[
SeniorDraw_t = SeniorCommitment \cdot w_t
\]

\[
MezzDraw_t = MezzCommitment \cdot w_t
\]

\[
EquityDraw_t = EquityCommitment \cdot w_t
\]

## 3. Revenue, OPEX, and CFADS

Revenue starts in Year 4 at \(R_4 = 375m\) and escalates by 2.5% per year:

\[
R_t = R_4(1+g)^{t-4}
\]

where:

\[
g = 2.5\%
\]

Base-case OPEX is 35% of revenue:

\[
OPEX_t = 0.35R_t
\]

Cash Flow Available for Debt Service is:

\[
CFADS_t = R_t - OPEX_t
\]

The model also deducts maintenance capex and a working capital reserve before cash flows through the operating waterfall:

\[
Tier1Reserve_t = MaintenanceCapex_t + WorkingCapitalReserve_t
\]

\[
CashAfterTier1_t = CFADS_t - Tier1Reserve_t
\]

This keeps covenant CFADS and actual waterfall cash separate. That matters because DSCR is usually measured on CFADS, but the cash account still has to survive real priority deductions.

## 4. Senior debt sizing

The senior facility amortizes straight-line over 15 years from Year 4 through Year 18.

If \(D_S\) is the senior commitment, annual scheduled principal is:

\[
P = \frac{D_S}{15}
\]

Opening senior balance in amortization year \(k\) is:

\[
B_k = D_S - (k-1)P
\]

Senior interest is:

\[
I_k = r_S B_k
\]

Senior debt service is:

\[
DS_k = I_k + P
\]

The sizing constraint is:

\[
\min_{k \in \{4,\dots,18\}} \frac{CFADS_k}{DS_k} \geq 1.30x
\]

The code solves this by bisection. For each trial debt amount, it computes the full DSCR vector and moves the debt balance up or down until the binding year is basically at the floor.

## 5. LLCR

Loan Life Coverage Ratio is calculated while the senior facility is outstanding:

\[
LLCR_t = \frac{\sum_{j=t}^{18} \frac{CFADS_j}{(1+r_S)^{j-t+1}}}{SeniorOpeningBalance_t}
\]

DSCR is the annual covenant. LLCR is the remaining cash depth behind the loan.

## 6. Mezzanine PIK mechanics

Mezzanine debt is 15% of CAPEX:

\[
D_M = 0.15C = 375m
\]

The mezzanine coupon is 7.5%:

\[
MezzInterest_t = r_M \cdot MezzOpeningBalance_t
\]

If cash after senior debt service cannot pay mezzanine interest, the unpaid amount is capitalized:

\[
PIK_t = \max(0, MezzInterest_t - MezzCashPaid_t)
\]

\[
MezzEndingBalance_t = MezzOpeningBalance_t + PIK_t - MezzPrincipalPaid_t
\]

Mezzanine principal is not amortized annually. It is repaid in Year 23 only if the cash waterfall has enough residual cash.

## 7. First-loss guarantee

In the protected stress case, the model adds a first-loss guarantee equal to 10% of senior debt:

\[
G_0 = 0.10D_S
\]

If cash after Tier 1 cannot cover senior debt service, the guarantee pool is drawn:

\[
GuaranteeDraw_t = \min(G_{t-1}, \max(0, SeniorDebtService_t - CashAfterTier1_t))
\]

Remaining guarantee capacity is:

\[
G_t = G_{t-1} - GuaranteeDraw_t
\]

A senior technical default is logged only if senior debt service is still unpaid after guarantee support.

## 8. WACC

The model reports a transaction WACC using capital stack weights:

\[
WACC = w_S r_S + w_M r_M^* + w_E r_E
\]

where:

- \(w_S\), \(w_M\), and \(w_E\) are senior, mezzanine, and equity weights
- \(r_S\) is the senior coupon after any guarantee spread adjustment
- \(r_M^*\) is realized mezzanine IRR if computable, otherwise the mezzanine coupon
- \(r_E\) is the sponsor target return assumption

For the guarantee case, the senior spread is reduced by 50%:

\[
r_{S,guaranteed} = r_f + Spread_S(1-50\%)
\]

That is not a market quote. It is a deterministic credit enhancement assumption so the effect of structural support is visible.

## 9. Stress case

The supply chain compression case applies during Years 6-9:

\[
R_t^{stress} = 0.75R_t
\]

\[
OPEX_t^{stress} = 0.45R_t^{stress}
\]

The same senior debt amount is used. That is intentional. The point is not to resize the deal under stress, but to see how the underwritten capital stack behaves after the shock hits.
