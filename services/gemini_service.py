# -*- coding: utf-8 -*-
"""
Servicio Gemini — BioMed App
Modelo activo: gemini-2.5-flash (marzo 2026)

Maneja las llamadas a la API de Google Gemini para análisis
de recetas médicas con contexto RAG.
"""

import os
import requests
import logging
from typing import Dict, Optional

_logger = logging.getLogger(__name__)

# Importar constantes centralizadas
try:
    from ..models.constants import (
        GEMINI_MODEL, GEMINI_API_URL, GEMINI_API_TIMEOUT,
    )
except ImportError:
    # Fallback para ejecución standalone (tests, scripts)
    GEMINI_MODEL = "gemini-2.5-flash"
    GEMINI_API_URL = (
        f"https://generativelanguage.googleapis.com/v1beta/models"
        f"/{GEMINI_MODEL}:generateContent"
    )
    GEMINI_API_TIMEOUT = 30


class GeminiService:
    """Cliente Google Gemini con soporte para análisis RAG."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        if not self.api_key:
            raise ValueError(
                "API Key de Gemini requerida. "
                "Configura en: BioMed → ⚙️ Configuración → 🔑 API Key"
            )

    # ─── Método principal ─────────────────────────────────────────────────

    def analyze_prescription_with_rag(
        self,
        image_base64: str,
        medicine_name: str,
        active_component: str,
        rag_prompt: str,
    ) -> Dict:
        """Analiza una receta médica con contexto RAG.

        Args:
            image_base64:     Imagen de la receta en Base64
            medicine_name:    Nombre del medicamento
            active_component: Principio activo del fármaco
            rag_prompt:       Prompt enriquecido generado por RAGService

        Returns:
            Dict con: approved, html_response, error, has_contraindications
        """
        if not image_base64 or not image_base64.strip():
            return self._error_result(
                '❌ Error: imagen vacía o inválida.',
                'Imagen Base64 vacía',
            )

        payload = {
            "contents": [{
                "parts": [
                    {"text": rag_prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_base64,
                        },
                    },
                ],
            }],
            "generationConfig": {
                "temperature": 0.2,
                "top_p": 0.95,
                "maxOutputTokens": 1024,
            },
        }

        try:
            url = f"{GEMINI_API_URL}?key={self.api_key}"
            _logger.info(
                "[GeminiService] Analizando receta: %s con %s",
                medicine_name, GEMINI_MODEL,
            )

            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=GEMINI_API_TIMEOUT,
            )

            if response.status_code == 200:
                return self._parse_success_response(response.json())
            return self._handle_error_response(response)

        except requests.exceptions.Timeout:
            return self._error_result(
                f'⏱️ Gemini tardó más de {GEMINI_API_TIMEOUT}s. '
                'Intenta con una imagen más pequeña.',
                'Timeout',
            )
        except requests.exceptions.ConnectionError:
            return self._error_result(
                '❌ Sin conexión a internet.',
                'Connection error',
            )
        except Exception as e:
            _logger.exception("[GeminiService] Error inesperado: %s", e)
            return self._error_result(
                f'❌ Error interno: {e}',
                str(e),
            )

    # ─── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _error_result(html_msg: str, error_str: str) -> dict:
        """Construye un resultado de error estandarizado."""
        return {
            'approved': False,
            'html_response': f'<div style="color:red;">{html_msg}</div>',
            'error': error_str,
            'has_contraindications': False,
        }

    @staticmethod
    def _parse_success_response(data: dict) -> dict:
        """Extrae y procesa la respuesta exitosa de Gemini."""
        try:
            html_response = (
                data['candidates'][0]['content']['parts'][0]['text'].strip()
            )
            html_response = (
                html_response.replace('```html', '').replace('```', '').strip()
            )

            has_contraindications = any(kw in html_response for kw in [
                '⚠️', 'CRÍTICO', 'ALTO', 'Riesgo',
                'contraindicación', 'CONTRAINDICACIÓN',
            ])
            approved = (
                ('✓' in html_response or 'APROBADO' in html_response)
                and 'RECHAZADO' not in html_response
            )

            _logger.info("[GeminiService] ✓ Análisis completado")
            return {
                'approved': approved,
                'html_response': html_response,
                'error': None,
                'has_contraindications': has_contraindications,
            }

        except (KeyError, IndexError, TypeError) as e:
            _logger.error(
                "[GeminiService] Error parseando respuesta: %s", e,
            )
            return GeminiService._error_result(
                f'Error parseando respuesta de Gemini: {e}',
                str(e),
            )

    @staticmethod
    def _handle_error_response(response) -> dict:
        """Maneja respuestas de error HTTP de Gemini."""
        code = response.status_code
        messages = {
            400: "❌ Solicitud inválida (400). Verifica imagen JPEG.",
            401: "🔑 API Key inválida o expirada (401). Actualízala.",
            403: "🚫 Sin permisos para este modelo (403).",
            404: (
                f"🔍 Modelo '{GEMINI_MODEL}' no encontrado (404). "
                "Verifica en Google AI Studio."
            ),
            429: "⏳ Límite de solicitudes alcanzado (429). Espera.",
            500: "🔥 Error interno de Google (500). Intenta más tarde.",
        }
        msg = messages.get(code, f"Error HTTP {code}: {response.text[:200]}")
        return GeminiService._error_result(msg, f"HTTP {code}")


# ─── Singleton ────────────────────────────────────────────────────────────────
_gemini_service: Optional[GeminiService] = None


def get_gemini_service(api_key: Optional[str] = None) -> GeminiService:
    """Factory para obtener instancia del servicio Gemini.

    Si se pasa una api_key diferente a la del singleton actual,
    recrea la instancia para usar la key más reciente.
    """
    global _gemini_service

    if not api_key:
        api_key = os.getenv('GOOGLE_GEMINI_API_KEY')

    # Recrea si: no existe, o la key cambió
    if (_gemini_service is None
            or (api_key and _gemini_service.api_key != api_key)):
        _gemini_service = GeminiService(api_key=api_key)

    return _gemini_service


def reset_gemini_service():
    """Resetea el singleton (para testing)."""
    global _gemini_service
    _gemini_service = None