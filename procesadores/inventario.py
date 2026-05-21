"""
procesadores/inventario.py - Procesa la hoja de Inventario aplicando el ajuste:
Libre Utilización = Libre Utilización - Entrega a cliente.
"""
import logging

import pandas as pd

from procesadores.utilidades import encontrar_columna_por_patron, normalizar_ids

logger = logging.getLogger(__name__)


def procesar_hoja_inventario_ajustada(df_inventario: pd.DataFrame) -> pd.DataFrame:
    """Procesa la hoja de inventario y realiza el cálculo:
    'Libre Utilización' - 'Entrega a cliente'.

    Nota: esta versión NO muestra mensajes de Streamlit directamente; eso se delega
    a la capa de UI. Solo registra por logger.
    """
    if df_inventario.empty:
        return pd.DataFrame()

    # Normalizar nombres de columnas
    df_inventario.columns = [
        col.replace("Almacen", "Almacén").replace("Almaçen", "Almacén")
        for col in df_inventario.columns
    ]

    columnas_requeridas = [
        "Centro",
        "Material",
        "Almacén",
        "Libre Utilización",
        "Cant. en Tránsito",
        "Entrega a cliente",
        "Descripción",
    ]

    mapeo_columnas = {}

    for col_req in columnas_requeridas:
        if col_req not in df_inventario.columns:
            patrones = {
                "Centro": ["centro", "center"],
                "Material": ["material", "mat", "artículo"],
                "Almacén": ["almacén", "almacen"],
                "Libre Utilización": [
                    "libre utilización",
                    "libre utilizacion",
                    "disponible",
                    "stock",
                ],
                "Cant. en Tránsito": [
                    "tránsito",
                    "transito",
                    "en tránsito",
                    "en transito",
                    "cant. en tránsito",
                ],
                "Entrega a cliente": [
                    "entrega a cliente",
                    "entrega cliente",
                    "entregado",
                    "cantidad entregada",
                    "entregas",
                ],
                "Descripción": [
                    "descripción",
                    "descripcion",
                    "texto breve",
                    "texto material",
                    "nombre",
                    "texto",
                    "descr",
                    "artículo",
                ],
            }
            col_encontrada = encontrar_columna_por_patron(
                df_inventario, patrones.get(col_req, [col_req])
            )
            if col_encontrada:
                mapeo_columnas[col_req] = col_encontrada
            else:
                if col_req in [
                    "Libre Utilización",
                    "Cant. en Tránsito",
                    "Entrega a cliente",
                ]:
                    df_inventario[col_req] = 0
                else:
                    df_inventario[col_req] = ""

    for col_dest, col_orig in mapeo_columnas.items():
        if col_orig in df_inventario.columns and col_dest not in df_inventario.columns:
            df_inventario[col_dest] = df_inventario[col_orig]

    for col in ["Centro", "Material", "Almacén"]:
        if col in df_inventario.columns:
            df_inventario[col] = normalizar_ids(df_inventario[col])

    columnas_numericas = ["Libre Utilización", "Cant. en Tránsito", "Entrega a cliente"]
    for col in columnas_numericas:
        if col in df_inventario.columns:
            df_inventario[col] = pd.to_numeric(
                df_inventario[col], errors="coerce"
            ).fillna(0)

    # CÁLCULO: "Libre Utilización" - "Entrega a cliente"
    if (
        "Libre Utilización" in df_inventario.columns
        and "Entrega a cliente" in df_inventario.columns
    ):
        df_inventario["Libre Utilización"] = (
            df_inventario["Libre Utilización"] - df_inventario["Entrega a cliente"]
        )
        df_inventario["Libre Utilización"] = df_inventario["Libre Utilización"].clip(
            lower=0
        )

        total_ajuste = df_inventario["Entrega a cliente"].sum()
        logger.info(
            f"Ajuste de inventario aplicado: {total_ajuste:,.0f} unidades restadas"
        )

    columnas_finales = [
        "Centro",
        "Material",
        "Almacén",
        "Descripción",
        "Libre Utilización",
        "Cant. en Tránsito",
    ]
    columnas_finales = [col for col in columnas_finales if col in df_inventario.columns]

    return df_inventario[columnas_finales]
