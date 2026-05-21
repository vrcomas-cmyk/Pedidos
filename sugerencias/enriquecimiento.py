"""
sugerencias/enriquecimiento.py - Post-proceso vectorizado que enriquece las
sugerencias con Promedio_Consumo_12M, Consumo promedio (Dest/Material) y
Meses_Inventario.
"""
import logging

import numpy as np
import pandas as pd

from config import Columnas

logger = logging.getLogger(__name__)


def _normalizar_clave(serie: pd.Series) -> pd.Series:
    return (
        serie.astype(str)
        .str.strip()
        .str.replace(r"\.0+$", "", regex=True)
        .str.upper()
    )


def enriquecer_sugerencias_con_consumo(
    df_sugerencias: pd.DataFrame,
    df_resumen: pd.DataFrame,
    df_facturacion: pd.DataFrame = None,
    df_reporte_consumo: pd.DataFrame = None,
) -> pd.DataFrame:
    """Agrega columnas Promedio_Consumo_12M, Consumo promedio (Dest/Material) y Meses_Inventario."""
    if df_sugerencias is None or df_sugerencias.empty:
        return df_sugerencias

    df = df_sugerencias.copy()

    # 1. Promedio_Consumo_12M desde Resumen
    if df_resumen is not None and not df_resumen.empty:
        cols_needed = ["Centro", "Material", "Almacen", "Promedio_Consumo_12M"]
        if all(c in df_resumen.columns for c in cols_needed):
            lookup_resumen = (
                df_resumen[cols_needed]
                .drop_duplicates(subset=["Centro", "Material", "Almacen"])
                .copy()
            )
            lookup_resumen = lookup_resumen.rename(
                columns={
                    "Centro": "_r_centro",
                    "Material": "_r_material",
                    "Almacen": "_r_almacen",
                    "Promedio_Consumo_12M": "_prom_resumen",
                }
            )
            df = df.merge(
                lookup_resumen,
                left_on=[
                    Columnas.CENTRO_PEDIDO,
                    Columnas.MATERIAL_SOLICITADO,
                    Columnas.ALMACEN,
                ],
                right_on=["_r_centro", "_r_material", "_r_almacen"],
                how="left",
            )
            df[Columnas.PROMEDIO_CONSUMO_12M] = df["_prom_resumen"].fillna(0)
            df.drop(
                columns=[
                    c
                    for c in ["_r_centro", "_r_material", "_r_almacen", "_prom_resumen"]
                    if c in df.columns
                ],
                inplace=True,
            )
    else:
        df[Columnas.PROMEDIO_CONSUMO_12M] = df.get(
            Columnas.PROMEDIO_CONSUMO_12M, pd.Series(0, index=df.index)
        ).fillna(0)

    # 2. Consumo promedio (Dest/Material)
    if df_reporte_consumo is not None and not df_reporte_consumo.empty:
        try:
            cols_lookup = ["Destinatario", "Material", "Consumo_promedio_mensual"]
            if all(c in df_reporte_consumo.columns for c in cols_lookup):
                lookup_rc = df_reporte_consumo[cols_lookup].drop_duplicates(
                    subset=["Destinatario", "Material"]
                ).copy()
                lookup_rc["_rc_key"] = (
                    _normalizar_clave(lookup_rc["Destinatario"])
                    + "||"
                    + _normalizar_clave(lookup_rc["Material"])
                )
                lookup_rc = lookup_rc[["_rc_key", "Consumo_promedio_mensual"]].rename(
                    columns={"Consumo_promedio_mensual": "_rc_consumo"}
                )
                df["_sug_key"] = (
                    _normalizar_clave(df[Columnas.DESTINATARIO])
                    + "||"
                    + _normalizar_clave(df[Columnas.MATERIAL_SOLICITADO])
                )
                df = df.merge(lookup_rc, left_on="_sug_key", right_on="_rc_key", how="left")
                df[Columnas.CONSUMO_DESTINATARIO_12M] = df["_rc_consumo"].fillna(0)
                df.drop(
                    columns=[c for c in ["_sug_key", "_rc_key", "_rc_consumo"] if c in df.columns],
                    inplace=True,
                )
            else:
                df[Columnas.CONSUMO_DESTINATARIO_12M] = 0.0
        except Exception as e:
            logger.warning(f"No se pudo calcular Consumo promedio (Dest/Material): {e}")
            df[Columnas.CONSUMO_DESTINATARIO_12M] = 0.0
    else:
        df[Columnas.CONSUMO_DESTINATARIO_12M] = 0.0

    # 3. Meses_Inventario
    almacen_col = df[Columnas.ALMACEN].astype(str).str.strip()
    inv_segun_almacen = np.select(
        [
            almacen_col == "1030",
            almacen_col == "1031",
            almacen_col == "1060",
        ],
        [
            pd.to_numeric(df[Columnas.INV_1030], errors="coerce").fillna(0),
            pd.to_numeric(df[Columnas.INV_1031], errors="coerce").fillna(0),
            pd.to_numeric(df[Columnas.INV_1060], errors="coerce").fillna(0),
        ],
        default=pd.to_numeric(df[Columnas.INV_1032], errors="coerce").fillna(0),
    )
    consumo_prom = pd.to_numeric(
        df[Columnas.PROMEDIO_CONSUMO_12M], errors="coerce"
    ).fillna(0)
    df[Columnas.MESES_INVENTARIO] = np.where(
        consumo_prom > 0,
        (inv_segun_almacen / consumo_prom).round(2),
        np.where(inv_segun_almacen == 0, 0.0, 999.0),
    )

    return df
