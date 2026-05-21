"""
sugerencias/motor_optimizado.py - Motor compartido para 'Todas las Sugerencias'
y 'Sugerencias desde Reporte de Consumo'.

Novedades respecto al original:
  1. Nueva fuente 'Revision' que funciona como Lento mov pero etiqueta la Fuente
     con 'Revision (Status)' usando el valor de la columna Status. Un material
     puede tener múltiples Status; se generan múltiples templates que luego
     consolidación fusiona en 'Revision (Status1, Status2)'.
  2. Template incluye campo 'meses_vigencia_lote' calculado a partir de la
     fecha de caducidad.
"""
import logging
from typing import Dict, List, Optional

import pandas as pd

from config import Columnas, FUENTES_COMBINABLES_CON_OTRAS
from procesadores.utilidades import (
    calcular_meses_vigencia,
    formatear_fecha_caducidad,
)

logger = logging.getLogger(__name__)


# =============================================================================
# FASE A — Pre-indexado
# =============================================================================
def build_inv_caches(inventario_df: pd.DataFrame) -> dict:
    """Construye todos los dicts de inventario necesarios para lookups O(1)."""
    caches: dict = {
        "inv_centro_alm": {},    # (centro, mat) → {alm: libre}
        "transito": {},          # (centro, mat) → {alm: transito}
        "inv_filtrado_mat": {},  # mat → {centro: suma_filt}
        "disp_1031": {},         # (mat, alm) → libre en centro 1031
    }

    if inventario_df is None or inventario_df.empty:
        return caches

    _inv = inventario_df.copy()
    _inv["Centro"] = _inv["Centro"].astype(str).str.strip()
    _inv["Material"] = _inv["Material"].astype(str).str.strip()
    _inv["Almacén"] = _inv["Almacén"].astype(str).str.strip()
    _inv["Libre Utilización"] = pd.to_numeric(
        _inv.get("Libre Utilización", 0), errors="coerce"
    ).fillna(0.0)
    _inv["Cant. en Tránsito"] = pd.to_numeric(
        _inv.get("Cant. en Tránsito", 0), errors="coerce"
    ).fillna(0.0)

    grp = _inv.groupby(["Centro", "Material", "Almacén"], sort=False)
    for (centro, mat, alm), g in grp:
        key_cm = (centro, mat)
        libre = float(g["Libre Utilización"].sum())
        trans = float(g["Cant. en Tránsito"].sum())
        caches["inv_centro_alm"].setdefault(key_cm, {})[alm] = libre
        caches["transito"].setdefault(key_cm, {})[alm] = trans

    _filt = _inv[_inv["Almacén"].isin(["1030", "1031", "1060"])]
    for (mat, centro), g in _filt.groupby(["Material", "Centro"], sort=False):
        caches["inv_filtrado_mat"].setdefault(mat, {})[centro] = float(
            g["Libre Utilización"].sum()
        )

    _c1031 = _inv[_inv["Centro"] == "1031"]
    for (mat, alm), g in _c1031.groupby(["Material", "Almacén"], sort=False):
        caches["disp_1031"][(mat, alm)] = float(g["Libre Utilización"].sum())

    return caches


def build_fuentes_index(
    hojas_externas: Dict[str, pd.DataFrame],
    fuentes_activas: List[str],
) -> Dict[str, Dict[str, List[dict]]]:
    """Convierte cada hoja externa en un índice {material: [row_dicts]}."""
    idx: Dict[str, Dict[str, List[dict]]] = {}
    for fuente in fuentes_activas:
        if fuente not in hojas_externas:
            continue
        df_f = hojas_externas[fuente]
        if df_f.empty or "Material" not in df_f.columns:
            continue
        _df = df_f.copy()
        _df["Material"] = _df["Material"].astype(str).str.strip()
        idx[fuente] = {}
        for mat, grp in _df.groupby("Material", sort=False):
            idx[fuente][mat] = grp.to_dict("records")
    return idx


