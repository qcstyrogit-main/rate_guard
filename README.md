# Rate Guard

Enforces the **Allow Rate** role across ERPNext doctypes, reports, and APIs,
except for configured regular transaction doctypes.

Users **without** the `Allow Rate` role will receive blank / None values for all
Currency, Percent, and financial Float fields — server-side, before data reaches
the browser. No F12 bypass is possible.

---

## What it protects

| Field Type | Hidden for non-Allow Rate |
|---|---|
| Currency | ✅ Always |
| Percent | ✅ Always |
| Float (rate/amount/price/cost/value/total/…) | ✅ Yes |
| Float (qty/stock_qty/actual_qty/…) | ❌ No — quantities remain visible |
| Int, Data, Link, etc. | ❌ No |

## Coverage

| Area | Protected |
|---|---|
| Form view | ✅ |
| REST API (`/api/resource/…`) | ✅ |
| Query Reports | ✅ |
| Script Reports | ✅ |
| Report Summary cards | ✅ |
| Report Charts | ✅ |
| Print Format | ✅ (loads document normally) |
| Prepared Reports | ✅ (re-runs through override) |

---

## Installation

```bash
# 1. Copy app to your bench
cp -r rate_guard /home/qcmc_admin/frappe-bench/apps/

# 2. Install into bench
cd /home/qcmc_admin/frappe-bench
bench install-app rate_guard

# 3. Install into your site
bench --site erp.qcstyro.local install-app rate_guard

# 4. Run migrate
bench --site erp.qcstyro.local migrate

# 5. Restart
bench restart
```

## Assigning Allow Rate role

Go to **ERPNext → User → (select user) → Roles** and add **Allow Rate**.

Users with this role see all figures normally.
Users without this role see blank for all financial fields.

## Excluded regular transactions

These doctypes are not protected by Rate Guard, so users can view the normal
transaction values:

- Sales Order
- Sales Order Item
- Purchase Receipt
- Purchase Receipt Item
- Purchase Order
- Purchase Order Item
- Sales Invoice
- Sales Invoice Item
- Purchase Invoice
- Purchase Invoice Item

## Excluded reports

These reports are not protected by Rate Guard. Edit `EXCLUDED_REPORTS` in
`rate_guard/overrides.py` to add or remove report names:

- Sales Register
- Purchase Register
- Sales Order Analysis
- Purchase Order Analysis
- Sales Order Trends
- Purchase Order Trends
- Sales Invoice Trends
- Purchase Invoice Trends
- Item-wise Sales Register
- Item-wise Purchase Register
- Ordered Items To Be Delivered
- Delivered Items To Be Billed
- Received Items To Be Billed

---

## Customising which fields are protected

Edit `rate_guard/overrides.py`:

- `FINANCIAL_FIELDTYPES` — add fieldtypes to always hide
- `FINANCIAL_FLOAT_KEYWORDS` — add keywords for Float field names/labels
- `ALWAYS_VISIBLE` — add fieldnames that should never be hidden
- `EXCLUDED_DOCTYPES` — add doctypes where Rate Guard should not apply
- `EXCLUDED_REPORTS` — add reports where Rate Guard should not apply

---

## Uninstalling

```bash
bench --site erp.qcstyro.local uninstall-app rate_guard
bench restart
```
