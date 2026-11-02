# data-ai-lab

Proyectos de datos donde muestro cómo trabajo: modelado y calidad de datos, pipelines, análisis y aplicaciones con LLMs. Cada carpeta se instala y corre por separado, con sus propios tests.

| Proyecto | Qué resuelve | Stack | Estado |
|---|---|---|---|
| [Agente text-to-SQL](proyectos/01-agente-text-to-sql) | Responde preguntas de negocio en lenguaje natural: escribe el SQL, lo valida, lo ejecuta y muestra la consulta que sustenta cada cifra | Python, LLM con tool calling, DuckDB, sqlglot, Streamlit | ✅ |
| [Pipeline de matrícula con dbt](proyectos/02-pipeline-matricula-dbt) | Limpia los exports de un sistema académico y los modela en capas para medir matrícula, ocupación de secciones y retención | dbt, DuckDB, Python, Streamlit | ✅ |
| [Pronóstico de demanda y reposición](proyectos/03-pronostico-demanda-boticas) | Pronostica la venta diaria de una cadena de boticas por local y producto, trata los quiebres de stock y simula el pedido semanal para bajar inventario sin perder venta | Python, LightGBM, conformal prediction, DuckDB, Streamlit | ✅ |
| [Experimentos A/B en una app de delivery](proyectos/04-experimentos-ab-delivery) | Lee los experimentos de producto con una regla fija: chequeo de SRM, CUPED, método delta, guardrails de no inferioridad y lectura secuencial; mide con un A/A cuánto se equivoca quien mira el tablero cada día | Python, SQL (DuckDB), SciPy, Streamlit, Altair | ✅ |
| [Capa semántica y monitor de KPIs](proyectos/05-capa-semantica-kpis-pagos) | Define las métricas de una pasarela de pagos una sola vez en YAML, las compila a SQL para cuatro motores, vigila cada KPI a diario y explica en qué segmento está cada anomalía (mezcla vs tasa) | Python, YAML, sqlglot, DuckDB, pydantic, Streamlit, Altair | ✅ |
| [Asistente del reglamento académico con RAG](proyectos/06-asistente-reglamento-rag) | Responde preguntas de estudiantes con el artículo vigente a la fecha de la consulta, se abstiene cuando el corpus no tiene la respuesta y cita cada fuente; evalúa BM25, vectores e híbrido con preguntas formales y en jerga | Python, embeddings locales (fastembed, e5), BM25, LLM con salida JSON, Streamlit, Altair | ✅ |
| 07 · Lakehouse de envíos con Iceberg y CDC | Data Engineering: ingesta incremental de los cambios de una base de pedidos de una empresa de logística (ficticia) a tablas Iceberg, con historial, compactación y contratos de datos | Python, PyIceberg, DuckDB, Dagster | En camino |
| 08 · Alerta temprana de deserción universitaria | Data Science (educativo): modelo de riesgo de abandono por semana del semestre en una universidad ficticia, calibrado y explicado, con la lista de alumnos a contactar | Python, LightGBM, SHAP, análisis de supervivencia, Streamlit | En camino |
| 09 · Cohortes y valor de vida en una fintech | Data Analytics: retención por cohorte, LTV con modelos BG/NBD y Gamma-Gamma, y qué canales de adquisición pagan su costo | SQL (DuckDB), Python, PyMC-Marketing, Streamlit | En camino |

## Sobre mí

Ingeniero industrial y analista de datos. Trabajo con SQL, Python, Power BI y automatización de procesos, y últimamente con agentes y LLMs aplicados a operaciones.
