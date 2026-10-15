from collections import defaultdict

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_amount


FINANCIAL_GROUP = "mmp_project_profit_loss.group_project_financial_viewer"


class ProjectProject(models.Model):
    _inherit = "project.project"

    pnl_revenue = fields.Monetary(
        string="Revenue", currency_field="currency_id", compute="_compute_profitability",
        groups=FINANCIAL_GROUP,
    )
    pnl_cost = fields.Monetary(
        string="Cost", currency_field="currency_id", compute="_compute_profitability",
        groups=FINANCIAL_GROUP,
    )
    pnl_profit = fields.Monetary(
        string="Profit / Loss", currency_field="currency_id", compute="_compute_profitability",
        groups=FINANCIAL_GROUP,
    )
    pnl_margin = fields.Float(
        string="Profit Margin (%)", compute="_compute_profitability", digits=(16, 2),
        groups=FINANCIAL_GROUP,
    )
    pnl_margin_available = fields.Boolean(compute="_compute_profitability", groups=FINANCIAL_GROUP)
    pnl_journal_item_count = fields.Integer(
        string="Journal Items", compute="_compute_profitability", groups=FINANCIAL_GROUP,
    )
    pnl_configuration_state = fields.Selection(
        [("ok", "Ready"), ("missing", "Missing Analytic Account"), ("shared", "Shared Analytic Account")],
        compute="_compute_profitability", groups=FINANCIAL_GROUP,
    )
    pnl_configuration_message = fields.Char(compute="_compute_profitability", groups=FINANCIAL_GROUP)
    pnl_account_detail_html = fields.Html(
        string="Details by Account",
        compute="_compute_pnl_account_detail_html",
        sanitize=True,
        groups=FINANCIAL_GROUP,
    )

    def _check_financial_access(self):
        if not self.env.user.has_group(FINANCIAL_GROUP):
            raise AccessError(_("You are not allowed to view project financial information."))

    @api.depends("analytic_account_id", "company_id")
    @api.depends_context("allowed_company_ids")
    def _compute_profitability(self):
        values = {
            project.id: {"revenue": 0.0, "cost": 0.0, "profit": 0.0, "count": 0}
            for project in self
        }
        accessible = self.filtered(lambda p: p.company_id in self.env.companies)
        if accessible and self.env.user.has_group(FINANCIAL_GROUP):
            rows = self.env["mmp.project.profit.loss.line"]._read_group(
                [("project_id", "in", accessible.ids)],
                ["project_id"],
                ["revenue:sum", "cost:sum", "net_financial_amount:sum", "move_line_id:count_distinct"],
            )
            for project, revenue, cost, profit, count in rows:
                values[project.id] = {
                    "revenue": revenue or 0.0,
                    "cost": cost or 0.0,
                    "profit": profit or 0.0,
                    "count": count or 0,
                }

        account_counts = {}
        analytic_ids = self.mapped("analytic_account_id").ids
        company_ids = self.mapped("company_id").ids
        if analytic_ids and company_ids:
            self.env.cr.execute(
                """
                SELECT analytic_account_id, company_id, COUNT(*)
                  FROM project_project
                 WHERE analytic_account_id IN %s AND company_id IN %s
              GROUP BY analytic_account_id, company_id
                """,
                [tuple(analytic_ids), tuple(company_ids)],
            )
            account_counts = {(analytic_id, company_id): count for analytic_id, company_id, count in self.env.cr.fetchall()}
        for project in self:
            result = values[project.id]
            project.pnl_revenue = result["revenue"]
            project.pnl_cost = result["cost"]
            project.pnl_profit = result["profit"]
            project.pnl_journal_item_count = result["count"]
            project.pnl_margin_available = result["revenue"] > 0
            project.pnl_margin = result["profit"] / result["revenue"] * 100.0 if result["revenue"] > 0 else 0.0
            if not project.analytic_account_id:
                project.pnl_configuration_state = "missing"
                project.pnl_configuration_message = _("Set an analytic account to calculate actual profitability.")
            elif account_counts.get((project.analytic_account_id.id, project.company_id.id), 0) > 1:
                project.pnl_configuration_state = "shared"
                project.pnl_configuration_message = _(
                    "This analytic account is shared by multiple projects. Financial results are excluded to prevent duplication."
                )
            else:
                project.pnl_configuration_state = "ok"
                project.pnl_configuration_message = False

    @api.depends("analytic_account_id", "company_id")
    @api.depends_context("allowed_company_ids", "lang")
    def _compute_pnl_account_detail_html(self):
        details = defaultdict(lambda: defaultdict(list))
        accessible = self.filtered(lambda project: project.company_id in self.env.companies)
        if accessible and self.env.user.has_group(FINANCIAL_GROUP):
            rows = self.env["mmp.project.profit.loss.line"]._read_group(
                [("project_id", "in", accessible.ids)],
                ["project_id", "section", "account_id"],
                ["revenue:sum", "cost:sum", "net_financial_amount:sum"],
                order="project_id, section, account_id",
            )
            for project, section, account, revenue, cost, net_amount in rows:
                actual_amount = revenue if section in ("revenue", "other_income") else cost
                details[project.id][section].append({
                    "account": account,
                    "actual_amount": actual_amount or 0.0,
                    "net_amount": net_amount or 0.0,
                })

        sections = [
            ("revenue", _("Revenue")),
            ("direct_cost", _("Direct Costs")),
            ("operating_expense", _("Operating Expenses")),
            ("other_income", _("Other Income")),
        ]
        for project in self:
            if not self.env.user.has_group(FINANCIAL_GROUP) or project not in accessible:
                project.pnl_account_detail_html = False
                continue
            project_details = details[project.id]
            if not any(project_details.values()):
                project.pnl_account_detail_html = Markup(
                    '<div class="text-muted py-3">%s</div>'
                ) % escape(_("No posted financial entries were found for this project."))
                continue

            body = []
            net_profit = 0.0
            for section_key, section_label in sections:
                account_rows = project_details.get(section_key, [])
                if not account_rows:
                    continue
                section_total = sum(row["actual_amount"] for row in account_rows)
                net_profit += sum(row["net_amount"] for row in account_rows)
                body.append(
                    '<tr class="table-light fw-bold">'
                    f'<td colspan="2">{escape(section_label)}</td>'
                    f'<td class="text-end">{escape(format_amount(self.env, section_total, project.currency_id))}</td>'
                    '</tr>'
                )
                for row in account_rows:
                    account = row["account"]
                    body.append(
                        '<tr>'
                        f'<td class="text-nowrap">{escape(account.code or "-")}</td>'
                        f'<td>{escape(account.name or "-")}</td>'
                        f'<td class="text-end text-nowrap">{escape(format_amount(self.env, row["actual_amount"], project.currency_id))}</td>'
                        '</tr>'
                    )

            profit_class = "text-success" if net_profit > 0 else "text-danger" if net_profit < 0 else "text-muted"
            project.pnl_account_detail_html = Markup(
                '<div class="table-responsive">'
                '<table class="table table-sm table-hover align-middle mb-0">'
                '<thead><tr>'
                f'<th>{escape(_("COA Code"))}</th>'
                f'<th>{escape(_("Account Name"))}</th>'
                f'<th class="text-end">{escape(_("Actual"))}</th>'
                '</tr></thead>'
                f'<tbody>{"".join(body)}</tbody>'
                '<tfoot><tr class="fw-bold border-top">'
                f'<td colspan="2">{escape(_("Net Profit / Loss"))}</td>'
                f'<td class="text-end {profit_class}">{escape(format_amount(self.env, net_profit, project.currency_id))}</td>'
                '</tr></tfoot>'
                '</table></div>'
            )

    def action_open_profit_loss(self):
        self.ensure_one()
        self._check_financial_access()
        self.check_access_rule("read")
        if self.company_id not in self.env.companies:
            raise AccessError(_("The project company is not among your allowed companies."))
        if self.pnl_configuration_state != "ok":
            raise UserError(self.pnl_configuration_message)
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": "project.project",
            "res_id": self.id,
            "view_mode": "form",
            "views": [(self.env.ref("project.edit_project").id, "form")],
            "target": "current",
            "context": {
                **self.env.context,
                "mmp_open_financial_profitability": True,
            },
        }

    def action_open_journal_history(self):
        self.ensure_one()
        self._check_financial_access()
        self.check_access_rule("read")
        if self.company_id not in self.env.companies:
            raise AccessError(_("The project company is not among your allowed companies."))
        return self._project_financial_line_action("mmp_project_profit_loss.action_project_journal_history")

    def _project_financial_line_action(self, xmlid):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(xmlid)
        action["domain"] = [("project_id", "=", self.id)]
        action["context"] = {"default_project_id": self.id, "search_default_project_id": self.id}
        return action
