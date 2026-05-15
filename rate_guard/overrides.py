"""
rate_guard.overrides
====================
Enforces the "Allow Rate" role — pure backend, no JS required.

Users WITHOUT "Allow Rate":
  - Forms   : financial fields removed from metadata + values stripped
  - Reports : financial columns removed entirely from response
  - API     : values never sent to browser

Administrator always bypasses the restriction.
"""

import frappe

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FINANCIAL_FIELDTYPES = frozenset(["Currency", "Percent"])

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
    user = frappe.session.user
    if user == "Administrator":
        return True
    if user == "Guest":
        return False
    return "Allow Rate" in frappe.get_roles(user)


def _is_financial_field(field) -> bool:
    ft = getattr(field, "fieldtype", None) or field.get("fieldtype", "")
    fn = (getattr(field, "fieldname", None) or field.get("fieldname", "") or "").lower()
    lb = (getattr(field, "label", None) or field.get("label", "") or "").lower()

    if ft in FINANCIAL_FIELDTYPES:
        return True
    if ft == "Float":
        if fn in ALWAYS_VISIBLE:
            return False
        for kw in FINANCIAL_FLOAT_KEYWORDS:
            if kw in fn or kw in lb:
                return True
    return False


def _is_financial_column(col) -> bool:
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
    if isinstance(col, dict):
        return col.get("fieldname") or col.get("key")
    if isinstance(col, str):
        return col.split(":")[0].strip()
    return None


def _strip_doc_financial_fields(doc):
    """Strip financial values from a doc dict and its child table rows."""
    if not isinstance(doc, dict):
        return
    doctype = doc.get("doctype", "")
    if not doctype:
        return
    try:
        meta = frappe.get_meta(doctype)
        for field in meta.fields:
            if _is_financial_field(field):
                doc[field.fieldname] = None

            elif field.fieldtype in ("Table", "Table MultiSelect"):
                child_rows = doc.get(field.fieldname) or []
                if not child_rows:
                    continue
                try:
                    child_meta = frappe.get_meta(field.options)
                    for row in child_rows:
                        if isinstance(row, dict):
                            for cf in child_meta.fields:
                                if _is_financial_field(cf):
                                    row[cf.fieldname] = None
                except Exception:
                    pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Doc Event — strips values on document load (also covers REST API)
# ---------------------------------------------------------------------------

def hide_rates_on_load(doc, method=None):
    try:
        if has_allow_rate():
            return
        meta = frappe.get_meta(doc.doctype)
        for field in meta.fields:
            if _is_financial_field(field):
                doc.set(field.fieldname, None)
            elif field.fieldtype in ("Table", "Table MultiSelect"):
                child_rows = doc.get(field.fieldname) or []
                if not child_rows:
                    continue
                try:
                    child_meta = frappe.get_meta(field.options)
                    for row in child_rows:
                        for cf in child_meta.fields:
                            if _is_financial_field(cf):
                                row.set(cf.fieldname, None)
                except Exception:
                    pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Form Load Override — strips field definitions from metadata
# so financial fields never render in the form at all
# ---------------------------------------------------------------------------

@frappe.whitelist()
def getdoc_override(doctype, name, user=None):
    """
    Replacement for frappe.desk.form.load.getdoc
    Calls the original, then:
      1. Strips financial field VALUES from every doc in the response
      2. Removes financial field DEFINITIONS from the doctype metadata
         so the fields are not rendered in the form at all
    """
    from frappe.desk.form.load import getdoc as _original_getdoc

    _original_getdoc(doctype, name, user)

    if has_allow_rate():
        return

    # 1. Strip values from docs in the response
    docs = frappe.response.get("docs") or []
    for doc in docs:
        _strip_doc_financial_fields(doc)

    # 2. Remove financial field definitions from the meta inside the response
    #    so the form never renders those columns/fields
    for doc in docs:
        if isinstance(doc, dict) and doc.get("doctype") == doctype:
            # Strip from inline docfields if present
            if "fields" in doc:
                doc["fields"] = [
                    f for f in doc["fields"]
                    if not _is_financial_field(f)
                ]

    # 3. Also patch the meta stored in frappe.response if present
    meta_docs = [d for d in docs if isinstance(d, dict)
                 and d.get("doctype") == "DocType"]
    for meta_doc in meta_docs:
        if "fields" in meta_doc:
            meta_doc["fields"] = [
                f for f in meta_doc["fields"]
                if not _is_financial_field(f)
            ]


# ---------------------------------------------------------------------------
# Report Override — removes financial columns entirely
# ---------------------------------------------------------------------------

@frappe.whitelist()
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

    _remove_financial_columns(result)
    return result


def _remove_financial_columns(result: dict) -> None:
    """Remove financial columns and their values entirely from report result."""
    columns = result.get("columns") or []
    rows    = result.get("result")  or []

    financial_indices    = set()
    financial_fieldnames = set()

    for i, col in enumerate(columns):
        if _is_financial_column(col):
            financial_indices.add(i)
            fn = _get_col_fieldname(col)
            if fn:
                financial_fieldnames.add(fn)

    if not financial_indices and not financial_fieldnames:
        return

    # Remove columns from header
    result["columns"] = [
        col for i, col in enumerate(columns)
        if i not in financial_indices
    ]

    # Remove values from rows
    clean_rows = []
    for row in rows:
        if isinstance(row, dict):
            clean_rows.append({k: v for k, v in row.items()
                                if k not in financial_fieldnames})
        elif isinstance(row, (list, tuple)):
            clean_rows.append([v for i, v in enumerate(row)
                                if i not in financial_indices])
        else:
            clean_rows.append(row)

    result["result"]         = clean_rows
    result["report_summary"] = []
    result.pop("chart", None)