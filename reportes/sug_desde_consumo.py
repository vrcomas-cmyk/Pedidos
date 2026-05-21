"""
reportes/sug_desde_consumo.py - Genera 'Sugerencias desde Reporte de Consumo'.

Cambios: incluye Columnas.MESES_VIGENCIA_LOTE en el orden de columnas finales,
justo después de Fecha de Caducidad.
"""
from typing import Callable, Dict, List, Optional

import pandas as pd

from sugerencias.consolidacion import consolidar_sugerencias_repetidas
from sugerencias.enriquecimiento import enriquecer_sugerencias_con_consumo
from sugerencias.motor_optimizado import (
    build_fuentes_index,
    build_inv_caches,
    buscar_templates_sugerencia,
    montar_linea_rc,
)

ProgressCallback = Optional[Callable[[float, str], None]]


def _noop(f: float, t: str) -> None:  # pragma: no cover
    pass


def generar_sugerencias_desde_reporte_consumo(
    df_reporte_consumo: pd.DataFrame,
    hojas_externas: Dict[str, pd.DataFrame],
    fuentes_activas: List[str],
    inventario_df: pd.DataFrame,
    df_resumen: pd.DataFrame = None,
    reportar_progreso: ProgressCallback = None,
) -> pd.DataFrame:
    """Genera sugerencias tomando como base el Reporte de Consumo."""
    if df_reporte_consumo is None or df_reporte_consumo.empty:
        return pd.DataFrame()

    cb = reportar_progreso or _noop

    cb(0.05, "Pre-indexando inventario (RC)…")
    inv_caches = build_inv_caches(inventario_df)
    cb(0.15, "Pre-indexando fuentes externas (RC)…")
    idx_fuentes = build_fuentes_index(hojas_externas, fuentes_activas)

    pares_unicos = (
        df_reporte_consumo[["Material", "Centro"]]
        .drop_duplicates()
        .dropna(subset=["Material"])
    )
    pares_unicos = pares_unicos[
        pares_unicos["Material"].astype(str).str.strip() != ""
    ]
    total_pares = max(len(pares_unicos), 1)

    templates_cache: Dict[tuple, List[dict]] = {}
    for i, (_, pair) in enumerate(pares_unicos.iterrows()):
        material = str(pair.get("Material", "") or "").strip()
        centro = str(pair.get("Centro", "") or "").strip()
        if not material:
            continue
        templates_cache[(material, centro)] = buscar_templates_sugerencia(
            material, fuentes_activas, idx_fuentes, inv_caches
        )
        if i % max(1, total_pares // 50) == 0:
            cb(0.20 + 0.40 * (i / total_pares), f"Sugerencias RC ({i}/{total_pares})…")

    cb(0.62, "Armando líneas RC…")

    total_rows = len(df_reporte_consumo)
    todas_lineas: List[dict] = []
    for i, (_, row) in enumerate(df_reporte_consumo.iterrows()):
        material = str(row.get("Material", "") or "").strip()
        centro = str(row.get("Centro", "") or "").strip()
        if not material:
            continue

        pedido_fields = {
            "gpo_cte": str(row.get("Grp. Cliente", "") or "").strip(),
            "fecha": str(row.get("Ultima_compra_cliente", "") or "").strip(),
            "gpo_vdor": str(row.get("Gpo. Vdor.", "") or "").strip(),
            "solicitante": str(row.get("Solicitante", "") or "").strip(),
            "destinatario": str(row.get("Destinatario", "") or "").strip(),
            "razon_social": str(row.get("Razón Social", "") or "").strip(),
            "centro": centro,
            "material": material,
            "texto_material": str(row.get("Texto Material", "") or "").strip(),
            "cantidad": float(row.get("Cantidad ultima", 0) or 0),
            "pendiente": float(row.get("Consumo_promedio_mensual", 0) or 0),
            "precio": float(row.get("Precio_unitario_ultima", 0) or 0),
        }

        todas_lineas.append(montar_linea_rc(pedido_fields, None, inv_caches, row.to_dict()))
        for tmpl in templates_cache.get((material, centro), []):
            todas_lineas.append(montar_linea_rc(pedido_fields, tmpl, inv_caches, row.to_dict()))

        if i % max(1, total_rows // 50) == 0:
            cb(0.62 + 0.25 * (i / total_rows), f"RC filas: {i}/{total_rows}")

    cb(0.90, "Consolidando y enriqueciendo RC…")

    if not todas_lineas:
        return pd.DataFrame()

    df_resultado = pd.DataFrame(todas_lineas)
    df_resultado = consolidar_sugerencias_repetidas(df_resultado)
    df_resultado = enriquecer_sugerencias_con_consumo(
        df_resultado,
        df_resumen if df_resumen is not None else pd.DataFrame(),
        df_reporte_consumo=df_reporte_consumo,
    )

    # Orden de columnas final para Sug Reporte Consumo
    COLUMNAS_FINALES_RC = [
        # Grupo 1: Reporte de Consumo
        "Centro", "Grp. Cliente", "Gpo. Vdor.", "Solicitante",
        "Destinatario", "Razón Social", "Material", "Texto Material",
        "Ultima_compra_cliente", "Ultima_facturacion_destinatario",
        "Consumo_promedio_mensual", "Consumo_actual", "UM",
        "Tendencia", "Tendencia de cantidad", "Ultimo mes facturacion",
        "Cantidad ultima", "Importe ultima", "Precio_unitario_ultima",
        "Penultima_fecha", "Cantidad_penultima", "Importe_penultima",
        "Precio_unitario_penultima", "precio_min", "precio_max", "precio_prom",
        # Grupo 2: Sugerencias
        "Fuente", "Material sugerido", "Descripción sugerida",
        "Centro sugerido", "Almacén sugerido", "Disponible", "Lote",
        "Fecha de Caducidad",
        "Meses vigencia lote",  # NUEVA
        "Centro (Inv)", "Inv 1030", "Inv 1031", "Inv 1032", "Inv 1060",
        "Meses_Inventario", "Promedio_Consumo_12M", "Cant. en Tránsito",
        "Cant. en Tránsito 1030", "Cant. en Tránsito 1031", "Cant. en Tránsito 1032",
        "Disponible 1031-1030", "Disponible 1031-1032",
        "Inv 1001", "Inv 1003", "Inv 1004", "Inv 1017", "Inv 1018",
        "Inv 1022", "Inv 1036",
    ]

    for col in COLUMNAS_FINALES_RC:
        if col not in df_resultado.columns:
            df_resultado[col] = ""

    cb(1.0, "Sug Reporte Consumo lista")
    return df_resultado[COLUMNAS_FINALES_RC]
