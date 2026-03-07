# -*- coding: utf-8 -*-
# BioMed v5 - Borra gestion ANTES que el producto (FK fix) + rollback seguro
# exec(open('/home/orlan/odoo-dev/custom_addons/farmacia_bio/scripts/cargar_medicamentos.py').read())

import base64
from datetime import date

def _svg(color, abrev, dosis=""):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300">'
        '<defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">'
        f'<stop offset="0%" style="stop-color:{color};stop-opacity:1"/>'
        f'<stop offset="100%" style="stop-color:{color}BB;stop-opacity:1"/>'
        '</linearGradient></defs>'
        '<rect width="300" height="300" rx="28" fill="url(#g)"/>'
        '<ellipse cx="150" cy="95" rx="58" ry="30" fill="white" opacity="0.2"/>'
        '<line x1="150" y1="65" x2="150" y2="125" stroke="white" stroke-width="3" opacity="0.3"/>'
        f'<text x="150" y="120" text-anchor="middle" fill="white" font-family="Arial Black,sans-serif" font-size="36" font-weight="900">{abrev}</text>'
        '<line x1="40" y1="153" x2="260" y2="153" stroke="white" stroke-width="1.5" opacity="0.25"/>'
        f'<text x="150" y="192" text-anchor="middle" fill="white" font-family="Arial,sans-serif" font-size="19" opacity="0.88">{dosis}</text>'
        '<rect x="78" y="224" width="144" height="33" rx="16" fill="white" opacity="0.17"/>'
        '<text x="150" y="245" text-anchor="middle" fill="white" font-family="Arial,sans-serif" font-size="13" font-weight="bold">BioMed</text>'
        '</svg>'
    )
    return base64.b64encode(svg.encode()).decode()

# ── ROLLBACK primero (limpiar transaccion abortada anterior) ──
try:
    env.cr.rollback()
    print("  Rollback OK (limpia transaccion anterior si habia)")
except Exception:
    pass

def borrar_todo(env):
    print("\n" + "-" * 52)
    print("  PASO 1: Borrando gestiones y medicamentos")
    print("-" * 52)

    # 1A — borrar historial de analisis (depende de gestion)
    historiales = env['farmacia.analisis.historial'].search([])
    if historiales:
        historiales.unlink()
        print(f"  x {len(historiales)} registros de historial IA")

    # 1B — borrar farmacia.gestion ANTES que product.template (FK!)
    gestiones = env['farmacia.gestion'].search([])
    n_g = len(gestiones)
    if gestiones:
        gestiones.unlink()
        print(f"  x {n_g} registros farmacia.gestion")

    # 1C — ahora si borrar los productos medicamento
    meds = env['product.template'].search([('is_medicine', '=', True)])
    n_m = len(meds)
    eliminados = 0
    archivados = 0
    for med in meds:
        nombre = med.name
        try:
            med.unlink()
            eliminados += 1
            print(f"  x producto: {nombre}")
        except Exception as ex:
            # Tiene otras dependencias (facturas, etc.) — archivar
            try:
                env.cr.rollback()
                med.write({'active': False, 'is_medicine': False})
                archivados += 1
                print(f"  ~ archivado: {nombre}")
            except Exception:
                print(f"  ! no se pudo: {nombre}")

    print(f"\n  -> {eliminados} eliminados, {archivados} archivados ({n_m} total)")
    return eliminados + archivados

