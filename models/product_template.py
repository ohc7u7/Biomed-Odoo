# -*- coding: utf-8 -*-
"""
ProductTemplate + ProductProduct — Campos médicos y herencias de producto.
"""

import logging
import requests
from odoo import models, fields, api
from odoo.exceptions import UserError
from .constants import FDA_API_BASE, FDA_API_TIMEOUT

_logger = logging.getLogger(__name__)


# ─── ProductTemplate ──────────────────────────────────────────────────────────
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_medicine = fields.Boolean(
        string='Es Medicamento', default=False,
    )
    active_component = fields.Char(
        string='Principio Activo',
    )
    fda_status = fields.Char(
        string='Estado Sanitario (FDA)', readonly=True, store=True,
    )
    requires_prescription = fields.Boolean(
        string='Requiere Receta Obligatoria', default=False,
    )
    prescription_file = fields.Binary(
        string='Receta Digital',
    )
    receta_aprobada_ia = fields.Boolean(
        string='Receta Aprobada por IA', default=False, readonly=True,
        help="True = puede comprarse. False = compra bloqueada.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        for product in products:
            if product.is_medicine:
                try:
                    name_part = (
                        product.name[:3] if len(product.name) >= 3
                        else product.name
                    ).upper()
                    self.env['farmacia.gestion'].create({
                        'medicamento_id': product.id,
                        'name': f"AUTO-{name_part}-{fields.Date.today()}",
                    })
                except Exception as e:
                    _logger.error(
                        "Error creando farmacia.gestion para %s: %s",
                        product.name, e,
                    )
        return products

    def action_validate_medicine_api(self):
        """Valida el medicamento contra la API de la FDA (openFDA)."""
        for record in self:
            if not record.name:
                continue
            search_term = record.name.split()[0].strip().lower()
            url = (
                f"{FDA_API_BASE}"
                f"?search=openfda.brand_name:{search_term}"
                f"+openfda.generic_name:{search_term}&limit=1"
            )
            try:
                response = requests.get(url, timeout=FDA_API_TIMEOUT)
                if response.status_code == 200:
                    data = response.json()
                    results = data.get('results', [])
                    if not results:
                        record.write({
                            'active_component': 'N/A',
                            'fda_status': "NO ENCONTRADO",
                        })
                        continue
                    openfda = results[0].get('openfda', {})
                    brand_names = [
                        b.lower() for b in openfda.get('brand_name', [])
                    ]
                    generic_names = [
                        g.lower() for g in openfda.get('generic_name', [])
                    ]
                    if (any(search_term in b for b in brand_names)
                            or any(search_term in g for g in generic_names)):
                        g_name = (
                            generic_names[0] if generic_names
                            else 'DESCONOCIDO'
                        )
                        record.write({
                            'active_component': g_name.upper(),
                            'fda_status': "APROBADO (REGISTRO FDA)",
                        })
                    else:
                        record.write({
                            'active_component': 'N/A',
                            'fda_status': "RECHAZADO: NO ES UN FÁRMACO",
                        })
                else:
                    record.write({
                        'active_component': 'N/A',
                        'fda_status': "SIN REGISTRO FDA",
                    })
            except Exception as e:
                _logger.error("Error FDA: %s", e)
                record.write({'fda_status': "ERROR DE CONEXIÓN"})

    def action_restock_purchase(self, qty=50.0, partner_id=False):
        """Genera una orden de compra para reabastecer stock."""
        orders = self.env['purchase.order']
        for record in self:
            if not record.product_variant_id:
                raise UserError(
                    f"Variante no configurada: {record.name}"
                )
            if not partner_id:
                raise UserError(
                    "Partner requerido para crear orden de compra"
                )
            new_order = self.env['purchase.order'].create({
                'partner_id': partner_id,
                'order_line': [(0, 0, {
                    'product_id': record.product_variant_id.id,
                    'name': f"Abastecimiento BioMed: {record.name}",
                    'product_qty': qty,
                    'price_unit': record.standard_price or 10.0,
                    'date_planned': fields.Datetime.now(),
                })],
            })
            orders += new_order
        return orders

    def action_abrir_wizard_inventario(self):
        """Abre el wizard de ajuste de inventario."""
        self.ensure_one()
        if not self.product_variant_id:
            raise UserError("Producto sin variante activa")
        return {
            'name': 'Agregar Unidades al Inventario',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.change.product.qty',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_id': self.product_variant_id.id,
                'default_product_tmpl_id': self.id,
                'default_new_quantity': self.qty_available,
            },
        }


# ─── ProductProduct — POS domain con receta_aprobada_ia ──────────────────────
class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _get_pos_ui_product_domain(self):
        res = super()._get_pos_ui_product_domain()
        biomed_domain = [
            '|',
            ('product_tmpl_id.is_medicine', '=', False),
            '&', '&', '&',
            ('product_tmpl_id.is_medicine', '=', True),
            ('product_tmpl_id.fda_status', '=', 'APROBADO (REGISTRO FDA)'),
            ('qty_available', '>', 0),
            '|',
            ('product_tmpl_id.requires_prescription', '=', False),
            ('product_tmpl_id.receta_aprobada_ia', '=', True),
        ]
        return res + biomed_domain
