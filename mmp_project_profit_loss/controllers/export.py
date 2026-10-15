import io

from odoo import http
from odoo.http import content_disposition, request
from odoo.tools.misc import xlsxwriter


class ProjectProfitLossExport(http.Controller):
    def _workbook_response(self, filename, builder):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        builder(workbook)
        workbook.close()
        return request.make_response(
            output.getvalue(),
            headers=[
                ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )

    def _wizard(self, wizard_id):
        wizard = request.env["mmp.project.profit.loss.wizard"].browse(wizard_id).exists()
        wizard._check_access()
        return wizard

    @http.route("/mmp_project_profit_loss/export/pnl/<int:wizard_id>", type="http", auth="user")
    def export_pnl(self, wizard_id, **kwargs):
        wizard = self._wizard(wizard_id)
        lines = request.env["mmp.project.profit.loss.line"].search(wizard._domain(), order="section, account_code")
        grouped = {}
        for line in lines:
            key = (line.section, line.account_code, line.account_name, line.account_type)
            values = grouped.setdefault(key, [0.0, 0.0, 0.0])
            values[0] += line.allocated_debit
            values[1] += line.allocated_credit
            values[2] += line.net_financial_amount

        def build(workbook):
            sheet = workbook.add_worksheet("Project P&L")
            bold = workbook.add_format({"bold": True})
            money = workbook.add_format({"num_format": "#,##0.00;[Red]-#,##0.00"})
            headers = ["Project", "Company", "Section", "COA Code", "COA Name", "Account Type", "Debit Allocation", "Credit Allocation", "Net Financial Amount"]
            sheet.write_row(0, 0, ["Project", wizard.project_id.display_name])
            sheet.write_row(1, 0, ["Company", wizard.company_id.display_name])
            sheet.write_row(2, 0, ["Date Range", str(wizard.date_from or "All Time"), str(wizard.date_to or "All Time")])
            sheet.write_row(4, 0, headers, bold)
            for row, ((section, code, name, account_type), amounts) in enumerate(grouped.items(), 5):
                sheet.write_row(row, 0, [wizard.project_id.display_name, wizard.company_id.display_name, dict(lines._fields["section"].selection).get(section), code, name, account_type])
                sheet.write_row(row, 6, amounts, money)
            sheet.autofilter(4, 0, max(len(grouped) + 4, 5), len(headers) - 1)
            sheet.freeze_panes(5, 0)
            sheet.set_column(0, 5, 22)
            sheet.set_column(6, 8, 18)

        return self._workbook_response(f"project-pnl-{wizard.project_id.id}.xlsx", build)

    @http.route("/mmp_project_profit_loss/export/history/<int:wizard_id>", type="http", auth="user")
    def export_history(self, wizard_id, **kwargs):
        wizard = self._wizard(wizard_id)
        lines = request.env["mmp.project.profit.loss.line"].search(wizard._domain(), order="date, move_line_id")

        def build(workbook):
            sheet = workbook.add_worksheet("Journal History")
            bold = workbook.add_format({"bold": True})
            money = workbook.add_format({"num_format": "#,##0.00;[Red]-#,##0.00"})
            headers = ["Date", "Journal Entry", "Journal", "Partner", "COA Code", "COA Name", "Debit", "Credit", "Analytic %", "Allocated Amount", "Company"]
            sheet.write_row(0, 0, headers, bold)
            for row, line in enumerate(lines, 1):
                sheet.write_row(row, 0, [str(line.date), line.move_name, line.journal_id.display_name, line.partner_id.display_name, line.account_code, line.account_name])
                sheet.write_row(row, 6, [line.debit, line.credit, line.analytic_percentage, line.allocated_balance], money)
                sheet.write(row, 10, line.company_id.display_name)
            sheet.autofilter(0, 0, max(len(lines), 1), len(headers) - 1)
            sheet.freeze_panes(1, 0)
            sheet.set_column(0, 5, 20)
            sheet.set_column(6, 10, 18)

        return self._workbook_response(f"project-journal-history-{wizard.project_id.id}.xlsx", build)
