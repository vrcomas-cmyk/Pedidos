"""
procesadores/externas.py - Procesa hojas externas:
  Corta caducidad, Lento mov, Cosmopark, Sustituto, PNC, Caduco, Revision (NUEVA).

Cambios clave respecto al original:
  1. NUEVA pestaña "Revision" con columnas Material / Texto breve de material / Status.
     Funciona como Lento mov pero conserva el valor de 'Status' para usarlo como
     sufijo en la columna Fuente del reporte final.
  2. Filtro en "Corta caducidad": solo materiales con FeCaduc/FePreferCons a menos
     de 1 año O en almacén == "1032".
"""
import logging
from datetime import timedelta

import pandas as pd

from config import ALMACEN_PERMITIDO_CORTA_CADUCIDAD, DIAS_MAX_CORTA_CADUCIDAD
from procesadores.utilidades import encontrar_columna_por_patron, normalizar_ids

logger = logging.getLogger(__name__)


def procesar_hoja_externa(df_externo: pd.DataFrame, nombre_hoja: str) -> pd.DataFrame:
    """Procesa una hoja externa. Delega al procesador específico por tipo de hoja."""
    if df_externo.empty:
        return pd.DataFrame()

    # Normalizar nombres de columnas
    df_externo.columns = [
        col.replace("Almacen", "Almacén").replace("Almaçen", "Almacén")
        for col in df_externo.columns
    ]
    df_externo.attrs["nombre_hoja"] = nombre_hoja

    columnas_a_buscar = _patrones_por_hoja(nombre_hoja)
    if not columnas_a_buscar:
        return df_externo

    # Búsqueda y mapeo
    mapeo = {}
    for col_std, patrones in columnas_a_buscar.items():
        col_encontrada = encontrar_columna_por_patron(df_externo, patrones)
        if col_encontrada:
            mapeo[col_std] = col_encontrada
        elif col_std == "Material":
            # Buscar Material en columnas numéricas tipo ID
            for col in df_externo.columns:
                if (
                    df_externo[col].dtype in ["int64", "float64"]
                    and df_externo[col].astype(str).str.match(r"^\d+$").any()
                ):
                    mapeo[col_std] = col
                    break

    for col_std, col_orig in mapeo.items():
        if col_orig in df_externo.columns and col_std not in df_externo.columns:
            df_externo[col_std] = df_externo[col_orig]

    # Asegurar columnas base
    columnas_base = ["Material", "Centro", "Almacén", "CantidadDisp"]
    for col in columnas_base:
        if col not in df_externo.columns:
            df_externo[col] = 0 if col == "CantidadDisp" else ""

    # Normalizar IDs
    for col in ["Centro", "Material", "Almacén"]:
        if col in df_externo.columns:
            df_externo[col] = normalizar_ids(df_externo[col])

    # Cantidad disponible a numérico
    if "CantidadDisp" in df_externo.columns:
        df_externo["CantidadDisp"] = pd.to_numeric(
            df_externo["CantidadDisp"], errors="coerce"
        ).fillna(0)

        if df_externo["CantidadDisp"].sum() == 0 and nombre_hoja in ["Cosmopark", "PNC"]:
            for col in df_externo.columns:
                if any(term in col.lower() for term in ["cant", "qty", "quantity"]):
                    df_externo["CantidadDisp"] = pd.to_numeric(
                        df_externo[col], errors="coerce"
                    ).fillna(0)
                    break

    # Fecha de caducidad
    if "FechaCaducidad" in df_externo.columns:
        df_externo["FechaCaducidad_dt"] = pd.to_datetime(
            df_externo["FechaCaducidad"], dayfirst=True, errors="coerce"
        )
        df_externo["FechaCaducidad"] = df_externo["FechaCaducidad_dt"].apply(
            lambda x: x.strftime("%d/%m/%Y") if pd.notnull(x) else ""
        )

    # Procesamiento específico por hoja
    if nombre_hoja == "Corta caducidad":
        df_externo = _filtrar_corta_caducidad(df_externo)
    elif nombre_hoja in ("Revision", "Revision2"):
        df_externo = _procesar_revision(df_externo)

    # Limpiar columna auxiliar
    if "FechaCaducidad_dt" in df_externo.columns:
        df_externo = df_externo.drop(columns=["FechaCaducidad_dt"])

    return df_externo