# =============================================================================
# FASE B — Buscar templates por par único (Material, Centro)
# =============================================================================
def buscar_templates_sugerencia(
    material: str,
    fuentes_activas: List[str],
    idx_fuentes: Dict[str, Dict[str, List[dict]]],
    inv_caches: dict,
) -> List[dict]:
    """Construye la lista de templates de sugerencia para un material dado."""
    templates: List[dict] = []
    if not material:
        return templates

    for fuente in fuentes_activas:
        if fuente not in idx_fuentes:
            continue

        # ── SUSTITUTO ────────────────────────────────────────────────────
        if fuente == "Sustituto":
            templates.extend(
                _templates_sustituto(material, fuentes_activas, idx_fuentes, inv_caches)
            )

        # ── LENTO MOV ────────────────────────────────────────────────────
        elif fuente == "Lento mov":
            templates.extend(
                _templates_lento_mov(material, fuentes_activas, idx_fuentes, inv_caches)
            )

        # ── REVISION (NUEVO) ─────────────────────────────────────────────
        elif fuente == "Revision":
            templates.extend(
                _templates_revision(material, fuentes_activas, idx_fuentes, inv_caches)
            )

        # ── CORTA CADUCIDAD / COSMOPARK / PNC / CADUCO ───────────────────
        else:
            for match in idx_fuentes.get(fuente, {}).get(material, []):
                disp = float(match.get("CantidadDisp", 0) or 0)
                if disp <= 0:
                    continue
                fecha_cad = formatear_fecha_caducidad(match.get("FechaCaducidad", ""))
                templates.append({
                    "fuente": fuente,
                    "material_sugerido": material,
                    "descripcion_sugerida": str(match.get("Descripcion", "") or ""),
                    "centro_sugerido": str(match.get("Centro", "") or "").strip(),
                    "almacen_sugerido": str(match.get("Almacén", "") or "").strip(),
                    "disponible": disp,
                    "lote": str(match.get("Lote", "") or "").strip(),
                    "fecha_caducidad": fecha_cad,
                    "meses_vigencia_lote": calcular_meses_vigencia(fecha_cad),
                    "material_inv_key": material,
                })

    return templates


def _templates_sustituto(
    material: str,
    fuentes_activas: List[str],
    idx_fuentes: dict,
    inv_caches: dict,
) -> List[dict]:
    """Genera templates para la fuente Sustituto."""
    templates = []
    otras = [
        f for f in fuentes_activas if f not in FUENTES_COMBINABLES_CON_OTRAS
    ]

    for s_row in idx_fuentes.get("Sustituto", {}).get(material, []):
        mat_sust = str(s_row.get("Material sustituto", "") or "").strip()
        desc_sust = str(s_row.get("Texto material sustituto", "") or "")
        if not mat_sust:
            continue

        encontrado = False
        for otra in otras:
            for om in idx_fuentes.get(otra, {}).get(mat_sust, []):
                disp = float(om.get("CantidadDisp", 0) or 0)
                if disp <= 0:
                    continue
                encontrado = True
                fecha_cad = formatear_fecha_caducidad(om.get("FechaCaducidad", ""))
                templates.append({
                    "fuente": f"Sustituto/{otra}",
                    "material_sugerido": mat_sust,
                    "descripcion_sugerida": desc_sust,
                    "centro_sugerido": str(om.get("Centro", "") or "").strip(),
                    "almacen_sugerido": str(om.get("Almacén", "") or "").strip(),
                    "disponible": disp,
                    "lote": str(om.get("Lote", "") or "").strip(),
                    "fecha_caducidad": fecha_cad,
                    "meses_vigencia_lote": calcular_meses_vigencia(fecha_cad),
                    "material_inv_key": mat_sust,
                })

        if not encontrado:
            disp_sust = sum(
                inv_caches["inv_filtrado_mat"].get(mat_sust, {}).values()
            )
            if disp_sust > 0:
                templates.append({
                    "fuente": "Sustituto",
                    "material_sugerido": mat_sust,
                    "descripcion_sugerida": desc_sust,
                    "centro_sugerido": "",
                    "almacen_sugerido": "",
                    "disponible": disp_sust,
                    "lote": "",
                    "fecha_caducidad": "",
                    "meses_vigencia_lote": "",
                    "material_inv_key": mat_sust,
                })

    return templates


