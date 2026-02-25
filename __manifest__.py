{
    'name': 'BioMed: Farmacia Clínica Maestro',
    'version': '1.0',
    'summary': 'Módulo Maestro de Gestión Farmacéutica',
    # Se añade 'website_sale' para habilitar el control de stock en el eCommerce
   'depends': ['base', 'stock', 'purchase', 'sale', 'point_of_sale', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/farmacia_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}