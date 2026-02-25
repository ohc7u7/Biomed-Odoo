# -*- coding: utf-8 -*-
import requests
import logging
import json
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_medicine = fields.Boolean(string='Es Medicamento', default=False)
    active_component = fields.Char(string='Principio Activo')
    fda_status = fields.Char(string='Estado Sanitario (FDA)', readonly=True, store=True)
    requires_prescription = fields.Boolean(string='Requiere Receta Obligatoria', default=False)
    prescription_file = fields.Binary(string="Receta Digital")

    @api.model_create_multi
    def create(self, vals_list):
        products = super(ProductTemplate, self).create(vals_list)
        for product in products:
            if product.is_medicine:
                self.env['farmacia.gestion'].create({
                    'medicamento_id': product.id,
                    'name': f"AUTO-{product.name[:3].upper()}"
                })
        return products

    def action_validate_medicine_api(self):
        """ Valida contra la FDA de forma estricta (Filtro anti-Almendra) """
        for record in self:
            if not record.name: 
                continue
            
            search_term = record.name.split()[0].strip().lower()
            url = f"https://api.fda.gov/drug/label.json?search=openfda.brand_name:{search_term}+openfda.generic_name:{search_term}&limit=1"
            
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    results = data.get('results', [])
                    
                    if not results:
                        record.write({'active_component': 'N/A', 'fda_status': "NO ENCONTRADO"})
                        continue

                    openfda = results[0].get('openfda', {})
                    brand_names = [b.lower() for b in openfda.get('brand_name', [])]
                    generic_names = [g.lower() for g in openfda.get('generic_name', [])]

                    if any(search_term in b for b in brand_names) or any(search_term in g for g in generic_names):
                        g_name = generic_names[0] if generic_names else 'DESCONOCIDO'
                        record.write({
                            'active_component': g_name.upper(), 
                            'fda_status': "APROBADO (REGISTRO FDA)"
                        })
                    else:
                        record.write({
                            'active_component': 'N/A', 
                            'fda_status': "RECHAZADO: NO ES UN FÁRMACO"
                        })
                else:
                    record.write({'active_component': 'N/A', 'fda_status': "SIN REGISTRO FDA"})
            
            except Exception as e:
                _logger.error("Error conectando con la API FDA: %s", e)
                record.write({'fda_status': "ERROR DE CONEXIÓN"})

    def action_restock_purchase(self, qty=50.0, partner_id=False):
        for record in self:
            product_variant = record.product_variant_id
            if not product_variant: 
                raise UserError("Variante no configurada.")
            
            return self.env['purchase.order'].create({
                'partner_id': partner_id,
                'order_line': [(0, 0, {
                    'product_id': product_variant.id,
                    'name': f"Abastecimiento BioMed: {record.name}",
                    'product_qty': qty,
                    'price_unit': record.standard_price or 10.0,
                    'date_planned': fields.Datetime.now(),
                })],
            })

    def action_abrir_wizard_inventario(self):
        self.ensure_one()
        if not self.product_variant_id:
            raise UserError("Este producto no tiene variante activa.")
            
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
            }
        }

class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _get_pos_ui_product_domain(self):
        res = super(ProductProduct, self)._get_pos_ui_product_domain()
        res.append('|')
        res.append(('is_medicine', '=', False))
        res.append('&')
        res.append(('fda_status', '=', 'APROBADO (REGISTRO FDA)'))
        res.append(('qty_available', '>', 0)) 
        return res

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    prescription_validated = fields.Boolean(string="Receta Validada (BioMed)", default=False)

    def action_confirm(self):
        for order in self:
            medicines = order.order_line.mapped('product_id').filtered(lambda p: p.requires_prescription)
            if medicines and not order.prescription_validated:
                raise UserError("Bloqueo BioMed: Falta validar receta médica.")
        return super(SaleOrder, self).action_confirm()

