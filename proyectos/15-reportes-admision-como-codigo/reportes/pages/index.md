---
title: Campaña 2027-1
---

```sql pub
select * from admision.publicacion
```

```sql kpi
select
    k.*,
    c.actual,
    c.anterior,
    c.variacion
from admision.kpi_campania k
left join admision.comparativo c on c.dimension = 'Total'
where k.campania = (select campania_actual from admision.publicacion)
```

```sql comparable
select
    semana,
    serie,
    etiqueta,
    postulantes,
    postulantes_acum
from admision.avance_comparado
order by serie desc, semana
```

```sql por_sede
select valor as sede, actual, anterior, variacion
from admision.comparativo
where dimension = 'Sede'
order by actual desc
```

```sql por_modalidad
select valor as modalidad, actual, anterior, variacion
from admision.comparativo
where dimension = 'Modalidad'
order by actual desc
```

```sql por_carrera
select valor as carrera, actual, anterior, variacion
from admision.comparativo
where dimension = 'Carrera'
order by variacion
```

Datos al <Value data={pub} column=corte_texto/> en la semana <Value data={kpi} column=semana_corte/> de la campaña. Esta versión se publicó el <Value data={pub} column=generado/> y pasó <Value data={pub} column=pruebas_aprobadas/> de <Value data={pub} column=pruebas/> pruebas de datos.

<BigValue data={kpi} value=postulantes title="Postulantes" fmt=num0 comparison=variacion comparisonFmt=pct1 comparisonTitle="vs 2026-1 a la misma semana"/>
<BigValue data={kpi} value=ingresantes title="Ingresantes" fmt=num0/>
<BigValue data={kpi} value=matriculados title="Matriculados" fmt=num0/>
<BigValue data={kpi} value=pendientes_matricula title="Ingresantes sin matrícula" fmt=num0/>
<BigValue data={kpi} value=interesados title="Leads en el CRM" fmt=num0/>

## Postulantes nuevos por semana

Cada persona cuenta una vez, en la semana de su primera inscripción, aunque luego se inscriba en otra modalidad o vuelva a dar el examen. La campaña 2026-1 está alineada por semana desde su inicio; el eje muestra la fecha de cierre de cada semana de 2027-1.

<LineChart
    data={comparable}
    x=etiqueta
    y=postulantes
    series=serie
    sort=false
    xType=category
    yScale=true
    yFmt=num0
    yAxisTitle="Postulantes"
    markers=true
    markerSize=5
    chartAreaHeight=260
/>

## Contra la misma semana de 2026-1

<Grid cols=2>

<DataTable data={por_sede} rows=all>
    <Column id=sede title="Sede"/>
    <Column id=actual title="2027-1" fmt=num0/>
    <Column id=anterior title="2026-1" fmt=num0/>
    <Column id=variacion title="Variación" fmt=pct1 contentType=delta/>
</DataTable>

<DataTable data={por_modalidad} rows=all>
    <Column id=modalidad title="Modalidad"/>
    <Column id=actual title="2027-1" fmt=num0/>
    <Column id=anterior title="2026-1" fmt=num0/>
    <Column id=variacion title="Variación" fmt=pct1 contentType=delta/>
</DataTable>

</Grid>

<DataTable data={por_carrera} rows=all>
    <Column id=carrera title="Carrera"/>
    <Column id=actual title="2027-1" fmt=num0/>
    <Column id=anterior title="2026-1" fmt=num0/>
    <Column id=variacion title="Variación" fmt=pct1 contentType=delta/>
</DataTable>
