# -*- coding: utf-8 -*-
# BioMed v2.3 — Farmacia Clínica Maestro
# [NEW-04] Flujo receta rechazada: bloquea compra sin cambiar estado del medicamento
# [NEW-05] Bloqueo en Website eCommerce via _verify_updated_quantity
# [NEW-06] Campo receta_aprobada_ia en ProductTemplate
# [FIX-15] action_analizar_receta_ia escribe receta_aprobada_ia según resultado Gemini

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError
import requests

_logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


# ─── 1. ProductTemplate ───────────────────────────────────────────────────────
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_medicine          = fields.Boolean(string='Es Medicamento', default=False)
    active_component     = fields.Char(string='Principio Activo')
    fda_status           = fields.Char(string='Estado Sanitario (FDA)', readonly=True, store=True)
    requires_prescription = fields.Boolean(string='Requiere Receta Obligatoria', default=False)
    prescription_file    = fields.Binary(string="Receta Digital")

    # [NEW-06] True = última receta aprobada por IA → puede comprarse
    #          False = rechazada o sin analizar → bloqueado en Website y POS
    receta_aprobada_ia = fields.Boolean(
        string='Receta Aprobada por IA', default=False, readonly=True,
        help="Controlado automáticamente por el análisis de Gemini. "
             "True = puede comprarse. False = compra bloqueada."
    )

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        for product in products:
            if product.is_medicine:
                try:
                    name_part = (product.name[:3] if len(product.name) >= 3 else product.name).upper()
                    self.env['farmacia.gestion'].create({
                        'medicamento_id': product.id,
                        'name': f"AUTO-{name_part}-{fields.Date.today()}",
                    })
                except Exception as e:
                    _logger.error(f"Error creando farmacia.gestion para {product.name}: {e}")
        return products

    def action_validate_medicine_api(self):
        for record in self:
            if not record.name:
                continue
            search_term = record.name.split()[0].strip().lower()
            url = (
                f"https://api.fda.gov/drug/label.json"
                f"?search=openfda.brand_name:{search_term}"
                f"+openfda.generic_name:{search_term}&limit=1"
            )
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    results = data.get('results', [])
                    if not results:
                        record.write({'active_component': 'N/A', 'fda_status': "NO ENCONTRADO"})
                        continue
                    openfda       = results[0].get('openfda', {})
                    brand_names   = [b.lower() for b in openfda.get('brand_name', [])]
                    generic_names = [g.lower() for g in openfda.get('generic_name', [])]
                    if any(search_term in b for b in brand_names) or \
                       any(search_term in g for g in generic_names):
                        g_name = generic_names[0] if generic_names else 'DESCONOCIDO'
                        record.write({'active_component': g_name.upper(), 'fda_status': "APROBADO (REGISTRO FDA)"})
                    else:
                        record.write({'active_component': 'N/A', 'fda_status': "RECHAZADO: NO ES UN FÁRMACO"})
                else:
                    record.write({'active_component': 'N/A', 'fda_status': "SIN REGISTRO FDA"})
            except Exception as e:
                _logger.error(f"Error FDA: {e}")
                record.write({'fda_status': "ERROR DE CONEXIÓN"})

    def action_restock_purchase(self, qty=50.0, partner_id=False):
        orders = self.env['purchase.order']
        for record in self:
            if not record.product_variant_id:
                raise UserError(f"Variante no configurada: {record.name}")
            if not partner_id:
                raise UserError("Partner requerido para crear orden de compra")
            new_order = self.env['purchase.order'].create({
                'partner_id': partner_id,
                'order_line': [(0, 0, {
                    'product_id':   record.product_variant_id.id,
                    'name':         f"Abastecimiento BioMed: {record.name}",
                    'product_qty':  qty,
                    'price_unit':   record.standard_price or 10.0,
                    'date_planned': fields.Datetime.now(),
                })],
            })
            orders += new_order
        return orders

    def action_abrir_wizard_inventario(self):
        self.ensure_one()
        if not self.product_variant_id:
            raise UserError("Producto sin variante activa")
        return {
            'name': 'Agregar Unidades al Inventario',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.change.product.qty',
            'view_mode': 'form', 'target': 'new',
            'context': {
                'default_product_id':      self.product_variant_id.id,
                'default_product_tmpl_id': self.id,
                'default_new_quantity':    self.qty_available,
            }
        }


