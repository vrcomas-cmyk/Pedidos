"""
app.py - Interfaz Streamlit minimalista.

Características:
  - Solo uploads de archivos; NO muestra tablas ni previews.
  - Barra de progreso global con estimación de tiempo restante (ETA).
  - Descarga automática del Excel al terminar (JavaScript + botón fallback).
"""
import base64
import io
import logging
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# Configuración global
pd.options.mode.chained_assignment = None
warnings.filterwarnings(
    "ignore", category=UserWarning, message="Parsing dates in.*%d/%m/%Y.*"
)
warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Imports de módulos propios
from config import FUENTES_DISPONIBLES
from io_loaders import (
    cargar_facturacion,
    cargar_hojas_externas,
    cargar_inventario,
    cargar_pedidos,
)
from procesadores.utilidades import Timer
from procesadores.facturacion import generar_reporte_consumo
from reportes.exportador import exportar_a_excel
from reportes.inventario_por_condicion import generar_inventario_por_condicion
from reportes.sin_sugerencias import generar_resumen_sin_sugerencias_optimizado
from reportes.sug_desde_consumo import generar_sugerencias_desde_reporte_consumo
from reportes.todas_sugerencias import generar_todas_sugerencias
from sugerencias.enriquecimiento import enriquecer_sugerencias_con_consumo


# ==============================================================================
# BARRA DE PROGRESO GLOBAL CON ETA
# ==============================================================================
class ProgresoGlobal:
    """Gestor de progreso global con ETA.

    El proceso se divide en fases con pesos relativos. Cada fase avanza de 0..1
    y el progreso total se pondera. El ETA se estima con base en el tiempo
    transcurrido y el porcentaje completado.
    """

    def __init__(self, fases_pesos: dict):
        """fases_pesos: {nombre_fase: peso_relativo}. La suma no necesita ser 1."""
        self.fases_pesos = fases_pesos
        total = sum(fases_pesos.values())
        self.fases_pct = {k: v / total for k, v in fases_pesos.items()}
        self.fase_actual = None
        self.pct_fase_actual = 0.0
        self.completado = 0.0  # progreso total acumulado [0..1]
        self.t_inicio = time.perf_counter()
        self.bar = st.progress(0.0)
        self.texto = st.empty()
        self.eta = st.empty()

    def iniciar_fase(self, nombre_fase: str):
        # Si hay una fase previa, cerrar a 100% su contribución
        if self.fase_actual is not None:
            self.completado += self.fases_pct[self.fase_actual] * (1 - self.pct_fase_actual)
        self.fase_actual = nombre_fase
        self.pct_fase_actual = 0.0
        self._pintar(f"🔄 {nombre_fase}")

    def actualizar(self, pct_fase: float, texto: str = ""):
        if self.fase_actual is None:
            return
        pct_fase = max(0.0, min(1.0, pct_fase))
        self.pct_fase_actual = pct_fase
        msg = f"🔄 {self.fase_actual}" + (f" — {texto}" if texto else "")
        self._pintar(msg)

    def saltar_fase(self, nombre_fase: str):
        """Marca una fase como omitida (peso igualmente descontado)."""
        if nombre_fase in self.fases_pct:
            self.completado += self.fases_pct[nombre_fase]
            self._pintar(f"⏭️ {nombre_fase} (omitido)")

    def finalizar(self):
        if self.fase_actual is not None:
            self.completado += self.fases_pct[self.fase_actual] * (1 - self.pct_fase_actual)
            self.fase_actual = None
        self.completado = 1.0
        self.bar.progress(1.0)
        elapsed = time.perf_counter() - self.t_inicio
        tiempo_str = f"{elapsed:.1f}s" if elapsed < 60 else f"{elapsed/60:.1f}min"
        self.texto.markdown(f"✅ **Proceso terminado** en {tiempo_str}")
        self.eta.empty()

    def _pintar(self, texto_fase: str):
        total = self.completado
        if self.fase_actual is not None:
            total += self.fases_pct[self.fase_actual] * self.pct_fase_actual
        total = max(0.0, min(1.0, total))
        self.bar.progress(total)

        elapsed = time.perf_counter() - self.t_inicio
        pct_mostrar = total * 100

        # ETA: requiere al menos 2s y 5% para ser razonablemente estable
        if total > 0.05 and elapsed > 2.0:
            total_est = elapsed / total
            restante = max(total_est - elapsed, 0)
            if restante < 60:
                eta_str = f"~{restante:.0f}s restantes"
            elif restante < 3600:
                eta_str = f"~{restante/60:.1f} min restantes"
            else:
                eta_str = f"~{restante/3600:.1f} h restantes"
        else:
            eta_str = "calculando ETA…"

        self.texto.markdown(f"{texto_fase}")
        self.eta.caption(f"{pct_mostrar:.0f}% completado · {eta_str}")