MEDICAMENTOS = [
    {"name":"Paracetamol",    "dosis":"500 mg",  "fda":"ACETAMINOPHEN",   "receta":False,"pventa":3.50, "pcosto":1.20,"stock":120,"color":"#4A90D9","abrev":"PAR"},
    {"name":"Ibuprofeno",     "dosis":"400 mg",  "fda":"IBUPROFEN",       "receta":False,"pventa":4.20, "pcosto":1.50,"stock":85, "color":"#E67E22","abrev":"IBU"},
    {"name":"Aspirina",       "dosis":"100 mg",  "fda":"ASPIRIN",         "receta":False,"pventa":2.80, "pcosto":0.90,"stock":200,"color":"#E74C3C","abrev":"ASP"},
    {"name":"Loratadina",     "dosis":"10 mg",   "fda":"LORATADINE",      "receta":False,"pventa":5.00, "pcosto":1.80,"stock":60, "color":"#27AE60","abrev":"LOR"},
    {"name":"Omeprazol",      "dosis":"20 mg",   "fda":"OMEPRAZOLE",      "receta":False,"pventa":6.50, "pcosto":2.10,"stock":95, "color":"#8E44AD","abrev":"OMP"},
    {"name":"Vitamina C",     "dosis":"500 mg",  "fda":"ASCORBIC ACID",   "receta":False,"pventa":3.00, "pcosto":0.80,"stock":300,"color":"#F39C12","abrev":"VIT"},
    {"name":"Clotrimazol",    "dosis":"1 %",     "fda":"CLOTRIMAZOLE",    "receta":False,"pventa":7.80, "pcosto":2.50,"stock":30, "color":"#BDC3C7","abrev":"CLO"},
    {"name":"Naproxeno",      "dosis":"250 mg",  "fda":"NAPROXEN",        "receta":False,"pventa":4.50, "pcosto":1.60,"stock":70, "color":"#2980B9","abrev":"NAP"},
    {"name":"Dextrometorfano","dosis":"15 mg",   "fda":"DEXTROMETHORPHAN","receta":False,"pventa":5.50, "pcosto":2.00,"stock":50, "color":"#1ABC9C","abrev":"DEX"},
    {"name":"Cetirizina",     "dosis":"10 mg",   "fda":"CETIRIZINE",      "receta":False,"pventa":4.80, "pcosto":1.60,"stock":65, "color":"#16A085","abrev":"CET"},
    {"name":"Hidrocortisona", "dosis":"1 %",     "fda":"HYDROCORTISONE",  "receta":False,"pventa":6.00, "pcosto":2.20,"stock":25, "color":"#F0B27A","abrev":"HID"},
    {"name":"Ranitidina",     "dosis":"150 mg",  "fda":"RANITIDINE",      "receta":False,"pventa":4.00, "pcosto":1.30,"stock":45, "color":"#D5D8DC","abrev":"RAN"},
    {"name":"Amoxicilina",    "dosis":"500 mg",  "fda":"AMOXICILLIN",     "receta":True, "pventa":8.90, "pcosto":3.20,"stock":40, "color":"#F1948A","abrev":"AMX"},
    {"name":"Metformina",     "dosis":"850 mg",  "fda":"METFORMIN",       "receta":True, "pventa":7.00, "pcosto":2.50,"stock":55, "color":"#58D68D","abrev":"MET"},
    {"name":"Warfarina",      "dosis":"5 mg",    "fda":"WARFARIN",        "receta":True, "pventa":12.00,"pcosto":4.50,"stock":20, "color":"#EC407A","abrev":"WAR"},
    {"name":"Enalapril",      "dosis":"10 mg",   "fda":"ENALAPRIL",       "receta":True, "pventa":9.50, "pcosto":3.00,"stock":65, "color":"#5DADE2","abrev":"ENA"},
    {"name":"Metoprolol",     "dosis":"100 mg",  "fda":"METOPROLOL",      "receta":True, "pventa":11.00,"pcosto":3.80,"stock":35, "color":"#2C3E50","abrev":"MTO"},
    {"name":"Fluconazol",     "dosis":"150 mg",  "fda":"FLUCONAZOLE",     "receta":True, "pventa":15.00,"pcosto":5.00,"stock":18, "color":"#A569BD","abrev":"FLU"},
    {"name":"Azitromicina",   "dosis":"500 mg",  "fda":"AZITHROMYCIN",    "receta":True, "pventa":14.00,"pcosto":4.80,"stock":30, "color":"#DC7633","abrev":"AZI"},
    {"name":"Atorvastatina",  "dosis":"20 mg",   "fda":"ATORVASTATIN",    "receta":True, "pventa":18.00,"pcosto":6.00,"stock":50, "color":"#2ECC71","abrev":"ATO"},
    {"name":"Losartan",       "dosis":"50 mg",   "fda":"LOSARTAN",        "receta":True, "pventa":10.50,"pcosto":3.50,"stock":75, "color":"#1E8BC3","abrev":"LOS"},
    {"name":"Levotiroxina",   "dosis":"50 mcg",  "fda":"LEVOTHYROXINE",   "receta":True, "pventa":22.00,"pcosto":8.00,"stock":8,  "color":"#F4D03F","abrev":"LEV"},
    {"name":"Alprazolam",     "dosis":"0.25 mg", "fda":"ALPRAZOLAM",      "receta":True, "pventa":25.00,"pcosto":9.00,"stock":5,  "color":"#E74C3C","abrev":"ALP"},
    {"name":"Prednisona",     "dosis":"20 mg",   "fda":"PREDNISONE",      "receta":True, "pventa":6.80, "pcosto":2.30,"stock":42, "color":"#F0E68C","abrev":"PRE"},
    {"name":"Insulina",       "dosis":"100 UI",  "fda":"INSULIN",         "receta":True, "pventa":35.00,"pcosto":14.0,"stock":15, "color":"#3498DB","abrev":"INS"},
]

