from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError


class ProjectProfitLossLine(models.Model):
    _name = "mmp.project.profit.loss.line"
    _description = "Project Profit and Loss Journal Allocation"
    _auto = False
    _rec_name = "move_name"
    _order = "date desc, move_line_id desc"

    project_id = fields.Many2one("project.project", readonly=True)
    analytic_account_id = fields.Many2one("account.analytic.account", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    date = fields.Date(readonly=True)
    move_line_id = fields.Many2one("account.move.line", string="Journal Item", readonly=True)
    move_id = fields.Many2one("account.move", string="Journal Entry", readonly=True)
    move_name = fields.Char(string="Journal Entry Number", readonly=True)
    journal_id = fields.Many2one("account.journal", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    account_id = fields.Many2one("account.account", string="COA", readonly=True)
    account_code = fields.Char(string="COA Code", readonly=True)
    account_name = fields.Char(related="account_id.name", string="COA Name", readonly=True)
    account_type = fields.Selection(selection=lambda self: self.env["account.account"]._fields["account_type"].selection, readonly=True)
    section = fields.Selection(
        [
            ("revenue", "Revenue"),
            ("direct_cost", "Direct Costs"),
            ("operating_expense", "Operating Expenses"),
            ("other_income", "Other Income"),
        ],
        readonly=True,
    )
    debit = fields.Monetary(string="Debit", currency_field="currency_id", readonly=True)
    credit = fields.Monetary(string="Credit", currency_field="currency_id", readonly=True)
    analytic_percentage = fields.Float(string="Analytic Percentage", readonly=True, digits=(16, 4))
    allocated_debit = fields.Monetary(string="Debit Allocation", currency_field="currency_id", readonly=True)
    allocated_credit = fields.Monetary(string="Credit Allocation", currency_field="currency_id", readonly=True)
    allocated_balance = fields.Monetary(string="Allocated Amount", currency_field="currency_id", readonly=True)
    revenue = fields.Monetary(currency_field="currency_id", readonly=True)
    cost = fields.Monetary(currency_field="currency_id", readonly=True)
    net_financial_amount = fields.Monetary(string="Net Financial Amount", currency_field="currency_id", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH unique_project_analytic AS (
                    SELECT analytic_account_id, company_id, MIN(id) AS project_id
                      FROM project_project
                     WHERE analytic_account_id IS NOT NULL
                  GROUP BY analytic_account_id, company_id
                    HAVING COUNT(*) = 1
                ), distribution AS (
                    SELECT aml.id AS move_line_id,
                           upa.project_id,
                           upa.analytic_account_id,
                           SUM(
                               CASE WHEN dist.value ~ '^[+]?[0-9]+([.][0-9]+)?$'
                                    THEN dist.value::numeric ELSE 0 END
                           ) AS percentage
                      FROM account_move_line aml
                      JOIN account_move source_move ON source_move.id = aml.move_id AND source_move.state = 'posted'
                      JOIN account_account source_account ON source_account.id = aml.account_id
                       AND source_account.account_type IN (
                           'income', 'income_other', 'expense',
                           'expense_direct_cost', 'expense_depreciation'
                       )
                      CROSS JOIN LATERAL jsonb_each_text(
                          CASE WHEN jsonb_typeof(aml.analytic_distribution) = 'object'
                               THEN aml.analytic_distribution ELSE '{{}}'::jsonb END
                      ) AS dist(key, value)
                      JOIN unique_project_analytic upa
                        ON upa.company_id = aml.company_id
                       AND upa.analytic_account_id::text = ANY(string_to_array(dist.key, ','))
                     WHERE aml.analytic_distribution IS NOT NULL
                       AND CASE WHEN dist.value ~ '^[+]?[0-9]+([.][0-9]+)?$'
                                THEN dist.value::numeric ELSE 0 END > 0
                       AND ARRAY[upa.analytic_account_id::text] && regexp_split_to_array(
                           jsonb_path_query_array(aml.analytic_distribution, '$.keyvalue()."key"')::text,
                           '\\D+'
                       )
                  GROUP BY aml.id, upa.project_id, upa.analytic_account_id
                )
                SELECT (('x' || substr(md5(aml.id::text || ':' || d.project_id::text), 1, 15))::bit(60)::bigint) AS id,
                       d.project_id,
                       d.analytic_account_id,
                       aml.company_id,
                       company.currency_id,
                       aml.date,
                       aml.id AS move_line_id,
                       aml.move_id,
                       move.name AS move_name,
                       aml.journal_id,
                       aml.partner_id,
                       aml.account_id,
                       account.code AS account_code,
                       account.account_type,
                       CASE
                           WHEN account.account_type = 'income' THEN 'revenue'
                           WHEN account.account_type = 'income_other' THEN 'other_income'
                           WHEN account.account_type = 'expense_direct_cost' THEN 'direct_cost'
                           ELSE 'operating_expense'
                       END AS section,
                       aml.debit,
                       aml.credit,
                       d.percentage AS analytic_percentage,
                       aml.debit * d.percentage / 100.0 AS allocated_debit,
                       aml.credit * d.percentage / 100.0 AS allocated_credit,
                       aml.balance * d.percentage / 100.0 AS allocated_balance,
                       CASE WHEN account.account_type IN ('income', 'income_other')
                            THEN -aml.balance * d.percentage / 100.0 ELSE 0 END AS revenue,
                       CASE WHEN account.account_type IN ('expense', 'expense_direct_cost', 'expense_depreciation')
                            THEN aml.balance * d.percentage / 100.0 ELSE 0 END AS cost,
                       -aml.balance * d.percentage / 100.0 AS net_financial_amount
                  FROM distribution d
                  JOIN account_move_line aml ON aml.id = d.move_line_id
                  JOIN account_move move ON move.id = aml.move_id AND move.state = 'posted'
                  JOIN account_account account ON account.id = aml.account_id
                  JOIN res_company company ON company.id = aml.company_id
                 WHERE account.account_type IN (
                       'income', 'income_other', 'expense',
                       'expense_direct_cost', 'expense_depreciation'
                 )
            )
            """
        )

    def action_open_journal_item(self):
        self.ensure_one()
        self.env["account.move.line"].check_access_rights("read")
        self.move_line_id.check_access_rule("read")
        self.env["account.move"].check_access_rights("read")
        self.move_id.check_access_rule("read")
        return {
            "type": "ir.actions.act_window",
            "name": _("Journal Entry"),
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "views": [(self.env.ref("account.view_move_form").id, "form")],
            "target": "current",
        }

    def get_formview_action(self, access_uid=None):
        return self.action_open_journal_item()

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_("Project financial allocations are read-only."))

    def write(self, vals):
        raise AccessError(_("Project financial allocations are read-only."))

    def unlink(self):
        raise AccessError(_("Project financial allocations are read-only."))