def _templates_lento_mov(
    material: str,
    fuentes_activas: List[str],
    idx_fuentes: dict,
    inv_caches: dict,
) -> List[dict]:
    """Genera templates para la fuente Lento mov."""
    templates = []
    if not idx_fuentes.get("Lento mov", {}).get(material):
        return templates

    otras = [
        f for f in fuentes_activas if f not in FUENTES_COMBINABLES_CON_OTRAS
    ]
    encontrado = False

    for otra in otras:
        if encontrado:
            break
        added_any = False
        for om in idx_fuentes.get(otra, {}).get(material, []):
            disp = float(om.get("CantidadDisp", 0) or 0)
            if disp <= 0:
                continue
            added_any = True
            fecha_cad = formatear_fecha_caducidad(om.get("FechaCaducidad", ""))
            templates.append({
                "fuente": f"Lento mov/{otra}",
                "material_sugerido": material,
                "descripcion_sugerida": "",
                "centro_sugerido": str(om.get("Centro", "") or "").strip(),
                "almacen_sugerido": str(om.get("Almacén", "") or "").strip(),
                "disponible": disp,
                "lote": str(om.get("Lote", "") or "").strip(),
                "fecha_caducidad": fecha_cad,
                "meses_vigencia_lote": calcular_meses_vigencia(fecha_cad),
                "material_inv_key": material,
            })
        if added_any:
            encontrado = True

    if not encontrado:
        disp_lm = sum(inv_caches["inv_filtrado_mat"].get(material, {}).values())
        if disp_lm > 0:
            templates.append({
                "fuente": "Lento mov",
                "material_sugerido": material,
                "descripcion_sugerida": "",
                "centro_sugerido": "",
                "almacen_sugerido": "",
                "disponible": disp_lm,
                "lote": "",
                "fecha_caducidad": "",
                "meses_vigencia_lote": "",
                "material_inv_key": material,
            })

    return templates


def _templates_revision(
    material: str,
    fuentes_activas: List[str],
    idx_fuentes: dict,
    inv_caches: dict,
) -> List[dict]:
    """Genera templates para la fuente Revision.

    Funciona como Lento mov pero etiqueta cada coincidencia con 'Revision (Status)'.
    Cuando un material tiene varios Status en la hoja, se generan múltiples
    templates; la consolidación final fusionará en 'Revision (Status1, Status2)'.
    """
    templates = []
    rows_revision = idx_fuentes.get("Revision", {}).get(material, [])
    if not rows_revision:
        return templates

    # Extraer la lista de Status únicos para este material
    statuses = []
    descripcion_revision = ""
    for row in rows_revision:
        st_val = str(row.get("Status", "") or "").strip()
        if st_val and st_val not in statuses:
            statuses.append(st_val)
        if not descripcion_revision:
            descripcion_revision = str(row.get("Descripcion", "") or "")

    if not statuses:
        statuses = [""]  # Al menos un elemento para crear un template

    otras = [
        f for f in fuentes_activas if f not in FUENTES_COMBINABLES_CON_OTRAS
    ]

    for status in statuses:
        etiqueta_rev = f"Revision ({status})" if status else "Revision"

        encontrado = False
        for otra in otras:
            if encontrado:
                break
            added_any = False
            for om in idx_fuentes.get(otra, {}).get(material, []):
                disp = float(om.get("CantidadDisp", 0) or 0)
                if disp <= 0:
                    continue
                added_any = True
                fecha_cad = formatear_fecha_caducidad(om.get("FechaCaducidad", ""))
                templates.append({
                    "fuente": f"{etiqueta_rev}/{otra}",
                    "material_sugerido": material,
                    "descripcion_sugerida": descripcion_revision,
                    "centro_sugerido": str(om.get("Centro", "") or "").strip(),
                    "almacen_sugerido": str(om.get("Almacén", "") or "").strip(),
                    "disponible": disp,
                    "lote": str(om.get("Lote", "") or "").strip(),
                    "fecha_caducidad": fecha_cad,
                    "meses_vigencia_lote": calcular_meses_vigencia(fecha_cad),
                    "material_inv_key": material,
                })
            if added_any:
                encontrado = True

        if not encontrado:
            disp_rev = sum(inv_caches["inv_filtrado_mat"].get(material, {}).values())
            if disp_rev > 0:
                templates.append({
                    "fuente": etiqueta_rev,
                    "material_sugerido": material,
                    "descripcion_sugerida": descripcion_revision,
                    "centro_sugerido": "",
                    "almacen_sugerido": "",
                    "disponible": disp_rev,
                    "lote": "",
                    "fecha_caducidad": "",
                    "meses_vigencia_lote": "",
                    "material_inv_key": material,
                })

    return templates


