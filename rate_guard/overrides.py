"""
rate_guard.overrides
====================
Enforces the "Allow Rate" role — pure backend, no JS required.

Users WITHOUT "Allow Rate":
  - Forms   : financial fields hidden in metadata + values stripped
  - Reports : financial columns removed entirely from response
  - API     : values never sent to browser

Administrator always bypasses the restriction.
"""

import copy
import json
from contextlib import contextmanager

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
    "base_grand",
])

ALWAYS_VISIBLE = frozenset([
    "qty", "stock_qty", "ordered_qty", "billed_qty",
    "received_qty", "delivered_qty", "actual_qty",
    "projected_qty", "reserved_qty", "transfer_qty",
    "conversion_factor", "uom_conversion_factor",
    "conversion_rate", "plc_conversion_rate",
    "idx", "docstatus", "progress", "percent_complete",
    "cost_allocation_per", "process_loss_percentage", "process_loss_per",
    "rate_per_minute", "custom_rate_per_minute",
    "latitude", "longitude",
])

EXCLUDED_DOCTYPES = frozenset([
    "Sales Order",
    "Sales Order Item",
    "Purchase Receipt",
    "Purchase Receipt Item",
    "Purchase Order",
    "Purchase Order Item",
    "Sales Invoice",
    "Sales Invoice Item",
    "Purchase Invoice",
    "Purchase Invoice Item",
])

EXCLUDED_REPORTS = frozenset([
    "Sales Register",
    "Purchase Register",
    "Sales Order Analysis",
    "Purchase Order Analysis",
    "Sales Order Trends",
    "Purchase Order Trends",
    "Sales Invoice Trends",
    "Purchase Invoice Trends",
    "Item-wise Sales Register",
    "Item-wise Purchase Register",
    "Ordered Items To Be Delivered",
    "Delivered Items To Be Billed",
    "Received Items To Be Billed",
])

