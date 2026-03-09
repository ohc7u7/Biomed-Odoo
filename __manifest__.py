# -*- coding: utf-8 -*-
{
    'name': 'BioMed — Farmacia Clínica Maestro',
    'version': '3.0',
    'summary': 'Gestión farmacéutica clínica con FDA, IA Gemini, RAG y control Website',
    'author': 'Orlán HC',
    'license': 'LGPL-3',
    'category': 'Healthcare',
    'sequence': 1,

    'depends': [
        'base', 'stock', 'purchase', 'sale',
        'point_of_sale', 'mail', 'web',
        'website', 'website_sale',
    ],

    'data': [
        'security/ir.model.access.csv',
        'views/farmacia_views.xml',
        'views/website_product_biomed.xml',
    ],

    'assets': {
        'web.assets_backend': [
            'farmacia_bio/static/src/xml/biomed_dashboard.xml',
            'farmacia_bio/static/src/js/biomed_dashboard.js',
        ],
        'web.assets_frontend': [
            'farmacia_bio/static/src/css/biomed_website.css',
            'farmacia_bio/static/src/js/biomed_website.js',
        ],
    },

    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',

    'installable': True,
    'application': True,
    'auto_install': False,
}