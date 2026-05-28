app_name        = "rate_guard"
app_title       = "Rate Guard"
app_publisher   = "QC Styropackaging Corporation"
app_description = "Enforces Allow Rate permission — hides financial figures from unauthorized users"
app_version     = "0.0.1"
app_icon        = "octicon octicon-shield"
app_color       = "red"
app_email       = ""
app_license     = "MIT"

app_include_js = "/assets/rate_guard/js/rate_guard.js"

before_request = ["rate_guard.overrides.before_request"]

doc_events = {
    "*": {
        "onload": "rate_guard.overrides.hide_rates_on_load",
    }
}

override_whitelisted_methods = {
    "run_doc_method":                                    "rate_guard.overrides.run_doc_method_override",
    "frappe.handler.run_doc_method":                     "rate_guard.overrides.run_doc_method_override",
    "frappe.desk.form.load.getdoctype":                  "rate_guard.overrides.getdoctype_override",
    "frappe.desk.query_report.run":                    "rate_guard.overrides.run_report_override",
    "frappe.desk.query_report.export_query":           "rate_guard.overrides.export_query_report_override",
    "frappe.desk.reportview.export_query":             "rate_guard.overrides.export_listview_override",
    "frappe.www.printview.get_html_and_style":          "rate_guard.overrides.get_html_and_style_override",
    "frappe.www.printview.get_rendered_raw_commands":   "rate_guard.overrides.get_rendered_raw_commands_override",
    "frappe.utils.print_format.report_to_pdf":         "rate_guard.overrides.report_to_pdf_override",
    "frappe.utils.print_format.download_pdf":          "rate_guard.overrides.download_pdf_override",
    "frappe.desk.form.load.getdoc":                    "rate_guard.overrides.getdoc_override",
}
