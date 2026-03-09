# -*- coding: utf-8 -*-
import logging
import base64
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class BiomedWebsiteController(http.Controller):

    @http.route(
        '/biomed/analizar-receta',
        type='json',
        auth='user',
        website=True,
        methods=['POST'],
    )
    def analizar_receta_website(self, product_id=None, imagen_b64=None, condiciones='', **kwargs):
        _logger.info("[BioMed] ===== PETICION RECIBIDA product_id=%s =====", product_id)

        if not product_id or not imagen_b64:
            return {'approved': False, 'html_response': '', 'error': 'Datos incompletos'}

        pid = int(product_id)

        # ── Resolver product.template ─────────────────────────────────────────
        # En website_sale, "product" en QWeb es product.product (variante)
        # Intentar como template primero, si no, buscar via variante
        tmpl = request.env['product.template'].sudo().browse(pid)
        if not tmpl.exists() or not tmpl.is_medicine:
            _logger.info("[BioMed] id=%s no es template, buscando como variante...", pid)
            variant = request.env['product.product'].sudo().browse(pid)
            if variant.exists():
                tmpl = variant.product_tmpl_id
                _logger.info("[BioMed] Encontrado via variante → template id=%s name=%s", tmpl.id, tmpl.name)
            else:
                _logger.error("[BioMed] Producto id=%s no encontrado", pid)
                return {'approved': False, 'html_response': '', 'error': f'Producto {pid} no encontrado'}

        if not tmpl.is_medicine:
            return {'approved': False, 'html_response': '', 'error': 'No es un medicamento'}

        if not tmpl.requires_prescription:
            return {'approved': True, 'html_response': '<p>Este medicamento no requiere receta.</p>', 'error': None}

        _logger.info("[BioMed] Medicamento: %s (id=%s)", tmpl.name, tmpl.id)

        # ── Buscar farmacia.gestion ───────────────────────────────────────────
        gestion = request.env['farmacia.gestion'].sudo().search(
            [('medicamento_id', '=', tmpl.id)], limit=1
        )
        if not gestion:
            _logger.error("[BioMed] No existe farmacia.gestion para template id=%s", tmpl.id)
            return {
                'approved': False,
                'html_response': '',
                'error': f'No existe panel farmacéutico para {tmpl.name}. Contacta al administrador.'
            }

        _logger.info("[BioMed] gestion id=%s encontrada", gestion.id)

        # ── Procesar y guardar imagen ─────────────────────────────────────────
        try:
            img = str(imagen_b64)
            if 'base64,' in img:
                img = img.split('base64,', 1)[1]
            img = img.strip()
            raw = base64.b64decode(img)
            img_b64_odoo = base64.b64encode(raw)

            # Escribir en product.template directamente
            # (gestion.receta_rel es related, se actualiza automáticamente)
            tmpl.sudo().write({'prescription_file': img_b64_odoo})
            _logger.info("[BioMed] Imagen guardada OK (%d bytes raw)", len(raw))

        except Exception as e:
            _logger.error("[BioMed] Error procesando imagen: %s", e)
            return {'approved': False, 'html_response': '', 'error': f'Error procesando imagen: {e}'}

        # ── Guardar condiciones ───────────────────────────────────────────────
        if condiciones and str(condiciones).strip():
            gestion.sudo().write({'condiciones_paciente': str(condiciones).strip()})

        # ── Limpiar cache para que action_analizar lea la imagen nueva ────────
        tmpl.invalidate_recordset(['prescription_file'])
        gestion.invalidate_recordset(['receta_rel'])

        # ── Ejecutar análisis IA ──────────────────────────────────────────────
        _logger.info("[BioMed] Iniciando action_analizar_receta_ia...")
        try:
            gestion.sudo().action_analizar_receta_ia()
            _logger.info("[BioMed] action_analizar_receta_ia completado")
        except Exception as e:
            _logger.error("[BioMed] Error en IA: %s", e, exc_info=True)
            return {
                'approved': False,
                'html_response': (
                    f'<div style="background:#f8d7da;border-left:4px solid #dc3545;'
                    f'padding:12px;border-radius:8px;color:#721c24;">'
                    f'<strong>⚠️ Error al analizar la receta</strong><br/>'
                    f'<small>{str(e)[:300]}</small></div>'
                ),
                'error': str(e)[:200],
            }

        # ── Leer resultado ────────────────────────────────────────────────────
        gestion.invalidate_recordset()
        tmpl.invalidate_recordset()

        approved = bool(tmpl.sudo().receta_aprobada_ia)
        html_response = gestion.sudo().ai_analysis_result or ''

        _logger.info("[BioMed] Resultado: aprobado=%s", approved)

        return {
            'approved': approved,
            'html_response': html_response,
            'error': None,
        }