# =============================================================================
# FASE C — Ensamblar líneas
# =============================================================================
def montar_linea_pedido(
    pedido: pd.Series,
    template: Optional[dict],
    inv_caches: dict,
) -> dict:
    """Ensambla una línea de 'Todas las Sugerencias' con lookups O(1)."""
    centro = str(pedido.get("Centro", "") or "").strip()
    material = str(pedido.get("Material", "") or "").strip()

    if template is not None:
        mat_inv = template["material_inv_key"]
        fuente_val = template["fuente"]
        mat_sug = template["material_sugerido"]
        desc_sug = template["descripcion_sugerida"]
        centro_sug = template["centro_sugerido"]
        alm_sug = template["almacen_sugerido"]
        disponible = template["disponible"]
        lote_val = template["lote"]
        fec_cad = template["fecha_caducidad"]
        vigencia = template.get("meses_vigencia_lote", "")
    else:
        mat_inv = material
        fuente_val = ""
        mat_sug = ""
        desc_sug = ""
        centro_sug = ""
        alm_sug = ""
        disponible = 0.0
        lote_val = ""
        fec_cad = ""
        vigencia = ""

    inv_alm = inv_caches["inv_centro_alm"].get((centro, mat_inv), {})
    inv_1030 = inv_alm.get("1030", 0.0)
    inv_1031 = inv_alm.get("1031", 0.0)
    inv_1032 = inv_alm.get("1032", 0.0)
    inv_1060 = inv_alm.get("1060", 0.0)

    tr = inv_caches["transito"].get((centro, mat_inv), {})
    tr_total = sum(tr.values())

    disp_1031_1030 = inv_caches["disp_1031"].get((mat_inv, "1030"), 0.0)
    disp_1031_1032 = inv_caches["disp_1031"].get((mat_inv, "1032"), 0.0)

    inv_por_centro = inv_caches["inv_filtrado_mat"].get(mat_inv, {})

    pendiente = float(pedido.get("Pendiente", 0) or 0)
    cantidad_ofertar = (
        min(pendiente, disponible)
        if (template is not None and pendiente > 0)
        else 0.0
    )

    bloqueado_val = ""
    if str(pedido.get("Sts. Créd.", "") or "").strip() == "B":
        bloqueado_val = "Crédito"
    bloqueo_ent = str(pedido.get("Bloqueo Ent.", "") or "").strip()
    if bloqueo_ent not in ("", "nan"):
        bloqueado_val = "Detenido por ambos" if bloqueado_val else "Detenido"

    return {
        Columnas.GRUPO_CLIENTE: str(pedido.get("Gpo. Cte.", "") or "").strip(),
        Columnas.FECHA: pedido.get("Fecha", ""),
        Columnas.PEDIDO: pedido.get("Pedido", ""),
        Columnas.GRUPO_VENDEDOR: pedido.get("Gpo.Vdor.", ""),
        Columnas.SOLICITANTE: pedido.get("Solicitante", ""),
        Columnas.DESTINATARIO: pedido.get("Destinatario", ""),
        Columnas.RAZON_SOCIAL: str(pedido.get("Razón Social", "") or ""),
        Columnas.CENTRO_PEDIDO: centro,
        Columnas.ALMACEN: str(pedido.get("Almacén", "") or "").strip(),
        Columnas.MATERIAL_SOLICITADO: material,
        Columnas.MATERIAL_BASE: material,
        Columnas.DESCRIPCION_SOLICITADA: str(pedido.get("Texto Material", "") or ""),
        Columnas.CANTIDAD_PEDIDO: pedido.get("Cantidad", ""),
        Columnas.CANTIDAD_PENDIENTE: pendiente,
        Columnas.CANTIDAD_OFERTAR: cantidad_ofertar,
        Columnas.PRECIO: pedido.get("Precio", 0),
        Columnas.FUENTE: fuente_val,
        Columnas.MATERIAL_SUGERIDO: mat_sug,
        Columnas.DESCRIPCION_SUGERIDA: desc_sug,
        Columnas.CENTRO_SUGERIDO: centro_sug,
        Columnas.ALMACEN_SUGERIDO: alm_sug,
        Columnas.DISPONIBLE: disponible,
        Columnas.LOTE: lote_val,
        Columnas.FECHA_CADUCIDAD: fec_cad,
        Columnas.MESES_VIGENCIA_LOTE: vigencia,  # NUEVA COLUMNA
        Columnas.CENTRO_INV: centro,
        Columnas.INV_1030: inv_1030,
        Columnas.INV_1031: inv_1031,
        Columnas.INV_1032: inv_1032,
        Columnas.INV_1060: inv_1060,
        Columnas.MESES_INVENTARIO: 0.0,
        Columnas.PROMEDIO_CONSUMO_12M: 0.0,
        Columnas.CONSUMO_DESTINATARIO_12M: 0.0,
        Columnas.CANT_TRANSITO: tr_total,
        Columnas.CANT_TRANSITO_1030: tr.get("1030", 0.0),
        Columnas.CANT_TRANSITO_1031: tr.get("1031", 0.0),
        Columnas.CANT_TRANSITO_1032: tr.get("1032", 0.0),
        Columnas.DISP_1031_1030: disp_1031_1030,
        Columnas.DISP_1031_1032: disp_1031_1032,
        Columnas.INV_1001: inv_por_centro.get("1001", 0.0),
        Columnas.INV_1003: inv_por_centro.get("1003", 0.0),
        Columnas.INV_1004: inv_por_centro.get("1004", 0.0),
        Columnas.INV_1017: inv_por_centro.get("1017", 0.0),
        Columnas.INV_1018: inv_por_centro.get("1018", 0.0),
        Columnas.INV_1022: inv_por_centro.get("1022", 0.0),
        Columnas.INV_1036: inv_por_centro.get("1036", 0.0),
        Columnas.BLOQUEADO: bloqueado_val,
    }


