(function () {
	if (!window.frappe) return;

	const FINANCIAL_FIELDTYPES = new Set(["Currency", "Percent"]);
	const FINANCIAL_FLOAT_KEYWORDS = [
		"rate",
		"amount",
		"price",
		"cost",
		"value",
		"total",
		"pay",
		"paid",
		"salary",
		"wage",
		"charge",
		"fee",
		"tax",
		"discount",
		"margin",
		"exchange",
		"commission",
		"interest",
		"premium",
		"rebate",
		"billing",
		"costing",
		"overhead",
		"grand",
		"net",
		"gross",
		"outstanding",
		"valuation",
		"incoming_rate",
		"outgoing_rate",
		"hour_rate",
		"base_rate",
		"base_amount",
		"base_total",
		"base_net",
		"base_grand",
	];
	const ALWAYS_VISIBLE = new Set([
		"qty",
		"stock_qty",
		"ordered_qty",
		"billed_qty",
		"received_qty",
		"delivered_qty",
		"actual_qty",
		"projected_qty",
		"reserved_qty",
		"transfer_qty",
		"conversion_factor",
		"uom_conversion_factor",
		"conversion_rate",
		"plc_conversion_rate",
		"idx",
		"docstatus",
		"progress",
		"percent_complete",
		"cost_allocation_per",
		"process_loss_percentage",
		"process_loss_per",
		"rate_per_minute",
		"custom_rate_per_minute",
		"latitude",
		"longitude",
	]);
	const EXCLUDED_DOCTYPES = new Set([
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
	]);

	function as_array(value) {
		return Array.isArray(value) ? value : [];
	}

	function get_meta_safe(doctype) {
		if (!doctype || typeof frappe.get_meta !== "function") return null;
		try {
			return frappe.get_meta(doctype);
		} catch (e) {
			return null;
		}
	}

	function is_table_field(df) {
		return !!df && as_array(frappe.model?.table_fields).includes(df.fieldtype);
	}

	function call_if_function(target, method, args) {
		if (typeof target?.[method] === "function") {
			return target[method].apply(target, args || []);
		}
	}

	function has_allow_rate() {
		return frappe.session?.user === "Administrator" || (frappe.user_roles || []).includes("Allow Rate");
	}

	function should_apply_rate_guard(doctype) {
		return !has_allow_rate() && !EXCLUDED_DOCTYPES.has(doctype);
	}

	function is_financial_field(df) {
		if (!df) return false;

		const fieldtype = df.fieldtype || "";
		const fieldname = String(df.fieldname || "").toLowerCase();
		const label = String(df.label || "").toLowerCase();

		if (ALWAYS_VISIBLE.has(fieldname)) return false;
		if (FINANCIAL_FIELDTYPES.has(fieldtype)) return true;
		if (fieldtype === "Float") {
			return FINANCIAL_FLOAT_KEYWORDS.some((kw) => fieldname.includes(kw) || label.includes(kw));
		}

		return false;
	}

	function remember_original_field_state(df) {
		if (!df || df.__rate_guard_original_state) return;

		df.__rate_guard_original_state = {
			hidden: df.hidden,
			reqd: df.reqd,
			in_list_view: df.in_list_view,
			in_standard_filter: df.in_standard_filter,
		};
	}

	function restore_original_field_state(df) {
		const original = df?.__rate_guard_original_state;
		if (!original) return;

		df.hidden = original.hidden;
		df.reqd = original.reqd;
		df.in_list_view = original.in_list_view;
		df.in_standard_filter = original.in_standard_filter;
		delete df.__rate_guard_original_state;
	}

	function restore_rate_guard_changes(frm) {
		if (!frm) return;

		as_array(frm.meta?.fields).forEach((df) => {
			if (!df) return;
			restore_original_field_state(df);

			if (is_table_field(df) && frm.fields_dict?.[df.fieldname]?.grid) {
				const grid = frm.fields_dict[df.fieldname].grid;
				const child_meta = get_meta_safe(df.options);

				as_array(child_meta?.fields).forEach((child_df) => {
					if (!child_df) return;
					const mapped_df = frappe.meta?.docfield_map?.[df.options]?.[child_df.fieldname];

					restore_original_field_state(child_df);
					restore_original_field_state(mapped_df);
				});

				call_if_function(grid, "refresh");
			}
		});
	}

	function hide_field_without_client_mandatory(frm, df) {
		if (!frm || !df?.fieldname) return;
		remember_original_field_state(df);

		df.hidden = 1;
		df.reqd = 0;
		df.in_list_view = 0;
		df.in_standard_filter = 0;

		call_if_function(frm, "set_df_property", [df.fieldname, "hidden", 1]);
		call_if_function(frm, "set_df_property", [df.fieldname, "reqd", 0]);
		call_if_function(frm, "set_df_property", [df.fieldname, "in_list_view", 0]);
		call_if_function(frm, "set_df_property", [df.fieldname, "in_standard_filter", 0]);
	}

	function hide_grid_field_without_client_mandatory(grid, child_doctype, child_df) {
		if (!grid || !child_df?.fieldname) return;
		remember_original_field_state(child_df);

		child_df.hidden = 1;
		child_df.reqd = 0;
		child_df.in_list_view = 0;
		child_df.in_standard_filter = 0;

		const mapped_df = frappe.meta?.docfield_map?.[child_doctype]?.[child_df.fieldname];
		if (mapped_df) {
			remember_original_field_state(mapped_df);

			mapped_df.hidden = 1;
			mapped_df.reqd = 0;
			mapped_df.in_list_view = 0;
			mapped_df.in_standard_filter = 0;
		}

		call_if_function(grid, "update_docfield_property", [child_df.fieldname, "hidden", 1]);
		call_if_function(grid, "update_docfield_property", [child_df.fieldname, "reqd", 0]);
		call_if_function(grid, "update_docfield_property", [child_df.fieldname, "in_list_view", 0]);
		call_if_function(grid, "update_docfield_property", [
			child_df.fieldname,
			"in_standard_filter",
			0,
		]);

		if (Array.isArray(grid.visible_columns)) {
			grid.visible_columns = [];
		}
	}

	function apply_rate_guard_to_form(frm) {
		if (!frm || frm.__rate_guard_applying) return;
		if (!should_apply_rate_guard(frm.doctype)) {
			restore_rate_guard_changes(frm);
			return;
		}

		frm.__rate_guard_applying = true;

		try {
			as_array(frm.meta?.fields).forEach((df) => {
				if (!df) return;
				if (is_financial_field(df)) {
					hide_field_without_client_mandatory(frm, df);
				} else if (is_table_field(df) && frm.fields_dict?.[df.fieldname]?.grid) {
					const grid = frm.fields_dict[df.fieldname].grid;
					const child_meta = get_meta_safe(df.options);
					if (!should_apply_rate_guard(df.options)) return;

					as_array(child_meta?.fields).forEach((child_df) => {
						if (!is_financial_field(child_df)) return;

						hide_grid_field_without_client_mandatory(grid, df.options, child_df);
					});

					call_if_function(grid, "refresh");
				}
			});
		} finally {
			frm.__rate_guard_applying = false;
		}
	}

	function install_form_hooks() {
		if (has_allow_rate() || !frappe.ui?.form?.Form?.prototype) return;

		const proto = frappe.ui.form.Form.prototype;
		if (proto.__rate_guard_installed) return;
		proto.__rate_guard_installed = true;

		const original_refresh = proto.refresh;
		proto.refresh = function () {
			patch_transaction_controller();
			patch_bom_controller();
			const out = original_refresh.apply(this, arguments);
			setTimeout(() => apply_rate_guard_to_form(this), 0);
			return out;
		};
	}

	function patch_transaction_controller() {
		const proto = window.erpnext?.TransactionController?.prototype;
		if (!proto || proto.__rate_guard_patched) return;
		proto.__rate_guard_patched = true;

		const original_price_list_currency = proto.price_list_currency;
		if (typeof original_price_list_currency !== "function") return;

		proto.price_list_currency = function () {
			const original_plc_conversion_rate = this.plc_conversion_rate;
			if (typeof original_plc_conversion_rate !== "function") {
				return original_price_list_currency.apply(this, arguments);
			}

			this.plc_conversion_rate = function (doc) {
				return original_plc_conversion_rate.call(this, doc || this.frm?.doc || {});
			};

			try {
				return original_price_list_currency.apply(this, arguments);
			} finally {
				this.plc_conversion_rate = original_plc_conversion_rate;
			}
		};
	}

	function patch_bom_controller() {
		const proto = window.erpnext?.bom?.BomController?.prototype;
		if (!proto || proto.__rate_guard_patched) return;
		proto.__rate_guard_patched = true;

		const original_plc_conversion_rate = proto.plc_conversion_rate;
		if (typeof original_plc_conversion_rate === "function") {
			proto.plc_conversion_rate = function (doc) {
				return original_plc_conversion_rate.call(this, doc || this.frm?.doc || {});
			};
		}
	}

	function install_rate_guard() {
		patch_transaction_controller();
		patch_bom_controller();
		install_form_hooks();
		if (window.cur_frm) apply_rate_guard_to_form(window.cur_frm);
	}

	if (typeof frappe.after_ajax === "function") {
		frappe.after_ajax(install_rate_guard);
	} else {
		setTimeout(install_rate_guard, 0);
	}

	if (window.$ && window.document) {
		$(document).on("form-refresh", function () {
			if (window.cur_frm) apply_rate_guard_to_form(window.cur_frm);
		});
	}
})();
