"""
test_cambios.py - Tests funcionales con datos sintéticos para validar:
  1. Hoja Revision se procesa con múltiples Status por material.
  2. Consolidación de Revision en 'Revision (Status1, Status2)'.
  3. Filtro Corta caducidad: <1 año o almacén 1032.
  4. Columna Meses vigencia lote se calcula correctamente.
  5. Columna Status Revisión en Resumen Sin Sugerencias.
"""
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, '.')


# ─────────────────────────────────────────────────────────────────────────
# TEST 1: Hoja Revision procesada correctamente
# ─────────────────────────────────────────────────────────────────────────
def test_procesar_hoja_revision():
    print("\n=== TEST 1: procesar_hoja_externa con Revision ===")
    from procesadores.externas import procesar_hoja_externa

    df_revision = pd.DataFrame({
        "Material": ["1001", "1002", "1001", "1003", ""],
        "Texto breve de material": ["Clavo 3/4", "Tornillo M8", "Clavo 3/4", "Arandela", ""],
        "Status": ["Urgente", "Pendiente", "En revision", "Urgente", "X"],
    })

    df_proc = procesar_hoja_externa(df_revision, "Revision")
    print(f"Filas procesadas: {len(df_proc)}")
    print(f"Columnas: {df_proc.columns.tolist()}")
    print(df_proc[["Material", "Status"]].to_string(index=False))

    assert "Material" in df_proc.columns, "falta Material"
    assert "Status" in df_proc.columns, "falta Status"
    assert len(df_proc) == 4, f"Se esperaban 4 filas (la última con Material vacío filtrada), obtuvo {len(df_proc)}"
    # Material 1001 debe tener 2 filas con Status distinto
    rows_1001 = df_proc[df_proc["Material"] == "1001"]
    assert len(rows_1001) == 2, f"Material 1001 debe tener 2 Status, tiene {len(rows_1001)}"
    print("✅ TEST 1 OK")


# ─────────────────────────────────────────────────────────────────────────
# TEST 2: Consolidación de Revision con múltiples Status
# ─────────────────────────────────────────────────────────────────────────
def test_consolidacion_revision():
    print("\n=== TEST 2: unir_fuentes_repetidas con Revision ===")
    from sugerencias.consolidacion import unir_fuentes_repetidas

    # Caso 1: dos Revision con Status distintos
    s1 = pd.Series(["Revision (Urgente)", "Revision (Pendiente)"])
    r1 = unir_fuentes_repetidas(s1)
    print(f"  [Urgente + Pendiente] → '{r1}'")
    assert r1 == "Revision (Urgente, Pendiente)", f"Esperado 'Revision (Urgente, Pendiente)', obtuvo '{r1}'"

    # Caso 2: Revision + otra fuente
    s2 = pd.Series(["Revision (Urgente)/Cosmopark", "Revision (Pendiente)/Cosmopark"])
    r2 = unir_fuentes_repetidas(s2)
    print(f"  [Rev(Urg)/Cosmo + Rev(Pen)/Cosmo] → '{r2}'")
    assert "Cosmopark" in r2 and "Urgente" in r2 and "Pendiente" in r2

    # Caso 3: Dedupe de fuentes normales
    s3 = pd.Series(["Sustituto/Cosmopark", "Sustituto/Cosmopark"])
    r3 = unir_fuentes_repetidas(s3)
    print(f"  [Sust/Cosmo + Sust/Cosmo] → '{r3}'")
    assert r3 == "Sustituto/Cosmopark", f"Esperado 'Sustituto/Cosmopark', obtuvo '{r3}'"

    # Caso 4: mezcla
    s4 = pd.Series(["Lento mov/Cosmopark", "Revision (Urgente)/Cosmopark", "Revision (En proceso)"])
    r4 = unir_fuentes_repetidas(s4)
    print(f"  [LM/Cosmo + Rev(U)/Cosmo + Rev(EP)] → '{r4}'")
    assert "Lento mov" in r4
    assert "Cosmopark" in r4
    assert "Urgente" in r4 and "En proceso" in r4

    print("✅ TEST 2 OK")


