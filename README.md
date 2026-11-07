# data-ai-lab

Proyectos de datos donde muestro cómo trabajo: modelado y calidad de datos, pipelines, análisis y aplicaciones con LLMs. Cada carpeta se instala y corre por separado, con sus propios tests.

| Proyecto | Qué resuelve | Stack | Estado |
|---|---|---|---|
| [Agente text-to-SQL](proyectos/01-agente-text-to-sql) | Responde preguntas de negocio en lenguaje natural: escribe el SQL, lo valida, lo ejecuta y muestra la consulta que sustenta cada cifra | Python, LLM con tool calling, DuckDB, sqlglot, Streamlit | Listo |
| [Pipeline de matrícula con dbt](proyectos/02-pipeline-matricula-dbt) | Limpia los exports de un sistema académico y los modela en capas para medir matrícula, ocupación de secciones y retención | dbt, DuckDB, Python, Streamlit | Listo |
| [Pronóstico de demanda y reposición](proyectos/03-pronostico-demanda-boticas) | Pronostica la venta diaria de una cadena de boticas por local y producto, trata los quiebres de stock y simula el pedido semanal para bajar inventario sin perder venta | Python, LightGBM, conformal prediction, DuckDB, Streamlit | Listo |
| [Experimentos A/B en una app de delivery](proyectos/04-experimentos-ab-delivery) | Lee los experimentos de producto con una regla fija: chequeo de SRM, CUPED, método delta, guardrails de no inferioridad y lectura secuencial; mide con un A/A cuánto se equivoca quien mira el tablero cada día | Python, SQL (DuckDB), SciPy, Streamlit, Altair | Listo |
| [Capa semántica y monitor de KPIs](proyectos/05-capa-semantica-kpis-pagos) | Define las métricas de una pasarela de pagos una sola vez en YAML, las compila a SQL para cuatro motores, vigila cada KPI a diario y explica en qué segmento está cada anomalía (mezcla vs tasa) | Python, YAML, sqlglot, DuckDB, pydantic, Streamlit, Altair | Listo |
| [Asistente del reglamento académico con RAG](proyectos/06-asistente-reglamento-rag) | Responde preguntas de estudiantes con el artículo vigente a la fecha de la consulta, se abstiene cuando el corpus no tiene la respuesta y cita cada fuente; evalúa BM25, vectores e híbrido con preguntas formales y en jerga | Python, embeddings locales (fastembed, e5), BM25, LLM con salida JSON, Streamlit, Altair | Listo |
| [Lakehouse de envíos con Iceberg y CDC](proyectos/07-lakehouse-envios-iceberg) | Carga el CDC de la tabla de envíos de un courier a tablas Iceberg en bronce, plata y oro: ordena por lsn, descarta duplicados, manda a cuarentena lo que rompe el contrato de datos, evoluciona el esquema y deja cada publicación de la mañana etiquetada para volver a ella | Python, PyIceberg, DuckDB, Dagster, pydantic, Streamlit | Listo |
| [Alerta temprana de deserción](proyectos/08-alerta-desercion-universitaria) | Calcula cada semana el riesgo de que un alumno no vuelva el próximo ciclo, con las razones en texto para tutoría, y mide con 100 llamadas por semana a cuántos desertores se llega a tiempo frente a la regla actual (educativo, universidad ficticia) | Python, LightGBM, SHAP, lifelines, DuckDB, Streamlit | Listo |
| 09 · Cohortes y valor de vida en una fintech | Data Analytics: retención por cohorte, LTV con modelos BG/NBD y Gamma-Gamma, y qué canales de adquisición pagan su costo | SQL (DuckDB), Python, PyMC-Marketing, Streamlit | En camino |
| 10 · Agente de reclamos con herramientas MCP | AI Engineering: agente que atiende reclamos de clientes de una fintech ficticia consultando sus sistemas por MCP, con permisos por herramienta, guardrails y evaluación offline con un juez LLM calibrado contra etiquetas humanas | Python, MCP, LLM con tool calling, pydantic, pytest | En camino |
| 11 · Modelo de Power BI como código | BI Engineering (educativo): el modelo semántico de matrícula de una universidad ficticia en formato PBIP/TMDL, versionado en git, con pruebas de medidas DAX y despliegue por ambientes desde GitHub Actions | Power BI (PBIP, TMDL), DAX, Python, GitHub Actions | En camino |
| 12 · Pedidos en tiempo real con Kafka | Data Engineering: ingesta en streaming de pedidos de una app de delivery ficticia, ventanas por minuto, eventos tardíos con watermark y métricas operativas casi en vivo | Python, Redpanda (Kafka), Quix Streams, DuckDB | En camino |

## Sobre mí

Ingeniero industrial y analista de datos. Trabajo con SQL, Python, Power BI y automatización de procesos, y últimamente con agentes y LLMs aplicados a operaciones.
