# -*- coding: utf-8 -*-
"""
SaleOrder — Herencia única de sale.order para BioMed.

Fusiona la lógica de ventas internas (action_confirm) y
eCommerce (_verify_updated_quantity) en una sola clase,
con métodos compartidos de validación.
"""

import logging
from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ─── Validaciones compartidas ─────────────────────────────────────────

    @staticmethod
    def _check_prescription_approved(tmpl):
        """Valida que la receta esté aprobada por IA si es requerida.

        Args:
            tmpl: recordset de product.template

        Raises:
            UserError si la receta no está aprobada.
        """
        if tmpl.requires_prescription and not tmpl.receta_aprobada_ia:
            raise UserError(
                f"🚫 BioMed — Receta rechazada\n\n"
                f"'{tmpl.name}' requiere receta médica válida.\n"
                f"La última receta analizada fue RECHAZADA por el sistema IA.\n\n"
                f"El paciente debe presentar una receta válida y ejecutar "
                f"'ANALIZAR RECETA CON IA' antes de procesar la venta."
            )

    @staticmethod
    def _check_stock_available(tmpl, product, qty):
        """Valida que hay stock suficiente del producto.

        Args:
            tmpl:    recordset de product.template
            product: recordset de product.product (variante)
            qty:     cantidad solicitada

        Raises:
            UserError si el stock es insuficiente.
        """
        stock_disponible = product.qty_available
        if qty > stock_disponible:
            if stock_disponible <= 0:
                raise UserError(
                    f"🚫 Stock agotado: '{tmpl.name}'\n\n"
                    f"No hay unidades disponibles en inventario.\n"
                    f"Ve a BioMed → Panel de Control → Pedir Stock a Compras."
                )
            raise UserError(
                f"⚠️ Stock insuficiente: '{tmpl.name}'\n\n"
                f"  Cantidad pedida  : {int(qty)} unidades\n"
                f"  Stock disponible : {int(stock_disponible)} unidades\n\n"
                f"Ajusta la cantidad o solicita reposición en BioMed App."
            )

    # ─── Override ventas internas ─────────────────────────────────────────

    def action_confirm(self):
        """Bloquea confirmación si receta rechazada o stock insuficiente."""
        for order in self:
            for line in order.order_line:
                tmpl = line.product_id.product_tmpl_id
                if not tmpl.is_medicine:
                    continue
                self._check_prescription_approved(tmpl)
                self._check_stock_available(
                    tmpl, line.product_id, line.product_uom_qty,
                )
        return super().action_confirm()

    # ─── Override carrito eCommerce ───────────────────────────────────────

    def _verify_updated_quantity(self, order_line, product_id, qty, **kwargs):
        """Controla el carrito de website_sale:
        A) Medicamento en borrador → no disponible
        B) Receta rechazada → bloqueado
        C) Stock insuficiente → bloqueado
        """
        product = self.env['product.product'].browse(product_id)
        tmpl = product.product_tmpl_id

        if tmpl.is_medicine:
            # Control A: no liberado por FDA
            gestion = self.env['farmacia.gestion'].search(
                [('medicamento_id', '=', tmpl.id)], limit=1,
            )
            if gestion and gestion.estado == 'borrador':
                raise UserError(
                    f"🚫 '{tmpl.name}' no está disponible.\n"
                    f"Pendiente de validación sanitaria (FDA)."
                )

            # Control B: receta rechazada
            self._check_prescription_approved(tmpl)

            # Control C: stock insuficiente
            self._check_stock_available(tmpl, product, qty)

        return super()._verify_updated_quantity(
            order_line, product_id, qty, **kwargs,
        )
