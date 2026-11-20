---
title: Pendientes
---

```sql sedes
select distinct sede from admision.pendientes_matricula order by sede
```

<Dropdown data={sedes} name=sede value=sede title="Sede">
    <DropdownOption value="%" valueLabel="Todas"/>
</Dropdown>

```sql lista
select
    codigo_postulante,
    nombre_completo,
    celular,
    modalidad,
    carrera,
    sede,
    fecha_ingreso,
    dias_sin_matricula
from admision.pendientes_matricula
where sede like '${inputs.sede.value}'
order by dias_sin_matricula desc
```

```sql sin_asignar
select count(*) as pagos from admision.pagos_sin_asignar
where campania = (select campania_actual from admision.publicacion)
```

Ingresantes de la campaña en curso que todavía no pagan la matrícula, de quien lleva más días a quien menos. Es la lista de llamadas de la semana, de quien lleva más días sin pagar a quien menos. Hay <Value data={sin_asignar} column=pagos/> pagos de matrícula que tesorería registró sin código de postulante y con un documento que no cruza; mientras no se asignen, esas personas pueden estar en esta lista.

<DataTable data={lista} rows=25 search=true downloadable=true>
    <Column id=codigo_postulante title="Código"/>
    <Column id=nombre_completo title="Nombre completo"/>
    <Column id=celular title="Celular"/>
    <Column id=modalidad title="Modalidad"/>
    <Column id=carrera title="Carrera"/>
    <Column id=sede title="Sede"/>
    <Column id=fecha_ingreso title="Ingresó" fmt="dd/mm/yyyy"/>
    <Column id=dias_sin_matricula title="Días sin pagar" fmt=num0/>
</DataTable>