# ─── 2. ProductProduct — POS domain con receta_aprobada_ia ───────────────────
class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _get_pos_ui_product_domain(self):
        res = super()._get_pos_ui_product_domain()
        # Medicamentos en POS: FDA aprobado + stock > 0
        # Si requiere receta → receta_aprobada_ia debe ser True
        biomed_domain = [
            '|',
            ('product_tmpl_id.is_medicine', '=', False),
            '&', '&', '&',
            ('product_tmpl_id.is_medicine',   '=', True),
            ('product_tmpl_id.fda_status',    '=', 'APROBADO (REGISTRO FDA)'),
            ('qty_available',                 '>', 0),
            '|',
            ('product_tmpl_id.requires_prescription', '=', False),
            ('product_tmpl_id.receta_aprobada_ia',    '=', True),
        ]
        return res + biomed_domain


# ─── 3. SaleOrder — bloqueo en ventas internas y website ─────────────────────
class SaleOrder(models.Model):
    _inherit = 'sale.order'

    prescription_validated = fields.Boolean(string="Receta Validada (BioMed)", default=False)

    def action_confirm(self):
        """
        [NEW-04] Bloquea confirmación si algún medicamento con receta
        tiene receta_aprobada_ia = False.
        El medicamento permanece Liberado; solo se bloquea ESTA venta.
        """
        for order in self:
            for line in order.order_line:
                tmpl = line.product_id.product_tmpl_id
                if tmpl.is_medicine and tmpl.requires_prescription and not tmpl.receta_aprobada_ia:
                    raise UserError(
                        f"🚫 BioMed — Compra bloqueada\n\n"
                        f"El medicamento '{tmpl.name}' requiere receta médica válida.\n"
                        f"La última receta analizada fue RECHAZADA por el sistema IA.\n\n"
                        f"El paciente debe presentar una receta válida y ejecutar "
                        f"'ANALIZAR RECETA CON IA' antes de procesar la venta."
                    )
        return super().action_confirm()


# ─── 4. WebsiteSaleOrder — bloqueo en carrito eCommerce ──────────────────────
class WebsiteSaleOrder(models.Model):
    """
    [NEW-05] Hereda sale.order para interceptar el carrito de website_sale.
    Dos controles:
    A) Medicamento en borrador → no puede agregarse al carrito (no está liberado)
    B) Medicamento liberado + requiere receta + receta rechazada → bloqueado
    """
    _inherit = 'sale.order'

    def _verify_updated_quantity(self, order_line, product_id, qty, **kwargs):
        product = self.env['product.product'].browse(product_id)
        tmpl    = product.product_tmpl_id

        # Control A: medicamento no liberado → invisible en website pero por si acaso
        if tmpl.is_medicine:
            gestion = self.env['farmacia.gestion'].search(
                [('medicamento_id', '=', tmpl.id)], limit=1
            )
            if gestion and gestion.estado == 'borrador':
                raise UserError(
                    f"🚫 '{tmpl.name}' no está disponible para la venta.\n"
                    f"El medicamento está pendiente de validación sanitaria (FDA)."
                )

            # Control B: liberado pero receta rechazada
            if tmpl.requires_prescription and not tmpl.receta_aprobada_ia:
                raise UserError(
                    f"🚫 '{tmpl.name}' requiere receta médica válida.\n\n"
                    f"La última receta analizada por el sistema BioMed fue RECHAZADA.\n"
                    f"Por favor contacta a la farmacia y presenta una receta médica válida "
                    f"para que el farmacéutico la valide en el sistema."
                )

        return super()._verify_updated_quantity(order_line, product_id, qty, **kwargs)


# ─── 5. FarmaciaAnalisisHistorial ────────────────────────────────────────────
class FarmaciaAnalisisHistorial(models.Model):
    _name        = 'farmacia.analisis.historial'
    _description = 'Historial de Análisis IA — BioMed'
    _order       = 'timestamp desc'

    gestion_id              = fields.Many2one('farmacia.gestion', ondelete='cascade', required=True)
    medicamento_id          = fields.Many2one('product.template', related='gestion_id.medicamento_id', store=True)
    timestamp               = fields.Datetime(default=fields.Datetime.now, readonly=True)
    condiciones_paciente    = fields.Text(string='Condiciones Registradas', readonly=True)
    resultado_html          = fields.Html(string='Resultado IA', readonly=True)
    tuvo_contraindicaciones = fields.Boolean(string='¿Contraindicaciones?', readonly=True)
    receta_aprobada         = fields.Boolean(string='Receta Aprobada', readonly=True)
    modelo_usado            = fields.Char(string='Modelo IA', default=GEMINI_MODEL, readonly=True)
    rag_utilizado           = fields.Boolean(string='RAG activo', readonly=True)
    resumen_rag             = fields.Char(string='Resumen RAG', readonly=True)


