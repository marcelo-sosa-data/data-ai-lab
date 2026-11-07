# Agente text-to-SQL con guardrails

Un gerente pregunta en español, el agente arma el SQL, lo valida, lo corre y devuelve la cifra junto con la consulta que la respalda.

## De dónde sale

En cualquier equipo de datos llegan a diario preguntas como "¿cuánto vendimos con Yape en Miraflores en julio?". Cada una toma cinco minutos, pero son veinte a la semana. Un LLM escribe SQL razonable; lo difícil es que respete las definiciones del negocio (Callao cuenta como Lima), que no pueda tocar nada fuera de lo permitido y que se pueda medir si un cambio en el prompt lo empeora.

Así queda el proceso con el agente en medio:

```mermaid
flowchart LR
    subgraph U["Gerente o jefe de tienda"]
        I((Inicio)) --> P[Escribir la pregunta en español]
        R[Leer la cifra y el SQL que la sustenta] --> F(((Fin)))
    end
    subgraph A["Agente LLM"]
        E[Revisar tablas y valores de columnas] --> S[Redactar SQL según el glosario]
        K[Leer el error y corregir] --> L{¿Quedan pasos?}
        L -- Sí --> S
        L -- No --> N[Avisar que no llegó a respuesta]
        OK[Responder con texto y SQL]
    end
    subgraph D["Guard y DuckDB"]
        V{¿Pasa el guard?} -- Sí --> X[Ejecutar en solo lectura]
        X --> C{¿Corrió sin error?}
        Z[Reejecutar el SQL final para la tabla completa]
    end
    P --> E
    S --> V
    V -- No --> K
    C -- No --> K
    C -- Sí --> OK
    OK --> Z
    N --> R
    Z --> R
    classDef sobrio fill:#f4f4f4,stroke:#555,color:#222
    class P,R,E,S,K,N,OK,X,Z sobrio
```

## Por dentro

```mermaid
flowchart LR
    UI["app.py / cli.py"] --> AG["agente.py<br/>loop de hasta 10 pasos"]
    AG <--> LLM["llm.py<br/>API chat completions"]
    PR["prompts.py<br/>glosario de negocio"] --> AG
    AG --> HE["herramientas.py<br/>listar, describir, ejecutar, responder"]
    HE --> GU["guard.py<br/>sqlglot, solo SELECT, LIMIT 200"]
    GU --> DB[("db.py<br/>DuckDB solo lectura")]
    DB -- "resultado o error" --> AG
```

El modelo trabaja con cuatro herramientas vía tool calling: `listar_tablas`, `describir_tabla`, `ejecutar_sql` y `responder`. El formato final lo fija el esquema de `responder`, que exige texto y SQL. Sin SQL no hay cifra.

`describir_tabla` también devuelve los valores posibles de las columnas de texto. Con eso el modelo escribe `'Yape'` y no `'YAPE'`, el error más común en text-to-SQL. Si una consulta falla, el error vuelve al modelo y la corrige.

El cliente funciona con cualquier API compatible con chat completions (OpenAI, Groq, Together, Ollama o vLLM en local). El proveedor se cambia con `LLM_BASE_URL` y `LLM_MODELO`.

Usé DuckDB porque corre embebido; para Postgres o BigQuery basta cambiar `db.py` y el dialecto de sqlglot. El modelo ve 50 filas y el usuario hasta 200, porque cada fila cuesta tokens. Como el LLM está detrás de `completar()`, el loop se testea con respuestas guionadas, sin red ni costo.

## Qué deja pasar el guard

Todo SQL pasa por [`guard.py`](src/text2sql/guard.py), que revisa el árbol sintáctico con sqlglot en lugar de usar expresiones regulares. Acepta un solo `SELECT` sobre las tablas permitidas y bloquea `DROP`, `COPY`, `ATTACH`, `read_csv('/etc/passwd')`, `getenv('LLM_API_KEY')` y SQL dinámico. Si falta `LIMIT` agrega `LIMIT 200`, y cancela lo que pase de 15 s. La conexión a DuckDB, además, es de solo lectura. Cada caso tiene su test en [`test_guard.py`](tests/test_guard.py).

## El glosario

Muchos errores de text-to-SQL son de definición y no de sintaxis. Venta, ticket promedio, Lima Metropolitana y tiendas comparables están definidas una sola vez en [`prompts.py`](src/text2sql/prompts.py).

La regla de tiendas comparables salió del set de evaluación. Al preguntar qué tiendas crecieron más, Barranco salía primera con **+2,605%** porque abrió en septiembre de 2025. Un analista de retail lo descarta al toque. Ahora el glosario pide usar solo tiendas abiertas antes del periodo base, o advertirlo si no se aplica.

## La base

Es una cadena ficticia de 24 minimarkets en Lima y provincias, con unas 510 mil boletas y 1.4 millones de líneas de venta entre enero de 2025 y septiembre de 2026, generadas con [`generar_datos.py`](datos/generar_datos.py). Tiene estacionalidad (diciembre 2025 cierra en S/ 1.03 millones cuando un mes normal ronda S/ 0.7 millones), dos tiendas nuevas, Piura y Barranco, y un alza de precios de +4.5% en enero de 2026. Provincia paga más en efectivo:

```mermaid
xychart-beta
    title "Boletas pagadas en efectivo"
    x-axis [Lima, Provincia]
    y-axis "%" 0 --> 60
    bar [41, 51]
```

```mermaid
erDiagram
    tiendas ||--o{ ventas : "emite"
    clientes |o--o{ ventas : "compra (si usa tarjeta)"
    ventas ||--|{ detalle_venta : "contiene"
    productos ||--o{ detalle_venta : "se vende en"
    categorias ||--o{ productos : "agrupa"
```

Tablas y columnas tienen comentarios (`COMMENT ON`) que el agente lee.

## Cómo lo mido

[`evals/casos.json`](evals/casos.json) tiene 15 preguntas, de fáciles a difíciles, cada una con su SQL de referencia. Comparo lo que devuelve cada consulta y no su texto: mismas filas sin importar orden ni nombres de columna. La lógica está en [`evaluacion.py`](src/text2sql/evaluacion.py).

```bash
python evals/evaluar.py              # las 15 preguntas contra el modelo configurado
python evals/evaluar.py --solo e11   # una sola
```

Cada corrida deja un reporte en `evals/resultados/` con aciertos por dificultad, tokens y tiempo.

## Para correrlo

Python 3.10+.

```bash
cd proyectos/01-agente-text-to-sql
pip install -e ".[app,dev]"
python datos/generar_datos.py           # ~5 s, 46 MB

# sin API key: modo demo con las preguntas del set de evaluación
python -m text2sql --demo "¿Cuál es el ticket promedio de 2026?"

# con un LLM
cp .env.example .env                    # LLM_API_KEY, LLM_MODELO y, si aplica, LLM_BASE_URL
python -m text2sql "¿Cuánto vendimos con Yape en Miraflores en julio 2026?"
python -m text2sql --detalle "..."      # muestra cada paso

streamlit run app.py
pytest                                  # 57 tests
```

El modo demo no llama a ningún modelo: pasa el SQL de referencia de la pregunta por el mismo pipeline. Sirve para ver el flujo, no para medir calidad.

## Lo que falta

Hoy cada pregunta es independiente, así que "¿y en agosto?" no funciona; le falta memoria de conversación. Tampoco repregunta cuando algo es ambiguo, toma un supuesto y lo dice. Más adelante quiero mover el glosario a una capa semántica que usen también los dashboards, y agregar caché para las preguntas frecuentes.
