
{
    "name": "MMP Project Profit & Loss",
    "version": "17.0.1.0.0",
    "category": "Services/Project",
    "summary": "Actual project profitability from posted analytic journal items",
    "author": "MMP Consulting",
    "license": "LGPL-3",
    "depends": [
        "project",
        "account",
    ],
    "data": [
        "security/project_profit_loss_security.xml",
        "security/ir.model.access.csv",
        "wizard/project_profit_loss_wizard_views.xml",
        "views/project_profit_loss_views.xml",
        "views/project_project_views.xml",
        "views/project_profit_loss_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mmp_project_profit_loss/static/src/js/project_financial_tab.js",
        ],
    },
    "installable": True,
    "application": False,
}
