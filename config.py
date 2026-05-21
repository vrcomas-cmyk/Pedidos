"""
config.py - Constantes, clase Columnas y configuración general del proyecto.
"""

# ==============================================================================
# FUENTES DISPONIBLES
# ==============================================================================
FUENTES_DISPONIBLES = [
    "Corta caducidad",
    "Lento mov",
    "Cosmopark",
    "Sustituto",
    "PNC",
    "Caduco",
    "Revision",  # NUEVO
]

# Fuentes que se pueden combinar con "otras" fuentes (Sustituto/Lento mov/Revision)
# Las "otras" son fuentes con inventario físico asignable
FUENTES_COMBINABLES_CON_OTRAS = {"Sustituto", "Lento mov", "Revision"}

# Hojas que se cargan del archivo de hojas externas pero NO son fuentes para el
# motor de sugerencias — se usan en reportes específicos (ej. 'Revision2' alimenta
# la pestaña 'Inventario por condicion').
HOJAS_ADICIONALES = ["Revision2"]

# Centros estándar
CENTROS_INTERES = ["1001", "1003", "1004", "1017", "1018", "1022", "1036"]
ALMACENES_STANDARD = ["1030", "1031", "1032", "1060"]

# Para filtro de Corta caducidad
ALMACEN_PERMITIDO_CORTA_CADUCIDAD = "1032"
DIAS_MAX_CORTA_CADUCIDAD = 365  # menos de 1 año


# ==============================================================================
# CLASE COLUMNAS - nombres de columnas centralizados
# ==============================================================================
class Columnas:
    GRUPO_CLIENTE = "Gpo. Cte."
    FECHA = "Fecha"
    PEDIDO = "Pedido"
    GRUPO_VENDEDOR = "Gpo.Vdor."
    SOLICITANTE = "Solicitante"
    DESTINATARIO = "Destinatario"
    RAZON_SOCIAL = "Razón Social"
    CENTRO_PEDIDO = "Centro pedido"
    ALMACEN = "Almacén"
    MATERIAL_SOLICITADO = "Material solicitado"
    MATERIAL_BASE = "Material base"
    DESCRIPCION_SOLICITADA = "Descripción solicitada"
    CANTIDAD_PEDIDO = "Cantidad pedido"
    CANTIDAD_PENDIENTE = "Cantidad pendiente"
    CANTIDAD_OFERTAR = "Cantidad a Ofertar"
    PRECIO = "Precio"
    FUENTE = "Fuente"
    MATERIAL_SUGERIDO = "Material sugerido"
    DESCRIPCION_SUGERIDA = "Descripción sugerida"
    CENTRO_SUGERIDO = "Centro sugerido"
    ALMACEN_SUGERIDO = "Almacén sugerido"
    DISPONIBLE = "Disponible"
    LOTE = "Lote"
    FECHA_CADUCIDAD = "Fecha de Caducidad"
    MESES_VIGENCIA_LOTE = "Meses vigencia lote"  # NUEVA COLUMNA
    CENTRO_INV = "Centro (Inv)"
    INV_1030 = "Inv 1030"
    INV_1031 = "Inv 1031"
    INV_1032 = "Inv 1032"
    INV_1060 = "Inv 1060"
    MESES_INVENTARIO = "Meses_Inventario"
    PROMEDIO_CONSUMO_12M = "Promedio_Consumo_12M"
    CONSUMO_DESTINATARIO_12M = "Consumo promedio (Destinatario/Material)"
    CANT_TRANSITO = "Cant. en Tránsito"
    CANT_TRANSITO_1030 = "Cant. en Tránsito 1030"
    CANT_TRANSITO_1031 = "Cant. en Tránsito 1031"
    CANT_TRANSITO_1032 = "Cant. en Tránsito 1032"
    DISP_1031_1030 = "Disponible 1031-1030"
    DISP_1031_1032 = "Disponible 1031-1032"
    INV_1001 = "Inv 1001"
    INV_1003 = "Inv 1003"
    INV_1004 = "Inv 1004"
    INV_1017 = "Inv 1017"
    INV_1018 = "Inv 1018"
    INV_1022 = "Inv 1022"
    INV_1036 = "Inv 1036"
    BLOQUEADO = "Bloqueado"
    STATUS_REVISION = "Status Revisión"  # NUEVA - para Resumen Sin Sugerencias