def montar_linea_rc(
    pedido_fields: dict,
    template: Optional[dict],
    inv_caches: dict,
    rc_row_all: Optional[dict] = None,
) -> dict:
    """Ensambla una línea para 'Sugerencias desde Reporte de Consumo'."""
    centro = pedido_fields["centro"]
    material = pedido_fields["material"]
    rc = rc_row_all or {}

    if template is not None:
        mat_inv = template["material_inv_key"]
        fuente_val = template["fuente"]
        mat_sug = template["material_sugerido"]
        desc_sug = template["descripcion_sugerida"]
        centro_sug = template["centro_sugerido"]
        alm_sug = template["almacen_sugerido"]
        disponible = template["disponible"]
        lote_val = template["lote"]
        fec_cad = template["fecha_caducidad"]
        vigencia = template.get("meses_vigencia_lote", "")
    else:
        mat_inv = material
        fuente_val = ""
        mat_sug = ""
        desc_sug = ""
        centro_sug = ""
        alm_sug = ""
        disponible = 0.0
        lote_val = ""
        fec_cad = ""
        vigencia = ""

    inv_alm = inv_caches["inv_centro_alm"].get((centro, mat_inv), {})
    inv_1030 = inv_alm.get("1030", 0.0)
    inv_1031 = inv_alm.get("1031", 0.0)
    inv_1032 = inv_alm.get("1032", 0.0)
    inv_1060 = inv_alm.get("1060", 0.0)

    tr = inv_caches["transito"].get((centro, mat_inv), {})
    tr_total = sum(tr.values())

    disp_1031_1030 = inv_caches["disp_1031"].get((mat_inv, "1030"), 0.0)
    disp_1031_1032 = inv_caches["disp_1031"].get((mat_inv, "1032"), 0.0)

    inv_por_centro = inv_caches["inv_filtrado_mat"].get(mat_inv, {})

    pendiente = pedido_fields["pendiente"]
    cantidad_ofertar = (
        min(pendiente, disponible) if (template is not None and pendiente > 0) else 0.0
    )

    def _s(key, default=""):
        return str(rc.get(key, default) or default).strip()

    def _f(key, default=0.0):
        try:
            return float(rc.get(key, default) or default)
        except (ValueError, TypeError):
            return float(default)

    return {
        "Centro": centro,
        "Grp. Cliente": _s("Grp. Cliente"),
        "Gpo. Vdor.": _s("Gpo. Vdor."),
        "Solicitante": _s("Solicitante"),
        "Destinatario": _s("Destinatario"),
        "Razón Social": _s("Razón Social"),
        "Material": material,
        "Texto Material": _s("Texto Material"),
        "Ultima_compra_cliente": _s("Ultima_compra_cliente"),
        "Ultima_facturacion_destinatario": _s("Ultima_facturacion_destinatario"),
        "Consumo_promedio_mensual": pedido_fields["pendiente"],
        "Consumo_actual": _f("Consumo_actual"),
        "UM": _s("UM"),
        "Tendencia": _f("Tendencia"),
        "Tendencia de cantidad": _f("Tendencia de cantidad"),
        "Ultimo mes facturacion": _s("Ultimo mes facturacion"),
        "Cantidad ultima": pedido_fields["cantidad"],
        "Importe ultima": _f("Importe ultima"),
        "Precio_unitario_ultima": pedido_fields["precio"],
        "Penultima_fecha": _s("Penultima_fecha"),
        "Cantidad_penultima": _f("Cantidad_penultima"),
        "Importe_penultima": _f("Importe_penultima"),
        "Precio_unitario_penultima": _f("Precio_unitario_penultima"),
        "precio_min": _f("precio_min"),
        "precio_max": _f("precio_max"),
        "precio_prom": _f("precio_prom"),
        # Sugerencia
        Columnas.FUENTE: fuente_val,
        Columnas.MATERIAL_SUGERIDO: mat_sug,
        Columnas.DESCRIPCION_SUGERIDA: desc_sug,
        Columnas.CENTRO_SUGERIDO: centro_sug,
        Columnas.ALMACEN_SUGERIDO: alm_sug,
        Columnas.DISPONIBLE: disponible,
        Columnas.LOTE: lote_val,
        Columnas.FECHA_CADUCIDAD: fec_cad,
        Columnas.MESES_VIGENCIA_LOTE: vigencia,  # NUEVA COLUMNA
        Columnas.CENTRO_INV: centro,
        Columnas.INV_1030: inv_1030,
        Columnas.INV_1031: inv_1031,
        Columnas.INV_1032: inv_1032,
        Columnas.INV_1060: inv_1060,
        Columnas.MESES_INVENTARIO: 0.0,
        Columnas.PROMEDIO_CONSUMO_12M: 0.0,
        Columnas.CONSUMO_DESTINATARIO_12M: 0.0,
        Columnas.CANT_TRANSITO: tr_total,
        Columnas.CANT_TRANSITO_1030: tr.get("1030", 0.0),
        Columnas.CANT_TRANSITO_1031: tr.get("1031", 0.0),
        Columnas.CANT_TRANSITO_1032: tr.get("1032", 0.0),
        Columnas.DISP_1031_1030: disp_1031_1030,
        Columnas.DISP_1031_1032: disp_1031_1032,
        Columnas.INV_1001: inv_por_centro.get("1001", 0.0),
        Columnas.INV_1003: inv_por_centro.get("1003", 0.0),
        Columnas.INV_1004: inv_por_centro.get("1004", 0.0),
        Columnas.INV_1017: inv_por_centro.get("1017", 0.0),
        Columnas.INV_1018: inv_por_centro.get("1018", 0.0),
        Columnas.INV_1022: inv_por_centro.get("1022", 0.0),
        Columnas.INV_1036: inv_por_centro.get("1036", 0.0),
        # Alias internos
        Columnas.CENTRO_PEDIDO: centro,
        Columnas.MATERIAL_SOLICITADO: material,
        Columnas.ALMACEN: "",
    }
