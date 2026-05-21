"""
reportes/inventario_por_condicion.py

Genera dos DataFrames para el reporte final:

1. df_inventario_por_condicion — Una fila por (Material, Condicion), con columnas
   por centro de interés (Inv {c}, Cant. en Tránsito Inv {c}) y dos columnas
   informativas (Disponible 1031-1030, Disponible 1031-1032).

   Fuentes de filas:
   - Sección A: hoja externa 'Revision2' (Material, Descripcion, Status).
       * Condicion = Status (tal cual).
       * Si Status text contiene keyword de caducidad → se calculan celdas con
         inventario_df filtrado a Almacén=1032 únicamente.
       * Si NO contiene keyword → inventario_df filtrado a Almacenes
         {1030, 1031, 1060}.
   - Sección B: hoja externa 'Corta caducidad' (ya filtrada a <12m o alm 1032).
       * Una fila por Material con Condicion = 'Corta caducidad', siempre que
         el material no esté ya en Sección A con un Status que contenga
         keyword de caducidad.
       * Celdas calculadas con CantidadDisp de la hoja externa (opción b).

2. df_detalle_lotes_cc — Una fila por lote para los materiales de la Sección B
   (los detectados como Corta caducidad por la hoja externa). Columnas:
   Material, Texto breve, Centro, Almacén, Lote, FechaCaducidad, CantidadDisp.
"""
import logging
import re
from typing import Dict, List, Tuple

import pandas as pd

from config import CENTROS_INTERES

logger = logging.getLogger(__name__)

# Patrones (case-insensitive) que marcan un Status como "Corta Caducidad"
# y obligan a usar Almacén=1032 para sus cálculos.
_CADUCIDAD_RE = re.compile(r"caducidad|corta|cor[\s\.\-]*cad", re.IGNORECASE)

ALMACENES_NORMAL = ["1030", "1031", "1060"]
ALMACEN_CORTA = "1032"


def _contiene_caducidad(texto: str) -> bool:
    """True si el texto contiene 'caducidad', 'corta', o 'cor cad' (case-insens)."""
    if not isinstance(texto, str) or not texto.strip():
        return False
    return bool(_CADUCIDAD_RE.search(texto))


def _construir_indice_inventario(
    inventario_df: pd.DataFrame,
) -> Tuple[Dict, Dict, Dict, Dict]:
    """Construye 4 índices vectorizados para lookups O(1) sobre inventario.

    Retorna:
      - libre_por_key:   {(centro, material, almacen): libre_utilizacion}
      - transito_por_key:{(centro, material, almacen): cant_transito}
      - desc_por_mat:    {material: descripcion}
      - mats_existentes: set de materiales presentes en inventario
    """
    libre_por_key: Dict[Tuple[str, str, str], float] = {}
    transito_por_key: Dict[Tuple[str, str, str], float] = {}
    desc_por_mat: Dict[str, str] = {}
    mats_existentes: set = set()

    if inventario_df is None or inventario_df.empty:
        return libre_por_key, transito_por_key, desc_por_mat, mats_existentes

    inv = inventario_df.copy()
    inv["_centro"] = inv["Centro"].astype(str).str.strip()
    inv["_material"] = inv["Material"].astype(str).str.strip()
    inv["_almacen"] = inv["Almacén"].astype(str).str.strip()
    libre_num = pd.to_numeric(
        inv.get("Libre Utilización", 0), errors="coerce"
    ).fillna(0.0)
    transito_num = pd.to_numeric(
        inv.get("Cant. en Tránsito", 0), errors="coerce"
    ).fillna(0.0)

    for c, m, a, lib, tr in zip(
        inv["_centro"], inv["_material"], inv["_almacen"], libre_num, transito_num
    ):
        key = (c, m, a)
        libre_por_key[key] = libre_por_key.get(key, 0.0) + float(lib)
        transito_por_key[key] = transito_por_key.get(key, 0.0) + float(tr)
        mats_existentes.add(m)

    # Descripción por material — primera no-vacía encontrada
    if "Descripción" in inv.columns:
        for mat, desc in zip(inv["_material"], inv["Descripción"].astype(str)):
            if mat and mat not in desc_por_mat and desc and desc.lower() != "nan":
                desc_por_mat[mat] = desc

    return libre_por_key, transito_por_key, desc_por_mat, mats_existentes


def _suma_por_almacenes(
    indice: Dict[Tuple[str, str, str], float],
    centro: str,
    material: str,
    almacenes: List[str],
) -> float:
    """Suma los valores del índice para los almacenes dados en (centro, material)."""
    total = 0.0
    for alm in almacenes:
        total += indice.get((centro, material, alm), 0.0)
    return total