# ==============================================================================
# DESCARGA AUTOMÁTICA (JS + fallback a botón)
# ==============================================================================
def disparar_descarga_automatica(excel_bytes: bytes, filename: str):
    """Dispara una descarga automática del archivo usando JS, con fallback a botón.

    Muestra SIEMPRE el st.download_button como red de seguridad; si el navegador
    bloquea la descarga automática, el usuario puede hacer click manual.
    """
    b64 = base64.b64encode(excel_bytes).decode("utf-8")

    html_js = f"""
    <html>
    <body>
    <script>
    (function() {{
        try {{
            var a = document.createElement('a');
            a.href = "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}";
            a.download = "{filename}";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }} catch(e) {{
            console.log('Descarga automática bloqueada:', e);
        }}
    }})();
    </script>
    <p style="font-family: sans-serif; color: #666; font-size: 12px; margin: 4px;">
      Si la descarga no inicia automáticamente, usa el botón de abajo.
    </p>
    </body>
    </html>
    """
    components.html(html_js, height=40)

    # Fallback: botón manual siempre visible
    st.download_button(
        label=f"📥 Descargar {filename}",
        data=excel_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_fallback",
        use_container_width=True,
    )


# ==============================================================================
# UI
# ==============================================================================
st.set_page_config(page_title="Sugeridor de Materiales", layout="wide")
st.title("📊 Sugeridor de Materiales - Asignación 1:1")
st.caption("Carga los archivos y el reporte se generará y descargará automáticamente.")

# Sidebar con configuración mínima
st.sidebar.header("Configuración")
fuentes_activas = st.sidebar.multiselect(
    "Fuentes a considerar:",
    options=FUENTES_DISPONIBLES,
    default=FUENTES_DISPONIBLES,
    help="Incluye 'Revision' — nueva pestaña con columna Status",
)

st.sidebar.header("Reportes a generar")
gen_todas = st.sidebar.checkbox("Todas las Sugerencias", value=True)
gen_resumen = st.sidebar.checkbox("Resumen Sin Sugerencias", value=True)
gen_reporte_consumo = st.sidebar.checkbox("Reporte de Consumo", value=False)
gen_sug_consumo = st.sidebar.checkbox(
    "Sugerencias desde Consumo",
    value=False,
    help="Requiere también 'Reporte de Consumo' y archivo de facturación.",
)

# Uploads
st.header("Archivos de entrada")
col1, col2 = st.columns(2)
with col1:
    archivo_principal = st.file_uploader(
        "1. Pedidos (hoja 'Seg pedidos' o 'sheets1')",
        type=["xlsx", "xls"],
        key="principal",
    )
    archivo_externas = st.file_uploader(
        "3. Hojas externas (Corta caducidad, Lento mov, Revision, etc.)",
        type=["xlsx", "xls"],
        key="externas",
    )
with col2:
    archivo_inventario = st.file_uploader(
        "2. Inventario (hoja 'Inventario' o 'sheets1')",
        type=["xlsx", "xls"],
        key="inventario",
    )
    _necesita_facturacion = gen_reporte_consumo or gen_sug_consumo
    if _necesita_facturacion:
        archivo_facturacion = st.file_uploader(
            "4. Facturación (hoja 'Facturacion' o 'sheets1')",
            type=["xlsx", "xls"],
            key="facturacion",
        )
    else:
        archivo_facturacion = None

# Verificar archivos mínimos
archivos_ok = (
    archivo_principal
    and archivo_inventario
    and archivo_externas
    and (not _necesita_facturacion or (_necesita_facturacion and archivo_facturacion))
)

if not archivos_ok:
    st.info(
        "⏳ Sube los archivos requeridos para comenzar el procesamiento automático."
    )
    st.stop()

# ==============================================================================
# PROCESAMIENTO
# ==============================================================================
timer_total = Timer()

