# -*- coding: utf-8 -*-
"""
FarmaciaGestion — Panel central BioMed.

Gestiona la trazabilidad farmacéutica, validación FDA,
análisis IA de recetas con contexto RAG, y solicitudes de stock.
"""

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError
from .constants import GEMINI_MODEL, STOCK_CRITICAL_THRESHOLD

_logger = logging.getLogger(__name__)


class FarmaciaGestion(models.Model):
    _name = 'farmacia.gestion'
    _description = 'Panel Central BioMed'
    _order = 'id desc'

    _sql_constraints = [
        ('medicamento_unico', 'unique(medicamento_id)',
         'Ya existe registro para este medicamento'),
    ]

    name = fields.Char(
        string='N° Lote', readonly=True, default='NUEVA',
    )
    medicamento_id = fields.Many2one(
        'product.template', string='Insumo Farmacéutico', required=True,
    )
    proveedor_id = fields.Many2one(
        'res.partner', string='Laboratorio Proveedor',
    )
    stock_actual = fields.Float(
        related='medicamento_id.qty_available',
        string='Stock Bodega', readonly=True, store=True,
    )
    principio_activo_rel = fields.Char(
        related='medicamento_id.active_component',
        string='Principio Activo', readonly=True,
    )
    alerta_stock = fields.Selection(
        [('normal', 'OK'), ('critico', 'CRÍTICO')],
        compute='_compute_alerta_stock', store=True,
    )
    cantidad = fields.Float(
        string='Cant. a Adquirir', default=10.0,
    )
    purchase_order_id = fields.Many2one(
        'purchase.order', string='Orden Compra', readonly=True,
    )
    estado = fields.Selection(
        [('borrador', 'En Revisión'), ('procesado', 'Liberado')],
        default='borrador',
    )
    requires_prescription_rel = fields.Boolean(
        related='medicamento_id.requires_prescription',
        string='¿Requiere Receta?', readonly=False,
    )
    receta_rel = fields.Binary(
        related='medicamento_id.prescription_file',
        string='Receta', readonly=False,
    )
    receta_aprobada_ia_rel = fields.Boolean(
        related='medicamento_id.receta_aprobada_ia',
        string='Receta IA Aprobada', readonly=True,
    )
    ai_analysis_result = fields.Html(
        string='Último Resultado IA', readonly=True,
    )
    ai_analysis_timestamp = fields.Datetime(
        string='Timestamp Último Análisis', readonly=True,
    )
    condiciones_paciente = fields.Text(
        string='Condiciones del Paciente',
        help=(
            "Condiciones separadas por coma. "
            "Ej: Diabetes, Insuficiencia Renal\nAlimenta el RAG."
        ),
    )
    analisis_ids = fields.One2many(
        'farmacia.analisis.historial', 'gestion_id', string='Historial IA',
    )
    total_analisis = fields.Integer(
        string='Total Análisis',
        compute='_compute_total_analisis', store=True,
    )

    # ─── Computed fields ──────────────────────────────────────────────────

    @api.depends('analisis_ids')
    def _compute_total_analisis(self):
        for r in self:
            r.total_analisis = len(r.analisis_ids)

    @api.depends('stock_actual')
    def _compute_alerta_stock(self):
        for r in self:
            r.alerta_stock = (
                'critico' if r.stock_actual < STOCK_CRITICAL_THRESHOLD
                else 'normal'
            )

    # ─── Helpers privados ─────────────────────────────────────────────────

    def _get_api_key(self):
        """Obtiene la API key de Gemini desde la configuración del sistema."""
        key = self.env['ir.config_parameter'].sudo().get_param(
            'farmacia_bio.gemini_api_key',
        )
        if not key:
            raise UserError(
                "⚙️ API Key no configurada.\n"
                "Ve a: BioMed App → ⚙️ Configuración → 🔑 API Key de Gemini"
            )
        return key.strip()

    def _load_rag_service(self):
        """Carga el servicio RAG si está disponible.

        Returns:
            tuple: (rag_service_instance, is_available)
        """
        try:
            from ..services.rag_service import get_rag_service
            return get_rag_service(), True
        except Exception as e:
            _logger.warning("[BioMed RAG] No disponible: %s", e)
            return None, False

    def _get_rag_context(self, rag, med_name, condiciones_raw):
        """Obtiene contexto de contraindicaciones desde ChromaDB.

        Args:
            rag:              instancia de RAGService
            med_name:         nombre del medicamento
            condiciones_raw:  texto de condiciones del paciente (o False)

        Returns:
            dict con claves: encontradas, contraindicaciones, resumen_ejecutivo
        """
        fallback = {
            'encontradas': False,
            'contraindicaciones': [],
            'resumen_ejecutivo': 'RAG no disponible',
        }
        if not rag:
            return fallback
        try:
            condiciones = (
                [c.strip() for c in (condiciones_raw or '').split(',')
                 if c.strip()]
                or [f"Medicamento {med_name}"]
            )
            return rag.retrieve_context(med_name, condiciones, n_results=5)
        except Exception as e:
            _logger.warning("[BioMed RAG] Error ChromaDB: %s", e)
            return fallback

    def _build_rag_prompt(self, rag, rag_disponible, med_name, comp_name,
                          contexto_rag):
        """Genera el prompt para Gemini, con o sin enriquecimiento RAG."""
        try:
            if rag_disponible and rag:
                return rag.generate_rag_prompt(
                    med_name, comp_name, contexto_rag,
                )
        except Exception:
            pass
        return self._build_fallback_prompt(med_name, comp_name)

    def _build_result_html(self, html_response, receta_aprobada, contexto_rag):
        """Construye el HTML final del resultado, con banners de estado."""
        parts = []

        # Banner de contexto RAG
        if contexto_rag.get('encontradas'):
            parts.append(
                '<div style="background:#fff3cd;border-left:4px solid #ff9800;'
                'padding:8px 12px;margin-bottom:10px;border-radius:4px;'
                'font-size:13px;">'
                f'🧬 <strong>Contexto RAG:</strong> '
                f'{contexto_rag.get("resumen_ejecutivo", "")}</div>'
            )

        # Respuesta principal de Gemini
        parts.append(html_response)

        # Banner de aprobación/rechazo
        if receta_aprobada:
            parts.append(
                '<div style="background:#d4edda;border-left:4px solid #28a745;'
                'padding:12px;margin-top:12px;border-radius:4px;font-size:14px;'
                'font-weight:bold;">'
                '✅ RECETA APROBADA — El medicamento PUEDE ser comprado '
                'en Website y POS</div>'
            )
        else:
            parts.append(
                '<div style="background:#f8d7da;border-left:4px solid #dc3545;'
                'padding:12px;margin-top:12px;border-radius:4px;font-size:14px;'
                'font-weight:bold;">'
                '🚫 RECETA RECHAZADA — La compra está BLOQUEADA.</div>'
            )

        return ''.join(parts)

    @staticmethod
    def _build_fallback_prompt(med_name, comp_name):
        """Prompt de análisis cuando RAG no está disponible.

        Acepta nombres comerciales y genéricos.
        Ej: Amoxil = Amoxicilina = AMOXICILLIN → todos válidos.
        """
        base_name = med_name.split()[0] if med_name else med_name
        return (
            f"Eres un auditor farmacéutico certificado.\n"
            f"Analiza la imagen de receta médica adjunta.\n\n"
            f"MEDICAMENTO A VERIFICAR:\n"
            f"  - Nombre genérico: {base_name} / {comp_name}\n"
            f"  - Nombre completo registrado: {med_name}\n\n"
            f"IMPORTANTE: El medicamento puede aparecer en la receta como:\n"
            f"  - Su nombre genérico: '{base_name}' o '{comp_name}'\n"
            f"  - Un nombre comercial equivalente "
            f"(ej: Amoxil, Amoxidal, Trimox para Amoxicilina)\n"
            f"  - Con dosis diferente a la registrada (aún así puede ser válido)\n"
            f"  - Con mayúsculas/minúsculas distintas\n\n"
            f"CRITERIOS DE APROBACIÓN (basta con UNO):\n"
            f"  ✓ La receta menciona '{base_name}' (o variante comercial conocida)\n"
            f"  ✓ La receta menciona '{comp_name}' (principio activo)\n"
            f"  ✓ El medicamento prescrito tiene el mismo principio activo\n\n"
            f"CRITERIOS DE RECHAZO (todos deben cumplirse):\n"
            f"  ✗ La imagen NO es una receta médica real\n"
            f"  ✗ La receta NO contiene '{base_name}', '{comp_name}' "
            f"ni equivalentes\n"
            f"  ✗ Falta firma o sello del médico\n\n"
            f"FORMATO DE RESPUESTA: HTML puro, sin markdown, sin backticks.\n"
            f"Incluye exactamente una de estas palabras en mayúsculas: "
            f"APROBADO o RECHAZADO.\n"
            f"Si el medicamento o su equivalente aparece en la receta "
            f"→ APROBADO."
        )

    # ─── Acciones de botón ────────────────────────────────────────────────

    def action_analizar_receta_ia(self):
        """Ejecuta el análisis IA de la receta con contexto RAG."""
        for record in self:
            if not record.receta_rel:
                raise UserError(
                    "📎 Debe adjuntar la imagen de la receta digital."
                )

            med_name = record.medicamento_id.name or "Medicamento"
            comp_name = record.principio_activo_rel or med_name
            api_key = self._get_api_key()

            # Validar imagen
            raw = record.receta_rel
            imagen_b64 = (
                raw.decode('utf-8') if isinstance(raw, bytes) else str(raw)
            )
            if not imagen_b64 or len(imagen_b64) < 100:
                raise UserError(
                    "❌ La imagen adjunta parece estar vacía o corrupta."
                )

            # Cargar RAG
            rag, rag_disponible = self._load_rag_service()

            # Obtener contexto de contraindicaciones
            contexto_rag = self._get_rag_context(
                rag, med_name, record.condiciones_paciente,
            )

            # Generar prompt
            prompt = self._build_rag_prompt(
                rag, rag_disponible, med_name, comp_name, contexto_rag,
            )

            # Llamar a Gemini
            try:
                from ..services.gemini_service import get_gemini_service
                gemini = get_gemini_service(api_key=api_key)
                resultado = gemini.analyze_prescription_with_rag(
                    imagen_b64, med_name, comp_name, prompt,
                )
            except ImportError:
                raise UserError("❌ GeminiService no disponible.")

            if (resultado.get('error')
                    and not resultado.get('html_response', '').strip()):
                raise UserError(
                    f"Error en Gemini: {resultado['error']}"
                )

            html_response = resultado.get('html_response', '')
            receta_aprobada = resultado.get('approved', False)
            tuvo_contraindicaciones = resultado.get(
                'has_contraindications', False,
            )

            # Construir HTML final
            html_final = self._build_result_html(
                html_response, receta_aprobada, contexto_rag,
            )

            # Guardar resultados
            now = fields.Datetime.now()
            record.medicamento_id.sudo().write({
                'receta_aprobada_ia': receta_aprobada,
            })
            record.write({
                'ai_analysis_result': html_final,
                'ai_analysis_timestamp': now,
            })

            self.env['farmacia.analisis.historial'].create({
                'gestion_id': record.id,
                'timestamp': now,
                'condiciones_paciente': (
                    record.condiciones_paciente or '(sin condiciones)'
                ),
                'resultado_html': html_final,
                'tuvo_contraindicaciones': tuvo_contraindicaciones,
                'receta_aprobada': receta_aprobada,
                'modelo_usado': GEMINI_MODEL,
                'rag_utilizado': rag_disponible,
                'resumen_rag': contexto_rag.get('resumen_ejecutivo', ''),
            })
            _logger.info(
                "[BioMed] %s → %s",
                med_name,
                'APROBADA' if receta_aprobada else 'RECHAZADA',
            )
        return True

    def action_validar_medicamento(self):
        """Valida el medicamento contra la FDA y actualiza estados."""
        for record in self:
            record.medicamento_id.action_validate_medicine_api()
            if record.medicamento_id.fda_status == "APROBADO (REGISTRO FDA)":
                pos_category = self.env['pos.category'].search(
                    [('name', '=', 'Medicamentos')], limit=1,
                )
                record.medicamento_id.write({
                    'available_in_pos': True,
                    'pos_categ_ids': (
                        [(4, pos_category.id)] if pos_category else []
                    ),
                    'sale_ok': True,
                    'is_published': True,
                })
                record.write({
                    'estado': 'procesado',
                    'name': (
                        f"BATCH-"
                        f"{record.medicamento_id.name[:3].upper()}-"
                        f"{fields.Date.today()}"
                    ),
                })
            else:
                record.medicamento_id.write({'is_published': False})
                record.write({'estado': 'borrador'})
        return True

    def action_solicitar_stock_compra(self):
        """Genera una PO de reabastecimiento y la confirma."""
        for record in self:
            if record.medicamento_id.fda_status != "APROBADO (REGISTRO FDA)":
                raise UserError("Medicamento sin validación FDA")
            if not record.proveedor_id:
                raise UserError("Debe seleccionar proveedor")
            ordenes = record.medicamento_id.action_restock_purchase(
                qty=record.cantidad,
                partner_id=record.proveedor_id.id,
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
                _logger.error("Error recepción automática: %s", e)
                raise UserError(
                    f"PO creada pero error en recepción: {e}"
                )
        return True

    @api.model
    def get_dashboard_data(self):
        """Retorna métricas del dashboard BioMed.

        Cuenta product.template con is_medicine=True como fuente de verdad,
        no solo registros de farmacia.gestion.
        """
        Gestion = self.env['farmacia.gestion']
        Historial = self.env['farmacia.analisis.historial']
        ProductTpl = self.env['product.template']

        total_meds = ProductTpl.search_count([
            ('is_medicine', '=', True),
        ])
        procesados = Gestion.search_count([
            ('estado', '=', 'procesado'),
        ])
        en_revision = Gestion.search_count([
            ('estado', '=', 'borrador'),
        ])
        stock_critico = Gestion.search_count([
            ('alerta_stock', '=', 'critico'),
        ])
        sin_stock = Gestion.search_count([
            ('stock_actual', '=', 0),
        ])

        # Top medicamentos más analizados
        top_meds = []
        todas_gestiones = Gestion.search([])
        gestiones_con_analisis = todas_gestiones.filtered(
            lambda g: g.total_analisis > 0,
        )
        gestiones_ordenadas = sorted(
            gestiones_con_analisis,
            key=lambda g: g.total_analisis,
            reverse=True,
        )[:5]
        for g in gestiones_ordenadas:
            top_meds.append({
                'nombre': g.medicamento_id.name,
                'cantidad': g.total_analisis,
                'estado': g.estado,
            })

        return {
            'total_medicamentos': total_meds,
            'stock_critico': stock_critico,
            'procesados': procesados,
            'en_revision': en_revision,
            'sin_stock': sin_stock,
            'total_analisis': Historial.search_count([]),
            'analisis_con_riesgo': Historial.search_count([
                ('tuvo_contraindicaciones', '=', True),
            ]),
            'analisis_hoy': Historial.search_count([
                ('timestamp', '>=', fields.Date.today()),
            ]),
            'recetas_rechazadas': Historial.search_count([
                ('receta_aprobada', '=', False),
            ]),
            'recetas_aprobadas': Historial.search_count([
                ('receta_aprobada', '=', True),
            ]),
            'top_meds': top_meds,
        }
