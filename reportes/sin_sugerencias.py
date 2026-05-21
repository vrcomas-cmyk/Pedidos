"""
reportes/sin_sugerencias.py - Genera el reporte 'Resumen Sin Sugerencias'.

Cambios:
  - Nueva columna 'Status Revisión' con los Status concatenados del material
    desde la hoja 'Revision' (si el material aparece en dicha hoja).
"""
import logging
from typing import Dict, List

import numpy as np
import pandas as pd

from config import CENTROS_INTERES, Columnas
from procesadores.facturacion import (
    calcular_estadisticas_consumo_por_centro_material_almacen,
)

logger = logging.getLogger(__name__)


def calcular_pendiente_por_centro_sin_bloqueo(
    df_todas_sugerencias: pd.DataFrame,
    centros: List[str] = None,
) -> Dict[str, Dict[str, float]]:
    """Calcula la cantidad pendiente por centro sin estatus de bloqueo.

    Retorna {centro: {material: pendiente_total}} — totalizado por Material
    sumando todos los almacenes de ese centro. La clave es solo el Material
    para que el valor pueda propagarse a todas las filas del mismo material
    en el reporte (independientemente del Centro/Almacén de cada fila).
    """
    if centros is None:
        centros = CENTROS_INTERES
    if df_todas_sugerencias.empty:
        return {}

    try:
        df_sin_bloqueo = df_todas_sugerencias[
            (df_todas_sugerencias[Columnas.FUENTE] == "")
            & (df_todas_sugerencias[Columnas.BLOQUEADO] == "")
            & (df_todas_sugerencias[Columnas.CANTIDAD_PENDIENTE] > 0)
        ].copy()

        if df_sin_bloqueo.empty:
            return {}

        resultados = {centro: {} for centro in centros}

        for centro in centros:
            df_centro = df_sin_bloqueo[
                (df_sin_bloqueo[Columnas.CENTRO_PEDIDO] == str(centro))
            ]
            if df_centro.empty:
                continue

            # Deduplicar a nivel pedido (un mismo pedido aparece varias veces
            # si tiene múltiples sugerencias) para no contar pendientes dobles.
            df_agrupado = (
                df_centro.groupby(
                    [
                        Columnas.MATERIAL_SOLICITADO,
                        Columnas.ALMACEN,
                        Columnas.PEDIDO,
                    ]
                )
                .agg({Columnas.CANTIDAD_PENDIENTE: "first"})
                .reset_index()
            )

            # Totalizar por Material sumando todos los almacenes del centro.
            df_final = (
                df_agrupado.groupby([Columnas.MATERIAL_SOLICITADO])
                .agg(Pendiente_Total=(Columnas.CANTIDAD_PENDIENTE, "sum"))
                .reset_index()
            )

            for _, row in df_final.iterrows():
                material = str(row[Columnas.MATERIAL_SOLICITADO]).strip()
                resultados[centro][material] = float(row["Pendiente_Total"])

        return resultados

    except Exception as e:
        logger.error(f"Error al calcular pendiente por centro: {str(e)}")
        return {}


def _construir_mapa_revision(df_revision: pd.DataFrame) -> Dict[str, str]:
    """Construye un mapa {material: 'Status1, Status2, ...'} desde la hoja Revision.

    Se concatenan los Status únicos de cada material en el orden de aparición.
    """
    mapa: Dict[str, str] = {}
    if df_revision is None or df_revision.empty:
        return mapa
    if "Material" not in df_revision.columns or "Status" not in df_revision.columns:
        return mapa

    tmp = df_revision.copy()
    tmp["Material"] = tmp["Material"].astype(str).str.strip()
    tmp["Status"] = tmp["Status"].fillna("").astype(str).str.strip()

    for mat, grp in tmp.groupby("Material", sort=False):
        statuses = []
        for s in grp["Status"]:
            if s and s not in statuses:
                statuses.append(s)
        if statuses:
            mapa[mat] = ", ".join(statuses)

    return mapa


