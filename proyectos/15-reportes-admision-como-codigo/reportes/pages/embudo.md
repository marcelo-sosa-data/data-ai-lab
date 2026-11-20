---
title: Embudo
---

```sql campanias
select campania from admision.kpi_campania order by campania desc
```

<Dropdown data={campanias} name=campania value=campania title="Campaña" defaultValue="2027-1"/>

```sql embudo
select
    modalidad,
    inscripciones,
    evaluadas,
    ingresos,
    matriculas,
    ingresos / nullif(evaluadas, 0) as tasa_ingreso,
    matriculas / nullif(ingresos, 0) as tasa_matricula
from admision.embudo_modalidad
where campania = '${inputs.campania.value}'
order by inscripciones desc
```

```sql etapas
select 'Inscripciones' as etapa, sum(inscripciones) as n, 1 as orden from admision.embudo_modalidad where campania = '${inputs.campania.value}'
union all
select 'Evaluadas', sum(evaluadas), 2 from admision.embudo_modalidad where campania = '${inputs.campania.value}'
union all
select 'Ingresos', sum(ingresos), 3 from admision.embudo_modalidad where campania = '${inputs.campania.value}'
union all
select 'Matrículas', sum(matriculas), 4 from admision.embudo_modalidad where campania = '${inputs.campania.value}'
order by orden
```

El embudo se cuenta por inscripción: quien dio el examen dos veces aporta dos inscripciones y, si ingresó, un solo ingreso, en la modalidad por la que ingresó. En la campaña en curso las evaluadas incluyen solo los resultados publicados hasta el corte.

<FunnelChart data={etapas} nameCol=etapa valueCol=n showPercent=true chartAreaHeight=220/>

<DataTable data={embudo} rows=all>
    <Column id=modalidad title="Modalidad"/>
    <Column id=inscripciones title="Inscripciones" fmt=num0/>
    <Column id=evaluadas title="Evaluadas" fmt=num0/>
    <Column id=ingresos title="Ingresos" fmt=num0/>
    <Column id=matriculas title="Matrículas" fmt=num0/>
    <Column id=tasa_ingreso title="Ingreso / evaluadas" fmt=pct1/>
    <Column id=tasa_matricula title="Matrícula / ingreso" fmt=pct1/>
</DataTable>
