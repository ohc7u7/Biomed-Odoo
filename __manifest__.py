# -*- coding: utf-8 -*-
# BioMed — Farmacia Clínica Maestro v2.3
# [FIX] JS + XML del dashboard ambos en assets
{
    'name': 'BioMed — Farmacia Clínica Maestro',
    'version': '2.3',
    'summary': 'Gestión farmacéutica clínica con FDA, IA Gemini, RAG y control Website',
    'description': """
        Módulo BioMed para Odoo 18:
        - Validación FDA via OpenFDA API
        - Análisis de recetas con Google Gemini 2.5 Flash + RAG ChromaDB
        - Control de compra en Website y POS según estado de receta IA
        - Medicamentos en borrador no visibles en Website
        - Historial de análisis IA con auditoría completa
        - Dashboard de métricas en tiempo real (OWL)
    """,
    'author': 'Orlán HC',
    'website': 'https://github.com/ohc7u7/Biomed-Odoo',
    'license': 'LGPL-3',
    'category': 'Healthcare',
    'sequence': 1,

    'depends': [
        'base',
        'stock',
        'purchase',
        'sale',
        'point_of_sale',
        'mail',
        'web',
        'website',
        'website_sale',
    ],

    'data': [
        'security/ir.model.access.csv',
        'views/farmacia_views.xml',
    ],

    'assets': {
        'web.assets_backend': [
            # XML primero — el JS lo referencia por nombre de template
            'farmacia_bio/static/src/xml/biomed_dashboard.xml',
            'farmacia_bio/static/src/js/biomed_dashboard.js',
        ],
    },

    'post_init_hook': 'post_init_hook',

    'installable': True,
    'application': True,
    'auto_install': False,
}