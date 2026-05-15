# Rate Guard

Enforces the **Allow Rate** role across all ERPNext doctypes, reports, and APIs.

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

---

## Customising which fields are protected

Edit `rate_guard/overrides.py`:

- `FINANCIAL_FIELDTYPES` — add fieldtypes to always hide
- `FINANCIAL_FLOAT_KEYWORDS` — add keywords for Float field names/labels
- `ALWAYS_VISIBLE` — add fieldnames that should never be hidden

---

## Uninstalling

```bash
bench --site erp.qcstyro.local uninstall-app rate_guard
bench restart
```
