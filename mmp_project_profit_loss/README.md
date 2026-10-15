# MMP Project Profit & Loss

Actual project profitability for Odoo 17 Community, calculated only from posted
`account.move.line` records and their `analytic_distribution`.

## Installation

1. Add this repository's `addons` directory to `addons_path`.
2. Update the Apps list and install **MMP Project Profit & Loss**.
3. Assign **Project Financial Reporting / Project Financial Viewer** only to users allowed to see
   project financial data.
4. Set one unique analytic account on each project.

No accounting entries are created or changed by this module.

## Accounting rules

- Revenue: `income` and `income_other`; displayed as `-allocated balance`.
- Direct Costs: `expense_direct_cost`.
- Operating Expenses: `expense` and `expense_depreciation`.
- Gross Profit: Revenue minus Direct Costs.
- Net Profit/Loss: Revenue plus Other Income minus all costs.
- Company-currency `balance` is used. Signed refunds, adjustments, and reversals
  therefore reduce or increase results naturally.
- Only posted entries with a positive, valid analytic percentage are included.
- Combined analytic keys such as `"12,34"` are split and the percentage is
  applied once to each matching project's analytic account.
- Projects sharing an analytic account inside one company are excluded and
  shown with a configuration warning. The journal item itself cannot identify
  which of those projects owns the result.

## Performance and security

Detail data is exposed by a read-only PostgreSQL view. Project cards use one
batch `_read_group` query rather than querying each project separately. Values
are intentionally non-stored so posted-entry changes are reflected immediately.

The dedicated viewer group, model ACL, allowed-company record rule, field group
restrictions, and server-side checks protect reports and exports. Opening the
source journal item still requires the user's normal Accounting read access.

## Known limitations

- Classification is limited to standard Odoo account types. A chart of accounts
  cannot distinguish operating from non-operating expense beyond those types.
- Margin is N/A when revenue is zero or negative.
- Shared analytic accounts must be separated before the project values can be
  attributed without ambiguity.
- The included XLSX exporter uses Odoo's bundled `xlsxwriter`; OCA
  `report_xlsx` is not required.
