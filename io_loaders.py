"""
io_loaders.py - Carga de archivos Excel. No depende de Streamlit; devuelve
DataFrames procesados listos para usar.
"""
import logging
from typing import Dict, Tuple

import pandas as pd

from config import FUENTES_DISPONIBLES, HOJAS_ADICIONALES
from procesadores.externas import procesar_hoja_externa
from procesadores.facturacion import procesar_datos_facturacion
from procesadores.inventario import procesar_hoja_inventario_ajustada
from procesadores.utilidades import encontrar_columna_por_patron, normalizar_ids

logger = logging.getLogger(__name__)


def cargar_pedidos(archivo) -> Tuple[pd.DataFrame, str]:
    """Carga el archivo de pedidos."""
    xls = pd.ExcelFile(archivo)
    sheet_map = {s.strip().casefold(): s for s in xls.sheet_names}
    hoja = None
    for candidato in ["seg pedidos", "sheets1"]:
        if candidato in sheet_map:
            hoja = sheet_map[candidato]
            break
    if hoja is None:
        cols_min = {"Pedido", "Material", "Centro"}
        for sh in xls.sheet_names:
            try:
                cols = set(pd.read_excel(xls, sh, nrows=0).columns)
                if cols_min.issubset(cols):
                    hoja = sh
                    break
            except Exception:
                pass
    if hoja is None:
        raise ValueError(
            f"No se encontró hoja de pedidos. Hojas: {xls.sheet_names}"
        )

    df = pd.read_excel(xls, hoja)
    df.columns = [
        col.replace("Almacen", "Almacén").replace("Almaçen", "Almacén")
        for col in df.columns
    ]
    col_gpo = encontrar_columna_por_patron(
        df, ["gpo.vdor", "gpo. vdor", "gpo vdor", "grupo vendedor", "vdor"]
    )
    if "Gpo.Vdor." not in df.columns:
        df["Gpo.Vdor."] = df[col_gpo] if col_gpo else ""
    df["Gpo.Vdor."] = (
        df["Gpo.Vdor."]
        .astype(str)
        .str.strip()
        .replace({"nan": "", "None": ""})
    )
    for col in ["Centro", "Material", "Almacén"]:
        if col in df.columns:
            df[col] = normalizar_ids(df[col])
    return df, hoja


def cargar_inventario(archivo) -> Tuple[pd.DataFrame, str]:
    """Carga el archivo de inventario."""
    xls = pd.ExcelFile(archivo)
    hoja = None
    for h in xls.sheet_names:
        if "inventario" in h.lower() or "sheets1" in h.lower():
            hoja = h
            break
    if hoja is None:
        hoja = xls.sheet_names[0]
    df_raw = pd.read_excel(xls, hoja)
    df = procesar_hoja_inventario_ajustada(df_raw)
    return df, hoja


def cargar_hojas_externas(archivo) -> Dict[str, pd.DataFrame]:
    """Carga el archivo de hojas externas (Corta caducidad, Lento mov, etc.).

    Procesa hojas en FUENTES_DISPONIBLES (fuentes del motor) y en
    HOJAS_ADICIONALES (hojas para reportes específicos, ej. Revision2).
    """
    xls = pd.ExcelFile(archivo)
    hojas: Dict[str, pd.DataFrame] = {}
    hojas_validas = set(FUENTES_DISPONIBLES) | set(HOJAS_ADICIONALES)
    for hoja in xls.sheet_names:
        if "inventario" in hoja.lower():
            continue
        if hoja not in hojas_validas:
            continue
        df_hoja = pd.read_excel(xls, hoja)
        hojas[hoja] = procesar_hoja_externa(df_hoja, hoja)
    return hojas


def cargar_facturacion(archivo) -> Tuple[pd.DataFrame, str]:
    """Carga el archivo de facturación."""
    xls = pd.ExcelFile(archivo)
    hoja = None
    for h in xls.sheet_names:
        if "facturacion" in h.lower() or "sheets1" in h.lower():
            hoja = h
            break
    if hoja is None:
        hoja = xls.sheet_names[0]
    df_raw = pd.read_excel(xls, hoja)
    df = procesar_datos_facturacion(df_raw)
    return df, hoja
