---
title: Calidad
---

```sql pruebas
select prueba, severidad, estado, filas, descripcion, detalle
from admision.resultados_pruebas
order by case estado when 'error' then 0 when 'aviso' then 1 else 2 end, prueba
```

```sql comparacion
select
    campania,
    medida,
    as_is,
    to_be,
    verdad,
    error_as_is,
    error_to_be
from admision.comparacion
where medida <> 'interesados'
order by campania, case medida when 'postulantes' then 1 when 'ingresantes' then 2 else 3 end
```

```sql llamadas
select
    case reporte when 'as_is' then 'Excel actual' else 'Proceso nuevo' end as reporte,
    en_lista, ya_pagaron, no_son_ingresantes_reales, repetidos, llamadas_inutiles, pct_inutiles
from admision.pendientes_comparados
```

```sql incidencias
select descripcion, actual_resultado, actual_desvio, nuevo_resultado, pruebas_con_error
from admision.incidencias
```

## Pruebas de la última carga

Las pruebas con severidad error bloquean la publicación: si alguna falla, el sitio se queda con la versión anterior y el workflow avisa en GitHub.

<DataTable data={pruebas} rows=all>
    <Column id=prueba title="Prueba"/>
    <Column id=severidad title="Severidad"/>
    <Column id=estado title="Estado"/>
    <Column id=filas title="Filas" fmt=num0/>
    <Column id=descripcion title="Qué revisa" wrap=true/>
</DataTable>

## El Excel actual contra este proceso

Con datos sintéticos se sabe qué pasó de verdad, así que se puede medir cuánto se equivoca cada reporte.

<DataTable data={comparacion} rows=all>
    <Column id=campania title="Campaña"/>
    <Column id=medida title="Medida"/>
    <Column id=as_is title="Excel actual" fmt=num0/>
    <Column id=to_be title="Proceso nuevo" fmt=num0/>
    <Column id=verdad title="Real" fmt=num0/>
    <Column id=error_as_is title="Error Excel" fmt=pct1/>
    <Column id=error_to_be title="Error nuevo" fmt=pct1/>
</DataTable>

<DataTable data={llamadas} rows=all>
    <Column id=reporte title="Lista de llamadas"/>
    <Column id=en_lista title="En la lista" fmt=num0/>
    <Column id=ya_pagaron title="Ya pagaron" fmt=num0/>
    <Column id=no_son_ingresantes_reales title="No son reales" fmt=num0/>
    <Column id=repetidos title="Repetidos" fmt=num0/>
    <Column id=pct_inutiles title="Llamadas inútiles" fmt=pct1/>
</DataTable>

## Incidencias sembradas

Quince cambios que suelen llegar en los exports, aplicados sobre una copia de la campaña en curso.

<DataTable data={incidencias} rows=all>
    <Column id=descripcion title="Incidencia" wrap=true/>
    <Column id=actual_resultado title="Excel actual"/>
    <Column id=actual_desvio title="Desvío" fmt=pct1/>
    <Column id=nuevo_resultado title="Proceso nuevo"/>
    <Column id=pruebas_con_error title="Pruebas que fallan" wrap=true/>
</DataTable>

## La proyección de vacantes contra el cierre real

```sql proyeccion
select * from admision.proyeccion_revisada order by sede
```

El generador sabe cómo termina la campaña 2027-1, así que la proyección por sede de la página de vacantes se puede contrastar con el cierre.

<DataTable data={proyeccion} rows=all>
    <Column id=sede title="Sede"/>
    <Column id=vacantes title="Vacantes" fmt=num0/>
    <Column id=matriculados_hoy title="Matriculados al corte" fmt=num0/>
    <Column id=proyectados title="Proyectados" fmt=num0/>
    <Column id=al_cierre title="Al cierre" fmt=num0/>
    <Column id=error title="Error" fmt=pct1/>
    <Column id=cobertura_proyectada title="Cobertura proyectada" fmt=pct0/>
    <Column id=cobertura_al_cierre title="Cobertura real" fmt=pct0/>
</DataTable>
