# -*- coding: utf-8 -*-
"""
Servicio de embeddings para análisis semántico de recetas.
Usa sentence-transformers local (all-MiniLM-L6-v2) como motor principal.

CAMBIOS v2.1:
─────────────────────────────────────────────────────────────────────────────
[FIX-06] Faltaba `import os` en el archivo. El método _embed_with_gemini()
         usaba os.getenv() pero os nunca fue importado → NameError en runtime
         si se intentaba usar el fallback de Gemini para embeddings.
─────────────────────────────────────────────────────────────────────────────
"""

import os          # [FIX-06] AGREGADO — faltaba completamente
import logging
import requests
from typing import List, Optional

_logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer
    LOCAL_EMBEDDINGS_AVAILABLE = True
except ImportError:
    LOCAL_EMBEDDINGS_AVAILABLE = False
    _logger.warning(
        "sentence-transformers no instalado. "
        "Instala con: pip install sentence-transformers --break-system-packages"
    )


class EmbeddingService:
    """
    Genera embeddings de textos médicos.
    Prioriza modelo local (all-MiniLM-L6-v2, 384 dims, sin API key).
    Fallback a Gemini si sentence-transformers no está disponible.
    """

    def __init__(self, use_local: bool = True):
        """
        Args:
            use_local: Si True, intenta usar modelo local sin API key.
        """
        self.use_local = use_local and LOCAL_EMBEDDINGS_AVAILABLE

        if self.use_local:
            try:
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
                _logger.info("✓ Modelo de embeddings local cargado (all-MiniLM-L6-v2)")
            except Exception as e:
                _logger.warning(f"Error cargando modelo local: {e}. Fallback a Gemini.")
                self.use_local = False
                self.model = None
        else:
            self.model = None

    def embed_text(self, text: str) -> Optional[List[float]]:
        """
        Genera embedding de un texto.

        Args:
            text: Texto a vectorizar

        Returns:
            Vector (lista de floats) o None si falla
        """
        if not text or not text.strip():
            return None

        try:
            if self.use_local and self.model:
                return self.model.encode(text).tolist()
            else:
                return self._embed_with_gemini(text)
        except Exception as e:
            _logger.error(f"Error generando embedding: {e}")
            return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Genera embeddings para múltiples textos (más eficiente en batch).

        Args:
            texts: Lista de textos

        Returns:
            Lista de vectores
        """
        if not texts:
            return []

        try:
            if self.use_local and self.model:
                embeddings = self.model.encode(texts)
                return embeddings.tolist()
            else:
                return [self._embed_with_gemini(text) for text in texts]
        except Exception as e:
            _logger.error(f"Error en batch embedding: {e}")
            return [None] * len(texts)

    @staticmethod
    def _embed_with_gemini(text: str) -> Optional[List[float]]:
        """
        Fallback: usa variables de entorno para embeddings externos.

        NOTA: Gemini no tiene endpoint dedicado de embeddings en v1beta.
        Para producción, usa siempre sentence-transformers local.
        Este método existe como placeholder documentado.

        [FIX-06] os ya está importado al inicio del módulo.
        """
        api_key = os.getenv('GOOGLE_GEMINI_API_KEY')  # os ahora disponible
        if not api_key:
            _logger.warning(
                "GOOGLE_GEMINI_API_KEY no configurada para embeddings. "
                "Instala sentence-transformers para embeddings locales."
            )
            return None

        _logger.warning(
            "Gemini no tiene endpoint de embeddings en v1beta. "
            "Instala sentence-transformers: pip install sentence-transformers"
        )
        return None


# ─── Singleton ────────────────────────────────────────────────────────────────
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service(use_local: bool = True) -> EmbeddingService:
    """Factory para obtener el servicio de embeddings (singleton)."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(use_local=use_local)
    return _embedding_service