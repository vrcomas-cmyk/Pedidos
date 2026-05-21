"""
reportes/exportador.py - Exporta los DataFrames a un archivo Excel con todas las
hojas configuradas.
"""
import io

import pandas as pd


def exportar_a_excel(
    df_todas_sugerencias: pd.DataFrame = None,
    df_resumen_sin_sugerencias: pd.DataFrame = None,
    df_reporte_consumo: pd.DataFrame = None,
    df_sug_consumo: pd.DataFrame = None,
    df_inventario_por_condicion: pd.DataFrame = None,
    df_detalle_lotes_cc: pd.DataFrame = None,
) -> bytes:
    """Exporta los reportes en un solo archivo Excel con varias hojas."""
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if df_todas_sugerencias is not None and not df_todas_sugerencias.empty:
            df_todas_sugerencias.to_excel(
                writer, sheet_name="Todas las Sugerencias", index=False
            )

        if (
            df_resumen_sin_sugerencias is not None
            and not df_resumen_sin_sugerencias.empty
        ):
            df_resumen_sin_sugerencias.to_excel(
                writer, sheet_name="Resumen Sin Sugerencias", index=False
            )

        if df_reporte_consumo is not None and not df_reporte_consumo.empty:
            df_reporte_consumo.to_excel(
                writer, sheet_name="Reporte de Consumo", index=False
            )

        if df_sug_consumo is not None and not df_sug_consumo.empty:
            df_sug_consumo.to_excel(
                writer, sheet_name="Sug Reporte Consumo", index=False
            )

        if (
            df_inventario_por_condicion is not None
            and not df_inventario_por_condicion.empty
        ):
            df_inventario_por_condicion.to_excel(
                writer, sheet_name="Inventario por condicion", index=False
            )

        if df_detalle_lotes_cc is not None and not df_detalle_lotes_cc.empty:
            df_detalle_lotes_cc.to_excel(
                writer,
                sheet_name="Detalle Lotes Corta Caducidad",
                index=False,
            )

    return output.getvalue()
