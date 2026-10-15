/** @odoo-module **/

import { ProjectFormRenderer } from "@project/views/project_form/project_form_renderer";
import { patch } from "@web/core/utils/patch";
import { onMounted, useRef } from "@odoo/owl";

patch(ProjectFormRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        const formRoot = useRef("compiled_view_root");
        onMounted(() => {
            if (!this.props.record.context.mmp_open_financial_profitability) {
                return;
            }
            formRoot.el
                ?.querySelector('.nav-link[name="financial_profitability"]')
                ?.click();
        });
    },
});
