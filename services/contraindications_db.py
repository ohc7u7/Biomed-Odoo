# -*- coding: utf-8 -*-
"""
Gestión de la base de datos de contraindicaciones médicas.
Usa ChromaDB para almacenar y recuperar información sobre
medicamentos peligrosos según condiciones del paciente.

CAMBIOS v2.1:
─────────────────────────────────────────────────────────────────────────────
[FIX-07] except desnudo (sin tipo) en __init__ al obtener la colección
         ChromaDB. Un except: captura KeyboardInterrupt, SystemExit y otros
         no relacionados con errores de colección. Corregido a except Exception.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from typing import List, Dict, Optional

_logger = logging.getLogger(__name__)

try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    _logger.warning(
        "ChromaDB no está instalado. "
        "Instala con: pip install chromadb --break-system-packages"
    )


class ContraindicationsDatabase:
    """
    Gestiona la base de datos vectorial de contraindicaciones médicas.
    Usa ChromaDB en modo persistente (~/.biomed_rag/).
    Compatible con ChromaDB 0.4.x+
    """

    def __init__(self, persist_directory: Optional[str] = None):
        if not CHROMADB_AVAILABLE:
            raise ImportError("ChromaDB requerido. Instala: pip install chromadb")

        if persist_directory is None:
            persist_directory = os.path.expanduser("~/.biomed_rag")

        os.makedirs(persist_directory, exist_ok=True)

        try:
            self.client = chromadb.PersistentClient(path=persist_directory)
            _logger.info(f"✓ ChromaDB inicializado en: {persist_directory}")
        except Exception as e:
            _logger.error(f"Error inicializando ChromaDB: {e}")
            raise

        # [FIX-07] Cambiado de `except:` a `except Exception:`
        # El except desnudo anterior capturaba SystemExit y KeyboardInterrupt,
        # ocultando errores graves de configuración del sistema.
        try:
            self.collection = self.client.get_collection(
                name="biomed_contraindications"
            )
            _logger.info("✓ Colección ChromaDB existente cargada")
        except Exception:
            self.collection = self.client.create_collection(
                name="biomed_contraindications",
                metadata={"hnsw:space": "cosine"}
            )
            _logger.info("✓ Colección ChromaDB nueva creada")

    @staticmethod
    def _get_default_contraindications() -> List[Dict]:
        """Retorna las contraindicaciones base precargadas."""
        return [
            {
                "id": "contra_001",
                "medicamento": "Paracetamol",
                "condicion": "Insuficiencia Hepática",
                "riesgo": "CRÍTICO",
                "descripcion": "El paracetamol es metabolizado por el hígado. En pacientes con insuficiencia hepática, puede causar acumulación tóxica y necrosis hepática. Dosis máxima recomendada: <2g/día.",
                "fuente": "Ministerio de Salud - Guía de Medicamentos Peligrosos"
            },
            {
                "id": "contra_002",
                "medicamento": "Ibuprofen",
                "condicion": "Úlcera Gástrica Activa",
                "riesgo": "CRÍTICO",
                "descripcion": "Los AINE como ibuprofen aumentan riesgo de hemorragia gastrointestinal en pacientes con úlcera activa. Contraindicado absoluto.",
                "fuente": "Ministerio de Salud - Guía de Medicamentos Peligrosos"
            },
            {
                "id": "contra_003",
                "medicamento": "Metformina",
                "condicion": "Insuficiencia Renal Severa",
                "riesgo": "CRÍTICO",
                "descripcion": "La metformina se elimina por riñón. En insuficiencia renal severa (eGFR <30), riesgo de acidosis láctica fatal. Contraindicado.",
                "fuente": "Ministerio de Salud - Guía de Medicamentos Peligrosos"
            },
            {
                "id": "contra_004",
                "medicamento": "Warfarina",
                "condicion": "Embarazo",
                "riesgo": "CRÍTICO",
                "descripcion": "Warfarina es teratogénica, especialmente en 1er trimestre. Aumenta riesgo de síndrome fetal warfarina con deformidades esqueléticas y del SNC.",
                "fuente": "Ministerio de Salud - Guía de Medicamentos Peligrosos"
            },
            {
                "id": "contra_005",
                "medicamento": "Enalapril",
                "condicion": "Embarazo (2º y 3º trimestre)",
                "riesgo": "ALTO",
                "descripcion": "Los IECA causan oligohidramnios, insuficiencia renal fetal y muerte fetal en 2º y 3º trimestres. Evitar especialmente después de 1er trimestre.",
                "fuente": "Ministerio de Salud - Guía de Medicamentos Peligrosos"
            },
            {
                "id": "contra_006",
                "medicamento": "Codeína",
                "condicion": "Asma o EPOC",
                "riesgo": "ALTO",
                "descripcion": "La codeína deprime el centro respiratorio. En pacientes con asma/EPOC, riesgo de depresión respiratoria severa.",
                "fuente": "Ministerio de Salud - Guía de Medicamentos Peligrosos"
            },
            {
                "id": "contra_007",
                "medicamento": "Estatinas",
                "condicion": "Edad >70 años",
                "riesgo": "MEDIO",
                "descripcion": "Riesgo aumentado de miopatía y rabdomiolisis en adultos mayores. Requiere monitoreo de CPK. Considerar dosis menores.",
                "fuente": "Ministerio de Salud - Guía de Medicamentos Peligrosos"
            },
            {
                "id": "contra_008",
                "medicamento": "Dipirona (Metamizol)",
                "condicion": "Antecedente de agranulocitosis",
                "riesgo": "CRÍTICO",
                "descripcion": "Riesgo 10-50x mayor de agranulocitosis en pacientes con antecedentes. Puede causar infecciones fatales. Contraindicado absoluto.",
                "fuente": "Ministerio de Salud - Guía de Medicamentos Peligrosos"
            },
            {
                "id": "contra_009",
                "medicamento": "Fluconazol",
                "condicion": "QT prolongado basal",
                "riesgo": "ALTO",
                "descripcion": "Fluconazol prolonga intervalo QT. En pacientes con QT basal prolongado, riesgo de torsades de pointes. EKG previo recomendado.",
                "fuente": "Ministerio de Salud - Guía de Medicamentos Peligrosos"
            },
            {
                "id": "contra_010",
                "medicamento": "Nitrofurantoína",
                "condicion": "Insuficiencia Renal",
                "riesgo": "MEDIO",
                "descripcion": "Se acumula en insuficiencia renal. Riesgo de neuropatía periférica y neurotoxicidad. Usar con precaución si eGFR <30.",
                "fuente": "Ministerio de Salud - Guía de Medicamentos Peligrosos"
            }
        ]

    def load_initial_data(self):
        """Carga datos iniciales. Solo ejecuta si la colección está vacía."""
        count = self.collection.count()
        if count > 0:
            _logger.info(f"✓ Colección ya contiene {count} documentos. Saltando carga.")
            return

        contraindications = self._get_default_contraindications()
        ids       = [item["id"] for item in contraindications]
        documents = [item["descripcion"] for item in contraindications]
        metadatas = [
            {
                "medicamento": item["medicamento"],
                "condicion":   item["condicion"],
                "riesgo":      item["riesgo"],
                "fuente":      item["fuente"]
            }
            for item in contraindications
        ]

        self.collection.add(ids=ids, documents=documents, metadatas=metadatas)
        _logger.info(f"✓ Cargados {len(contraindications)} documentos en ChromaDB")

    def search_contraindications(
        self,
        medicina_nombre: str,
        condiciones_paciente: List[str],
        n_results: int = 5
    ) -> List[Dict]:
        """
        Busca contraindicaciones relevantes para un medicamento y condiciones dadas.

        Args:
            medicina_nombre:      Nombre del medicamento
            condiciones_paciente: Lista de condiciones del paciente
            n_results:            Cuántos resultados retornar

        Returns:
            Lista de contraindicaciones con score de relevancia
        """
        query = f"Medicamento {medicina_nombre}. Condiciones: {', '.join(condiciones_paciente)}"

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=min(n_results, self.collection.count())
            )

            contraindications = []
            if results and results['ids'] and len(results['ids']) > 0:
                for i, doc_id in enumerate(results['ids'][0]):
                    contraindications.append({
                        'id':        doc_id,
                        'documento': results['documents'][0][i] if results['documents'] else "",
                        'metadata':  results['metadatas'][0][i] if results['metadatas'] else {},
                        'distancia': results['distances'][0][i] if results['distances'] else 1.0
                    })
            return contraindications

        except Exception as e:
            _logger.error(f"Error buscando contraindicaciones: {e}")
            return []

    def reset_database(self):
        """Limpia la base de datos. SOLO para desarrollo/testing."""
        try:
            self.client.delete_collection(name="biomed_contraindications")
            self.collection = self.client.create_collection(
                name="biomed_contraindications",
                metadata={"hnsw:space": "cosine"}
            )
            _logger.info("✓ Base de datos de contraindicaciones reseteada")
        except Exception as e:
            _logger.error(f"Error reseteando BD: {e}")


# ─── Singleton ────────────────────────────────────────────────────────────────
_db_instance: Optional[ContraindicationsDatabase] = None


def get_contraindications_db() -> ContraindicationsDatabase:
    """Factory para obtener instancia de la BD (singleton con lazy loading)."""
    global _db_instance
    if _db_instance is None:
        _db_instance = ContraindicationsDatabase()
        _db_instance.load_initial_data()
    return _db_instance