"""
procesadores/utilidades.py - Funciones auxiliares compartidas:
normalización de IDs, búsqueda de columnas por patrón, formato de fechas
y cálculo de meses de vigencia de lote.
"""
import time
from typing import List, Optional

import pandas as pd


class Timer:
    """Cronómetro ligero para mostrar tiempos en la UI."""

    def __init__(self):
        self._start = time.perf_counter()

    def elapsed(self) -> str:
        s = time.perf_counter() - self._start
        return f"{s:.1f}s" if s < 60 else f"{s/60:.1f}min"

    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self._start


def normalizar_ids(serie: pd.Series) -> pd.Series:
    """Normaliza IDs quitando espacios y sufijos .0"""
    if isinstance(serie, str):
        return pd.Series([], dtype=str)
    return serie.astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)


def encontrar_columna_por_patron(
    df: pd.DataFrame, patrones: List[str]
) -> Optional[str]:
    """Busca una columna que coincida con alguno de los patrones (case insensitive)."""
    for col in df.columns:
        col_lower = col.lower()
        for patron in patrones:
            if patron.lower() in col_lower:
                return col
    return None


def formatear_fecha_caducidad(fecha) -> str:
    """Normaliza fechas a dd/mm/aaaa sin reinterpretar formatos ya correctos."""
    if pd.isna(fecha):
        return ""

    if isinstance(fecha, str):
        fecha = fecha.strip()
        if not fecha or fecha.lower() == "nan":
            return ""

    try:
        fecha_dt = pd.to_datetime(fecha, dayfirst=True, errors="coerce")
        if pd.notnull(fecha_dt):
            return fecha_dt.strftime("%d/%m/%Y")
    except Exception:
        pass

    return str(fecha).strip()


def calcular_meses_vigencia(fecha_caducidad, fecha_referencia=None) -> str:
    """
    Calcula los meses de vigencia de un lote desde hoy hasta la fecha de caducidad.

    Retorna:
      - "" (string vacío) si no hay fecha de caducidad
      - número de meses redondeado a 1 decimal como float-string si hay fecha
      - "0" si la fecha ya venció (negativo o 0)
    """
    if fecha_caducidad is None or fecha_caducidad == "":
        return ""

    if isinstance(fecha_caducidad, str):
        fecha_caducidad = fecha_caducidad.strip()
        if not fecha_caducidad or fecha_caducidad.lower() == "nan":
            return ""

    try:
        fecha_cad_dt = pd.to_datetime(fecha_caducidad, dayfirst=True, errors="coerce")
        if pd.isna(fecha_cad_dt):
            return ""

        if fecha_referencia is None:
            fecha_referencia = pd.Timestamp.today()
        else:
            fecha_referencia = pd.to_datetime(fecha_referencia)

        delta_dias = (fecha_cad_dt - fecha_referencia).days
        meses = delta_dias / 30.4375  # promedio de días/mes

        if meses < 0:
            return "0"

        return f"{meses:.1f}"
    except Exception:
        return ""
