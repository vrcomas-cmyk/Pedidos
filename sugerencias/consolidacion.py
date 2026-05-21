"""
sugerencias/consolidacion.py - Consolida sugerencias idénticas agrupando la
columna Fuente. Maneja correctamente el nuevo formato "Revision (Status1, Status2)".
"""
import re

import numpy as np
import pandas as pd

from config import Columnas


def _separar_fuentes(fuente_str: str):
    """Separa una cadena de fuente en partes individuales.

    Respeta el patrón 'Revision (Status1, Status2)' manteniéndolo como una sola
    unidad, y separa por '/' el resto.

    Ejemplos:
      'Sustituto/Cosmopark'              → ['Sustituto', 'Cosmopark']
      'Revision (Urgente)/Cosmopark'     → ['Revision (Urgente)', 'Cosmopark']
      'Revision (Urgente, Pendiente)'    → ['Revision (Urgente, Pendiente)']
    """
    if not fuente_str:
        return []

    # Primero extraer bloques "Revision (...)" completos
    partes = []
    resto = str(fuente_str)

    patron_revision = re.compile(r"Revision\s*\([^)]*\)")
    while True:
        m = patron_revision.search(resto)
        if not m:
            break
        pre = resto[: m.start()]
        partes_pre = [p.strip() for p in pre.split("/") if p.strip()]
        partes.extend(partes_pre)
        partes.append(m.group(0).strip())
        resto = resto[m.end() :]
        # Quitar separador / al inicio del resto si lo hay
        resto = resto.lstrip("/").strip()

    if resto:
        partes_resto = [p.strip() for p in resto.split("/") if p.strip()]
        partes.extend(partes_resto)

    return partes


def _fusionar_revisiones(partes: list) -> list:
    """Si hay múltiples partes 'Revision (...)' las fusiona en una sola con todos los status.

    'Revision (Urgente)' + 'Revision (Pendiente)' → 'Revision (Urgente, Pendiente)'
    """
    revisiones_status = []
    otras = []
    for p in partes:
        m = re.match(r"Revision\s*\(([^)]*)\)", p)
        if m:
            for s in m.group(1).split(","):
                s = s.strip()
                if s and s not in revisiones_status:
                    revisiones_status.append(s)
        elif p.casefold() == "revision":
            # Revision sin paréntesis (caso borde); se mantiene como marcador
            if "" not in revisiones_status:
                revisiones_status.append("")
        else:
            otras.append(p)

    resultado = []
    # Agregar primero las "otras" fuentes preservando el orden
    for p in otras:
        if p not in resultado:
            resultado.append(p)
    # Agregar Revision consolidada al final si hay
    if revisiones_status:
        status_limpio = [s for s in revisiones_status if s]
        if status_limpio:
            resultado.append(f"Revision ({', '.join(status_limpio)})")
        else:
            resultado.append("Revision")
    return resultado


def unir_fuentes_repetidas(fuentes: pd.Series) -> str:
    """Une fuentes repetidas preservando orden, deduplicando y consolidando Revision."""
    partes_acumuladas = []
    vistos = set()

    for fuente in fuentes.fillna(""):
        for parte in _separar_fuentes(str(fuente)):
            clave = parte.casefold()
            # Revision se maneja por separado (no deduplicar por nombre completo)
            if parte.lower().startswith("revision"):
                partes_acumuladas.append(parte)
            else:
                if clave not in vistos:
                    vistos.add(clave)
                    partes_acumuladas.append(parte)

    # Fusionar todas las Revision en una sola con todos los status
    partes_final = _fusionar_revisiones(partes_acumuladas)
    return "/".join(partes_final)


def consolidar_sugerencias_repetidas(df_resultado: pd.DataFrame) -> pd.DataFrame:
    """Consolida sugerencias idénticas y solo agrupa la columna Fuente."""
    if (
        df_resultado is None
        or df_resultado.empty
        or Columnas.FUENTE not in df_resultado.columns
    ):
        return df_resultado

    df = df_resultado.copy()
    df["_orden_original"] = np.arange(len(df))

    mask_sugerencias = df[Columnas.FUENTE].fillna("").astype(str).str.strip() != ""
    if not mask_sugerencias.any():
        return df.drop(columns=["_orden_original"])

    df_sin_sugerencia = df[~mask_sugerencias].copy()
    df_con_sugerencia = df[mask_sugerencias].copy()

    columnas_clave = [
        col
        for col in df_con_sugerencia.columns
        if col not in [Columnas.FUENTE, "_orden_original"]
    ]

    df_consolidado = (
        df_con_sugerencia.groupby(columnas_clave, dropna=False, as_index=False)
        .agg(
            {
                Columnas.FUENTE: unir_fuentes_repetidas,
                "_orden_original": "min",
            }
        )
        .sort_values("_orden_original")
    )

    df_final = pd.concat(
        [df_sin_sugerencia, df_consolidado],
        ignore_index=True,
        sort=False,
    ).sort_values("_orden_original")

    return df_final.drop(columns=["_orden_original"]).reset_index(drop=True)
