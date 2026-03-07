# -*- coding: utf-8 -*-
# BioMed v2.4 — Farmacia Clínica Maestro
# [v2.4-NEW] Bloqueo de stock insuficiente en ventas internas (sale.order)
# [v2.4-NEW] Bloqueo de stock insuficiente ya existía en eCommerce (_verify_updated_quantity)
# [v2.4-FIX] get_dashboard_data ahora cuenta product.template con is_medicine=True
#            en lugar de solo farmacia.gestion → dashboard muestra datos correctos

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError
import requests

_logger = logging.getLogger(__name__)

GEMINI_MODEL    = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


# ─── 1. ProductTemplate ───────────────────────────────────────────────────────
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_medicine           = fields.Boolean(string='Es Medicamento', default=False)
    active_component      = fields.Char(string='Principio Activo')
    fda_status            = fields.Char(string='Estado Sanitario (FDA)', readonly=True, store=True)
    requires_prescription = fields.Boolean(string='Requiere Receta Obligatoria', default=False)
    prescription_file     = fields.Binary(string="Receta Digital")
    receta_aprobada_ia    = fields.Boolean(
        string='Receta Aprobada por IA', default=False, readonly=True,
        help="True = puede comprarse. False = compra bloqueada."
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
            # IMPORTANTE: usar solo la primera palabra en minúsculas para la FDA
            # "Paracetamol 500mg" → busca "paracetamol" ✓
            # Si el nombre tiene mg, la FDA no lo reconoce → siempre usar solo la droga
            search_term = record.name.split()[0].strip().lower()
            url = (
                f"https://api.fda.gov/drug/label.json"
                f"?search=openfda.brand_name:{search_term}"
                f"+openfda.generic_name:{search_term}&limit=1"
            )
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data    = response.json()
                    results = data.get('results', [])
                    if not results:
                        record.write({'active_component': 'N/A', 'fda_status': "NO ENCONTRADO"})
                        continue
                    openfda       = results[0].get('openfda', {})
                    brand_names   = [b.lower() for b in openfda.get('brand_name', [])]
                    generic_names = [g.lower() for g in openfda.get('generic_name', [])]
                    if (any(search_term in b for b in brand_names) or
                            any(search_term in g for g in generic_names)):
                        g_name = generic_names[0] if generic_names else 'DESCONOCIDO'
                        record.write({
                            'active_component': g_name.upper(),
                            'fda_status': "APROBADO (REGISTRO FDA)",
                        })
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


# ─── 3. SaleOrder — bloqueo en ventas internas ───────────────────────────────
class SaleOrder(models.Model):
    _inherit = 'sale.order'

    prescription_validated = fields.Boolean(string="Receta Validada (BioMed)", default=False)

    def action_confirm(self):
        """
        [v2.3] Bloquea si receta rechazada.
        [v2.4-NEW] Bloquea si cantidad pedida supera el stock disponible.
        El medicamento permanece Liberado; solo se bloquea ESTA venta.
        """
        for order in self:
            for line in order.order_line:
                tmpl     = line.product_id.product_tmpl_id
                variante = line.product_id

                if not tmpl.is_medicine:
                    continue

                # ── Bloqueo 1: receta rechazada ──
                if tmpl.requires_prescription and not tmpl.receta_aprobada_ia:
                    raise UserError(
                        f"🚫 BioMed — Receta rechazada\n\n"
                        f"'{tmpl.name}' requiere receta médica válida.\n"
                        f"La última receta analizada fue RECHAZADA por el sistema IA.\n\n"
                        f"El paciente debe presentar una receta válida y ejecutar "
                        f"'ANALIZAR RECETA CON IA' antes de procesar la venta."
                    )

                # ── Bloqueo 2: stock insuficiente ──────────────────────────
                # [v2.4-NEW] Si el pedido supera lo disponible → error claro
                stock_disponible = variante.qty_available
                qty_pedida       = line.product_uom_qty

                if qty_pedida > stock_disponible:
                    if stock_disponible <= 0:
                        raise UserError(
                            f"🚫 Stock agotado: '{tmpl.name}'\n\n"
                            f"No hay unidades disponibles en inventario.\n"
                            f"Ve a BioMed → Panel de Control → Pedir Stock a Compras."
                        )
                    raise UserError(
                        f"⚠️ Stock insuficiente: '{tmpl.name}'\n\n"
                        f"  Cantidad pedida  : {int(qty_pedida)} unidades\n"
                        f"  Stock disponible : {int(stock_disponible)} unidades\n\n"
                        f"Ajusta la cantidad o solicita reposición en BioMed App."
                    )

        return super().action_confirm()


# ─── 4. WebsiteSaleOrder — bloqueo en carrito eCommerce ──────────────────────
class WebsiteSaleOrder(models.Model):
    """
    Controla el carrito de website_sale.
    A) Medicamento en borrador → no disponible para venta
    B) Receta rechazada → bloqueado
    C) Stock insuficiente → bloqueado (con mensaje claro)
    """
    _inherit = 'sale.order'

    def _verify_updated_quantity(self, order_line, product_id, qty, **kwargs):
        product = self.env['product.product'].browse(product_id)
        tmpl    = product.product_tmpl_id

        if tmpl.is_medicine:
            # Control A: no liberado por FDA
            gestion = self.env['farmacia.gestion'].search(
                [('medicamento_id', '=', tmpl.id)], limit=1
            )
            if gestion and gestion.estado == 'borrador':
                raise UserError(
                    f"🚫 '{tmpl.name}' no está disponible.\n"
                    f"Pendiente de validación sanitaria (FDA)."
                )

            # Control B: receta rechazada
            if tmpl.requires_prescription and not tmpl.receta_aprobada_ia:
                raise UserError(
                    f"🚫 '{tmpl.name}' requiere receta médica válida.\n\n"
                    f"La última receta fue RECHAZADA por el sistema IA de BioMed.\n"
                    f"Contacta a la farmacia para validar tu receta antes de comprar."
                )

            # Control C: stock insuficiente [v2.3 + v2.4 mejorado]
            stock_disponible = product.qty_available
            if qty > stock_disponible:
                if stock_disponible <= 0:
                    raise UserError(
                        f"🚫 '{tmpl.name}' está agotado.\n"
                        f"No hay unidades disponibles en este momento."
                    )
                raise UserError(
                    f"⚠️ Stock insuficiente para '{tmpl.name}'.\n\n"
                    f"  Solicitaste : {int(qty)} unidades\n"
                    f"  Disponible  : {int(stock_disponible)} unidades\n\n"
                    f"Ajusta la cantidad al máximo disponible."
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

    name                      = fields.Char(string='N° Lote', readonly=True, default='NUEVA')
    medicamento_id            = fields.Many2one('product.template', string='Insumo Farmacéutico', required=True)
    proveedor_id              = fields.Many2one('res.partner', string='Laboratorio Proveedor')
    stock_actual              = fields.Float(related='medicamento_id.qty_available', string='Stock Bodega', readonly=True, store=True)
    principio_activo_rel      = fields.Char(related='medicamento_id.active_component', string='Principio Activo', readonly=True)
    alerta_stock              = fields.Selection([('normal','OK'),('critico','CRÍTICO')], compute="_compute_alerta_stock", store=True)
    cantidad                  = fields.Float(string='Cant. a Adquirir', default=10.0)
    purchase_order_id         = fields.Many2one('purchase.order', string='Orden Compra', readonly=True)
    estado                    = fields.Selection([('borrador','En Revisión'),('procesado','Liberado')], default='borrador')
    requires_prescription_rel = fields.Boolean(related='medicamento_id.requires_prescription', string="¿Requiere Receta?", readonly=False)
    receta_rel                = fields.Binary(related='medicamento_id.prescription_file', string='Receta', readonly=False)
    receta_aprobada_ia_rel    = fields.Boolean(related='medicamento_id.receta_aprobada_ia', string='Receta IA Aprobada', readonly=True)
    ai_analysis_result        = fields.Html(string="Último Resultado IA", readonly=True)
    ai_analysis_timestamp     = fields.Datetime(string="Timestamp Último Análisis", readonly=True)
    condiciones_paciente      = fields.Text(
        string='Condiciones del Paciente',
        help="Condiciones separadas por coma. Ej: Diabetes, Insuficiencia Renal\nAlimenta el RAG."
    )
    analisis_ids   = fields.One2many('farmacia.analisis.historial', 'gestion_id', string='Historial IA')
    total_analisis = fields.Integer(string='Total Análisis', compute='_compute_total_analisis', store=True)

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
            raise UserError(
                "⚙️ API Key no configurada.\n"
                "Ve a: BioMed App → ⚙️ Configuración → 🔑 API Key de Gemini"
            )
        return key.strip()

    def action_analizar_receta_ia(self):
        for record in self:
            if not record.receta_rel:
                raise UserError("📎 Debe adjuntar la imagen de la receta digital.")

            med_name  = record.medicamento_id.name or "Medicamento"
            comp_name = record.principio_activo_rel or med_name
            api_key   = self._get_api_key()

            raw        = record.receta_rel
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
                except Exception as e:
                    _logger.warning(f"[BioMed RAG] Error ChromaDB: {e}")

            try:
                prompt = rag.generate_rag_prompt(med_name, comp_name, contexto_rag) \
                    if RAG_DISPONIBLE and rag else self._build_fallback_prompt(med_name, comp_name)
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
                    '🚫 RECETA RECHAZADA — La compra está BLOQUEADA.</div>'
                )

            now = fields.Datetime.now()
            record.medicamento_id.sudo().write({'receta_aprobada_ia': receta_aprobada})
            record.write({'ai_analysis_result': html_response, 'ai_analysis_timestamp': now})

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
            _logger.info(f"[BioMed] {med_name} → {'APROBADA' if receta_aprobada else 'RECHAZADA'}")
        return True

    @staticmethod
    def _build_fallback_prompt(med_name, comp_name):
        """
        [v2.5-FIX] Prompt que acepta nombres comerciales y genéricos.
        Amoxil = Amoxicilina = AMOXICILLIN → todos son el mismo fármaco.
        """
        # Extraer solo el nombre base sin dosis (ej: "Amoxicilina 500mg" → "Amoxicilina")
        base_name = med_name.split()[0] if med_name else med_name

        return (
            f"Eres un auditor farmacéutico certificado.\n"
            f"Analiza la imagen de receta médica adjunta.\n\n"
            f"MEDICAMENTO A VERIFICAR:\n"
            f"  - Nombre genérico: {base_name} / {comp_name}\n"
            f"  - Nombre completo registrado: {med_name}\n\n"
            f"IMPORTANTE: El medicamento puede aparecer en la receta como:\n"
            f"  - Su nombre genérico: '{base_name}' o '{comp_name}'\n"
            f"  - Un nombre comercial equivalente (ej: Amoxil, Amoxidal, Trimox para Amoxicilina)\n"
            f"  - Con dosis diferente a la registrada (aún así puede ser válido)\n"
            f"  - Con mayúsculas/minúsculas distintas\n\n"
            f"CRITERIOS DE APROBACIÓN (basta con UNO):\n"
            f"  ✓ La receta menciona '{base_name}' (o variante comercial conocida)\n"
            f"  ✓ La receta menciona '{comp_name}' (principio activo)\n"
            f"  ✓ El medicamento prescrito tiene el mismo principio activo\n\n"
            f"CRITERIOS DE RECHAZO (todos deben cumplirse):\n"
            f"  ✗ La imagen NO es una receta médica real\n"
            f"  ✗ La receta NO contiene '{base_name}', '{comp_name}' ni equivalentes\n"
            f"  ✗ Falta firma o sello del médico\n\n"
            f"FORMATO DE RESPUESTA: HTML puro, sin markdown, sin backticks.\n"
            f"Incluye exactamente una de estas palabras en mayúsculas: APROBADO o RECHAZADO.\n"
            f"Si el medicamento o su equivalente aparece en la receta → APROBADO."
        )

    def action_validar_medicamento(self):
        for record in self:
            record.medicamento_id.action_validate_medicine_api()
            if record.medicamento_id.fda_status == "APROBADO (REGISTRO FDA)":
                pos_category = self.env['pos.category'].search([('name', '=', 'Medicamentos')], limit=1)
                record.medicamento_id.write({
                    'available_in_pos': True,
                    'pos_categ_ids':    [(4, pos_category.id)] if pos_category else [],
                    'sale_ok':          True,
                    'is_published':     True,
                })
                record.write({
                    'estado': 'procesado',
                    'name':   f"BATCH-{record.medicamento_id.name[:3].upper()}-{fields.Date.today()}",
                })
            else:
                record.medicamento_id.write({'is_published': False})
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
        """
        [v2.4-FIX] Ahora cuenta product.template con is_medicine=True
        en lugar de solo registros de farmacia.gestion.
        Esto evita que el dashboard muestre 0 cuando hay medicamentos
        cargados por script (sin farmacia.gestion creado manualmente).
        """
        Gestion    = self.env['farmacia.gestion']
        Historial  = self.env['farmacia.analisis.historial']
        ProductTpl = self.env['product.template']

        # Métricas de inventario desde product.template (fuente de verdad)
        total_meds     = ProductTpl.search_count([('is_medicine', '=', True)])
        procesados     = Gestion.search_count([('estado', '=', 'procesado')])
        en_revision    = Gestion.search_count([('estado', '=', 'borrador')])
        stock_critico  = Gestion.search_count([('alerta_stock', '=', 'critico')])
        sin_stock      = Gestion.search_count([('stock_actual', '=', 0)])

        # Top medicamentos más analizados
        # Usamos sorted() en Python porque total_analisis es computed
        # (aunque ahora es stored, esta forma es más segura)
        top_meds = []
        todas_gestiones = Gestion.search([])
        gestiones_con_analisis = todas_gestiones.filtered(lambda g: g.total_analisis > 0)
        gestiones_ordenadas = sorted(gestiones_con_analisis, key=lambda g: g.total_analisis, reverse=True)[:5]
        for g in gestiones_ordenadas:
            top_meds.append({
                'nombre':   g.medicamento_id.name,
                'cantidad': g.total_analisis,
                'estado':   g.estado,
            })

        return {
            'total_medicamentos':  total_meds,       # ← FIX: antes era Gestion.search_count([])
            'stock_critico':       stock_critico,
            'procesados':          procesados,
            'en_revision':         en_revision,
            'sin_stock':           sin_stock,
            'total_analisis':      Historial.search_count([]),
            'analisis_con_riesgo': Historial.search_count([('tuvo_contraindicaciones', '=', True)]),
            'analisis_hoy':        Historial.search_count([('timestamp', '>=', fields.Date.today())]),
            'recetas_rechazadas':  Historial.search_count([('receta_aprobada', '=', False)]),
            'recetas_aprobadas':   Historial.search_count([('receta_aprobada', '=', True)]),
            'top_meds':            top_meds,
        }