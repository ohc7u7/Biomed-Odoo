# -*- coding: utf-8 -*-
"""
Servicio RAG: Retrieval-Augmented Generation.
Extrae contexto de la BD vectorial de contraindicaciones
y lo pasa a Gemini para análisis enriquecido de recetas.

CAMBIOS v2.2:
─────────────────────────────────────────────────────────────────────────────
[FIX v2.2] embedding_service eliminado del __init__ de RAGService.
           Antes: self.embedding_service = get_embedding_service() se ejecutaba
           al instanciar RAGService, lo que cargaba sentence-transformers.
           Si sentence-transformers no está instalado, el proceso se bloqueaba
           silenciosamente al hacer action_analizar_receta_ia().
           ChromaDB hace su propia vectorización interna — no necesitamos
           cargar sentence-transformers desde RAGService.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
from typing import Dict, List, Optional
from .contraindications_db import get_contraindications_db

_logger = logging.getLogger(__name__)


class RAGService:
    """
    Orquesta el flujo de:
    1. Búsqueda en BD vectorial de contraindicaciones
    2. Extracción de contexto relevante
    3. Generación de prompt enriquecido para Gemini
    """

    def __init__(self):
        # [FIX v2.2] Solo carga ChromaDB, NO embedding_service
        # embedding_service requiere sentence-transformers que puede no estar instalado
        self.db = get_contraindications_db()

    def retrieve_context(
        self,
        medicina_nombre: str,
        condiciones_paciente: List[str] = None,
        n_results: int = 5
    ) -> Dict:
        """
        Recupera contexto de contraindicaciones relevantes desde ChromaDB.

        Args:
            medicina_nombre:      Nombre del medicamento
            condiciones_paciente: Lista de condiciones médicas del paciente
            n_results:            Cuántos resultados retornar

        Returns:
            {
                'encontradas': bool,
                'contraindicaciones': [...],
                'resumen_ejecutivo': str
            }
        """
        if condiciones_paciente is None:
            condiciones_paciente = []

        results = self.db.search_contraindications(
            medicina_nombre=medicina_nombre,
            condiciones_paciente=condiciones_paciente,
            n_results=n_results
        )

        contraindicaciones = []
        for result in results:
            metadata  = result.get('metadata', {})
            distancia = result.get('distancia', 1.0)
            relevancia = max(0, 1 - distancia)

            if relevancia > 0.3:
                contraindicaciones.append({
                    'medicamento': metadata.get('medicamento', 'Desconocido'),
                    'condicion':   metadata.get('condicion', 'Desconocida'),
                    'riesgo':      metadata.get('riesgo', 'DESCONOCIDO'),
                    'descripcion': result.get('documento', ''),
                    'relevancia':  round(relevancia, 2)
                })

        riesgo_order = {'CRÍTICO': 0, 'ALTO': 1, 'MEDIO': 2, 'BAJO': 3}
        contraindicaciones.sort(
            key=lambda x: (riesgo_order.get(x['riesgo'], 4), -x['relevancia'])
        )

        if contraindicaciones:
            criticos = [c for c in contraindicaciones if c['riesgo'] == 'CRÍTICO']
            if criticos:
                resumen = f"⚠️ ALERTA: {len(criticos)} contraindicación(es) CRÍTICA(s) encontradas"
            else:
                resumen = "⚠️ PRECAUCIÓN: Se encontraron contraindicaciones relevantes"
        else:
            resumen = "✓ No se encontraron contraindicaciones conocidas"

        return {
            'encontradas':       len(contraindicaciones) > 0,
            'contraindicaciones': contraindicaciones,
            'resumen_ejecutivo': resumen
        }

    def generate_rag_prompt(
        self,
        medicina_nombre: str,
        componente_activo: str,
        contexto_contraindicaciones: Dict
    ) -> str:
        """
        Genera prompt enriquecido para Gemini con contexto RAG.

        Args:
            medicina_nombre:              Nombre del medicamento
            componente_activo:            Componente activo del fármaco
            contexto_contraindicaciones:  Resultado de retrieve_context()

        Returns:
            Prompt HTML para Gemini
        """
        contraindicaciones_str = ""

        if contexto_contraindicaciones.get('contraindicaciones'):
            contraindicaciones_str = "\n\n## CONTRAINDICACIONES CONOCIDAS (de BD médica):\n"
            for i, contra in enumerate(contexto_contraindicaciones['contraindicaciones'][:3], 1):
                contraindicaciones_str += (
                    f"\n{i}. [{contra['riesgo']}] Condición: {contra['condicion']}\n"
                    f"   Descripción: {contra['descripcion']}\n"
                    f"   Relevancia: {contra['relevancia']*100:.0f}%\n"
                )

        prompt = f"""INSTRUCCIONES CRÍTICAS PARA AUDITORÍA FARMACÉUTICA CON IA:

## MEDICAMENTO A AUDITAR:
- Nombre: {medicina_nombre}
- Componente Activo: {componente_activo}

## TAREA 1 - Validación de Receta:
1. ¿Es realmente una receta médica válida? (no es foto de persona, paisaje, etc.)
2. ¿Se puede leer el medicamento '{medicina_nombre}' o su componente '{componente_activo}'?
3. ¿Hay información visible sobre condiciones del paciente?

## TAREA 2 - Análisis de Riesgos:
La siguiente información proviene de una base de datos médica actualizada.
Si el medicamento aparece en estas contraindicaciones, DEBES ALERTAR:
{contraindicaciones_str}

## GENERACIÓN DE RESPUESTA:
Responde ESTRICTAMENTE en HTML puro (sin markdown, sin backticks).

Estructura OBLIGATORIA:
<div style="font-family: Arial; padding: 15px; border-radius: 8px;">
  <h4>📋 Auditoría de Receta - BioMed AI</h4>

  <section style="margin-top: 15px; padding: 10px; background-color: #f0f0f0; border-left: 4px solid #333;">
    <h5>Validación de Documento</h5>
    <ul>
      <li>✓ o ✗ + descripción de qué ves en la foto</li>
      <li>✓ o ✗ + si contiene el medicamento solicitado</li>
      <li>✓ o ✗ + si se puede leer claramente</li>
    </ul>
  </section>

  <section style="margin-top: 15px; padding: 10px; background-color: #fff3cd; border-left: 4px solid #ff9800;">
    <h5>⚠️ Análisis de Riesgos (si aplica)</h5>
    <p>Tu análisis de contraindicaciones basado en datos médicos</p>
  </section>

  <section style="margin-top: 15px; padding: 10px; border-left: 4px solid #333;">
    <h5>Veredicto Final</h5>
    <p style="font-size: 16px; font-weight: bold;">
      <span style="color: green;">✓ APROBADO</span> o <span style="color: red;">✗ RECHAZADO</span>
    </p>
    <p>Razón clara y concisa.</p>
  </section>
</div>"""

        return prompt


# ─── Singleton ────────────────────────────────────────────────────────────────
_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    """Factory para obtener el servicio RAG (singleton)."""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service