def cargar_medicamentos(env):
    print("\n" + "-" * 52)
    print("  PASO 2: Cargando 25 medicamentos")
    print("-" * 52)

    ProductTemplate = env['product.template']
    FarmaciaGestion = env['farmacia.gestion']
    StockQuant      = env['stock.quant']

    ubicacion = env['stock.location'].search(
        [('complete_name', 'ilike', 'WH/Stock'), ('usage', '=', 'internal')], limit=1
    )
    if not ubicacion:
        ubicacion = env['stock.location'].search([('usage', '=', 'internal')], limit=1)
    print(f"  Ubicacion: {ubicacion.complete_name if ubicacion else 'No encontrada'}")

    categ = env['product.category'].search([('name', '=', 'Medicamentos')], limit=1)
    if not categ:
        categ = env['product.category'].create({'name': 'Medicamentos'})

    pos_categ = env['pos.category'].search([('name', '=', 'Medicamentos')], limit=1)
    if not pos_categ:
        pos_categ = env['pos.category'].create({'name': 'Medicamentos'})

    hoy = date.today().strftime("%Y-%m-%d")
    creados = 0

    for med in MEDICAMENTOS:
        imagen = _svg(med['color'], med['abrev'], med['dosis'])
        vals = {
            'name':                  med['name'],
            'categ_id':              categ.id,
            'list_price':            med['pventa'],
            'standard_price':        med['pcosto'],
            'is_medicine':           True,
            'active_component':      med['fda'],
            'fda_status':            'APROBADO (REGISTRO FDA)',
            'requires_prescription': med['receta'],
            'receta_aprobada_ia':    False,
            'description_sale':      med['dosis'],
            'available_in_pos':      True,
            'pos_categ_ids':         [(4, pos_categ.id)],
            'sale_ok':               True,
            'purchase_ok':           True,
            'is_published':          True,
            'image_1920':            imagen,
        }

        try:
            producto = ProductTemplate.create(vals)
            creados += 1
        except Exception as ex:
            print(f"  ERROR {med['name']}: {ex}")
            env.cr.rollback()
            continue

        # Ajustar stock
        stock_ok = False
        if ubicacion and med['stock'] > 0:
            variante = producto.product_variant_id
            if variante:
                try:
                    quant = StockQuant.search([
                        ('product_id', '=', variante.id),
                        ('location_id', '=', ubicacion.id),
                    ], limit=1)
                    if quant:
                        quant.sudo().write({'quantity': float(med['stock'])})
                    else:
                        StockQuant.sudo().create({
                            'product_id':  variante.id,
                            'location_id': ubicacion.id,
                            'quantity':    float(med['stock']),
                        })
                    stock_ok = True
                except Exception:
                    pass  # tipo no soporta quants, no es fatal

        # Farmacia.gestion — el create() de ProductTemplate ya lo crea
        # via override, pero lo buscamos para asegurar estado=procesado
        gestion = FarmaciaGestion.search([('medicamento_id', '=', producto.id)], limit=1)
        if not gestion:
            FarmaciaGestion.create({
                'medicamento_id': producto.id,
                'name':           f"BATCH-{med['abrev']}-{hoy}",
                'estado':         'procesado',
                'cantidad':       max(20.0, float(med['stock'])),
            })
        else:
            gestion.write({'estado': 'procesado', 'name': f"BATCH-{med['abrev']}-{hoy}"})

        icono  = "[R]" if med['receta'] else "   "
        alerta = " CRITICO" if med['stock'] < 10 else ""
        stxt   = f"{med['stock']:>4}" if stock_ok else " N/A"
        print(f"  + {icono} {med['name']:<18} stock:{stxt}  [{med['fda']}]{alerta}")

    print(f"\n  -> {creados} creados")
    return creados

# ── Ejecucion principal ───────────────────────────────────
print("=" * 52)
print("  BioMed v5 - FK fix + nombres ES + FDA ingles")
print("=" * 52)

n_b = borrar_todo(env)
n_c = cargar_medicamentos(env)
env.cr.commit()

print("\n" + "=" * 52)
print(f"  Eliminados : {n_b}  |  Creados : {n_c}")
print("=" * 52)
print("""
Listo. Los 25 medicamentos tienen:
  - Nombre en espanol (visible en UI)
  - Principio activo en ingles (FDA lo reconoce)
  - Estado: APROBADO (REGISTRO FDA)
  - Estado BioMed: Liberado

Recarga el navegador y ve al dashboard.
""")