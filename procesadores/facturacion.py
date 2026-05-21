"""
procesadores/facturacion.py - Procesa datos de facturación y genera el Reporte
de Consumo histórico.

Cambio respecto al original: las barras de progreso de Streamlit se extrajeron;
esta función acepta un callback opcional ``reportar_progreso(fraccion, texto)``
que la capa de UI puede pasar para pintar una barra única global.
"""
import logging
from typing import Callable, Optional

import numpy as np
import pandas as pd

from procesadores.utilidades import encontrar_columna_por_patron

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[float, str], None]]


def _noop(fraccion: float, texto: str) -> None:  # pragma: no cover
    pass


def procesar_datos_facturacion(df_facturacion: pd.DataFrame) -> pd.DataFrame:
    """Procesamiento optimizado de facturación."""
    if df_facturacion.empty:
        return pd.DataFrame()

    df_facturacion.columns = [
        col.replace("Almacen", "Almacén").replace("Almaçen", "Almacén")
        for col in df_facturacion.columns
    ]

    patrones = {
        "Solicitante": ["solicitante", "solicitud", "cliente solicitante"],
        "Razón Social": ["razón social", "razon social", "nombre cliente"],
        "Destinatario": ["destinatario", "cliente final", "destino"],
        "Fecha": ["fecha", "fecha factura", "fecha documento"],
        "Factura": ["factura", "no. factura", "documento"],
        "Material": ["material", "artículo", "producto"],
        "Texto Material": ["texto material", "descripción", "descripcion"],
        "Cantidad": ["cantidad", "qty", "quantity"],
        "UM": ["um", "unidad medida", "unidad"],
        "Importe": ["importe", "valor", "monto", "total"],
        "Centro": ["centro", "plant", "sede"],
        "Almacén": ["almacén", "almacen", "warehouse"],
        "Doc. Ventas": ["doc. ventas", "documento ventas", "pedido"],
        "Gpo. Vdor.": ["gpo. vdor.", "grupo vendedor", "vendedor"],
        "Grp. Cliente": ["grp. cliente", "grupo cliente", "tipo cliente"],
    }

    mapeo_columnas = {}
    for col_requerida, patrones_list in patrones.items():
        if col_requerida not in df_facturacion.columns:
            for col in df_facturacion.columns:
                if any(p in col.lower() for p in patrones_list):
                    mapeo_columnas[col_requerida] = col
                    break
            if col_requerida not in mapeo_columnas:
                df_facturacion[col_requerida] = ""

    for col_dest, col_orig in mapeo_columnas.items():
        if col_orig in df_facturacion.columns:
            df_facturacion[col_dest] = df_facturacion[col_orig]

    for col in ["Centro", "Material", "Almacén", "Destinatario", "Solicitante"]:
        if col in df_facturacion.columns:
            df_facturacion[col] = (
                df_facturacion[col]
                .astype(str)
                .str.strip()
                .str.replace(r"\.0+$", "", regex=True)
            )

    if "Fecha" in df_facturacion.columns:
        df_facturacion["Fecha"] = pd.to_datetime(
            df_facturacion["Fecha"], dayfirst=True, errors="coerce"
        )

    for col in ["Cantidad", "Importe"]:
        if col in df_facturacion.columns:
            df_facturacion[col] = pd.to_numeric(
                df_facturacion[col], errors="coerce"
            ).fillna(0)

    return df_facturacion


