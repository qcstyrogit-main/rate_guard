"""
rate_guard.overrides
====================
Enforces the "Allow Rate" role across:
  - All DocType form loads        (doc_events onload)
  - All Query / Script Reports    (override_whitelisted_methods)
  - Report Summaries              (stripped from report response)

Users WITHOUT the "Allow Rate" role will receive None / blank for every
field that is classified as a financial figure.  The data is stripped
server-side — it never travels to the browser.

Administrator always bypasses the restriction.
"""

import frappe

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Field types that are always treated as financial
FINANCIAL_FIELDTYPES = frozenset(["Currency", "Percent"])

# For Float fields, only hide if the fieldname / label contains one of these
FINANCIAL_FLOAT_KEYWORDS = frozenset([
    "rate", "amount", "price", "cost", "value", "total",
    "pay", "paid", "salary", "wage", "charge", "fee",
    "tax", "discount", "margin", "exchange", "commission",
    "interest", "premium", "rebate", "billing", "costing",
    "overhead", "grand", "net", "gross", "outstanding",
    "valuation", "incoming_rate", "outgoing_rate", "hour_rate",
    "base_rate", "base_amount", "base_total", "base_net",
    "base_grand", "plc_conversion",
])

# Float fields that look financial but should ALWAYS remain visible
# (quantities, progress counters, etc.)
ALWAYS_VISIBLE = frozenset([
    "qty", "stock_qty", "ordered_qty", "billed_qty",
    "received_qty", "delivered_qty", "actual_qty",
    "projected_qty", "reserved_qty", "transfer_qty",
    "conversion_factor", "uom_conversion_factor",
    "idx", "docstatus", "progress", "percent_complete",
    "latitude", "longitude",
])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def has_allow_rate() -> bool:
    """Return True if the current user is allowed to see financial figures."""
    user = frappe.session.user
    if user == "Administrator":
        return True
    if user == "Guest":
        return False
    return frappe.has_role("Allow Rate")


def _is_financial_field(field) -> bool:
    """Return True if the field should be hidden from non-Allow-Rate users."""
    ft = field.fieldtype

    # Always hide Currency and Percent
    if ft in FINANCIAL_FIELDTYPES:
        return True

    if ft == "Float":
        fn = (field.fieldname or "").lower()
        lb = (field.label or "").lower()

        # Never hide quantity / location / non-financial floats
        if fn in ALWAYS_VISIBLE:
            return False

        # Hide if the name or label suggests a monetary / rate value
        for kw in FINANCIAL_FLOAT_KEYWORDS:
            if kw in fn or kw in lb:
                return True

    return False


def _is_financial_column(col) -> bool:
    """
    Return True if a report column is financial.
    col may be a dict or a colon-delimited string such as
    "fieldname:fieldtype:Label:width".
    """
    if isinstance(col, dict):
        ft = col.get("fieldtype", "") or ""
        fn = (col.get("fieldname") or col.get("key") or "").lower()
        lb = (col.get("label") or "").lower()
    elif isinstance(col, str):
        parts = col.split(":")
        ft = parts[1].strip() if len(parts) > 1 else ""
        fn = parts[0].strip().lower()
        lb = parts[2].strip().lower() if len(parts) > 2 else ""
    else:
        return False

    if ft in FINANCIAL_FIELDTYPES:
        return True

    if ft == "Float":
        if fn in ALWAYS_VISIBLE:
            return False
        for kw in FINANCIAL_FLOAT_KEYWORDS:
            if kw in fn or kw in lb:
                return True

    return False


def _get_col_fieldname(col):
    """Extract fieldname / key from a column definition."""
    if isinstance(col, dict):
        return col.get("fieldname") or col.get("key")
    if isinstance(col, str):
        return col.split(":")[0].strip()
    return None


# ---------------------------------------------------------------------------
# Doc Event — hides fields on every document load
# ---------------------------------------------------------------------------

def hide_rates_on_load(doc, method=None):
    """
    Called via doc_events → "*" → onload.
    Strips financial field values from the document before it is
    serialised and sent to the client.
    """
    try:
        if has_allow_rate():
            return

        meta = frappe.get_meta(doc.doctype)
        for field in meta.fields:
            if _is_financial_field(field):
                doc.set(field.fieldname, "*****")

    except Exception:
        # Never break a document load — fail silently
        pass


# ---------------------------------------------------------------------------
# Report Override — masks numeric columns in query / script report results
# ---------------------------------------------------------------------------

def run_report_override(
    report_name,
    filters=None,
    user=None,
    ignore_prepared_report=False,
    are_default_filters=True,
    start=0,
    add_total_row=None,
    custom_columns=None,
    is_tree=False,
    parent_field=None,
):
    """
    Replacement for frappe.desk.query_report.run
    Calls the original, then strips financial columns for unauthorised users.
    """
    from frappe.desk.query_report import run as _original_run

    result = _original_run(
        report_name=report_name,
        filters=filters,
        user=user,
        ignore_prepared_report=ignore_prepared_report,
        are_default_filters=are_default_filters,
        start=start,
        add_total_row=add_total_row,
        custom_columns=custom_columns,
        is_tree=is_tree,
        parent_field=parent_field,
    )

    if has_allow_rate():
        return result

    _mask_report_result(result)
    return result


def _mask_report_result(result: dict) -> None:
    """
    Mutate *result* in-place:
      - Blank out values in financial columns for every data row.
      - Remove report_summary (contains aggregated financial figures).
      - Remove chart data (may contain financial figures on axes).
    """
    columns = result.get("columns") or []
    rows    = result.get("result")  or []

    # Identify financial columns by index and by fieldname
    financial_indices   = set()
    financial_fieldnames = set()

    for i, col in enumerate(columns):
        if _is_financial_column(col):
            financial_indices.add(i)
            fn = _get_col_fieldname(col)
            if fn:
                financial_fieldnames.add(fn)

    if not financial_indices and not financial_fieldnames:
        return  # Nothing to mask

    masked_rows = []
    for row in rows:
        if isinstance(row, dict):
            row = dict(row)
            for fn in financial_fieldnames:
                if fn in row:
                    row[fn] = "*****"
            masked_rows.append(row)

        elif isinstance(row, (list, tuple)):
            row = list(row)
            for idx in financial_indices:
                if idx < len(row):
                    row[idx] = "*****"
            masked_rows.append(row)

        else:
            masked_rows.append(row)

    result["result"] = masked_rows

    # Strip summary cards (they expose financial totals)
    result["report_summary"] = []

    # Strip chart payload
    result.pop("chart", None)
