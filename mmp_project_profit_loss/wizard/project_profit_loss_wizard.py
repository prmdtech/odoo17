from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


FINANCIAL_GROUP = "mmp_project_profit_loss.group_project_financial_viewer"


class ProjectProfitLossWizard(models.TransientModel):
    _name = "mmp.project.profit.loss.wizard"
    _description = "Project Profit and Loss"

    project_id = fields.Many2one("project.project", required=True, domain="[('company_id', 'in', allowed_company_ids)]")
    company_id = fields.Many2one(related="project_id.company_id", readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    allowed_company_ids = fields.Many2many("res.company", compute="_compute_allowed_company_ids")
    period = fields.Selection(
        [("all", "All Time"), ("month", "This Month"), ("year", "This Year"), ("custom", "Custom")],
        required=True, default="all",
    )
    date_from = fields.Date()
    date_to = fields.Date()
    revenue = fields.Monetary(compute="_compute_totals", currency_field="currency_id")
    direct_cost = fields.Monetary(compute="_compute_totals", currency_field="currency_id")
    gross_profit = fields.Monetary(compute="_compute_totals", currency_field="currency_id")
    operating_expense = fields.Monetary(compute="_compute_totals", currency_field="currency_id")
    other_income = fields.Monetary(compute="_compute_totals", currency_field="currency_id")
    net_profit = fields.Monetary(compute="_compute_totals", currency_field="currency_id")
    margin = fields.Float(string="Profit Margin (%)", compute="_compute_totals", digits=(16, 2))
    margin_available = fields.Boolean(compute="_compute_totals")

    @api.depends_context("allowed_company_ids")
    def _compute_allowed_company_ids(self):
        for wizard in self:
            wizard.allowed_company_ids = self.env.companies

    @api.onchange("period")
    def _onchange_period(self):
        today = fields.Date.context_today(self)
        if self.period == "month":
            self.date_from = today.replace(day=1)
            self.date_to = self.date_from + relativedelta(months=1, days=-1)
        elif self.period == "year":
            self.date_from = today.replace(month=1, day=1)
            self.date_to = today.replace(month=12, day=31)
        elif self.period == "all":
            self.date_from = False
            self.date_to = False

    @api.constrains("period", "date_from", "date_to")
    def _check_dates(self):
        for wizard in self:
            if wizard.period == "custom" and (not wizard.date_from or not wizard.date_to):
                raise ValidationError(_("Both dates are required for a custom period."))
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError(_("The start date cannot be after the end date."))

    def _domain(self):
        self.ensure_one()
        domain = [("project_id", "=", self.project_id.id)]
        if self.date_from:
            domain.append(("date", ">=", self.date_from))
        if self.date_to:
            domain.append(("date", "<=", self.date_to))
        return domain

    @api.depends("project_id", "period", "date_from", "date_to")
    def _compute_totals(self):
        for wizard in self:
            totals = {key: 0.0 for key in ("revenue", "direct_cost", "operating_expense", "other_income")}
            if wizard.project_id and self.env.user.has_group(FINANCIAL_GROUP):
                rows = self.env["mmp.project.profit.loss.line"]._read_group(
                    wizard._domain(), ["section"], ["net_financial_amount:sum"]
                )
                for section, amount in rows:
                    totals[section] = amount or 0.0
            wizard.revenue = totals["revenue"]
            wizard.direct_cost = -totals["direct_cost"]
            wizard.gross_profit = totals["revenue"] + totals["direct_cost"]
            wizard.operating_expense = -totals["operating_expense"]
            wizard.other_income = totals["other_income"]
            wizard.net_profit = sum(totals.values())
            wizard.margin_available = wizard.revenue > 0
            wizard.margin = wizard.net_profit / wizard.revenue * 100 if wizard.revenue > 0 else 0.0

    def _check_access(self):
        self.ensure_one()
        if not self.env.user.has_group(FINANCIAL_GROUP):
            raise AccessError(_("You are not allowed to view project financial information."))
        self.project_id.check_access_rule("read")
        if self.project_id.company_id not in self.env.companies:
            raise AccessError(_("The project company is not among your allowed companies."))

    def action_open_details(self):
        self._check_access()
        action = self.env["ir.actions.actions"]._for_xml_id("mmp_project_profit_loss.action_project_profit_loss_detail")
        action["domain"] = self._domain()
        action["context"] = {"search_default_group_by_section": 1, "search_default_group_by_account": 1}
        return action

    def action_open_history(self):
        self._check_access()
        action = self.env["ir.actions.actions"]._for_xml_id("mmp_project_profit_loss.action_project_journal_history")
        action["domain"] = self._domain()
        return action

    def action_export_profit_loss(self):
        self._check_access()
        return {"type": "ir.actions.act_url", "url": f"/mmp_project_profit_loss/export/pnl/{self.id}", "target": "self"}

    def action_export_history(self):
        self._check_access()
        return {"type": "ir.actions.act_url", "url": f"/mmp_project_profit_loss/export/history/{self.id}", "target": "self"}