# ─────────────────────────────────────────────────────────────────────────
# TEST 3: Filtro Corta caducidad (< 1 año o almacén 1032)
# ─────────────────────────────────────────────────────────────────────────
def test_filtro_corta_caducidad():
    print("\n=== TEST 3: filtro Corta caducidad ===")
    from procesadores.externas import procesar_hoja_externa

    hoy = pd.Timestamp.today()
    en_6_meses = (hoy + timedelta(days=180)).strftime("%d/%m/%Y")
    en_2_anos = (hoy + timedelta(days=730)).strftime("%d/%m/%Y")

    df_cc = pd.DataFrame({
        "Material": ["M1", "M2", "M3", "M4"],
        "Centro": ["1001", "1001", "1001", "1001"],
        "Almacén": ["1030", "1031", "1030", "1032"],
        "CantidadDisp": [100, 200, 300, 400],
        "Lote": ["L1", "L2", "L3", "L4"],
        "FeCaduc/FePreferCons": [en_6_meses, en_2_anos, en_2_anos, en_2_anos],
    })

    df_proc = procesar_hoja_externa(df_cc, "Corta caducidad")
    print(f"Original: {len(df_cc)} filas → Filtrado: {len(df_proc)} filas")
    print(df_proc[["Material", "Almacén", "Lote", "FechaCaducidad"]].to_string(index=False))

    # M1 pasa porque caduca en <1 año (aunque alm != 1032)
    # M2 NO pasa (caduca en 2 años y alm != 1032)
    # M3 NO pasa (caduca en 2 años y alm != 1032)
    # M4 pasa porque alm == 1032
    materiales_ok = set(df_proc["Material"].tolist())
    assert "M1" in materiales_ok, "M1 (caduca <1 año) debe estar"
    assert "M2" not in materiales_ok, "M2 (caduca en 2 años, alm 1031) NO debe estar"
    assert "M3" not in materiales_ok, "M3 (caduca en 2 años, alm 1030) NO debe estar"
    assert "M4" in materiales_ok, "M4 (alm 1032) debe estar"

    print("✅ TEST 3 OK")


# ─────────────────────────────────────────────────────────────────────────
# TEST 4: calcular_meses_vigencia
# ─────────────────────────────────────────────────────────────────────────
def test_meses_vigencia():
    print("\n=== TEST 4: calcular_meses_vigencia ===")
    from procesadores.utilidades import calcular_meses_vigencia

    # En 6 meses
    hoy = pd.Timestamp.today()
    en_6 = (hoy + timedelta(days=180)).strftime("%d/%m/%Y")
    r1 = calcular_meses_vigencia(en_6)
    print(f"  ~6 meses adelante → '{r1}'")
    assert abs(float(r1) - 5.9) < 0.5, f"Esperado ~6.0, obtuvo {r1}"

    # Vacío
    r2 = calcular_meses_vigencia("")
    print(f"  vacío → '{r2}'")
    assert r2 == ""

    # None
    r3 = calcular_meses_vigencia(None)
    print(f"  None → '{r3}'")
    assert r3 == ""

    # Ya vencido
    hace_30 = (hoy - timedelta(days=30)).strftime("%d/%m/%Y")
    r4 = calcular_meses_vigencia(hace_30)
    print(f"  hace 30 días → '{r4}'")
    assert r4 == "0"

    print("✅ TEST 4 OK")


# ─────────────────────────────────────────────────────────────────────────
# TEST 5: Motor optimizado con Revision
# ─────────────────────────────────────────────────────────────────────────
def test_motor_revision():
    print("\n=== TEST 5: Motor con Revision genera templates con Status ===")
    from sugerencias.motor_optimizado import (
        build_fuentes_index, build_inv_caches, buscar_templates_sugerencia,
    )
    from procesadores.externas import procesar_hoja_externa

    inventario_df = pd.DataFrame({
        "Centro": ["1030", "1030", "1031"],
        "Material": ["M1", "M1", "M1"],
        "Almacén": ["1030", "1031", "1030"],
        "Libre Utilización": [50.0, 30.0, 100.0],
        "Cant. en Tránsito": [0.0, 0.0, 0.0],
        "Descripción": ["Clavo", "Clavo", "Clavo"],
    })

    df_revision_raw = pd.DataFrame({
        "Material": ["M1", "M1"],
        "Texto breve de material": ["Clavo", "Clavo"],
        "Status": ["Urgente", "En revisión"],
    })
    df_revision = procesar_hoja_externa(df_revision_raw, "Revision")

    hojas = {"Revision": df_revision}
    inv_caches = build_inv_caches(inventario_df)
    idx = build_fuentes_index(hojas, ["Revision"])

    templates = buscar_templates_sugerencia("M1", ["Revision"], idx, inv_caches)
    print(f"Templates generados: {len(templates)}")
    for t in templates:
        print(f"  - fuente='{t['fuente']}', disp={t['disponible']}")

    # Debe haber 2 templates (uno por cada Status), ambos con fuente tipo "Revision (...)"
    assert len(templates) == 2
    fuentes = [t["fuente"] for t in templates]
    assert "Revision (Urgente)" in fuentes
    assert "Revision (En revisión)" in fuentes

    print("✅ TEST 5 OK")


