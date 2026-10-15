from datetime import date

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProjectProfitLoss(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.group = cls.env.ref("mmp_project_profit_loss.group_project_financial_viewer")
        cls.env.user.groups_id = [Command.link(cls.group.id)]
        cls.plan = cls.env["account.analytic.plan"].create({"name": "Project P&L Test"})
        cls.aa_a = cls._analytic("Project A")
        cls.aa_b = cls._analytic("Project B")
        cls.aa_dimension = cls._analytic("Department")
        cls.project_a = cls._project("Project A", cls.aa_a)
        cls.project_b = cls._project("Project B", cls.aa_b)
        cls.revenue_account = cls._account("TPLREV", "Test Revenue", "income")
        cls.other_income_account = cls._account("TPLOTH", "Test Other Income", "income_other")
        cls.expense_account = cls._account("TPLEXP", "Test Expense", "expense")
        cls.direct_cost_account = cls._account("TPLCOS", "Test Direct Cost", "expense_direct_cost")
        cls.balance_account = cls._account("TPLBAL", "Test Current Asset", "asset_current")
        cls.receivable_account = cls._account("TPLREC", "Test Receivable", "asset_receivable")
        cls.payable_account = cls._account("TPLPAY", "Test Payable", "liability_payable")
        cls.partner = cls.env["res.partner"].create({"name": "Project P&L Partner"})
        cls.partner.with_company(cls.company).write({
            "property_account_receivable_id": cls.receivable_account.id,
            "property_account_payable_id": cls.payable_account.id,
        })
        cls.journal = cls.env["account.journal"].create({
            "name": "Project P&L Test", "code": "TPL", "type": "general", "company_id": cls.company.id,
        })
        cls.sale_journal = cls.env["account.journal"].create({
            "name": "Project P&L Sales", "code": "TPS", "type": "sale", "company_id": cls.company.id,
        })
        cls.purchase_journal = cls.env["account.journal"].create({
            "name": "Project P&L Purchases", "code": "TPP", "type": "purchase", "company_id": cls.company.id,
        })

    @classmethod
    def _analytic(cls, name, company=None):
        return cls.env["account.analytic.account"].create({
            "name": name, "plan_id": cls.plan.id, "company_id": (company or cls.company).id,
        })

    @classmethod
    def _project(cls, name, analytic, company=None):
        return cls.env["project.project"].create({
            "name": name, "company_id": (company or cls.company).id, "analytic_account_id": analytic.id,
        })

    @classmethod
    def _account(cls, code, name, account_type, company=None):
        return cls.env["account.account"].create({
            "code": code, "name": name, "account_type": account_type,
            "company_id": (company or cls.company).id,
        })

    def _entry(self, account, balance, distribution=None, state="posted", entry_date=None, company=None,
               journal=None, counterpart=None, move_type="entry"):
        company = company or self.company
        if move_type in ("out_invoice", "out_refund"):
            journal = journal or self.sale_journal
            counterpart = counterpart or self.receivable_account
        elif move_type in ("in_invoice", "in_refund"):
            journal = journal or self.purchase_journal
            counterpart = counterpart or self.payable_account
        partner = self.partner if move_type != "entry" else self.env["res.partner"]
        move_values = {
            "move_type": move_type,
            "partner_id": partner.id,
            "date": entry_date or date(2026, 1, 15),
            "journal_id": (journal or self.journal).id,
        }
        if move_type == "entry":
            move_values["line_ids"] = [
                Command.create({
                    "name": "Project amount", "account_id": account.id,
                    "debit": max(balance, 0), "credit": max(-balance, 0),
                    "analytic_distribution": distribution,
                    "partner_id": partner.id,
                }),
                Command.create({
                    "name": "Counterpart", "account_id": (counterpart or self.balance_account).id,
                    "debit": max(-balance, 0), "credit": max(balance, 0),
                    "partner_id": partner.id,
                }),
            ]
        else:
            move_values["invoice_date"] = entry_date or date(2026, 1, 15)
            move_values["invoice_line_ids"] = [Command.create({
                "name": "Project amount",
                "account_id": account.id,
                "quantity": 1,
                "price_unit": abs(balance),
                "analytic_distribution": distribution,
            })]
        move = self.env["account.move"].with_company(company).create(move_values)
        if state == "posted":
            move.action_post()
        return move

    def _totals(self, project, domain=None):
        domain = [("project_id", "=", project.id)] + (domain or [])
        rows = self.env["mmp.project.profit.loss.line"]._read_group(
            domain, [], ["revenue:sum", "cost:sum", "net_financial_amount:sum"]
        )
        return rows[0] if rows else (0.0, 0.0, 0.0)

    def test_01_posted_revenue_100_percent(self):
        self._entry(self.revenue_account, -1000, {str(self.aa_a.id): 100}, move_type="out_invoice")
        self.assertEqual(self._totals(self.project_a), (1000, 0, 1000))

    def test_02_posted_vendor_cost_100_percent(self):
        self._entry(self.expense_account, 400, {str(self.aa_a.id): 100}, move_type="in_invoice")
        self.assertEqual(self._totals(self.project_a), (0, 400, -400))

    def test_03_split_allocation_two_projects(self):
        self._entry(self.expense_account, 10000000, {str(self.aa_a.id): 70, str(self.aa_b.id): 30})
        self.assertEqual(self._totals(self.project_a)[1], 7000000)
        self.assertEqual(self._totals(self.project_b)[1], 3000000)

    def test_04_draft_is_excluded(self):
        self._entry(self.revenue_account, -1000, {str(self.aa_a.id): 100}, state="draft")
        self.assertEqual(self._totals(self.project_a), (0, 0, 0))

    def test_05_balance_sheet_is_excluded(self):
        other_asset = self._account("TPLBA2", "Other Asset", "asset_current")
        self._entry(self.balance_account, 500, {str(self.aa_a.id): 100}, counterpart=other_asset)
        self.assertEqual(self._totals(self.project_a), (0, 0, 0))

    def test_06_credit_note_reduces_revenue(self):
        self._entry(self.revenue_account, -1000, {str(self.aa_a.id): 100}, move_type="out_invoice")
        self._entry(self.revenue_account, 250, {str(self.aa_a.id): 100}, move_type="out_refund")
        self.assertEqual(self._totals(self.project_a)[0], 750)

    def test_07_vendor_refund_reduces_cost(self):
        self._entry(self.expense_account, 600, {str(self.aa_a.id): 100}, move_type="in_invoice")
        self._entry(self.expense_account, -100, {str(self.aa_a.id): 100}, move_type="in_refund")
        self.assertEqual(self._totals(self.project_a)[1], 500)

    def test_08_reversing_entry_changes_results(self):
        self._entry(self.expense_account, 600, {str(self.aa_a.id): 100})
        self._entry(self.expense_account, -600, {str(self.aa_a.id): 100})
        self.assertEqual(self._totals(self.project_a), (0, 0, 0))

    def test_09_multi_company_isolation(self):
        company_2 = self.env["res.company"].create({"name": "P&L Company 2"})
        self.env.user.company_ids = [Command.link(company_2.id)]
        aa_2 = self.env["account.analytic.account"].create({"name": "Project C", "plan_id": self.plan.id, "company_id": company_2.id})
        project_2 = self._project("Project C", aa_2, company_2)
        revenue_2 = self._account("TPLREV", "Revenue C2", "income", company_2)
        balance_2 = self._account("TPLBAL", "Asset C2", "asset_current", company_2)
        journal_2 = self.env["account.journal"].create({"name": "P&L C2", "code": "TPC", "type": "general", "company_id": company_2.id})
        self._entry(revenue_2, -900, {str(aa_2.id): 100}, company=company_2, journal=journal_2, counterpart=balance_2)
        self.assertEqual(self._totals(project_2)[0], 900)
        self.assertEqual(self._totals(self.project_a)[0], 0)

    def test_10_date_filtering(self):
        self._entry(self.revenue_account, -100, {str(self.aa_a.id): 100}, entry_date=date(2025, 12, 31))
        self._entry(self.revenue_account, -200, {str(self.aa_a.id): 100}, entry_date=date(2026, 1, 1))
        self.assertEqual(self._totals(self.project_a, [("date", ">=", date(2026, 1, 1))])[0], 200)

    def test_11_history_total_equals_profit_loss(self):
        self._entry(self.revenue_account, -1000, {str(self.aa_a.id): 100})
        self._entry(self.expense_account, 350, {str(self.aa_a.id): 100})
        lines = self.env["mmp.project.profit.loss.line"].search([("project_id", "=", self.project_a.id)])
        self.assertEqual(sum(lines.mapped("net_financial_amount")), self._totals(self.project_a)[2])

    def test_12_combined_analytic_distribution_key(self):
        key = f"{self.aa_a.id},{self.aa_dimension.id}"
        self._entry(self.expense_account, 500, {key: 100})
        self.assertEqual(self._totals(self.project_a)[1], 500)
        self.assertEqual(self.env["mmp.project.profit.loss.line"].search_count([("project_id", "=", self.project_a.id)]), 1)

    def test_13_shared_and_missing_analytic_account(self):
        missing = self.env["project.project"].create({"name": "Missing Analytic", "company_id": self.company.id})
        shared = self._project("Shared", self.aa_a)
        self._entry(self.revenue_account, -1000, {str(self.aa_a.id): 100})
        self.assertEqual(self._totals(self.project_a), (0, 0, 0))
        self.assertEqual(self._totals(shared), (0, 0, 0))
        self.assertEqual(missing.pnl_configuration_state, "missing")
        self.assertEqual(shared.pnl_configuration_state, "shared")

    def test_14_security_access_restrictions(self):
        user = self.env["res.users"].create({
            "name": "No Financial Access", "login": "no-financial-access",
            "groups_id": [Command.set([self.env.ref("project.group_project_user").id])],
        })
        with self.assertRaises(AccessError):
            self.project_a.with_user(user).action_open_profit_loss()
        with self.assertRaises(AccessError):
            self.env["mmp.project.profit.loss.line"].with_user(user).search([])

    def test_15_kanban_totals_match_detail(self):
        self._entry(self.revenue_account, -1000, {str(self.aa_a.id): 100})
        self._entry(self.direct_cost_account, 300, {str(self.aa_a.id): 100})
        revenue, cost, profit = self._totals(self.project_a)
        self.project_a.invalidate_recordset()
        self.assertEqual((self.project_a.pnl_revenue, self.project_a.pnl_cost, self.project_a.pnl_profit), (revenue, cost, profit))
        self.assertAlmostEqual(self.project_a.pnl_margin, 70.0)
        wizard = self.env["mmp.project.profit.loss.wizard"].create({"project_id": self.project_a.id})
        self.assertAlmostEqual(wizard.margin, 70.0)
        self.assertIn("TPLREV", self.project_a.pnl_account_detail_html)
        self.assertIn("TPLCOS", self.project_a.pnl_account_detail_html)
        self.assertIn("Net Profit / Loss", self.project_a.pnl_account_detail_html)
        action = self.project_a.action_open_profit_loss()
        self.assertEqual(action["res_model"], "project.project")
        self.assertEqual(action["res_id"], self.project_a.id)
        self.assertTrue(action["context"]["mmp_open_financial_profitability"])