def generar_reporte_consumo(
    df_facturacion: pd.DataFrame,
    reportar_progreso: ProgressCallback = None,
) -> pd.DataFrame:
    """Genera el reporte de consumo histórico a partir de facturación."""
    if df_facturacion.empty:
        return pd.DataFrame()

    cb = reportar_progreso or _noop
    cb(0.05, "Preparando datos de facturación…")

    df_facturacion = df_facturacion.drop_duplicates()

    mask_fecha_valida = df_facturacion["Fecha"].notna()
    df_facturacion = df_facturacion[mask_fecha_valida].copy()

    if df_facturacion.empty:
        return pd.DataFrame()

    df_facturacion["AñoMes"] = df_facturacion["Fecha"].dt.to_period("M")

    mask_precio_valido = (df_facturacion["Cantidad"] > 0) & (
        df_facturacion["Importe"] > 0
    )
    df_facturacion["PrecioUnitario"] = np.where(
        mask_precio_valido,
        df_facturacion["Importe"] / df_facturacion["Cantidad"],
        np.nan,
    )

    mes_actual = pd.Timestamp.now().to_period("M")
    mask_mes_actual = df_facturacion["AñoMes"] == mes_actual
    mask_historico = df_facturacion["AñoMes"] < mes_actual

    cb(0.15, "Agrupando datos…")

    df_ultimo_centro = df_facturacion.sort_values(
        "Fecha", ascending=False
    ).drop_duplicates("Destinatario")[["Destinatario", "Centro", "Fecha"]]
    df_ultimo_centro["Ultima_compra_cliente"] = df_ultimo_centro["Fecha"].dt.strftime(
        "%m/%Y"
    )
    ultimo_centro_dict = df_ultimo_centro.set_index("Destinatario")["Centro"].to_dict()
    ultima_compra_dict = df_ultimo_centro.set_index("Destinatario")[
        "Ultima_compra_cliente"
    ].to_dict()

    df_ultima_fact_dest = df_facturacion.sort_values(
        "Fecha", ascending=False
    ).drop_duplicates("Destinatario")[["Destinatario", "Fecha"]]
    df_ultima_fact_dest["Ultima_facturacion_destinatario"] = df_ultima_fact_dest[
        "Fecha"
    ].dt.strftime("%m/%Y")
    ultima_fact_destinatario_dict = df_ultima_fact_dest.set_index("Destinatario")[
        "Ultima_facturacion_destinatario"
    ].to_dict()

    cb(0.30, "Calculando estadísticas por material…")
    df_historico = df_facturacion[mask_historico]

    df_mes_actual_grouped = (
        df_facturacion[mask_mes_actual]
        .groupby(["Solicitante", "Destinatario", "Material"])
        .agg(consumo_actual=("Cantidad", "sum"))
        .reset_index()
    )

    df_historico_grouped = (
        df_historico.groupby(["Solicitante", "Destinatario", "Material"])
        .agg(
            cantidad_total_historico=("Cantidad", "sum"),
            fecha_min_historico=("Fecha", "min"),
            fecha_max_historico=("Fecha", "max"),
            meses_con_factura=("AñoMes", "nunique"),
            count_facturas=("Fecha", "count"),
        )
        .reset_index()
    )

    df_para_precios = df_facturacion[
        (df_facturacion["Cantidad"] > 0) & (df_facturacion["Importe"] > 0)
    ]
    df_precios_grouped = (
        df_para_precios.groupby(["Solicitante", "Destinatario", "Material"])
        .agg(
            precio_min=(
                "PrecioUnitario",
                lambda x: x[x > 0].min() if (x > 0).any() else 0,
            ),
            precio_max=(
                "PrecioUnitario",
                lambda x: x[x > 0].max() if (x > 0).any() else 0,
            ),
            precio_prom=(
                "PrecioUnitario",
                lambda x: x[x > 0].mean() if (x > 0).any() else 0,
            ),
        )
        .reset_index()
    )

    cb(0.55, "Obteniendo últimos meses facturados…")
    df_facturacion["MesAno_str"] = df_facturacion["AñoMes"].dt.strftime("%m/%Y")
    df_facturacion["MesAno_num"] = (
        df_facturacion["AñoMes"].dt.year * 100 + df_facturacion["AñoMes"].dt.month
    )

    monthly_totals = (
        df_facturacion.groupby(
            ["Solicitante", "Destinatario", "Material", "MesAno_num", "MesAno_str"]
        )
        .agg(
            Cantidad_mes=("Cantidad", "sum"),
            Importe_mes=("Importe", "sum"),
            Fecha_max=("Fecha", "max"),
        )
        .reset_index()
    )

    monthly_totals = monthly_totals.sort_values(
        ["Solicitante", "Destinatario", "Material", "MesAno_num"],
        ascending=[True, True, True, False],
    )
    monthly_totals["orden"] = (
        monthly_totals.groupby(["Solicitante", "Destinatario", "Material"]).cumcount()
        + 1
    )

    df_ultimas_meses = monthly_totals[monthly_totals["orden"] <= 2].copy()
    df_ultimas_pivot = df_ultimas_meses.pivot_table(
        index=["Solicitante", "Destinatario", "Material"],
        columns="orden",
        values=["MesAno_str", "Cantidad_mes", "Importe_mes", "Fecha_max"],
        aggfunc="first",
    )
    df_ultimas_pivot.columns = [
        f"{col[0]}_{col[1]}" for col in df_ultimas_pivot.columns
    ]
    df_ultimas_pivot = df_ultimas_pivot.reset_index()

    df_ultimas_pivot["PrecioUnitario_1"] = np.where(
        df_ultimas_pivot["Cantidad_mes_1"] > 0,
        df_ultimas_pivot["Importe_mes_1"] / df_ultimas_pivot["Cantidad_mes_1"],
        0,
    )
    df_ultimas_pivot["PrecioUnitario_2"] = np.where(
        df_ultimas_pivot["Cantidad_mes_2"] > 0,
        df_ultimas_pivot["Importe_mes_2"] / df_ultimas_pivot["Cantidad_mes_2"],
        0,
    )

    mask_mismos_meses = (
        df_ultimas_pivot["MesAno_str_1"] == df_ultimas_pivot["MesAno_str_2"]
    )
    df_ultimas_pivot.loc[
        mask_mismos_meses,
        [
            "MesAno_str_2",
            "Cantidad_mes_2",
            "Importe_mes_2",
            "PrecioUnitario_2",
            "Fecha_max_2",
        ],
    ] = ["", 0, 0, 0, pd.NaT]

    cb(0.75, "Preparando datos básicos…")
    df_basicos = (
        df_facturacion.sort_values(
            ["Solicitante", "Destinatario", "Material", "Fecha"],
            ascending=[True, True, True, False],
        )
        .groupby(["Solicitante", "Destinatario", "Material"])
        .first()
        .reset_index()[
            [
                "Solicitante",
                "Destinatario",
                "Material",
                "Razón Social",
                "Texto Material",
                "UM",
                "Gpo. Vdor.",
                "Grp. Cliente",
            ]
        ]
    )

    cb(0.85, "Combinando datos…")
    grupos_unicos = df_facturacion[
        ["Solicitante", "Destinatario", "Material"]
    ].drop_duplicates()
    reporte_final = grupos_unicos

    for df_merge in (
        df_basicos,
        df_historico_grouped,
        df_mes_actual_grouped,
        df_precios_grouped,
        df_ultimas_pivot,
    ):
        reporte_final = pd.merge(
            reporte_final,
            df_merge,
            on=["Solicitante", "Destinatario", "Material"],
            how="left",
        )

    reporte_final["Centro"] = reporte_final["Destinatario"].map(ultimo_centro_dict)
    reporte_final["Ultima_compra_cliente"] = reporte_final["Destinatario"].map(
        ultima_compra_dict
    )
    reporte_final["Ultima_facturacion_destinatario"] = reporte_final[
        "Destinatario"
    ].map(ultima_fact_destinatario_dict)

    cb(0.92, "Calculando campos finales…")
    reporte_final["meses_diff_historico"] = (
        reporte_final["fecha_max_historico"].dt.year
        - reporte_final["fecha_min_historico"].dt.year
    ) * 12 + (
        reporte_final["fecha_max_historico"].dt.month
        - reporte_final["fecha_min_historico"].dt.month
    )
    reporte_final["meses_diff_historico"] = reporte_final["meses_diff_historico"].clip(
        lower=1
    )

    reporte_final["Consumo_promedio_mensual"] = (
        (
            reporte_final["cantidad_total_historico"]
            / reporte_final["meses_diff_historico"]
        )
        .fillna(0)
        .astype(int)
    )

    reporte_final["Tendencia"] = (
        (reporte_final["meses_diff_historico"] / reporte_final["meses_con_factura"])
        .fillna(0)
        .round(2)
    )
    reporte_final["Tendencia de cantidad"] = (
        (reporte_final["cantidad_total_historico"] / reporte_final["count_facturas"])
        .fillna(0)
        .round(2)
    )

    reporte_final["Ultimo mes facturacion"] = reporte_final["MesAno_str_1"]
    reporte_final["Penultima_fecha"] = reporte_final["MesAno_str_2"]

    # NUEVO: cálculos basados en Fecha_max_1 (última fact.) y Fecha_max_2 (penúltima)
    _fecha_max_1 = pd.to_datetime(reporte_final.get("Fecha_max_1"), errors="coerce")
    _fecha_max_2 = pd.to_datetime(reporte_final.get("Fecha_max_2"), errors="coerce")

    # Meses ultimo - penultimo: diferencia en meses calendario entre última y
    # penúltima facturación. "N/A" cuando solo hay un mes facturado (NaT en
    # Fecha_max_2, ya sea porque solo existe un mes o porque última y penúltima
    # caen en el mismo mes — caso normalizado a NaT más arriba).
    _diff_up = (
        (_fecha_max_1.dt.year - _fecha_max_2.dt.year) * 12
        + (_fecha_max_1.dt.month - _fecha_max_2.dt.month)
    )
    reporte_final["Meses ultimo - penultimo"] = [
        "N/A" if pd.isna(d) else int(d) for d in _diff_up
    ]

    # Meses ult fac - Fecha act: meses calendario desde la última facturación
    # hasta hoy. "N/A" si no hay fecha de última facturación.
    _hoy = pd.Timestamp.now()
    _diff_act = (
        (_hoy.year - _fecha_max_1.dt.year) * 12
        + (_hoy.month - _fecha_max_1.dt.month)
    )
    reporte_final["Meses ult fac - Fecha act"] = [
        "N/A" if pd.isna(d) else int(d) for d in _diff_act
    ]

    reporte_final = reporte_final.rename(
        columns={
            "consumo_actual": "Consumo_actual",
            "Cantidad_mes_1": "Cantidad ultima",
            "Importe_mes_1": "Importe ultima",
            "PrecioUnitario_1": "Precio_unitario_ultima",
            "Cantidad_mes_2": "Cantidad_penultima",
            "Importe_mes_2": "Importe_penultima",
            "PrecioUnitario_2": "Precio_unitario_penultima",
        }
    )

    for col in [
        "Consumo_actual",
        "Cantidad ultima",
        "Importe ultima",
        "Cantidad_penultima",
        "Importe_penultima",
        "cantidad_total_historico",
        "meses_con_factura",
        "count_facturas",
        "Precio_unitario_ultima",
        "Precio_unitario_penultima",
    ]:
        if col in reporte_final.columns:
            reporte_final[col] = reporte_final[col].fillna(0)

    for col in [
        "Ultimo mes facturacion",
        "Penultima_fecha",
        "Ultima_compra_cliente",
        "Ultima_facturacion_destinatario",
        "Razón Social",
        "Texto Material",
        "UM",
        "Gpo. Vdor.",
        "Grp. Cliente",
        "Centro",
    ]:
        if col in reporte_final.columns:
            reporte_final[col] = reporte_final[col].fillna("")

    columnas_orden = [
        "Centro",
        "Grp. Cliente",
        "Gpo. Vdor.",
        "Solicitante",
        "Destinatario",
        "Razón Social",
        "Material",
        "Texto Material",
        "Ultima_compra_cliente",
        "Ultima_facturacion_destinatario",
        "Consumo_promedio_mensual",
        "Consumo_actual",
        "UM",
        "Tendencia",
        "Tendencia de cantidad",
        "Ultimo mes facturacion",
        "Cantidad ultima",
        "Importe ultima",
        "Precio_unitario_ultima",
        "Penultima_fecha",
        "Cantidad_penultima",
        "Importe_penultima",
        "Precio_unitario_penultima",
        "Meses ultimo - penultimo",
        "Meses ult fac - Fecha act",
        "precio_min",
        "precio_max",
        "precio_prom",
    ]

    for col in columnas_orden:
        if col not in reporte_final.columns:
            if col in [
                "Centro",
                "Grp. Cliente",
                "Gpo. Vdor.",
                "Solicitante",
                "Destinatario",
                "Razón Social",
                "Material",
                "Texto Material",
                "UM",
                "Ultima_facturacion_destinatario",
                "Ultima_compra_cliente",
            ]:
                reporte_final[col] = ""
            else:
                reporte_final[col] = 0

    cb(1.0, "Reporte de consumo listo")
    return reporte_final[columnas_orden]