# Definir fases con pesos relativos (basados en tiempos típicos observados)
fases_pesos = {
    "Cargando archivos": 10,
}
if gen_reporte_consumo or gen_sug_consumo:
    fases_pesos["Generando Reporte de Consumo"] = 15
if gen_todas or gen_resumen:
    fases_pesos["Generando Todas las Sugerencias"] = 35
if gen_resumen:
    fases_pesos["Generando Resumen Sin Sugerencias"] = 10
    fases_pesos["Enriqueciendo sugerencias"] = 5
if gen_sug_consumo:
    fases_pesos["Generando Sug Reporte Consumo"] = 20
fases_pesos["Generando Inventario por condicion"] = 3
fases_pesos["Generando archivo Excel"] = 5

progreso = ProgresoGlobal(fases_pesos)

try:
    # ── FASE 1: Carga ────────────────────────────────────────────────────────
    progreso.iniciar_fase("Cargando archivos")

    def _t_pedidos():
        return cargar_pedidos(archivo_principal)

    def _t_inventario():
        return cargar_inventario(archivo_inventario)

    def _t_externas():
        return cargar_hojas_externas(archivo_externas)

    def _t_facturacion():
        if _necesita_facturacion:
            return cargar_facturacion(archivo_facturacion)
        return None, None

    tareas = {
        "pedidos": _t_pedidos,
        "inventario": _t_inventario,
        "externas": _t_externas,
        "facturacion": _t_facturacion,
    }
    resultados = {}
    errores = {}

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fn): k for k, fn in tareas.items()}
        completados = 0
        for fut in as_completed(futures):
            key = futures[fut]
            completados += 1
            progreso.actualizar(completados / len(tareas), f"{key}")
            try:
                resultados[key] = fut.result()
            except Exception as e:
                errores[key] = str(e)

    if "pedidos" in errores:
        st.error(f"Error cargando pedidos: {errores['pedidos']}")
        st.stop()
    if "inventario" in errores:
        st.error(f"Error cargando inventario: {errores['inventario']}")
        st.stop()
    if "externas" in errores:
        st.error(f"Error cargando externas: {errores['externas']}")
        st.stop()

    pedidos_df, _ = resultados["pedidos"]
    inventario_df, _ = resultados["inventario"]
    hojas_externas = resultados["externas"]
    if _necesita_facturacion:
        if "facturacion" in errores:
            st.error(f"Error cargando facturación: {errores['facturacion']}")
            st.stop()
        df_facturacion_procesado, _ = resultados["facturacion"]
    else:
        df_facturacion_procesado = None

    df_revision = hojas_externas.get("Revision")

    progreso.actualizar(1.0, "archivos listos")

    # ── FASE 2: Reporte de Consumo ───────────────────────────────────────────
    df_reporte_consumo = None
    if gen_reporte_consumo or gen_sug_consumo:
        progreso.iniciar_fase("Generando Reporte de Consumo")
        if df_facturacion_procesado is not None and not df_facturacion_procesado.empty:
            df_reporte_consumo = generar_reporte_consumo(
                df_facturacion_procesado,
                reportar_progreso=lambda p, t: progreso.actualizar(p, t),
            )
        else:
            progreso.actualizar(1.0, "sin facturación")
    # Si no se genera reporte de consumo pero la fase existe (no debería), saltar

    # ── FASE 3: Todas las Sugerencias ────────────────────────────────────────
    df_todas_sugerencias = None
    if gen_todas or gen_resumen:
        progreso.iniciar_fase("Generando Todas las Sugerencias")
        df_todas_sugerencias = generar_todas_sugerencias(
            pedidos_df,
            hojas_externas,
            fuentes_activas,
            inventario_df,
            reportar_progreso=lambda p, t: progreso.actualizar(p, t),
        )

    # ── FASE 4: Resumen Sin Sugerencias ──────────────────────────────────────
    df_resumen_sin_sugerencias = None
    if gen_resumen:
        progreso.iniciar_fase("Generando Resumen Sin Sugerencias")
        df_resumen_sin_sugerencias = generar_resumen_sin_sugerencias_optimizado(
            df_todas_sugerencias,
            inventario_df,
            df_todas_sugerencias,
            df_facturacion_procesado,
            df_revision=df_revision,  # NUEVO: pasa la hoja Revision para Status
        )
        progreso.actualizar(1.0, "resumen listo")

    # ── FASE 5: Enriquecimiento ──────────────────────────────────────────────
    if gen_resumen and df_todas_sugerencias is not None and not df_todas_sugerencias.empty:
        progreso.iniciar_fase("Enriqueciendo sugerencias")
        df_todas_sugerencias = enriquecer_sugerencias_con_consumo(
            df_todas_sugerencias,
            df_resumen_sin_sugerencias if df_resumen_sin_sugerencias is not None else pd.DataFrame(),
            df_facturacion=df_facturacion_procesado,
            df_reporte_consumo=df_reporte_consumo,
        )
        progreso.actualizar(1.0, "enriquecimiento listo")

    # ── FASE 6: Sug Reporte Consumo ──────────────────────────────────────────
    df_sug_consumo = None
    if gen_sug_consumo and df_reporte_consumo is not None and not df_reporte_consumo.empty:
        progreso.iniciar_fase("Generando Sug Reporte Consumo")
        df_sug_consumo = generar_sugerencias_desde_reporte_consumo(
            df_reporte_consumo,
            hojas_externas,
            fuentes_activas,
            inventario_df,
            df_resumen=df_resumen_sin_sugerencias,
            reportar_progreso=lambda p, t: progreso.actualizar(p, t),
        )

    # ── FASE 6b: Inventario por condicion ────────────────────────────────────
    # Requiere hoja externa 'Revision2' (con columnas Material, Texto breve, Status)
    # y opcionalmente 'Corta caducidad' para los detalles de lote.
    df_inventario_por_condicion = None
    df_detalle_lotes_cc = None
    df_revision2 = hojas_externas.get("Revision2")
    df_corta_caducidad = hojas_externas.get("Corta caducidad")
    if (
        df_revision2 is not None
        and not df_revision2.empty
    ) or (
        df_corta_caducidad is not None
        and not df_corta_caducidad.empty
    ):
        progreso.iniciar_fase("Generando Inventario por condicion")
        df_inventario_por_condicion, df_detalle_lotes_cc = (
            generar_inventario_por_condicion(
                df_revision2=df_revision2,
                df_corta_caducidad=df_corta_caducidad,
                inventario_df=inventario_df,
            )
        )
        progreso.actualizar(1.0, "inventario por condicion listo")
    else:
        progreso.saltar_fase("Generando Inventario por condicion")

    # ── FASE 7: Exportación ──────────────────────────────────────────────────
    progreso.iniciar_fase("Generando archivo Excel")
    excel_bytes = exportar_a_excel(
        df_todas_sugerencias if gen_todas else None,
        df_resumen_sin_sugerencias if gen_resumen else None,
        df_reporte_consumo if gen_reporte_consumo else None,
        df_sug_consumo if gen_sug_consumo else None,
        df_inventario_por_condicion=df_inventario_por_condicion,
        df_detalle_lotes_cc=df_detalle_lotes_cc,
    )
    progreso.actualizar(1.0, "archivo listo")

    # Finalizar
    progreso.finalizar()

    # ── Métricas resumen (sin tablas) ────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    if df_todas_sugerencias is not None and not df_todas_sugerencias.empty:
        m1.metric("Todas las Sugerencias", f"{len(df_todas_sugerencias):,} líneas")
    if df_resumen_sin_sugerencias is not None and not df_resumen_sin_sugerencias.empty:
        m2.metric("Resumen Sin Sugerencias", f"{len(df_resumen_sin_sugerencias):,} filas")
    if df_reporte_consumo is not None and not df_reporte_consumo.empty:
        m3.metric("Reporte de Consumo", f"{len(df_reporte_consumo):,} filas")
    if df_sug_consumo is not None and not df_sug_consumo.empty:
        m4.metric("Sug Reporte Consumo", f"{len(df_sug_consumo):,} líneas")

    # ── Descarga automática ──────────────────────────────────────────────────
    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Reporte_Completo_{timestamp}.xlsx"

    st.success(f"✅ Reporte generado ({len(excel_bytes) / 1024:.0f} KB)")
    disparar_descarga_automatica(excel_bytes, filename)

except Exception as e:
    st.error(f"❌ Error: {e}")
    logger.error(f"Error detallado: {e}", exc_info=True)
