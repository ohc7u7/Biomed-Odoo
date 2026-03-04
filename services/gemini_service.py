# -*- coding: utf-8 -*-
"""
Servicio Gemini — BioMed App
Modelo activo: gemini-2.5-flash (marzo 2026)

CAMBIOS v2.1:
─────────────────────────────────────────────────────────────────────────────
[FIX-05] Singleton no actualizaba la api_key si ya había instancia.
         Antes: get_gemini_service(nueva_key) ignoraba la key si _gemini_service
         ya existía. Ahora compara la key actual y recrea si cambió.

[FIX-06] _embed_with_gemini en embedding_service usaba os sin importarlo.
         Aquí se documenta el modelo correcto activo para evitar 404.
─────────────────────────────────────────────────────────────────────────────
"""

import os
import requests
import logging
from typing import Dict, Optional

_logger = logging.getLogger(__name__)

# ─── Modelos activos en v1beta (marzo 2026) ───────────────────────────────────
# gemini-1.5-pro              → DEPRECADO, retorna 404
# gemini-2.0-flash            → RETIRADO el 03/03/2026, retorna 404
# gemini-2.5-flash            → ✅ ACTIVO, free tier sin billing, recomendado
# gemini-2.5-flash-lite       → ✅ ACTIVO, más rápido, menor calidad
# gemini-2.5-pro              → ✅ ACTIVO, mayor calidad, más lento
GEMINI_MODEL   = "gemini-2.5-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


class GeminiService:
    """Cliente Google Gemini con soporte para análisis RAG de recetas médicas."""

    REQUEST_TIMEOUT = 30  # segundos

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        if not self.api_key:
            raise ValueError(
                "API Key de Gemini requerida. "
                "Configura en: BioMed → ⚙️ Configuración → 🔑 API Key"
            )

    def analyze_prescription_with_rag(
        self,
        image_base64: str,
        medicine_name: str,
        active_component: str,
        rag_prompt: str
    ) -> Dict:
        """
        Analiza una receta médica con contexto RAG.

        Args:
            image_base64:     Imagen de la receta en Base64
            medicine_name:    Nombre del medicamento
            active_component: Principio activo del fármaco
            rag_prompt:       Prompt enriquecido generado por RAGService

        Returns:
            {
                'approved':              bool,
                'html_response':         str,
                'error':                 Optional[str],
                'has_contraindications': bool
            }
        """
        if not image_base64 or not image_base64.strip():
            return {
                'approved': False,
                'html_response': '<div style="color:red;">❌ Error: imagen vacía o inválida.</div>',
                'error': 'Imagen Base64 vacía',
                'has_contraindications': False
            }

        payload = {
            "contents": [{
                "parts": [
                    {"text": rag_prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_base64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "temperature":     0.2,
                "top_p":           0.95,
                "maxOutputTokens": 1024
            }
        }

        try:
            url = f"{GEMINI_API_URL}?key={self.api_key}"
            _logger.info(f"[GeminiService] Analizando receta: {medicine_name} con {GEMINI_MODEL}")

            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self.REQUEST_TIMEOUT
            )

            if response.status_code == 200:
                return self._parse_success_response(response.json())

            return self._handle_error_response(response)

        except requests.exceptions.Timeout:
            return {
                'approved': False,
                'html_response': (
                    '<div style="color:orange;">⏱️ Gemini tardó más de 30s. '
                    'Intenta con una imagen más pequeña.</div>'
                ),
                'error': 'Timeout',
                'has_contraindications': False
            }
        except requests.exceptions.ConnectionError:
            return {
                'approved': False,
                'html_response': '<div style="color:red;">❌ Sin conexión a internet.</div>',
                'error': 'Connection error',
                'has_contraindications': False
            }
        except Exception as e:
            _logger.exception(f"[GeminiService] Error inesperado: {e}")
            return {
                'approved': False,
                'html_response': f'<div style="color:red;">❌ Error interno: {str(e)}</div>',
                'error': str(e),
                'has_contraindications': False
            }

    @staticmethod
    def _parse_success_response(data: dict) -> dict:
        """Extrae y procesa la respuesta exitosa de Gemini."""
        try:
            html_response = data['candidates'][0]['content']['parts'][0]['text'].strip()
            html_response = html_response.replace('```html', '').replace('```', '').strip()

            has_contraindications = any(kw in html_response for kw in [
                '⚠️', 'CRÍTICO', 'ALTO', 'Riesgo', 'contraindicación', 'CONTRAINDICACIÓN'
            ])
            approved = (
                ('✓' in html_response or 'APROBADO' in html_response) and
                'RECHAZADO' not in html_response
            )

            _logger.info("[GeminiService] ✓ Análisis completado")
            return {
                'approved':              approved,
                'html_response':         html_response,
                'error':                 None,
                'has_contraindications': has_contraindications
            }

        except (KeyError, IndexError, TypeError) as e:
            _logger.error(f"[GeminiService] Error parseando respuesta: {e}")
            return {
                'approved':              False,
                'html_response':         f'<div style="color:red;">Error parseando respuesta de Gemini: {e}</div>',
                'error':                 str(e),
                'has_contraindications': False
            }

    @staticmethod
    def _handle_error_response(response) -> dict:
        """Maneja respuestas de error HTTP de Gemini."""
        code = response.status_code
        messages = {
            400: "❌ Solicitud inválida (400). Verifica que la imagen sea JPEG válido.",
            401: "🔑 API Key inválida o expirada (401). Actualízala en ⚙️ Configuración.",
            403: "🚫 Sin permisos para usar este modelo (403). Verifica tu cuenta de Google AI.",
            404: (
                f"🔍 Modelo no encontrado (404). '{GEMINI_MODEL}' no disponible "
                "en tu plan. Verifica en Google AI Studio."
            ),
            429: "⏳ Límite de solicitudes alcanzado (429). Espera unos segundos.",
            500: "🔥 Error interno de Google (500). Intenta más tarde.",
        }
        msg = messages.get(code, f"Error HTTP {code}: {response.text[:200]}")
        return {
            'approved':              False,
            'html_response':         f'<div style="color:red;">{msg}</div>',
            'error':                 f"HTTP {code}",
            'has_contraindications': False
        }


# ─── Singleton robusto ────────────────────────────────────────────────────────
_gemini_service: Optional[GeminiService] = None


def get_gemini_service(api_key: Optional[str] = None) -> GeminiService:
    """
    Factory para obtener instancia del servicio Gemini.

    [FIX-05] Si se pasa una api_key diferente a la del singleton actual,
    recrea la instancia. Esto garantiza que siempre se use la key más
    reciente guardada en ir.config_parameter, sin necesidad de reiniciar Odoo.
    """
    global _gemini_service

    if not api_key:
        api_key = os.getenv('GOOGLE_GEMINI_API_KEY')

    # Recrea si: no existe, o la key cambió
    if _gemini_service is None or (api_key and _gemini_service.api_key != api_key):
        _gemini_service = GeminiService(api_key=api_key)

    return _gemini_service


def reset_gemini_service():
    """
    Resetea el singleton.
    Llamar desde action_analizar_receta_ia() para forzar
    lectura de la key más reciente desde la DB.
    """
    global _gemini_service
    _gemini_service = None