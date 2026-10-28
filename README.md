# data-ai-lab

Proyectos de datos donde muestro cómo trabajo: modelado y calidad de datos, pipelines, análisis y aplicaciones con LLMs. Cada carpeta se instala y corre por separado, con sus propios tests.

| Proyecto | Qué resuelve | Stack |
|---|---|---|
| [Agente text-to-SQL](proyectos/01-agente-text-to-sql) | Responde preguntas de negocio en lenguaje natural: escribe el SQL, lo valida, lo ejecuta y muestra la consulta que sustenta cada cifra | Python, LLM con tool calling, DuckDB, sqlglot, Streamlit |
| [Pipeline de matrícula con dbt](proyectos/02-pipeline-matricula-dbt) | Limpia los exports de un sistema académico y los modela en capas para medir matrícula, ocupación de secciones y retención | dbt, DuckDB, Python, Streamlit |
| [Pronóstico de demanda y reposición](proyectos/03-pronostico-demanda-boticas) | Pronostica la venta diaria de una cadena de boticas por local y producto, trata los quiebres de stock y simula el pedido semanal para bajar inventario sin perder venta | Python, LightGBM, conformal prediction, DuckDB, Streamlit |

## Sobre mí

Ingeniero industrial y analista de datos. Trabajo con SQL, Python, Power BI y automatización de procesos, y últimamente con agentes y LLMs aplicados a operaciones.
