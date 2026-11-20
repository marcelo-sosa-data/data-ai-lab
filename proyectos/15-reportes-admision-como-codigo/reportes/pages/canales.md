---
title: Canales
---

```sql campanias
select campania from admision.kpi_campania order by campania desc
```

<Dropdown data={campanias} name=campania value=campania title="Campaña" defaultValue="2026-2"/>

```sql canales
select * from admision.canales
where campania = '${inputs.campania.value}'
order by tasa_conversion desc
```

Un lead convierte cuando la misma persona, por documento o por celular, aparece como postulante en la campaña. Antes se juntan los leads repetidos del CRM. En la campaña en curso la conversión es parcial: buena parte de los leads todavía puede inscribirse.

<BarChart data={canales} x=canal y=tasa_conversion swapXY=true yFmt=pct1 labels=true title="Leads que llegan a postular" chartAreaHeight=200 sort=false/>

<DataTable data={canales} rows=all>
    <Column id=canal title="Canal"/>
    <Column id=interesados title="Leads" fmt=num0/>
    <Column id=postulantes title="Postulan" fmt=num0/>
    <Column id=ingresantes title="Ingresan" fmt=num0/>
    <Column id=matriculados title="Se matriculan" fmt=num0/>
    <Column id=tasa_conversion title="Lead a postulante" fmt=pct1/>
</DataTable>
