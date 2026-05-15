app_name        = "rate_guard"
app_title       = "Rate Guard"
app_publisher   = "QC Styropackaging Corporation"
app_description = "Enforces Allow Rate permission — hides financial figures from unauthorized users"
app_version     = "0.0.1"
app_icon        = "octicon octicon-shield"
app_color       = "red"
app_email       = ""
app_license     = "MIT"

# ---------------------------------------------------------------------------
# Document Events
# Fires on every DocType load — hides Currency / Float / Percent fields
# for users who do NOT have the "Allow Rate" role.
# ---------------------------------------------------------------------------
doc_events = {
    "*": {
        "onload": "rate_guard.overrides.hide_rates_on_load",
    }
}

# ---------------------------------------------------------------------------
# Method Overrides
# Wraps the core report runner so numeric columns are blanked-out in the
# response before it ever reaches the browser.
# ---------------------------------------------------------------------------
override_whitelisted_methods = {
    "frappe.desk.query_report.run": "rate_guard.overrides.run_report_override",
}
