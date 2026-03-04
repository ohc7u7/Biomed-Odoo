/** @odoo-module **/
/**
 * BioMed Dashboard — Odoo 18
 * [FIX] "rpc" service no existe en Odoo 18 → usar "orm" service
 *       orm.call(model, method, args, kwargs) reemplaza al RPC manual
 */

import { registry }   from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

export class BiomedDashboard extends Component {
    static template = "farmacia_bio.BiomedDashboard";
    static props    = {};

    setup() {
        this.orm    = useService("orm");      // Odoo 18: orm, NO rpc
        this.action = useService("action");
        this.state  = useState({
            loading: true,
            data: {
                total_medicamentos:  0,
                stock_critico:       0,
                procesados:          0,
                en_revision:         0,
                sin_stock:           0,
                total_analisis:      0,
                analisis_con_riesgo: 0,
                analisis_hoy:        0,
                recetas_aprobadas:   0,
                recetas_rechazadas:  0,
                top_meds:            [],
            }
        });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        try {
            // Odoo 18: orm.call(model, method, args, kwargs)
            this.state.data = await this.orm.call(
                "farmacia.gestion",
                "get_dashboard_data",
                [],
                {}
            );
        } catch (e) {
            console.error("[BioMed Dashboard] Error:", e);
        } finally {
            this.state.loading = false;
        }
    }

    goToGestion() {
        this.action.doAction("farmacia_bio.action_farmacia_main");
    }

    goToHistorial() {
        this.action.doAction("farmacia_bio.action_farmacia_historial");
    }

    goToCriticos() {
        this.action.doAction({
            type:      "ir.actions.act_window",
            name:      "⚠️ Stock Crítico",
            res_model: "farmacia.gestion",
            view_mode: "list,form",
            domain:    [["alerta_stock", "=", "critico"]],
        });
    }
}

registry.category("actions").add("biomed_dashboard", BiomedDashboard);