class FarmaciaGestion(models.Model):
    _name = 'farmacia.gestion'
    _description = 'Panel Central BioMed'
    _order = 'id desc'

    name = fields.Char(string='N° Lote', readonly=True, default='NUEVA')
    medicamento_id = fields.Many2one('product.template', string='Insumo Farmacéutico', required=True)
    proveedor_id = fields.Many2one('res.partner', string='Laboratorio Proveedor')
    stock_actual = fields.Float(related='medicamento_id.qty_available', string='Stock Bodega', readonly=True, store=True)
    principio_activo_rel = fields.Char(related='medicamento_id.active_component', string='Principio Activo', readonly=True)
    alerta_stock = fields.Selection([('normal', 'OK'), ('critico', 'CRÍTICO')], compute="_compute_alerta_stock", store=True)
    cantidad = fields.Float(string='Cant. a Adquirir', default=10.0)
    purchase_order_id = fields.Many2one('purchase.order', string='Orden Compra', readonly=True)
    estado = fields.Selection([('borrador', 'En Revisión'), ('procesado', 'Liberado')], default='borrador')

    # --- CAMPOS IA y SEGURIDAD LÓGICA ---
    requires_prescription_rel = fields.Boolean(related='medicamento_id.requires_prescription', string="¿Requiere Receta Medica?", readonly=False)
    receta_rel = fields.Binary(related='medicamento_id.prescription_file', string='Receta del Paciente', readonly=False)
    ai_analysis_result = fields.Html(string="Resultado IA", readonly=True)

    @api.depends('stock_actual')
    def _compute_alerta_stock(self):
        for record in self:
            record.alerta_stock = 'critico' if record.stock_actual < 10 else 'normal'

    def action_analizar_receta_ia(self):
        """ Envía la imagen a Google Gemini 1.5 Flash para analizarla """
        for record in self:
            if not record.receta_rel:
                raise UserError("Debe subir la imagen de la Receta Digital antes de que la IA pueda analizarla.")
            
            med_name = record.medicamento_id.name or "Medicamento"
            comp_name = record.principio_activo_rel or "Componente"
            
            # --- 1. CLAVE DE GOOGLE GEMINI CORREGIDA EXACTA ---
            api_key = "AIzaSyDZVClmF5J9Tz5WrbydOw7gxEUcjjIsJmU" 

            # --- 2. DECODIFICAR IMAGEN ---
            imagen_base64 = record.receta_rel.decode('utf-8')

            # --- 3. PREPARAR LLAMADA A GOOGLE GEMINI ---
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}

            prompt = f"""
            Actúa como un estricto auditor farmacéutico. Analiza la imagen adjunta.
            1. ¿Es realmente una receta médica, prescripción o documento de salud? Si es la foto de una persona, un paisaje, dibujos animados o algo sin sentido, DEBES RECHAZARLO.
            2. Si es una receta, verifica si se logra leer (incluso con mala letra) el medicamento '{med_name}' o su componente '{comp_name}'.
            
            Devuelve tu análisis ESTRICTAMENTE en código HTML puro (sin markdown, sin backticks).
            Usa un div con un color de fondo claro (ej. #f4f8f9). Pon un título <h4>. Usa <ul> y <li> con emojis para explicar:
            - Qué ves en la foto.
            - Si hace match con el medicamento solicitado.
            - Veredicto Final: Si la apruebas (texto verde) o la rechazas por no coincidir o no ser receta (texto rojo).
            """

            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": "image/jpeg",
                                    "data": imagen_base64
                                }
                            }
                        ]
                    }
                ]
            }

            # --- 4. EJECUTAR Y GUARDAR ---
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=30)
                
                if response.status_code == 200:
                    result_data = response.json()
                    try:
                        # Estructura de respuesta específica de Gemini
                        analisis_html = result_data['candidates'][0]['content']['parts'][0]['text']
                        
                        # Limpiamos el markdown rebelde
                        analisis_html = analisis_html.replace('```html', '').replace('```', '').strip()
                        
                        record.write({'ai_analysis_result': analisis_html})
                    except KeyError:
                        raise UserError("La IA no devolvió el formato esperado. Intenta con otra imagen.")
                else:
                    raise UserError(f"Error en Gemini API: {response.text}")

            except requests.exceptions.Timeout:
                raise UserError("La Inteligencia Artificial tardó demasiado en responder. Intente nuevamente.")
            except Exception as e:
                raise UserError(f"Fallo de conexión con Google Gemini: {str(e)}")

        return True

    def action_validar_medicamento(self):
        for record in self:
            record.medicamento_id.action_validate_medicine_api()
            
            if record.medicamento_id.fda_status == "APROBADO (REGISTRO FDA)":
                pos_category = self.env['pos.category'].search([('name', '=', 'Medicamentos')], limit=1)
                record.medicamento_id.write({
                    'available_in_pos': True,            
                    'pos_categ_ids': [(4, pos_category.id)] if pos_category else False,
                    'website_published': True,          
                    'sale_ok': True,                    
                    'is_published': True                
                })
                
                record.write({
                    'estado': 'procesado',
                    'name': f"BATCH-{record.medicamento_id.name[:3].upper()}-{fields.Date.today()}"
                })
            else:
                record.write({'estado': 'borrador'})
        return True

    def action_solicitar_stock_compra(self):
        for record in self:
            if record.medicamento_id.fda_status != "APROBADO (REGISTRO FDA)":
                raise UserError("No se puede comprar: El producto no tiene validación oficial FDA.")
                
            if not record.proveedor_id:
                raise UserError("Debe seleccionar un Laboratorio Proveedor antes de pedir stock.")
            
            orden = record.medicamento_id.action_restock_purchase(
                qty=record.cantidad, 
                partner_id=record.proveedor_id.id
            )
            record.purchase_order_id = orden.id
            
            try:
                orden.with_context(tracking_disable=True, mail_notrack=True).button_confirm()
                for picking in orden.picking_ids:
                    for move in picking.move_ids:
                        move.quantity = move.product_uom_qty
                    picking.button_validate()
            except Exception as e:
                _logger.warning("Error auto-confirmando compra: %s", e)

        return True