def calcular_estadisticas_consumo_por_centro_material_almacen(
    df_facturacion: pd.DataFrame,
) -> pd.DataFrame:
    """Estadísticas por Centro/Material/Almacén:
      - Promedio_Consumo_12M: promedio mensual de los últimos 12 meses cerrados
        (no incluye el mes actual, por no estar cerrado).
      - Ultimo_Mes_Consumo / Cantidad_Ultimo_Mes: calculados sobre TODO el
        histórico, sin filtro temporal, para que aparezcan aunque la última
        facturación sea de hace más de un año.
      - Penultimo_Mes_Consumo / Cantidad_Penultimo_Mes: idem (segundo mes más
        reciente con facturación).
    """
    if df_facturacion is None or df_facturacion.empty:
        return pd.DataFrame()

    cols_req = ["Centro", "Material", "Almacén", "Fecha", "Cantidad"]
    for c in cols_req:
        if c not in df_facturacion.columns:
            return pd.DataFrame()

    df = df_facturacion.copy()
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df = df[df["Fecha"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    df["AñoMes"] = df["Fecha"].dt.to_period("M")
    df["MesAno"] = df["Fecha"].dt.strftime("%m/%Y")

    # ── 1) Último y penúltimo mes: sobre TODO el histórico ───────────────────
    # Esto es independiente del filtro de 12 meses: si hay facturación de hace
    # 3 años y nada reciente, igualmente queremos ver esa última compra.
    monthly = (
        df.groupby(["Centro", "Material", "Almacén", "AñoMes", "MesAno"])
        .agg(Cantidad_mes=("Cantidad", "sum"))
        .reset_index()
        .sort_values(
            ["Centro", "Material", "Almacén", "AñoMes"],
            ascending=[True, True, True, False],
        )
    )
    monthly["orden"] = (
        monthly.groupby(["Centro", "Material", "Almacén"]).cumcount() + 1
    )
    monthly_2 = monthly[monthly["orden"] <= 2]
    piv = monthly_2.pivot_table(
        index=["Centro", "Material", "Almacén"],
        columns="orden",
        values=["MesAno", "Cantidad_mes"],
        aggfunc="first",
    )
    if piv.empty:
        return pd.DataFrame()
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv = piv.reset_index().rename(
        columns={
            "MesAno_1": "Ultimo_Mes_Consumo",
            "Cantidad_mes_1": "Cantidad_Ultimo_Mes",
            "MesAno_2": "Penultimo_Mes_Consumo",
            "Cantidad_mes_2": "Cantidad_Penultimo_Mes",
        }
    )

    # ── 2) Promedio últimos 12 meses cerrados ────────────────────────────────
    # Si no hay data reciente para un material, su Promedio_Consumo_12M será 0
    # pero seguimos mostrando la información del último/penúltimo mes.
    mes_actual = pd.Timestamp.now().to_period("M")
    hace_12 = mes_actual - 12
    df_12 = df[(df["AñoMes"] > hace_12) & (df["AñoMes"] < mes_actual)]

    if not df_12.empty:
        df_grp = (
            df_12.groupby(["Centro", "Material", "Almacén"])
            .agg(
                total=("Cantidad", "sum"),
                meses=("AñoMes", "nunique"),
            )
            .reset_index()
        )
        df_grp["Promedio_Consumo_12M"] = (
            df_grp["total"] / df_grp["meses"].clip(lower=1)
        ).round(2)
        df_grp = df_grp[["Centro", "Material", "Almacén", "Promedio_Consumo_12M"]]
    else:
        df_grp = pd.DataFrame(
            columns=["Centro", "Material", "Almacén", "Promedio_Consumo_12M"]
        )

    # ── 3) Combinar: la base es 'piv' (últimos meses de todo el histórico) ───
    # Los materiales sin consumo en los últimos 12 meses quedan con
    # Promedio_Consumo_12M = 0 pero conservan Ultimo_Mes_Consumo.
    result = pd.merge(
        piv,
        df_grp,
        on=["Centro", "Material", "Almacén"],
        how="left",
    )
    result["Promedio_Consumo_12M"] = result["Promedio_Consumo_12M"].fillna(0)
    result = result.rename(columns={"Almacén": "Almacen"})

    for c in ["Ultimo_Mes_Consumo", "Penultimo_Mes_Consumo"]:
        if c in result.columns:
            result[c] = result[c].fillna("")
    for c in ["Cantidad_Ultimo_Mes", "Cantidad_Penultimo_Mes"]:
        if c in result.columns:
            result[c] = result[c].fillna(0)

    return result