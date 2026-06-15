# Transaction Notes

## Asset profile

The modeled asset is a secure deepwater maritime logistics hub. The revenue base is meant to resemble long-term contracted throughput, port-adjacent logistics fees, secure warehousing, berth access, maintenance services, and resilience-linked capacity payments.

The project is not modeled as a merchant port. It has a strategic infrastructure profile, so the main credit questions are more like:

- how much senior debt can the operating cash flow actually carry
- how exposed the structure is to margin compression
- how much mezzanine interest turns into PIK when senior lenders get paid first
- whether a first-loss support layer changes the senior credit outcome enough to matter

## Capital structure

The model has three funding layers:

1. **Senior commercial bank debt**
   - sized to a 1.30x DSCR floor
   - 15-year straight-line amortization
   - fixed coupon
   - protected first in the operating waterfall

2. **Mezzanine multilateral debt**
   - fixed at 15% of total CAPEX
   - subordinated to senior debt
   - interest can PIK when cash is tight
   - final principal repayment in Year 23 if the waterfall has enough cash

3. **Sponsor equity**
   - absorbs the residual funding need
   - receives only the final excess spread after senior and mezzanine debt service

## Why the stress is built this way

The downside case hits both revenue and operating margin. That is worse than just a volume shock because the asset loses top-line cash while also becoming more expensive to operate. For a logistics hub, that can happen if regional shipping patterns break, insurance costs rise, labor and security expenses spike, or supply chain rerouting lowers throughput.

The model keeps the shock in Years 6-9. That timing is deliberately uncomfortable: the project is already operating, but senior debt is still large, so the DSCR math can break before the capital stack has had time to de-risk.

## Guarantee layer

The first-loss guarantee is not treated like free money. It is a finite pool equal to 10% of senior debt. It can only be used to protect senior debt service. It cannot pay mezzanine interest, repay mezzanine principal, or support sponsor dividends.

That distinction matters. A guarantee can keep senior lenders whole while still leaving the junior capital structure impaired. The model shows that split directly through senior shortfalls, mezzanine PIK, and equity dividend compression.

## Main outputs

The terminal report prints:

- annual construction funding ledger
- operating cash flow waterfall
- senior and mezzanine debt balances
- DSCR and LLCR path
- overcollateralization ratio
- guarantee draw schedule
- sponsor equity IRR
- mezzanine realized yield
- WACC
- covenant breach log

The breach log is intentionally plain. If DSCR breaks, it says when. If senior cash is short after guarantee support, it logs the technical default. No vague risk language needed.
