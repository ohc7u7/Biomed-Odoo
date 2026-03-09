# -*- coding: utf-8 -*-
"""
FarmaciaAnalisisHistorial — Historial de análisis IA de recetas.
"""

import logging
from odoo import models, fields
from .constants import GEMINI_MODEL

_logger = logging.getLogger(__name__)


class FarmaciaAnalisisHistorial(models.Model):
    _name = 'farmacia.analisis.historial'
    _description = 'Historial de Análisis IA — BioMed'
    _order = 'timestamp desc'

    gestion_id = fields.Many2one(
        'farmacia.gestion', ondelete='cascade', required=True,
    )
    medicamento_id = fields.Many2one(
        'product.template', related='gestion_id.medicamento_id', store=True,
    )
    timestamp = fields.Datetime(
        default=fields.Datetime.now, readonly=True,
    )
    condiciones_paciente = fields.Text(
        string='Condiciones Registradas', readonly=True,
    )
    resultado_html = fields.Html(
        string='Resultado IA', readonly=True,
    )
    tuvo_contraindicaciones = fields.Boolean(
        string='¿Contraindicaciones?', readonly=True,
    )
    receta_aprobada = fields.Boolean(
        string='Receta Aprobada', readonly=True,
    )
    modelo_usado = fields.Char(
        string='Modelo IA', default=GEMINI_MODEL, readonly=True,
    )
    rag_utilizado = fields.Boolean(
        string='RAG activo', readonly=True,
    )
    resumen_rag = fields.Char(
        string='Resumen RAG', readonly=True,
    )
