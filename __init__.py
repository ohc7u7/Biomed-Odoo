# -*- coding: utf-8 -*-
"""
__init__.py raíz — BioMed Farmacia Clínica Maestro

CAMBIOS v2.1:
─────────────────────────────────────────────────────────────────────────────
[FIX]    wizards/ no estaba importado → BiomedConfigWizard no cargaba.
[NEW-02] El modelo FarmaciaAnalisisHistorial y BiomedDashboard están en
         models/medicamento.py, no requieren archivo separado.
─────────────────────────────────────────────────────────────────────────────
"""
from . import models
from . import wizards   # [FIX] agregado — faltaba completamente
from . import controllers


def post_init_hook(cr, registry):
    """
    Se ejecuta UNA VEZ al instalar el módulo en Odoo.
    Carga las 10 contraindicaciones iniciales en ChromaDB.
    """
    try:
        from .services.contraindications_db import get_contraindications_db
        db = get_contraindications_db()
        db.load_initial_data()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f"[BioMed] No se pudo cargar ChromaDB en post_init_hook: {e}. "
            "Instala chromadb con: pip install chromadb --break-system-packages"
        )