EXCLUDED_GRID_PARENT_DOCTYPES = frozenset([
    "Sales Order",
    "Purchase Receipt",
    "Purchase Order",
    "Sales Invoice",
    "Purchase Invoice",
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


def should_apply_rate_guard(doctype=None, parent_doctype=None) -> bool:
    if has_allow_rate():
        return False
    return doctype not in EXCLUDED_DOCTYPES and parent_doctype not in EXCLUDED_DOCTYPES


def should_apply_rate_guard_to_report(report_name=None) -> bool:
    if has_allow_rate():
        return False
    return report_name not in EXCLUDED_REPORTS


def _loads_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _collect_doctypes(value):
    value = _loads_json(value)
    doctypes = set()

    if isinstance(value, list):
        for row in value:
            doctypes.update(_collect_doctypes(row))
        return doctypes

    if not isinstance(value, dict):
        return doctypes

    doctype = value.get("doctype")
    parenttype = value.get("parenttype")
    if doctype:
        doctypes.add(doctype)
    if parenttype:
        doctypes.add(parenttype)

    for child_value in value.values():
        if isinstance(child_value, (dict, list)):
            doctypes.update(_collect_doctypes(child_value))

    return doctypes


def _has_excluded_doctype_context(*values):
    doctypes = set()
    for value in values:
        doctypes.update(_collect_doctypes(value))

    return bool(doctypes.intersection(EXCLUDED_DOCTYPES))


def reset_excluded_transaction_grid_settings():
    """
    Remove per-user grid column overrides for excluded transaction doctypes.

    This repairs users who saved Configure Columns while older Rate Guard
    browser metadata had marked extra rate/amount fields as grid columns.
    """
    from frappe.model.utils.user_settings import sync_user_settings

    sync_user_settings()

    rows = frappe.db.sql(
        """
        select user, doctype, data
        from `__UserSettings`
        where doctype in %(doctypes)s
        """,
        {"doctypes": tuple(EXCLUDED_GRID_PARENT_DOCTYPES)},
        as_dict=True,
    )

    updated = []
    deleted = []

    for row in rows:
        try:
            data = json.loads(row.data or "{}")
        except Exception:
            continue

        grid_view = data.get("GridView")
        if not isinstance(grid_view, dict):
            continue

        changed = False
        for child_doctype in list(grid_view):
            if child_doctype in EXCLUDED_DOCTYPES:
                grid_view.pop(child_doctype, None)
                changed = True

        if not changed:
            continue

        if grid_view:
            data["GridView"] = grid_view
        else:
            data.pop("GridView", None)

        if data:
            frappe.db.sql(
                """
                update `__UserSettings`
                set data = %(data)s
                where user = %(user)s and doctype = %(doctype)s
                """,
                {
                    "data": json.dumps(data),
                    "user": row.user,
                    "doctype": row.doctype,
                },
            )
            updated.append({"user": row.user, "doctype": row.doctype})
        else:
            frappe.db.sql(
                """
                delete from `__UserSettings`
                where user = %(user)s and doctype = %(doctype)s
                """,
                {"user": row.user, "doctype": row.doctype},
            )
            deleted.append({"user": row.user, "doctype": row.doctype})

        frappe.cache.hdel("_user_settings", f"{row.doctype}::{row.user}")

    frappe.db.commit()

    return {
        "updated": updated,
        "deleted": deleted,
        "total": len(updated) + len(deleted),
    }


def _is_financial_field(field) -> bool:
    ft = getattr(field, "fieldtype", None) or field.get("fieldtype", "")
    fn = (getattr(field, "fieldname", None) or field.get("fieldname", "") or "").lower()
    lb = (getattr(field, "label", None) or field.get("label", "") or "").lower()

    if fn in ALWAYS_VISIBLE:
        return False
    if ft in FINANCIAL_FIELDTYPES:
        return True
    if ft == "Float":
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

    if fn in ALWAYS_VISIBLE:
        return False
    if ft in FINANCIAL_FIELDTYPES:
        return True
    if ft == "Float":
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


def _strip_value_financial_fields(value, doctype=None):
    """Strip financial values from dict/list/document responses."""
    if not should_apply_rate_guard(doctype):
        return value

    if isinstance(value, list):
        for row in value:
            _strip_value_financial_fields(row, doctype=doctype)
        return value

    if isinstance(value, tuple):
        return tuple(_strip_value_financial_fields(list(value), doctype=doctype))

    if hasattr(value, "doctype") and hasattr(value, "meta"):
        hide_rates_on_load(value)
        return value

    if not isinstance(value, dict):
        return value

    if value.get("doctype"):
        if not should_apply_rate_guard(value.get("doctype")):
            return value
        _strip_doc_financial_fields(value)
        return value

    fields = []
    if doctype:
        try:
            fields = frappe.get_meta(doctype).fields
        except Exception:
            fields = []

    if fields:
        for field in fields:
            if _is_financial_field(field):
                value[field.fieldname] = None

    for key in list(value):
        key_lower = key.lower()
        if key_lower not in ALWAYS_VISIBLE and any(kw in key_lower for kw in FINANCIAL_FLOAT_KEYWORDS):
            value[key] = None

    for child_value in value.values():
        if isinstance(child_value, (dict, list)):
            _strip_value_financial_fields(child_value)

    return value


def _strip_doc_financial_fields(doc):
    """Strip financial values from a doc dict and its child table rows."""
    if not isinstance(doc, dict):
        return
    doctype = doc.get("doctype", "")
    if not doctype or not should_apply_rate_guard(doctype):
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


def _hide_meta_financial_fields(meta_doc):
    """Keep financial field definitions available to client scripts, but hide them."""
    try:
        meta_doctype = (
            getattr(meta_doc, "name", None)
            or getattr(meta_doc, "doctype", None)
            or (meta_doc.get("name") if isinstance(meta_doc, dict) else None)
            or (meta_doc.get("doctype") if isinstance(meta_doc, dict) else None)
        )
        if not should_apply_rate_guard(meta_doctype):
            return

        fields = getattr(meta_doc, "fields", None)
        if fields is None and isinstance(meta_doc, dict):
            fields = meta_doc.get("fields")

        for field in fields or []:
            if not _is_financial_field(field):
                continue

            if hasattr(field, "hidden"):
                field.hidden = 1
                field.reqd = 0
                field.print_hide = 1
                field.in_list_view = 0
                field.in_standard_filter = 0
            elif isinstance(field, dict):
                field["hidden"] = 1
                field["reqd"] = 0
                field["print_hide"] = 1
                field["in_list_view"] = 0
                field["in_standard_filter"] = 0
    except Exception:
        pass


def _copy_and_hide_meta_financial_fields(meta_doc):
    """Return a sanitized metadata copy without mutating Frappe's cached FormMeta."""
    meta_doc = copy.deepcopy(meta_doc)
    _hide_meta_financial_fields(meta_doc)
    return meta_doc


@contextmanager
def _print_meta_guard():
    """Temporarily return sanitized meta copies while rendering print formats."""
    original_get_meta = frappe.get_meta
    sanitized = {}

    def guarded_get_meta(doctype, *args, **kwargs):
        meta = original_get_meta(doctype, *args, **kwargs)
        meta_doctype = getattr(meta, "name", None) or getattr(meta, "doctype", None) or str(doctype)

        if meta_doctype not in sanitized:
            sanitized[meta_doctype] = _copy_and_hide_meta_financial_fields(meta)

        return sanitized[meta_doctype]

    frappe.get_meta = guarded_get_meta
    try:
        yield
    finally:
        frappe.get_meta = original_get_meta


def _sanitize_print_document(doc):
    """Strip print values without changing the saved document."""
    doc = copy.deepcopy(doc)
    hide_rates_on_load(doc)
    return doc


def before_request():
    """Patch the full /printview page renderer for non-Allow-Rate users."""
    if not should_apply_rate_guard():
        return

    path = (getattr(frappe.local, "request", None) and frappe.local.request.path) or ""
    if path.rstrip("/") != "/printview":
        return

    try:
        import frappe.www.printview as printview
    except Exception:
        return

    if getattr(printview, "__rate_guard_printview_patched", False):
        return

    original_get_rendered_template = printview.get_rendered_template
    original_get_html = None

    def guarded_get_rendered_template(
        doc,
        print_format=None,
        meta=None,
        no_letterhead=None,
        letterhead=None,
        trigger_print=False,
        settings=None,
    ):
        if not should_apply_rate_guard(getattr(doc, "doctype", None)):
            return original_get_rendered_template(
                doc=doc,
                print_format=print_format,
                meta=meta,
                no_letterhead=no_letterhead,
                letterhead=letterhead,
                trigger_print=trigger_print,
                settings=settings,
            )

        doc = _sanitize_print_document(doc)
        if meta is not None:
            meta = _copy_and_hide_meta_financial_fields(meta)

        with _print_meta_guard():
            return original_get_rendered_template(
                doc=doc,
                print_format=print_format,
                meta=meta,
                no_letterhead=no_letterhead,
                letterhead=letterhead,
                trigger_print=trigger_print,
                settings=settings,
            )

    printview.get_rendered_template = guarded_get_rendered_template

    try:
        import frappe.utils.weasyprint as weasyprint
        original_get_html = weasyprint.get_html

        def guarded_get_html(doctype, name, print_format, letterhead=None):
            if not should_apply_rate_guard(doctype):
                return original_get_html(
                    doctype=doctype,
                    name=name,
                    print_format=print_format,
                    letterhead=letterhead,
                )

            doc = frappe.get_doc(doctype, name)
            doc = _sanitize_print_document(doc)
            with _print_meta_guard():
                return frappe.get_print(
                    doctype,
                    name,
                    print_format,
                    doc=doc,
                    letterhead=letterhead,
                    no_letterhead=frappe.form_dict.no_letterhead,
                )

        weasyprint.get_html = guarded_get_html
    except Exception:
        pass

    printview.__rate_guard_printview_patched = True
    printview.__rate_guard_original_get_rendered_template = original_get_rendered_template
    if original_get_html:
        printview.__rate_guard_original_weasyprint_get_html = original_get_html


# ---------------------------------------------------------------------------
# Doc Event — strips values on document load (also covers REST API)
# ---------------------------------------------------------------------------

def hide_rates_on_load(doc, method=None):
    try:
        if not should_apply_rate_guard(getattr(doc, "doctype", None)):
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
# Form Load Override — hides field definitions in metadata
# so financial fields do not render, while client scripts keep working
# ---------------------------------------------------------------------------

@frappe.whitelist()
def getdoc_override(doctype, name):
    """
    Replacement for frappe.desk.form.load.getdoc
    Calls the original, then:
      1. Strips financial field VALUES from every doc in the response
      2. Hides financial field DEFINITIONS in the doctype metadata
         so ERPNext client scripts can still access the fields
    """
    from frappe.desk.form.load import getdoc as _original_getdoc

    _original_getdoc(doctype, name)

    if not should_apply_rate_guard(doctype):
        return

    # 1. Strip values from docs in the response
    docs = frappe.response.get("docs") or []
    for doc in docs:
        _strip_doc_financial_fields(doc)

    # 2. Hide financial field definitions inside the response, but keep them
    #    available so ERPNext client scripts can still run calculations.
    for index, doc in enumerate(docs):
        if isinstance(doc, dict) and doc.get("doctype") == doctype:
            if "fields" in doc:
                docs[index] = _copy_and_hide_meta_financial_fields(doc)

    # 3. Also patch the meta stored in frappe.response if present
    for index, doc in enumerate(docs):
        if isinstance(doc, dict) and doc.get("doctype") == "DocType":
            docs[index] = _copy_and_hide_meta_financial_fields(doc)


@frappe.whitelist()
def getdoctype_override(doctype, with_parent=False):
    """
    Replacement for frappe.desk.form.load.getdoctype.
    Covers new documents, where getdoc/onload is not called yet.
    """
    from frappe.desk.form.load import getdoctype as _original_getdoctype

    _original_getdoctype(doctype, with_parent=with_parent)

    if not should_apply_rate_guard(doctype):
        return

    frappe.response["docs"] = [
        _copy_and_hide_meta_financial_fields(doc)
        for doc in frappe.response.get("docs") or []
    ]


@frappe.whitelist()
def run_doc_method_override(method, docs=None, dt=None, dn=None, arg=None, args=None):
    """
    Replacement for frappe.handler.run_doc_method.
    Covers whitelisted document methods such as BOM.get_bom_material_detail,
    which can return rates while a new document is still being created.
    """
    from frappe.handler import run_doc_method as _original_run_doc_method

    result = _original_run_doc_method(method, docs=docs, dt=dt, dn=dn, arg=arg, args=args)

    if not should_apply_rate_guard(dt) or _has_excluded_doctype_context(docs, arg, args):
        return result

    response_docs = frappe.response.get("docs") or []
    for doc in response_docs:
        if isinstance(doc, dict) and doc.get("doctype"):
            _strip_doc_financial_fields(doc)

    response_message = frappe.response.get("message")
    if response_message is not None:
        response_doctype = None
        if response_docs:
            response_doctype = getattr(response_docs[0], "doctype", None) or response_docs[0].get("doctype")

        frappe.response["message"] = _strip_value_financial_fields(
            response_message,
            doctype=response_doctype,
        )

    return result


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

    if not should_apply_rate_guard_to_report(report_name):
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

    report_name = frappe.form_dict.get("report_name")
    if not should_apply_rate_guard_to_report(report_name):
        return _original(**clean_kwargs)

    # Non-Allow-Rate: generate our own stripped export
    try:
        from frappe.desk.query_report import generate_report_result, get_report_doc

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

    if not should_apply_rate_guard(doctype, parent_doctype):
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
def get_html_and_style_override(
    doc,
    name=None,
    print_format=None,
    no_letterhead=None,
    letterhead=None,
    trigger_print=False,
    style=None,
    settings=None,
):
    """
    Replacement for frappe.www.printview.get_html_and_style.
    Covers the print preview page, which renders independently from form metadata.
    """
    from frappe.www.printview import get_html_and_style as _original

    if not should_apply_rate_guard(doc):
        return _original(
            doc=doc,
            name=name,
            print_format=print_format,
            no_letterhead=no_letterhead,
            letterhead=letterhead,
            trigger_print=trigger_print,
            style=style,
            settings=settings,
        )

    if isinstance(name, str):
        document = frappe.get_lazy_doc(doc, name, check_permission=True)
    else:
        document = frappe.get_doc(json.loads(doc) if isinstance(doc, str) else doc, check_permission=True)

    hide_rates_on_load(document)

    with _print_meta_guard():
        return _original(
            doc=document.as_json(),
            name=None,
            print_format=print_format,
            no_letterhead=no_letterhead,
            letterhead=letterhead,
            trigger_print=trigger_print,
            style=style,
            settings=settings,
        )


@frappe.whitelist()
def get_rendered_raw_commands_override(doc, name=None, print_format=None):
    """
    Replacement for frappe.www.printview.get_rendered_raw_commands.
    Covers raw printer formats.
    """
    from frappe.www.printview import get_rendered_raw_commands as _original

    if not should_apply_rate_guard(doc):
        return _original(doc=doc, name=name, print_format=print_format)

    if isinstance(name, str):
        document = frappe.get_lazy_doc(doc, name, check_permission=True)
    else:
        document = frappe.get_doc(json.loads(doc) if isinstance(doc, str) else doc, check_permission=True)

    hide_rates_on_load(document)

    with _print_meta_guard():
        return _original(doc=document.as_json(), name=None, print_format=print_format)


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

    if not should_apply_rate_guard(doctype):
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

    with _print_meta_guard():
        return _original(
            doctype=doctype,
            name=name,
            format=format,
            doc=_doc,
            no_letterhead=no_letterhead,
            language=language,
            letterhead=letterhead,
        )