def _patrones_por_hoja(nombre_hoja: str) -> dict:
    """Retorna los patrones de columnas esperadas para cada tipo de hoja."""
    if nombre_hoja == "Corta caducidad":
        return {
            "Material": ["material", "mat", "artículo"],
            "Centro": ["centro", "center"],
            "Almacén": ["almacén", "almacen"],
            "CantidadDisp": [
                "cantidad",
                "disp",
                "disponible",
                "stock",
                "libre utilización",
                "libre utilizacion",
            ],
            "Descripcion": ["descripción", "descripcion", "desc", "texto"],
            "Lote": ["lote", "batch"],
            "FechaCaducidad": [
                "fecaduc/feprefercons",
                "caducidad",
                "fecha caducidad",
                "vencimiento",
                "expira",
            ],
        }
    if nombre_hoja == "Lento mov":
        return {
            "Material": ["material", "mat", "artículo"],
            "Descripcion": [
                "descripción",
                "descripcion",
                "desc",
                "texto",
                "texto breve",
            ],
        }
    if nombre_hoja == "Cosmopark":
        return {
            "Material": ["material", "mat", "artículo", "codigo"],
            "Centro": ["centro", "center"],
            "CantidadDisp": ["cantidad", "disp", "disponible", "stock"],
            "Descripcion": [
                "descripción",
                "descripcion",
                "desc",
                "texto",
                "texto material",
            ],
            "Lote": ["lote", "batch"],
            "FechaCaducidad": ["caducidad", "fecha caducidad", "vencimiento", "expira"],
        }
    if nombre_hoja == "Sustituto":
        return {
            "Material": ["material", "mat", "artículo"],
            "Material sustituto": ["material sustituto", "sustituto", "alternativo"],
            "Texto material sustituto": [
                "texto material sustituto",
                "descripción sustituto",
                "desc sustituto",
            ],
        }
    if nombre_hoja in ["PNC", "Caduco"]:
        return {
            "Material": ["material", "mat", "artículo"],
            "Centro": ["centro", "center"],
            "Almacén": ["almacén", "almacen"],
            "CantidadDisp": ["cantidad", "disp", "disponible", "stock"],
            "Descripcion": ["descripción", "descripcion", "desc", "texto"],
            "Lote": ["lote", "batch"],
            "FechaCaducidad": ["caducidad", "fecha caducidad", "vencimiento", "expira"],
        }
    if nombre_hoja in ("Revision", "Revision2"):
        return {
            "Material": ["material", "mat", "artículo"],
            "Descripcion": [
                "texto breve de material",
                "texto breve",
                "descripción",
                "descripcion",
                "texto material",
                "texto",
                "desc",
            ],
            "Status": ["status", "estatus", "estado"],
        }
    return {}


def _filtrar_corta_caducidad(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra materiales de Corta caducidad:
    - Con FeCaduc/FePreferCons a menos de 1 año desde hoy, O
    - En almacén = '1032'.
    """
    if df.empty:
        return df

    hoy = pd.Timestamp.today().normalize()
    limite = hoy + timedelta(days=DIAS_MAX_CORTA_CADUCIDAD)

    if "FechaCaducidad_dt" in df.columns:
        mask_fecha = df["FechaCaducidad_dt"].notna() & (
            df["FechaCaducidad_dt"] <= limite
        )
    else:
        mask_fecha = pd.Series(False, index=df.index)

    if "Almacén" in df.columns:
        mask_almacen = df["Almacén"].astype(str).str.strip() == ALMACEN_PERMITIDO_CORTA_CADUCIDAD
    else:
        mask_almacen = pd.Series(False, index=df.index)

    mask_final = mask_fecha | mask_almacen
    df_filtrado = df[mask_final].copy()

    logger.info(
        f"Corta caducidad: {len(df)} filas originales → {len(df_filtrado)} tras filtro "
        f"(caducidad < 1año o almacén {ALMACEN_PERMITIDO_CORTA_CADUCIDAD})"
    )

    return df_filtrado


def _procesar_revision(df: pd.DataFrame) -> pd.DataFrame:
    """Procesa la hoja de Revisión:
    - Asegura columna 'Status' existente.
    - El mismo material puede tener múltiples Status (se procesa tal cual en fase de búsqueda).
    """
    if "Status" not in df.columns:
        df["Status"] = ""

    df["Status"] = df["Status"].fillna("").astype(str).str.strip()

    if "Descripcion" not in df.columns:
        df["Descripcion"] = ""
    df["Descripcion"] = df["Descripcion"].fillna("").astype(str)

    # Eliminar filas con material vacío
    if "Material" in df.columns:
        mask_valido = df["Material"].astype(str).str.strip() != ""
        df = df[mask_valido].copy()

    logger.info(f"Revision: {len(df)} materiales con Status")
    return df
