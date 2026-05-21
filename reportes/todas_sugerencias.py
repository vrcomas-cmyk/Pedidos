"""
reportes/todas_sugerencias.py - Genera el reporte 'Todas las Sugerencias'.

Cambios:
  - Usa motor_optimizado compartido.
  - Incluye nueva columna MESES_VIGENCIA_LOTE en el orden final, justo después
    de FECHA_CADUCIDAD.
"""
from typing import Callable, Dict, List, Optional

import pandas as pd

from config import Columnas
from sugerencias.consolidacion import consolidar_sugerencias_repetidas
from sugerencias.motor_optimizado import (
    build_fuentes_index,
    build_inv_caches,
    buscar_templates_sugerencia,
    montar_linea_pedido,
)

ProgressCallback = Optional[Callable[[float, str], None]]


def _noop(f: float, t: str) -> None:  # pragma: no cover
    pass


def generar_todas_sugerencias(
    pedidos_df: pd.DataFrame,
    hojas_externas: Dict[str, pd.DataFrame],
    fuentes_activas: List[str],
    inventario_df: pd.DataFrame,
    reportar_progreso: ProgressCallback = None,
) -> pd.DataFrame:
    """Genera todas las sugerencias para todos los pedidos."""
    if pedidos_df is None or pedidos_df.empty:
        return pd.DataFrame()

    cb = reportar_progreso or _noop

    # FASE A
    cb(0.05, "Pre-indexando inventario…")
    inv_caches = build_inv_caches(inventario_df)
    cb(0.15, "Pre-indexando fuentes externas…")
    idx_fuentes = build_fuentes_index(hojas_externas, fuentes_activas)
    cb(0.22, "Pre-indexación lista")

    # FASE B
    pares_unicos = (
        pedidos_df[["Material", "Centro"]]
        .drop_duplicates()
        .dropna(subset=["Material"])
    )
    pares_unicos = pares_unicos[
        pares_unicos["Material"].astype(str).str.strip() != ""
    ]
    total_pares = max(len(pares_unicos), 1)
    templates_cache: Dict[tuple, List[dict]] = {}

    for i, (_, pair) in enumerate(pares_unicos.iterrows()):
        mat = str(pair.get("Material", "") or "").strip()
        cen = str(pair.get("Centro", "") or "").strip()
        if not mat:
            continue
        templates_cache[(mat, cen)] = buscar_templates_sugerencia(
            mat, fuentes_activas, idx_fuentes, inv_caches
        )
        if i % max(1, total_pares // 50) == 0:
            cb(0.22 + 0.40 * (i / total_pares), f"Calculando sugerencias ({i}/{total_pares})…")

    cb(0.62, "Ensamblando líneas…")

    # FASE C
    total_pedidos = len(pedidos_df)
    todas_sugerencias: List[dict] = []
    for i, (_, pedido) in enumerate(pedidos_df.iterrows()):
        mat = str(pedido.get("Material", "") or "").strip()
        cen = str(pedido.get("Centro", "") or "").strip()
        if not mat:
            continue
        # Línea sin sugerencia
        todas_sugerencias.append(montar_linea_pedido(pedido, None, inv_caches))
        # Líneas con sugerencia
        for tmpl in templates_cache.get((mat, cen), []):
            todas_sugerencias.append(montar_linea_pedido(pedido, tmpl, inv_caches))

        if i % max(1, total_pedidos // 50) == 0:
            cb(0.62 + 0.30 * (i / total_pedidos), f"Pedidos procesados: {i}/{total_pedidos}")

    cb(0.95, "Consolidando sugerencias repetidas…")
    if not todas_sugerencias:
        return pd.DataFrame()

    df_resultado = pd.DataFrame(todas_sugerencias)
    df_resultado = consolidar_sugerencias_repetidas(df_resultado)

    # Formatear Fecha como dd/mm/aaaa (string) — sin componente de hora
    if Columnas.FECHA in df_resultado.columns:
        fecha_dt = pd.to_datetime(df_resultado[Columnas.FECHA], errors="coerce")
        df_resultado[Columnas.FECHA] = fecha_dt.dt.strftime("%d/%m/%Y").fillna("")

    # Orden de columnas — ahora incluye MESES_VIGENCIA_LOTE tras FECHA_CADUCIDAD
    columnas_orden = [
        Columnas.GRUPO_CLIENTE, Columnas.FECHA,
        Columnas.PEDIDO, Columnas.GRUPO_VENDEDOR,
        Columnas.SOLICITANTE, Columnas.DESTINATARIO,
        Columnas.RAZON_SOCIAL, Columnas.CENTRO_PEDIDO,
        Columnas.ALMACEN, Columnas.MATERIAL_SOLICITADO,
        Columnas.MATERIAL_BASE, Columnas.DESCRIPCION_SOLICITADA,
        Columnas.CANTIDAD_PEDIDO, Columnas.CANTIDAD_PENDIENTE,
        Columnas.CANTIDAD_OFERTAR, Columnas.PRECIO,
        Columnas.CONSUMO_DESTINATARIO_12M,
        Columnas.FUENTE, Columnas.MATERIAL_SUGERIDO,
        Columnas.DESCRIPCION_SUGERIDA, Columnas.CENTRO_SUGERIDO,
        Columnas.ALMACEN_SUGERIDO, Columnas.DISPONIBLE,
        Columnas.LOTE, Columnas.FECHA_CADUCIDAD,
        Columnas.MESES_VIGENCIA_LOTE,  # NUEVA
        Columnas.CENTRO_INV, Columnas.INV_1030,
        Columnas.INV_1031, Columnas.INV_1032,
        Columnas.INV_1060, Columnas.MESES_INVENTARIO,
        Columnas.PROMEDIO_CONSUMO_12M, Columnas.CANT_TRANSITO,
        Columnas.CANT_TRANSITO_1030, Columnas.CANT_TRANSITO_1031,
        Columnas.CANT_TRANSITO_1032, Columnas.DISP_1031_1030,
        Columnas.DISP_1031_1032, Columnas.INV_1001,
        Columnas.INV_1003, Columnas.INV_1004,
        Columnas.INV_1017, Columnas.INV_1018,
        Columnas.INV_1022, Columnas.INV_1036,
        Columnas.BLOQUEADO,
    ]

    for col in columnas_orden:
        if col not in df_resultado.columns:
            df_resultado[col] = ""

    cb(1.0, "Todas las sugerencias listas")
    return df_resultado[columnas_orden]
