# Sugeridor de Materiales - Versión modular

Sistema de sugerencias 1:1 de materiales con reporte Excel automático.

## Estructura

```
sugeridor/
├── app.py                              ← UI Streamlit (punto de entrada)
├── config.py                           ← Columnas, fuentes, constantes
├── io_loaders.py                       ← Carga de archivos Excel
├── test_cambios.py                     ← 7 tests funcionales
├── procesadores/
│   ├── utilidades.py                   ← Helpers (Timer, normalización, vigencia)
│   ├── inventario.py                   ← Procesamiento de hoja Inventario
│   ├── externas.py                     ← Procesamiento de hojas externas (incluye Revision)
│   └── facturacion.py                  ← Procesamiento de facturación + Reporte de Consumo
├── sugerencias/
│   ├── consolidacion.py                ← Unir fuentes repetidas (con agrupación de Revision)
│   ├── motor_optimizado.py             ← Motor compartido de sugerencias O(1)
│   └── enriquecimiento.py              ← Post-proceso con datos de consumo
└── reportes/
    ├── todas_sugerencias.py            ← Reporte "Todas las Sugerencias"
    ├── sin_sugerencias.py              ← Reporte "Resumen Sin Sugerencias"
    ├── sug_desde_consumo.py            ← Reporte "Sug Reporte Consumo"
    └── exportador.py                   ← Exportador a Excel
```

## Instalación

```bash
pip install streamlit pandas numpy openpyxl
```

## Ejecución

```bash
cd sugeridor
streamlit run app.py
```

## Ejecutar tests

```bash
cd sugeridor
python test_cambios.py
```

## Cambios respecto a la versión original

1. **Modularización completa**: de 1 archivo de 4,926 líneas a 13 módulos especializados.
2. **Nueva pestaña "Revision"** en el archivo de hojas externas:
   - Columnas: `Material`, `Texto breve de material`, `Status`
   - Funciona como "Lento mov" pero usa el valor de `Status` en lugar del nombre de la hoja
   - Un material con múltiples Status se consolida como `Revision (Status1, Status2)`
3. **Filtro en "Corta caducidad"**: solo materiales con `FeCaduc/FePreferCons` a menos
   de 1 año O en almacén `1032`.
4. **Nueva columna "Meses vigencia lote"** después de `Fecha de Caducidad` en:
   - Reporte "Todas las Sugerencias"
   - Reporte "Sug Reporte Consumo"
5. **Nueva columna "Status Revisión"** en el reporte "Resumen Sin Sugerencias"
   que muestra los Status concatenados si el material aparece en la hoja Revision.
6. **UI minimalista**: sin tablas ni previews, solo:
   - Carga de archivos
   - Barra de progreso global con ETA dinámico
   - Descarga automática del Excel al terminar (JS + botón fallback)
7. **Descarga automática**: al terminar el procesamiento, el navegador dispara
   la descarga vía JavaScript. Si el navegador la bloquea, el botón de descarga
   manual queda visible como red de seguridad.

## Notas

- La lógica de negocio NO cambió: los reportes salen idénticos a la versión
  original, con las nuevas columnas y filtros aplicados.
- El motor optimizado conserva el speedup de 30-150x del original.
- Todos los módulos son puros (no dependen de Streamlit excepto `app.py`),
  por lo que se pueden reusar en otros contextos (scripts, tests, API).
