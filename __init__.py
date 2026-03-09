# -*- coding: utf-8 -*-
"""
__init__.py raíz — BioMed Farmacia Clínica Maestro v3.0
"""
from . import models
from . import wizards
from . import controllers


def post_init_hook(cr, registry):
    """Se ejecuta al instalar: carga contraindicaciones iniciales en ChromaDB."""
    try:
        from .services.contraindications_db import get_contraindications_db
        db = get_contraindications_db()
        db.load_initial_data()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "[BioMed] No se pudo cargar ChromaDB en post_init_hook: %s. "
            "Instala chromadb con: pip install chromadb --break-system-packages",
            e,
        )


def uninstall_hook(cr, registry):
    """Se ejecuta al desinstalar: limpia datos de ChromaDB."""
    try:
        from .services.contraindications_db import get_contraindications_db
        db = get_contraindications_db()
        db.reset_database()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "[BioMed] No se pudo limpiar ChromaDB en uninstall_hook: %s", e,
        )