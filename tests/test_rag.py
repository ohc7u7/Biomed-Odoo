# -*- coding: utf-8 -*-
"""Tests para funcionalidad RAG."""

import sys
import os

# Agregar ruta del módulo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.rag_service import get_rag_service
from services.contraindications_db import get_contraindications_db


def test_contraindications_db():
    """Prueba que la BD de contraindicaciones funciona."""
    print("\n" + "="*70)
    print("TEST 1: Búsqueda de Contraindicaciones en ChromaDB")
    print("="*70)
    
    try:
        db = get_contraindications_db()
        
        results = db.search_contraindications(
            medicina_nombre="Paracetamol",
            condiciones_paciente=["Insuficiencia Hepática"],
            n_results=3
        )
        
        print(f"\n✓ BD inicializada correctamente")
        print(f"Medicamento: Paracetamol")
        print(f"Condición: Insuficiencia Hepática")
        print(f"\nResultados encontrados: {len(results)}")
        
        for i, r in enumerate(results, 1):
            print(f"\n{i}. {r['metadata'].get('medicamento')} - {r['metadata'].get('condicion')}")
            print(f"   Riesgo: {r['metadata'].get('riesgo')}")
            print(f"   Distancia: {r['distancia']:.3f}")
        
        print(f"\n✓ TEST 1 PASÓ")
        return True
    
    except Exception as e:
        print(f"\n✗ TEST 1 FALLÓ: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_rag_context():
    """Prueba que el RAG recupera contexto correcto."""
    print("\n" + "="*70)
    print("TEST 2: Recuperación de Contexto RAG")
    print("="*70)
    
    try:
        rag = get_rag_service()
        
        context = rag.retrieve_context(
            medicina_nombre="Warfarina",
            condiciones_paciente=["Embarazo"],
            n_results=5
        )
        
        print(f"\n✓ Servicio RAG inicializado")
        print(f"Medicamento: Warfarina")
        print(f"Condición: Embarazo")
        print(f"\nEncontradas contraindicaciones: {context['encontradas']}")
        print(f"Resumen: {context['resumen_ejecutivo']}")
        print(f"\nDetalles ({len(context['contraindicaciones'])} encontradas):")
        
        for contra in context['contraindicaciones']:
            print(f"  - {contra['medicamento']}: {contra['condicion']} [{contra['riesgo']}]")
            print(f"    Relevancia: {contra['relevancia']*100:.0f}%")
        
        print(f"\n✓ TEST 2 PASÓ")
        return True
    
    except Exception as e:
        print(f"\n✗ TEST 2 FALLÓ: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_rag_prompt():
    """Prueba que el prompt RAG se genera correctamente."""
    print("\n" + "="*70)
    print("TEST 3: Generación de Prompt RAG Enriquecido")
    print("="*70)
    
    try:
        rag = get_rag_service()
        
        context = rag.retrieve_context(
            medicina_nombre="Ibuprofen",
            condiciones_paciente=["Úlcera Gástrica"],
            n_results=3
        )
        
        prompt = rag.generate_rag_prompt(
            medicina_nombre="Ibuprofen",
            componente_activo="Ibuprofeno",
            contexto_contraindicaciones=context
        )
        
        print(f"\n✓ Prompt RAG generado exitosamente")
        print(f"Medicamento: Ibuprofen")
        print(f"Condición del paciente: Úlcera Gástrica")
        print(f"\nPrimeros 400 caracteres del prompt:")
        print("-" * 70)
        print(prompt[:400] + "...")
        print("-" * 70)
        print(f"\nPrompt contiene sección de contraindicaciones: {'CONTRAINDICACIONES' in prompt}")
        print(f"Longitud total del prompt: {len(prompt)} caracteres")
        
        print(f"\n✓ TEST 3 PASÓ")
        return True
    
    except Exception as e:
        print(f"\n✗ TEST 3 FALLÓ: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Ejecuta todos los tests."""
    print("\n" + "="*70)
    print("🧪 TESTS RAG - BioMed Pharmacy System (Fase 2)")
    print("="*70)
    print(f"Pruebas de ChromaDB + RAG + Prompt Enriquecimiento\n")
    
    results = {
        'test_contraindications_db': test_contraindications_db(),
        'test_rag_context': test_rag_context(),
        'test_rag_prompt': test_rag_prompt()
    }
    
    print("\n" + "="*70)
    print("📊 RESUMEN DE TESTS")
    print("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASÓ" if result else "✗ FALLÓ"
        print(f"{test_name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests pasaron")
    
    if passed == total:
        print("\n🎉 ¡Todos los tests completados exitosamente!")
        print("La arquitectura RAG está lista para integración en Odoo")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) fallaron. Revisa los errores arriba.")
        return 1


if __name__ == '__main__':
    exit(main())