def generar_resumen_sin_sugerencias_optimizado(
    df_sugerencias: pd.DataFrame,
    inventario_df: pd.DataFrame,
    df_todas_sugerencias: pd.DataFrame,
    df_facturacion_procesado: pd.DataFrame = None,
    df_revision: pd.DataFrame = None,
) -> pd.DataFrame:
    """Genera el resumen incluyendo Status Revisión por material si aplica."""

    # 1. Materiales con inventario > 0
    inventario_materiales = pd.DataFrame()
    if inventario_df is not None and not inventario_df.empty:
        inventario_filtrado = inventario_df[
            inventario_df["Libre Utilización"] > 0
        ].copy()

        if not inventario_filtrado.empty:
            inventario_materiales = (
                inventario_filtrado.groupby(["Centro", "Material", "Almacén"])
                .agg(
                    Descripcion=("Descripción", "first"),
                    Libre_Utilizacion_Total=("Libre Utilización", "sum"),
                    Transito_Total=("Cant. en Tránsito", "sum"),
                )
                .reset_index()
            )
            inventario_materiales = inventario_materiales.rename(
                columns={"Almacén": "Almacen"}
            )
            inventario_materiales["Fuente"] = "Inventario"

    # 2. Materiales con pedidos sin sugerencia y sin bloqueo
    pedidos_materiales = pd.DataFrame()
    if df_sugerencias is not None and not df_sugerencias.empty:
        df_sin_sugerencia = df_sugerencias[
            (df_sugerencias[Columnas.FUENTE] == "")
            & (df_sugerencias[Columnas.BLOQUEADO] == "")
            & (df_sugerencias[Columnas.CANTIDAD_PENDIENTE] > 0)
        ].copy()

        if not df_sin_sugerencia.empty:
            df_sin_sugerencia["Importe_Calculado"] = (
                df_sin_sugerencia[Columnas.CANTIDAD_PENDIENTE]
                * df_sin_sugerencia[Columnas.PRECIO]
            )
            pedidos_materiales = (
                df_sin_sugerencia.groupby(
                    [
                        Columnas.CENTRO_PEDIDO,
                        Columnas.ALMACEN,
                        Columnas.MATERIAL_SOLICITADO,
                    ]
                )
                .agg(
                    Pedidos=(Columnas.PEDIDO, "nunique"),
                    Descripcion=(Columnas.DESCRIPCION_SOLICITADA, "first"),
                    Cantidad_Pendiente=(Columnas.CANTIDAD_PENDIENTE, "sum"),
                    Importe_Pendiente=("Importe_Calculado", "sum"),
                )
                .reset_index()
            )
            pedidos_materiales = pedidos_materiales.rename(
                columns={
                    Columnas.CENTRO_PEDIDO: "Centro",
                    Columnas.ALMACEN: "Almacen",
                    Columnas.MATERIAL_SOLICITADO: "Material",
                }
            )
            pedidos_materiales["Fuente"] = "Pedidos"

    # 3. Combinar
    if not inventario_materiales.empty:
        for col in ["Pedidos", "Cantidad_Pendiente", "Importe_Pendiente"]:
            if col not in inventario_materiales.columns:
                inventario_materiales[col] = 0
    if not pedidos_materiales.empty:
        for col in ["Libre_Utilizacion_Total", "Transito_Total"]:
            if col not in pedidos_materiales.columns:
                pedidos_materiales[col] = 0

    if not inventario_materiales.empty and not pedidos_materiales.empty:
        combined = pd.concat(
            [inventario_materiales, pedidos_materiales], ignore_index=True
        )
        combined = combined.sort_values(
            by=["Centro", "Material", "Almacen", "Fuente"],
            ascending=[True, True, True, False],
        )
        grouped = combined.drop_duplicates(
            subset=["Centro", "Material", "Almacen"], keep="first"
        )
    elif not inventario_materiales.empty:
        grouped = inventario_materiales
    elif not pedidos_materiales.empty:
        grouped = pedidos_materiales
    else:
        return pd.DataFrame()

    for col in [
        "Pedidos", "Cantidad_Pendiente", "Importe_Pendiente",
        "Libre_Utilizacion_Total", "Transito_Total",
    ]:
        if col not in grouped.columns:
            grouped[col] = 0

    if "Descripcion" in grouped.columns:
        grouped["Descripcion"] = grouped["Descripcion"].fillna("")

    # 4. Caches de inventario vectorizados
    inventario_cache = {}
    transito_cache = {}
    # NUEVO: cache filtrado por Material→Centro (sumando almacenes 1030/1031/1060)
    # Misma lógica que motor_optimizado.build_inv_caches → "inv_filtrado_mat".
    # Se usa para poblar las columnas Inv 1001..Inv 1036 con la suma de
    # 'Libre Utilización' por Centro para almacenes 1030, 1031 y 1060.
    inv_filtrado_mat: Dict[str, Dict[str, float]] = {}
    if inventario_df is not None and not inventario_df.empty:
        inv_tmp = inventario_df.copy()
        inv_tmp["_centro"] = inv_tmp["Centro"].astype(str).str.strip()
        inv_tmp["_material"] = inv_tmp["Material"].astype(str).str.strip()
        inv_tmp["_almacen"] = inv_tmp["Almacén"].astype(str).str.strip()
        inv_tmp["_key_inv"] = (
            inv_tmp["_centro"] + "_" + inv_tmp["_material"] + "_" + inv_tmp["_almacen"]
        )
        inventario_cache = inv_tmp.set_index("_key_inv")["Libre Utilización"].to_dict()

        trans_sub = inv_tmp[inv_tmp["_almacen"].isin(["1030", "1031", "1032"])]
        if not trans_sub.empty:
            trans_grouped = (
                trans_sub.groupby(["_centro", "_material", "_almacen"])[
                    "Cant. en Tránsito"
                ]
                .sum()
                .reset_index()
            )
            # Cache plano (Centro_Material_Almacen → Cant. en Tránsito) para
            # permitir lookup vectorizado con .map() más abajo.
            trans_grouped["_key_flat"] = (
                trans_grouped["_centro"]
                + "_"
                + trans_grouped["_material"]
                + "_"
                + trans_grouped["_almacen"]
            )
            transito_cache = dict(
                zip(
                    trans_grouped["_key_flat"],
                    trans_grouped["Cant. en Tránsito"].astype(float),
                )
            )

        # Cache filtrado para Inv 1001..1036
        libre_num = pd.to_numeric(
            inv_tmp.get("Libre Utilización", 0), errors="coerce"
        ).fillna(0.0)
        inv_tmp["_libre_num"] = libre_num
        inv_filt = inv_tmp[inv_tmp["_almacen"].isin(["1030", "1031", "1060"])]
        if not inv_filt.empty:
            for (mat, centro), g in inv_filt.groupby(
                ["_material", "_centro"], sort=False
            ):
                inv_filtrado_mat.setdefault(mat, {})[centro] = float(
                    g["_libre_num"].sum()
                )

    # 5. Estadísticas de consumo
    estadisticas_consumo_df = None
    if df_facturacion_procesado is not None and not df_facturacion_procesado.empty:
        estadisticas_consumo_df = (
            calcular_estadisticas_consumo_por_centro_material_almacen(
                df_facturacion_procesado
            )
        )

    if estadisticas_consumo_df is not None and not estadisticas_consumo_df.empty:
        grouped = pd.merge(
            grouped,
            estadisticas_consumo_df,
            left_on=["Centro", "Material", "Almacen"],
            right_on=["Centro", "Material", "Almacen"],
            how="left",
        )
        for col in [
            "Promedio_Consumo_12M",
            "Cantidad_Ultimo_Mes",
            "Cantidad_Penultimo_Mes",
        ]:
            if col in grouped.columns:
                grouped[col] = grouped[col].fillna(0)
        for col in ["Ultimo_Mes_Consumo", "Penultimo_Mes_Consumo"]:
            if col in grouped.columns:
                grouped[col] = grouped[col].fillna("")
    else:
        grouped["Promedio_Consumo_12M"] = 0
        grouped["Ultimo_Mes_Consumo"] = ""
        grouped["Penultimo_Mes_Consumo"] = ""
        grouped["Cantidad_Ultimo_Mes"] = 0
        grouped["Cantidad_Penultimo_Mes"] = 0

    # 5.b NUEVO: filas con SOLO consumo (sin inventario ni pedido en esa combo
    # Centro+Material+Almacén). Se incluyen cuando Promedio_Consumo_12M > 0 y
    # la combinación NO existe ya en `grouped`. Fuente = "Consumo".
    if (
        estadisticas_consumo_df is not None
        and not estadisticas_consumo_df.empty
    ):
        _consumo = estadisticas_consumo_df.copy()
        _consumo["_centro"] = _consumo["Centro"].astype(str).str.strip()
        _consumo["_material"] = _consumo["Material"].astype(str).str.strip()
        _consumo["_almacen"] = _consumo["Almacen"].astype(str).str.strip()
        _consumo = _consumo[
            pd.to_numeric(_consumo["Promedio_Consumo_12M"], errors="coerce").fillna(0)
            > 0
        ]
        if not _consumo.empty:
            grouped_keys = set(
                zip(
                    grouped["Centro"].astype(str).str.strip(),
                    grouped["Material"].astype(str).str.strip(),
                    grouped["Almacen"].astype(str).str.strip(),
                )
            )
            consumo_keys = list(
                zip(_consumo["_centro"], _consumo["_material"], _consumo["_almacen"])
            )
            mask_nuevas = [k not in grouped_keys for k in consumo_keys]
            nuevas = _consumo[mask_nuevas].copy()

            if not nuevas.empty:
                # Lookup de descripción: primero df_facturacion (Texto Material),
                # luego inventario_df (Descripción), si no, vacío.
                # Optimización: deduplicar antes de astype(str) para no convertir
                # millones de filas de facturación si solo importan unos miles
                # de materiales únicos.
                desc_map: Dict[str, str] = {}
                if (
                    df_facturacion_procesado is not None
                    and not df_facturacion_procesado.empty
                    and "Texto Material" in df_facturacion_procesado.columns
                ):
                    desc_fact = (
                        df_facturacion_procesado[["Material", "Texto Material"]]
                        .dropna()
                        .drop_duplicates("Material")
                    )
                    desc_fact["Material"] = (
                        desc_fact["Material"].astype(str).str.strip()
                    )
                    desc_fact["Texto Material"] = desc_fact["Texto Material"].astype(
                        str
                    )
                    desc_map.update(
                        desc_fact.set_index("Material")["Texto Material"].to_dict()
                    )
                if inventario_df is not None and not inventario_df.empty:
                    if "Descripción" in inventario_df.columns:
                        desc_inv = (
                            inventario_df[["Material", "Descripción"]]
                            .dropna()
                            .drop_duplicates("Material")
                        )
                        desc_inv["Material"] = (
                            desc_inv["Material"].astype(str).str.strip()
                        )
                        desc_inv["Descripción"] = desc_inv["Descripción"].astype(str)
                        for mat, desc in (
                            desc_inv.set_index("Material")["Descripción"]
                            .to_dict()
                            .items()
                        ):
                            desc_map.setdefault(mat, desc)

                # Armar filas con la estructura de `grouped`
                filas_consumo = pd.DataFrame(
                    {
                        "Centro": nuevas["_centro"].values,
                        "Almacen": nuevas["_almacen"].values,
                        "Material": nuevas["_material"].values,
                        "Descripcion": [
                            desc_map.get(m, "") for m in nuevas["_material"].values
                        ],
                        "Pedidos": "",
                        "Cantidad_Pendiente": 0,
                        "Importe_Pendiente": 0,
                        "Libre_Utilizacion_Total": 0,
                        "Transito_Total": 0,
                        "Fuente": "Consumo",
                        "Promedio_Consumo_12M": pd.to_numeric(
                            nuevas["Promedio_Consumo_12M"], errors="coerce"
                        ).fillna(0).values,
                        "Ultimo_Mes_Consumo": nuevas["Ultimo_Mes_Consumo"]
                        .fillna("").astype(str).values,
                        "Cantidad_Ultimo_Mes": pd.to_numeric(
                            nuevas["Cantidad_Ultimo_Mes"], errors="coerce"
                        ).fillna(0).values,
                        "Penultimo_Mes_Consumo": nuevas["Penultimo_Mes_Consumo"]
                        .fillna("").astype(str).values,
                        "Cantidad_Penultimo_Mes": pd.to_numeric(
                            nuevas["Cantidad_Penultimo_Mes"], errors="coerce"
                        ).fillna(0).values,
                    }
                )
                # Append: las columnas de Inv {almacen}/{centro}, Pendiente {centro},
                # Suma inventario/pendiente, Meses_Inventario, etc. se calcularán
                # más abajo igual que para cualquier fila — para combinaciones sin
                # inventario / sin pedido todas darán 0 naturalmente.
                grouped = pd.concat(
                    [grouped, filas_consumo], ignore_index=True, sort=False
                )

    # 6. Inventario por almacén
    def _build_inv_col(suffix: str) -> pd.Series:
        keys = grouped["Centro"] + "_" + grouped["Material"] + "_" + suffix
        return keys.map(inventario_cache).fillna(0)

    grouped["Inv 1030"] = _build_inv_col("1030")
    grouped["Inv 1031"] = _build_inv_col("1031")
    grouped["Inv 1032"] = _build_inv_col("1032")
    grouped["Inv 1060"] = _build_inv_col("1060")

    # Tránsito por fila — vectorizado vía dict plano construido arriba
    _trans_keys = (
        grouped["Centro"].astype(str)
        + "_"
        + grouped["Material"].astype(str)
        + "_"
        + grouped["Almacen"].astype(str)
    )
    grouped["Cant. en Tránsito"] = _trans_keys.map(transito_cache).fillna(0)

    grouped["Disponible 1031-1030"] = grouped["Material"].map(
        lambda m: inventario_cache.get(f"1031_{m}_1030", 0)
    )
    grouped["Disponible 1031-1032"] = grouped["Material"].map(
        lambda m: inventario_cache.get(f"1031_{m}_1032", 0)
    )

    # NUEVO: Inv 1001..Inv 1036 — misma lógica que en 'Todas las Sugerencias'.
    # Para cada Material, suma Libre Utilización de almacenes 1030/1031/1060
    # agrupado por Centro. NO depende del Centro de la fila — depende solo del
    # Material (mismo material → mismos valores Inv 1001..Inv 1036 en todas
    # sus filas). Se prearma un dict por centro para usar .map(dict) — mucho
    # más rápido que .map(lambda) en DataFrames grandes.
    _mat_norm = grouped["Material"].astype(str).str.strip()
    for centro in CENTROS_INTERES:
        col_name = f"Inv {centro}"
        centro_dict = {
            m: float(vals.get(centro, 0.0))
            for m, vals in inv_filtrado_mat.items()
        }
        grouped[col_name] = _mat_norm.map(centro_dict).fillna(0.0)

    # NUEVO: Suma inventario = Σ(Inv 1001..Inv 1036) + Disponible 1031-1030
    # (Disponible 1031-1030 = Libre Utilización de Centro 1031, Almacén 1030)
    cols_inv_centros = [f"Inv {c}" for c in CENTROS_INTERES]
    grouped["Suma inventario"] = (
        grouped[cols_inv_centros].sum(axis=1)
        + pd.to_numeric(grouped["Disponible 1031-1030"], errors="coerce").fillna(0)
    )

    # 7. Meses_Inventario
    inv_segun_almacen = np.select(
        [
            grouped["Almacen"].astype(str).str.strip() == "1030",
            grouped["Almacen"].astype(str).str.strip() == "1031",
            grouped["Almacen"].astype(str).str.strip() == "1060",
        ],
        [grouped["Inv 1030"], grouped["Inv 1031"], grouped["Inv 1060"]],
        default=grouped["Inv 1032"],
    )
    consumo_prom = grouped["Promedio_Consumo_12M"]
    grouped["Meses_Inventario"] = np.where(
        consumo_prom > 0,
        (inv_segun_almacen / consumo_prom).round(2),
        np.where(inv_segun_almacen == 0, 0.0, 999.0),
    )

    # 8. Pendiente por centro
    pendiente_por_centro_dict = None
    if df_todas_sugerencias is not None and not df_todas_sugerencias.empty:
        pendiente_por_centro_dict = calcular_pendiente_por_centro_sin_bloqueo(
            df_todas_sugerencias
        )

    if pendiente_por_centro_dict:
        # Propagación por Material (no se filtra por el Centro de la fila):
        # el pendiente del centro X se muestra en TODAS las filas del mismo
        # material — misma lógica que Inv {centro}.
        _mat_pendiente = grouped["Material"].astype(str).str.strip()
        for centro in CENTROS_INTERES:
            col_name = f"Pendiente {centro}"
            centro_dict = pendiente_por_centro_dict.get(centro, {})
            if centro_dict:
                grouped[col_name] = _mat_pendiente.map(centro_dict).fillna(0)
            else:
                grouped[col_name] = 0
    else:
        for centro in CENTROS_INTERES:
            grouped[f"Pendiente {centro}"] = 0

    # NUEVO: Suma pendiente = Σ(Pendiente 1001..Pendiente 1036)
    cols_pend_centros = [f"Pendiente {c}" for c in CENTROS_INTERES]
    grouped["Suma pendiente"] = (
        grouped[cols_pend_centros]
        .apply(lambda s: pd.to_numeric(s, errors="coerce").fillna(0))
        .sum(axis=1)
    )

    # 9. NUEVO: Columna Status Revisión
    mapa_revision = _construir_mapa_revision(df_revision)
    if mapa_revision:
        grouped[Columnas.STATUS_REVISION] = grouped["Material"].astype(str).str.strip().map(
            mapa_revision
        ).fillna("")
    else:
        grouped[Columnas.STATUS_REVISION] = ""

    # 10. Ordenar columnas
    columnas_orden = [
        "Centro", "Almacen", "Pedidos", "Material", "Descripcion",
        "Cantidad_Pendiente", "Importe_Pendiente", "Promedio_Consumo_12M",
        "Ultimo_Mes_Consumo", "Cantidad_Ultimo_Mes",
        "Penultimo_Mes_Consumo", "Cantidad_Penultimo_Mes",
        "Meses_Inventario",
        "Inv 1030", "Inv 1031", "Inv 1032", "Inv 1060",
        "Cant. en Tránsito",
        "Disponible 1031-1030", "Disponible 1031-1032",
    ]
    # Pares Inv/Pendiente intercalados por centro (Inv 1001, Pendiente 1001, Inv 1003, ...)
    for centro in CENTROS_INTERES:
        columnas_orden.append(f"Inv {centro}")
        columnas_orden.append(f"Pendiente {centro}")
    columnas_orden.append("Suma inventario")          # Σ inventarios por centro
    columnas_orden.append("Suma pendiente")           # Σ pendientes por centro
    columnas_orden.append(Columnas.STATUS_REVISION)
    columnas_orden.append("Fuente")

    for col in columnas_orden:
        if col not in grouped.columns:
            if col in [
                "Descripcion", "Centro", "Almacen", "Material",
                "Ultimo_Mes_Consumo", "Penultimo_Mes_Consumo", "Fuente",
                Columnas.STATUS_REVISION,
            ]:
                grouped[col] = ""
            elif col == "Meses_Inventario":
                grouped[col] = 0.0
            else:
                grouped[col] = 0

    grouped = grouped.sort_values(
        by=["Centro", "Almacen", "Material"], ascending=[True, True, True]
    )

    return grouped[columnas_orden]
