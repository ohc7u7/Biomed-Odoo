# -*- coding: utf-8 -*-
"""
Constantes centralizadas del módulo BioMed.
Un solo lugar para ajustar modelos, umbrales y URLs.
"""

# ─── Gemini AI ────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_API_URL = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent"

# ─── Timeouts (segundos) ─────────────────────────────────────────────────────
FDA_API_TIMEOUT = 10
GEMINI_API_TIMEOUT = 30
CONFIG_TEST_TIMEOUT = 10

# ─── Umbrales ─────────────────────────────────────────────────────────────────
STOCK_CRITICAL_THRESHOLD = 10       # stock < este valor → alerta CRÍTICO
RAG_RELEVANCE_THRESHOLD = 0.3      # relevancia mínima para incluir contraindicación
API_KEY_MIN_LENGTH = 20            # longitud mínima aceptable para API key

# ─── ChromaDB ─────────────────────────────────────────────────────────────────
CHROMADB_COLLECTION_NAME = "biomed_contraindications"
CHROMADB_DEFAULT_DIR = "~/.biomed_rag"

# ─── FDA API ──────────────────────────────────────────────────────────────────
FDA_API_BASE = "https://api.fda.gov/drug/label.json"