def generar_inventario_por_condicion(
    df_revision2: pd.DataFrame,
    df_corta_caducidad: pd.DataFrame,
    inventario_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Genera el reporte 'Inventario por condicion' + el detalle de lotes.

    Args:
        df_revision2: hoja externa Revision2 (Material, Descripcion, Status).
        df_corta_caducidad: hoja externa Corta caducidad ya filtrada
            (caducidad <12m o almacén 1032). Columnas esperadas:
            Material, Centro, Almacén, CantidadDisp, Lote, FechaCaducidad.
        inventario_df: inventario crudo con Libre Utilización y Cant. en Tránsito
            por (Centro, Material, Almacén).

    Returns:
        (df_inventario_por_condicion, df_detalle_lotes_cc)
    """
    libre_idx, transito_idx, desc_idx, _ = _construir_indice_inventario(
        inventario_df
    )

    centros = list(CENTROS_INTERES)
    filas: List[dict] = []

    # ───────────── SECCIÓN A: cada (Material, Status) de Revision2 ─────────────
    materiales_a_caducidad: set = set()  # (material) ya tratados como caducidad en A

    if df_revision2 is not None and not df_revision2.empty:
        if "Material" in df_revision2.columns and "Status" in df_revision2.columns:
            tmp = df_revision2.copy()
            tmp["_material"] = tmp["Material"].astype(str).str.strip()
            tmp["_status"] = tmp["Status"].astype(str).fillna("").str.strip()
            tmp = tmp[tmp["_material"] != ""]

            for _, row in tmp.iterrows():
                mat = row["_material"]
                status = row["_status"]
                es_caducidad = _contiene_caducidad(status)
                almacenes = (
                    [ALMACEN_CORTA] if es_caducidad else ALMACENES_NORMAL
                )

                fila = {
                    "Condicion": status if status else "(sin status)",
                    "Material": mat,
                    "Texto breve de material": desc_idx.get(mat, ""),
                    "Disponible 1031-1030": libre_idx.get(("1031", mat, "1030"), 0.0),
                    "Disponible 1031-1032": libre_idx.get(("1031", mat, "1032"), 0.0),
                }
                for c in centros:
                    fila[f"Inv {c}"] = _suma_por_almacenes(
                        libre_idx, c, mat, almacenes
                    )
                    fila[f"Cant. en Tránsito Inv {c}"] = _suma_por_almacenes(
                        transito_idx, c, mat, almacenes
                    )
                filas.append(fila)

                if es_caducidad:
                    materiales_a_caducidad.add(mat)

    # ───────────── SECCIÓN B: Corta caducidad de la hoja externa ──────────────
    detalle_lotes: List[dict] = []

    if df_corta_caducidad is not None and not df_corta_caducidad.empty:
        cc = df_corta_caducidad.copy()
        cc["_material"] = cc["Material"].astype(str).str.strip()
        cc["_centro"] = cc.get("Centro", "").astype(str).str.strip()
        cc["_almacen"] = cc.get("Almacén", "").astype(str).str.strip()
        cc["_cant"] = pd.to_numeric(
            cc.get("CantidadDisp", 0), errors="coerce"
        ).fillna(0.0)
        cc = cc[cc["_material"] != ""]

        # Agregar fila resumen por cada Material que NO esté ya en Sección A
        # con keyword de caducidad.
        for mat, g in cc.groupby("_material", sort=True):
            if mat in materiales_a_caducidad:
                continue

            fila = {
                "Condicion": "Corta caducidad",
                "Material": mat,
                "Texto breve de material": desc_idx.get(mat, ""),
                "Disponible 1031-1030": libre_idx.get(("1031", mat, "1030"), 0.0),
                "Disponible 1031-1032": libre_idx.get(("1031", mat, "1032"), 0.0),
            }
            # Inv {c} desde CantidadDisp de hoja Corta caducidad (opción b)
            suma_por_centro = g.groupby("_centro")["_cant"].sum().to_dict()
            for c in centros:
                fila[f"Inv {c}"] = float(suma_por_centro.get(c, 0.0))
                # Tránsito desde inventario_df, almacén 1032 (la hoja externa no
                # trae info de tránsito).
                fila[f"Cant. en Tránsito Inv {c}"] = transito_idx.get(
                    (c, mat, ALMACEN_CORTA), 0.0
                )
            filas.append(fila)

        # Detalle de lotes (siempre que sea posible): una fila por lote real
        cols_detalle = ["Material", "Centro", "Almacén", "Lote", "FechaCaducidad", "CantidadDisp"]
        cols_presentes = [c for c in cols_detalle if c in cc.columns]
        if cols_presentes:
            det = cc[cols_presentes].copy()
            # Texto breve y orden
            det["Texto breve de material"] = (
                det["Material"].astype(str).str.strip().map(desc_idx).fillna("")
            )
            # Reordenar: Material, Texto breve, Centro, Almacén, Lote, FechaCad, CantidadDisp
            orden = ["Material", "Texto breve de material"]
            for c in ["Centro", "Almacén", "Lote", "FechaCaducidad", "CantidadDisp"]:
                if c in det.columns:
                    orden.append(c)
            det = det[orden].sort_values(
                by=[c for c in ["Material", "Centro", "Almacén", "Lote"] if c in det.columns]
            ).reset_index(drop=True)
            detalle_lotes = det.to_dict("records")

    # ───────────── Construir DataFrames finales ──────────────
    if not filas:
        df_resumen = pd.DataFrame()
    else:
        # Orden de columnas
        columnas = [
            "Condicion",
            "Material",
            "Texto breve de material",
            "Disponible 1031-1030",
            "Disponible 1031-1032",
        ]
        for c in centros:
            columnas.append(f"Inv {c}")
            columnas.append(f"Cant. en Tránsito Inv {c}")

        df_resumen = pd.DataFrame(filas)[columnas]
        # Orden de filas: por Condicion asc, luego Material asc
        df_resumen = df_resumen.sort_values(
            by=["Condicion", "Material"], kind="stable"
        ).reset_index(drop=True)

    df_detalle = (
        pd.DataFrame(detalle_lotes) if detalle_lotes else pd.DataFrame()
    )

    logger.info(
        f"Inventario por condicion: {len(df_resumen)} filas resumen + "
        f"{len(df_detalle)} filas detalle lotes."
    )

    return df_resumen, df_detalle