# ─── 6. FarmaciaGestion — panel central ──────────────────────────────────────
class FarmaciaGestion(models.Model):
    _name        = 'farmacia.gestion'
    _description = 'Panel Central BioMed'
    _order       = 'id desc'

    _sql_constraints = [
        ('medicamento_unico', 'unique(medicamento_id)', 'Ya existe registro para este medicamento')
    ]

    name          = fields.Char(string='N° Lote', readonly=True, default='NUEVA')
    medicamento_id = fields.Many2one('product.template', string='Insumo Farmacéutico', required=True)
    proveedor_id  = fields.Many2one('res.partner', string='Laboratorio Proveedor')
    stock_actual  = fields.Float(related='medicamento_id.qty_available', string='Stock Bodega', readonly=True, store=True)
    principio_activo_rel = fields.Char(related='medicamento_id.active_component', string='Principio Activo', readonly=True)
    alerta_stock  = fields.Selection([('normal','OK'),('critico','CRÍTICO')], compute="_compute_alerta_stock", store=True)
    cantidad      = fields.Float(string='Cant. a Adquirir', default=10.0)
    purchase_order_id = fields.Many2one('purchase.order', string='Orden Compra', readonly=True)
    estado        = fields.Selection([('borrador','En Revisión'),('procesado','Liberado')], default='borrador')

    requires_prescription_rel = fields.Boolean(related='medicamento_id.requires_prescription', string="¿Requiere Receta?", readonly=False)
    receta_rel    = fields.Binary(related='medicamento_id.prescription_file', string='Receta', readonly=False)

    # [NEW-06] Estado actual de la receta IA — visible en el panel
    receta_aprobada_ia_rel = fields.Boolean(
        related='medicamento_id.receta_aprobada_ia', string='Receta IA Aprobada', readonly=True
    )

    ai_analysis_result    = fields.Html(string="Último Resultado IA", readonly=True)
    ai_analysis_timestamp = fields.Datetime(string="Timestamp Último Análisis", readonly=True)
    condiciones_paciente  = fields.Text(
        string='Condiciones del Paciente',
        help="Condiciones médicas separadas por coma. Ej: Diabetes, Insuficiencia Renal\nAlimenta el sistema RAG para detectar contraindicaciones."
    )
    analisis_ids   = fields.One2many('farmacia.analisis.historial', 'gestion_id', string='Historial IA')
    total_analisis = fields.Integer(string='Total Análisis', compute='_compute_total_analisis')

    @api.depends('analisis_ids')
    def _compute_total_analisis(self):
        for r in self:
            r.total_analisis = len(r.analisis_ids)

    @api.depends('stock_actual')
    def _compute_alerta_stock(self):
        for r in self:
            r.alerta_stock = 'critico' if r.stock_actual < 10 else 'normal'

    def _get_api_key(self):
        key = self.env['ir.config_parameter'].sudo().get_param('farmacia_bio.gemini_api_key')
        if not key:
            raise UserError("⚙️ API Key no configurada.\nVe a: BioMed App → ⚙️ Configuración → 🔑 API Key de Gemini")
        return key.strip()

    def action_analizar_receta_ia(self):
        """
        Pipeline RAG v2.3:
        1. ChromaDB retrieve_context con condiciones_paciente reales
        2. generate_rag_prompt con contraindicaciones inyectadas
        3. GeminiService.analyze_prescription_with_rag
        4. [NEW-04] Escribe receta_aprobada_ia en el producto
        5. [NEW-02] Guarda en historial de auditoría
        """
        for record in self:
            if not record.receta_rel:
                raise UserError("📎 Debe adjuntar la imagen de la receta digital.")

            med_name  = record.medicamento_id.name or "Medicamento"
            comp_name = record.principio_activo_rel or med_name
            api_key   = self._get_api_key()

            raw = record.receta_rel
            imagen_b64 = raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
            if not imagen_b64 or len(imagen_b64) < 100:
                raise UserError("❌ La imagen adjunta parece estar vacía o corrupta.")

            RAG_DISPONIBLE = False
            rag = None
            try:
                from ..services.rag_service import get_rag_service
                rag = get_rag_service()
                RAG_DISPONIBLE = True
            except Exception as e:
                _logger.warning(f"[BioMed RAG] No disponible: {e}")

            contexto_rag = {'encontradas': False, 'contraindicaciones': [], 'resumen_ejecutivo': 'RAG no disponible'}
            if RAG_DISPONIBLE and rag:
                try:
                    condiciones = [c.strip() for c in record.condiciones_paciente.split(',') if c.strip()] \
                        if record.condiciones_paciente else [f"Medicamento {med_name}"]
                    contexto_rag = rag.retrieve_context(med_name, condiciones, n_results=5)
                    _logger.info(f"[BioMed RAG] {med_name}: {len(contexto_rag.get('contraindicaciones',[]))} resultados")
                except Exception as e:
                    _logger.warning(f"[BioMed RAG] Error ChromaDB: {e}")

            try:
                prompt = rag.generate_rag_prompt(med_name, comp_name, contexto_rag) if RAG_DISPONIBLE and rag \
                    else self._build_fallback_prompt(med_name, comp_name)
            except Exception:
                prompt = self._build_fallback_prompt(med_name, comp_name)

            try:
                from ..services.gemini_service import get_gemini_service, reset_gemini_service
                reset_gemini_service()
                gemini    = get_gemini_service(api_key=api_key)
                resultado = gemini.analyze_prescription_with_rag(imagen_b64, med_name, comp_name, prompt)
            except ImportError:
                raise UserError("❌ GeminiService no disponible.")

            if resultado.get('error') and not resultado.get('html_response', '').strip():
                raise UserError(f"Error en Gemini: {resultado['error']}")

            html_response           = resultado.get('html_response', '')
            receta_aprobada         = resultado.get('approved', False)
            tuvo_contraindicaciones = resultado.get('has_contraindications', False)

            if contexto_rag.get('encontradas'):
                html_response = (
                    f'<div style="background:#fff3cd;border-left:4px solid #ff9800;padding:8px 12px;'
                    f'margin-bottom:10px;border-radius:4px;font-size:13px;">'
                    f'🧬 <strong>Contexto RAG:</strong> {contexto_rag.get("resumen_ejecutivo","")}</div>'
                ) + html_response

            # Badge de estado de compra claro para el farmacéutico
            if receta_aprobada:
                html_response += (
                    '<div style="background:#d4edda;border-left:4px solid #28a745;padding:12px;'
                    'margin-top:12px;border-radius:4px;font-size:14px;font-weight:bold;">'
                    '✅ RECETA APROBADA — El medicamento PUEDE ser comprado en Website y POS</div>'
                )
            else:
                html_response += (
                    '<div style="background:#f8d7da;border-left:4px solid #dc3545;padding:12px;'
                    'margin-top:12px;border-radius:4px;font-size:14px;font-weight:bold;">'
                    '🚫 RECETA RECHAZADA — La compra está BLOQUEADA. '
                    'El paciente debe presentar una receta válida.</div>'
                )

            now = fields.Datetime.now()

            # [NEW-04] Actualizar receta_aprobada_ia en el producto
            # El estado del medicamento (Liberado/En Revisión) NO cambia
            # Solo se controla si se puede comprar en este momento
            record.medicamento_id.sudo().write({'receta_aprobada_ia': receta_aprobada})

            record.write({'ai_analysis_result': html_response, 'ai_analysis_timestamp': now})

            # [NEW-02] Historial de auditoría
            self.env['farmacia.analisis.historial'].create({
                'gestion_id':              record.id,
                'timestamp':               now,
                'condiciones_paciente':    record.condiciones_paciente or '(sin condiciones)',
                'resultado_html':          html_response,
                'tuvo_contraindicaciones': tuvo_contraindicaciones,
                'receta_aprobada':         receta_aprobada,
                'modelo_usado':            GEMINI_MODEL,
                'rag_utilizado':           RAG_DISPONIBLE,
                'resumen_rag':             contexto_rag.get('resumen_ejecutivo', ''),
            })

            _logger.info(f"[BioMed] {med_name} → Receta: {'APROBADA' if receta_aprobada else 'RECHAZADA'}")
        return True

    @staticmethod
    def _build_fallback_prompt(med_name, comp_name):
        return f"""Actúa como auditor farmacéutico. Analiza la imagen adjunta.
MEDICAMENTO: {med_name} (componente: {comp_name})
1. ¿Es una receta médica válida?
2. ¿Contiene '{med_name}' o '{comp_name}'?
Responde SOLO en HTML puro, sin markdown, sin backticks.
<div style="font-family:Arial;padding:15px;border-radius:8px;background:#f9f9f9;">
  <h4>Auditoría de Receta - BioMed</h4>
  <ul>
    <li>Tipo de documento: [describe]</li>
    <li>Medicamento encontrado: [sí/no]</li>
  </ul>
  <div style="margin-top:10px;font-weight:bold;">
    Veredicto: <span style="color:green;">APROBADO</span> o <span style="color:red;">RECHAZADO</span>
  </div>
</div>"""

    def action_validar_medicamento(self):
        for record in self:
            record.medicamento_id.action_validate_medicine_api()
            if record.medicamento_id.fda_status == "APROBADO (REGISTRO FDA)":
                pos_category = self.env['pos.category'].search([('name', '=', 'Medicamentos')], limit=1)
                record.medicamento_id.write({
                    'available_in_pos': True,
                    'pos_categ_ids':    [(4, pos_category.id)] if pos_category else [],
                    'sale_ok':          True,
                    'is_published':     True,   # Aparece en website cuando está liberado por FDA
                })
                record.write({
                    'estado': 'procesado',
                    'name': f"BATCH-{record.medicamento_id.name[:3].upper()}-{fields.Date.today()}"
                })
            else:
                record.medicamento_id.write({'is_published': False})  # Ocultar de website
                record.write({'estado': 'borrador'})
        return True

    def action_solicitar_stock_compra(self):
        for record in self:
            if record.medicamento_id.fda_status != "APROBADO (REGISTRO FDA)":
                raise UserError("Medicamento sin validación FDA")
            if not record.proveedor_id:
                raise UserError("Debe seleccionar proveedor")
            ordenes = record.medicamento_id.action_restock_purchase(
                qty=record.cantidad, partner_id=record.proveedor_id.id
            )
            if not ordenes:
                raise UserError("Error generando PO")
            orden = ordenes[0]
            record.purchase_order_id = orden.id
            try:
                orden.button_confirm()
                for picking in orden.picking_ids:
                    if picking.state not in ('done', 'cancel'):
                        for move in picking.move_ids:
                            move.quantity = move.product_uom_qty
                        picking.button_validate()
            except Exception as e:
                _logger.error(f"Error recepción automática: {e}")
                raise UserError(f"PO creada pero error en recepción: {str(e)}")
        return True

    @api.model
    def get_dashboard_data(self):
        Gestion   = self.env['farmacia.gestion']
        Historial = self.env['farmacia.analisis.historial']
        top_meds  = []
        for g in Gestion.search([('total_analisis', '>', 0)], order='total_analisis desc', limit=5):
            top_meds.append({'nombre': g.medicamento_id.name, 'cantidad': g.total_analisis, 'estado': g.estado})
        return {
            'total_medicamentos':  Gestion.search_count([]),
            'stock_critico':       Gestion.search_count([('alerta_stock', '=', 'critico')]),
            'procesados':          Gestion.search_count([('estado', '=', 'procesado')]),
            'en_revision':         Gestion.search_count([('estado', '=', 'borrador')]),
            'sin_stock':           Gestion.search_count([('stock_actual', '=', 0)]),
            'total_analisis':      Historial.search_count([]),
            'analisis_con_riesgo': Historial.search_count([('tuvo_contraindicaciones', '=', True)]),
            'analisis_hoy':        Historial.search_count([('timestamp', '>=', fields.Date.today())]),
            'recetas_rechazadas':  Historial.search_count([('receta_aprobada', '=', False)]),
            'recetas_aprobadas':   Historial.search_count([('receta_aprobada', '=', True)]),
            'top_meds':            top_meds,
        }