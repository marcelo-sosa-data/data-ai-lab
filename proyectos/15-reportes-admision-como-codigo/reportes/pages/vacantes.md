---
title: Vacantes
---

```sql campanias
select campania from admision.kpi_campania order by campania desc
```

```sql proyeccion
select
    sede,
    carrera,
    vacantes,
    matriculados,
    matriculados_proyectados,
    cobertura_proyectada
from admision.proyeccion_vacantes
order by cobertura_proyectada
```

```sql proyeccion_sede
select
    sede,
    sum(matriculados_proyectados) / sum(vacantes) as cobertura_proyectada
from admision.proyeccion_vacantes
group by sede
order by cobertura_proyectada
```

## Cómo cerraría la campaña en curso

Proyección al ritmo de 2026-1: los matriculados de hoy se multiplican por lo que creció cada sede en 2026-1 desde esta misma semana hasta el cierre. Es una regla simple para ordenar dónde reforzar captación, no un pronóstico; la página de calidad muestra cuánto se equivoca.

<BarChart data={proyeccion_sede} x=sede y=cobertura_proyectada swapXY=true yFmt=pct0 labels=true title="Vacantes cubiertas al cierre, proyectado" chartAreaHeight=140 sort=false/>

<DataTable data={proyeccion} rows=all>
    <Column id=sede title="Sede"/>
    <Column id=carrera title="Carrera"/>
    <Column id=vacantes title="Vacantes" fmt=num0/>
    <Column id=matriculados title="Matriculados hoy" fmt=num0/>
    <Column id=matriculados_proyectados title="Proyectados al cierre" fmt=num0/>
    <Column id=cobertura_proyectada title="Cobertura proyectada" fmt=pct0/>
</DataTable>

## Por campaña

<Dropdown data={campanias} name=campania value=campania title="Campaña" defaultValue="2026-2"/>

```sql cobertura
select
    sede,
    carrera,
    postulantes,
    ingresantes,
    matriculados,
    vacantes,
    pct_vacantes_cubiertas
from admision.embudo_sede_carrera
where campania = '${inputs.campania.value}'
order by sede, pct_vacantes_cubiertas
```

Vacantes cubiertas es matriculados entre vacantes. Las vacantes las fija Admisión al inicio de la campaña.

<DataTable data={cobertura} rows=all groupBy=sede subtotals=true>
    <Column id=sede title="Sede"/>
    <Column id=carrera title="Carrera"/>
    <Column id=postulantes title="Postulantes" fmt=num0 totalAgg=sum/>
    <Column id=ingresantes title="Ingresantes" fmt=num0 totalAgg=sum/>
    <Column id=matriculados title="Matriculados" fmt=num0 totalAgg=sum/>
    <Column id=vacantes title="Vacantes" fmt=num0 totalAgg=sum/>
    <Column id=pct_vacantes_cubiertas title="Cubiertas" fmt=pct0 totalAgg=weightedMean weightCol=vacantes/>
</DataTable>