# ─────────────────────────────────────────────────────────────────────────
# TEST 6: Columna MESES_VIGENCIA_LOTE en línea de sugerencia
# ─────────────────────────────────────────────────────────────────────────
def test_linea_con_vigencia():
    print("\n=== TEST 6: Columna MESES_VIGENCIA_LOTE presente ===")
    from config import Columnas
    from sugerencias.motor_optimizado import (
        build_fuentes_index, build_inv_caches, buscar_templates_sugerencia,
        montar_linea_pedido,
    )
    from procesadores.externas import procesar_hoja_externa

    hoy = pd.Timestamp.today()
    en_6m = (hoy + timedelta(days=180)).strftime("%d/%m/%Y")

    inventario_df = pd.DataFrame({
        "Centro": ["1030"],
        "Material": ["M1"],
        "Almacén": ["1030"],
        "Libre Utilización": [100.0],
        "Cant. en Tránsito": [0.0],
        "Descripción": ["Clavo"],
    })

    df_cosmo_raw = pd.DataFrame({
        "Material": ["M1"],
        "Centro": ["1030"],
        "Almacén": ["1030"],
        "CantidadDisp": [50],
        "Lote": ["LOTEA"],
        "Descripción": ["Clavo"],
        "FechaCaducidad": [en_6m],
    })
    df_cosmo = procesar_hoja_externa(df_cosmo_raw, "Cosmopark")

    hojas = {"Cosmopark": df_cosmo}
    inv_caches = build_inv_caches(inventario_df)
    idx = build_fuentes_index(hojas, ["Cosmopark"])
    templates = buscar_templates_sugerencia("M1", ["Cosmopark"], idx, inv_caches)

    assert len(templates) == 1
    print(f"  Meses vigencia en template: '{templates[0]['meses_vigencia_lote']}'")

    pedido = pd.Series({
        "Pedido": "P001",
        "Material": "M1",
        "Centro": "1030",
        "Almacén": "1030",
        "Pendiente": 30,
        "Cantidad": 30,
    })
    linea = montar_linea_pedido(pedido, templates[0], inv_caches)
    print(f"  Columna '{Columnas.MESES_VIGENCIA_LOTE}' = '{linea[Columnas.MESES_VIGENCIA_LOTE]}'")

    assert Columnas.MESES_VIGENCIA_LOTE in linea
    assert linea[Columnas.MESES_VIGENCIA_LOTE] != ""

    # También línea sin sugerencia: vigencia vacía
    linea_sin = montar_linea_pedido(pedido, None, inv_caches)
    print(f"  Línea sin sugerencia, vigencia = '{linea_sin[Columnas.MESES_VIGENCIA_LOTE]}'")
    assert linea_sin[Columnas.MESES_VIGENCIA_LOTE] == ""

    print("✅ TEST 6 OK")


# ─────────────────────────────────────────────────────────────────────────
# TEST 7: Resumen Sin Sugerencias con Status Revisión
# ─────────────────────────────────────────────────────────────────────────
def test_resumen_status_revision():
    print("\n=== TEST 7: Resumen con columna Status Revisión ===")
    from config import Columnas
    from reportes.sin_sugerencias import generar_resumen_sin_sugerencias_optimizado
    from procesadores.externas import procesar_hoja_externa

    inventario_df = pd.DataFrame({
        "Centro": ["1030", "1030"],
        "Material": ["M1", "M2"],
        "Almacén": ["1030", "1030"],
        "Libre Utilización": [100.0, 50.0],
        "Cant. en Tránsito": [0.0, 0.0],
        "Descripción": ["Clavo", "Tornillo"],
    })

    df_revision_raw = pd.DataFrame({
        "Material": ["M1", "M1", "M2"],
        "Texto breve de material": ["Clavo", "Clavo", "Tornillo"],
        "Status": ["Urgente", "Pendiente", "En revisión"],
    })
    df_revision = procesar_hoja_externa(df_revision_raw, "Revision")

    # df_sugerencias vacío: el resumen saldrá solo del inventario
    df_sug = pd.DataFrame()
    df_todas = pd.DataFrame()

    resultado = generar_resumen_sin_sugerencias_optimizado(
        df_sug, inventario_df, df_todas, df_revision=df_revision
    )

    print(f"Resumen: {len(resultado)} filas, columnas: {resultado.columns.tolist()[:10]}...")
    assert Columnas.STATUS_REVISION in resultado.columns, "Falta columna Status Revisión"

    # M1 debe tener "Urgente, Pendiente"
    m1_row = resultado[resultado["Material"] == "M1"]
    print(f"  M1 Status Revisión: '{m1_row[Columnas.STATUS_REVISION].iloc[0]}'")
    assert "Urgente" in m1_row[Columnas.STATUS_REVISION].iloc[0]
    assert "Pendiente" in m1_row[Columnas.STATUS_REVISION].iloc[0]

    # M2 debe tener "En revisión"
    m2_row = resultado[resultado["Material"] == "M2"]
    print(f"  M2 Status Revisión: '{m2_row[Columnas.STATUS_REVISION].iloc[0]}'")
    assert "En revisión" in m2_row[Columnas.STATUS_REVISION].iloc[0]

    print("✅ TEST 7 OK")


# ─────────────────────────────────────────────────────────────────────────
# Ejecutar todos
# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        test_procesar_hoja_revision,
        test_consolidacion_revision,
        test_filtro_corta_caducidad,
        test_meses_vigencia,
        test_motor_revision,
        test_linea_con_vigencia,
        test_resumen_status_revision,
    ]

    fallos = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            fallos += 1
            print(f"\n❌ FALLO en {t.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    if fallos == 0:
        print(f"✅ TODOS LOS {len(tests)} TESTS PASARON")
    else:
        print(f"❌ {fallos}/{len(tests)} tests fallaron")
        sys.exit(1)
