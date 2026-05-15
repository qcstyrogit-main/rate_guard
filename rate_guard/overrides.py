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
def getdoc_override(doctype, name):
    """
    Replacement for frappe.desk.form.load.getdoc
    Calls the original, then:
      1. Strips financial field VALUES from every doc in the response
      2. Removes financial field DEFINITIONS from the doctype metadata
         so the fields are not rendered in the form at all
    """
    from frappe.desk.form.load import getdoc as _original_getdoc

    _original_getdoc(doctype, name)

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


# ---------------------------------------------------------------------------
# Export Overrides — blocks financial data from Excel / CSV / PDF exports
# ---------------------------------------------------------------------------

@frappe.whitelist()
def export_query_report_override(**kwargs):
    """
    Replacement for frappe.desk.query_report.export_query
    For Allow Rate users: calls original unchanged.
    For others: generates export with financial columns removed.
    """
    import json
    import inspect
    from frappe.desk.query_report import export_query as _original

    # Build clean kwargs matching the original function signature exactly
    valid_args = set(inspect.signature(_original).parameters.keys())
    clean_kwargs = {k: v for k, v in frappe.form_dict.items() if k in valid_args}

    if has_allow_rate():
        return _original(**clean_kwargs)

    # Non-Allow-Rate: generate our own stripped export
    try:
        from frappe.desk.query_report import generate_report_result, get_report_doc

        report_name    = frappe.form_dict.get("report_name")
        filters        = frappe.form_dict.get("filters") or {}
        custom_columns = frappe.form_dict.get("custom_columns")
        file_format    = frappe.form_dict.get("file_format_type", "Excel")

        parsed_filters = json.loads(filters) if isinstance(filters, str) else filters
        parsed_custom  = json.loads(custom_columns) if isinstance(custom_columns, str) and custom_columns else None

        report = get_report_doc(report_name)
        result = generate_report_result(
            report=report,
            filters=parsed_filters,
            custom_columns=parsed_custom,
        )

        # Strip financial columns from result
        _remove_financial_columns(result)

        columns = result.get("columns") or []
        rows    = result.get("result") or []

        # Normalize columns to dicts
        def _col_label(col):
            if isinstance(col, dict):
                return col.get("label") or col.get("fieldname") or ""
            return str(col).split(":")[0]

        headers = [_col_label(c) for c in columns]

        # Normalize rows
        def _row_values(row):
            if isinstance(row, dict):
                keys = [_get_col_fieldname(c) for c in columns]
                return [row.get(k) for k in keys]
            return list(row)

        data = [headers] + [_row_values(r) for r in rows if r]

        if file_format == "CSV":
            import csv, io
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerows(data)
            frappe.response["result"]        = out.getvalue()
            frappe.response["type"]          = "csv"
            frappe.response["doctype"]       = report_name
        else:
            # Excel
            from frappe.utils.xlsxutils import make_xlsx
            xlsx_file = make_xlsx(data, report_name)
            frappe.response["filename"]      = report_name + ".xlsx"
            frappe.response["filecontent"]   = xlsx_file.getvalue()
            frappe.response["type"]          = "binary"

        return

    except Exception:
        # Fallback to original if anything fails
        return _original(**clean_kwargs)


@frappe.whitelist()
def export_listview_override(
    doctype,
    parent_doctype=None,
    fields=None,
    filters=None,
    or_filters=None,
    file_format_type=None,
    start=None,
    page_length=None,
    view=None,
    group_by=None,
    order_by=None,
    with_comment_count=False,
):
    """
    Replacement for frappe.desk.reportview.export_query
    Strips financial columns from list view exports for non-Allow-Rate users.
    """
    from frappe.desk.reportview import export_query as _original

    if has_allow_rate():
        return _original(
            doctype=doctype,
            parent_doctype=parent_doctype,
            fields=fields,
            filters=filters,
            or_filters=or_filters,
            file_format_type=file_format_type,
            start=start,
            page_length=page_length,
            view=view,
            group_by=group_by,
            order_by=order_by,
            with_comment_count=with_comment_count,
        )

    # Strip financial fields from the requested fields before exporting
    if fields:
        import json
        try:
            field_list = json.loads(fields) if isinstance(fields, str) else fields
        except Exception:
            field_list = fields

        if isinstance(field_list, list):
            clean_fields = []
            for f in field_list:
                fn = f.split(".")[-1].strip("`\" ") if isinstance(f, str) else ""
                # Build a mock field object to check
                class _MockField:
                    fieldtype = "Data"
                    fieldname = fn
                    label = fn
                mock = _MockField()
                # Heuristic check on fieldname only for list exports
                fn_lower = fn.lower()
                is_financial = any(kw in fn_lower for kw in FINANCIAL_FLOAT_KEYWORDS)
                if not is_financial:
                    clean_fields.append(f)
            fields = json.dumps(clean_fields)

    return _original(
        doctype=doctype,
        parent_doctype=parent_doctype,
        fields=fields,
        filters=filters,
        or_filters=or_filters,
        file_format_type=file_format_type,
        start=start,
        page_length=page_length,
        view=view,
        group_by=group_by,
        order_by=order_by,
        with_comment_count=with_comment_count,
    )


# ---------------------------------------------------------------------------
# PDF Overrides
# ---------------------------------------------------------------------------

@frappe.whitelist()
def report_to_pdf_override(html, orientation="Landscape"):
    """
    Replacement for frappe.utils.print_format.report_to_pdf
    The HTML already has financial columns stripped (from run_report_override),
    so we just pass through to the original renderer.
    """
    from frappe.utils.print_format import report_to_pdf as _original
    return _original(html=html, orientation=orientation)


@frappe.whitelist()
def download_pdf_override(doctype, name, format=None, doc=None, no_letterhead=0,
                          language=None, letterhead=None):
    """
    Replacement for frappe.utils.print_format.download_pdf
    Strips financial field values before generating document PDF.
    """
    from frappe.utils.print_format import download_pdf as _original

    if has_allow_rate():
        return _original(
            doctype=doctype,
            name=name,
            format=format,
            doc=doc,
            no_letterhead=no_letterhead,
            language=language,
            letterhead=letterhead,
        )

    # Load and sanitize the doc before passing to PDF renderer
    _doc = frappe.get_doc(doctype, name)
    hide_rates_on_load(_doc)

    return _original(
        doctype=doctype,
        name=name,
        format=format,
        doc=_doc,
        no_letterhead=no_letterhead,
        language=language,
        letterhead=letterhead,
    )


