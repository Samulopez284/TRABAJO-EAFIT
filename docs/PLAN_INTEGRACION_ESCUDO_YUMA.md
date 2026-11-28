# Plan de integración propia — Escudo Yuma

## Objetivo

Evolucionar el panel existente de TRABAJO-EAFIT para que consuma el motor antifraude Python propio de Yuma Pay. Este trabajo se desarrolla en la rama `feature/escudo-yuma-integracion-propia`; no modifica `main`.

El repositorio externo `D-A-V-I-D-A-R-A-N-G-O/Escudo_Yuma` se utiliza únicamente como referencia de capacidades y organización. No se copian archivos ni fragmentos de su implementación. Toda funcionalidad incorporada aquí debe tener implementación propia y pruebas verificables.

## Estado comprobado del repositorio propio

- Rama base: `main`.
- Interfaz existente: `index.html`.
- Documentación existente: `README.md`.
- El panel ya presenta un centro antifraude, indicadores, tabla de decisiones y simulador de escenario.
- El panel intenta comunicarse con una API local en el puerto `8080`.
- El JavaScript de la interfaz contiene una segunda evaluación de las reglas R001–R012. Debe dejar de tomar decisiones productivas: el motor Python debe ser la única fuente de decisiones.
- El README describe una demostración estática y aclara que las decisiones del simulador se calculan en el navegador. Esa limitación debe actualizarse únicamente cuando la integración esté probada.

## Componentes propios que deben integrarse

En el proyecto local YumaPay se han identificado:

- `04_Sandbox_API/escudo_yuma.py`: motor Python propio que evalúa señales, calcula puntaje, decide aprobar/desafiar/retener y registra razones.
- `04_Sandbox_API/mock_api.py`: API local de demostración basada en la biblioteca estándar de Python, puerto 8080.
- `04_Sandbox_API/openapi.yaml`: contrato OpenAPI existente.
- `03_Datos/`: datos sintéticos del reto, incluidos transacciones, clientes, eventos y alertas.
- `09_Auditoria_y_Entregables/auditar_datos.py`: auditoría reproducible de integridad y línea base.

No duplicar ni reemplazar estos componentes sin comparar primero sus versiones y contratos.

## Contrato de integración que debe verificarse

El motor/API local ha sido documentado en el trabajo previo con estas rutas:

- `GET /v1/salud`
- `POST /v1/reiniciar` (solo entorno de pruebas)
- `GET /v1/transacciones/siguiente?cantidad=N`
- `POST /v1/decisiones`
- `GET /v1/metricas`

Antes de conectar el panel, contrastar cada ruta, método, prefijo, esquema JSON y códigos HTTP con `mock_api.py` y `openapi.yaml`. No asumir que un endpoint existe solo porque la interfaz lo solicita.

### Reglas de integración

1. La API y el motor Python son la fuente única de verdad para puntaje, decisión y razones.
2. El navegador no debe recalcular R001–R012 para decidir sobre las transacciones del conjunto de datos.
3. La interfaz solo representa la respuesta recibida y permite inspeccionar sus razones.
4. Las métricas deben provenir de la API o de un cálculo backend reproducible, no de valores decorativos.
5. El simulador manual debe estar claramente separado del procesamiento de transacciones históricas y etiquetado como escenario didáctico.
6. Los datos del reto son sintéticos. No introducir datos personales o financieros reales.

## Fases de implementación

### Fase 0 — Protección y trazabilidad
- Trabajar solo en esta rama.
- Mantener intacta la rama `main`.
- Registrar los archivos originales y revisar diferencias antes de cada sustitución.
- No incorporar código del repositorio externo.

### Fase 1 — Contrato y conexión
- Verificar el contrato real de `mock_api.py` y `openapi.yaml`.
- Definir una única configuración de URL base para el backend.
- Conectar el chequeo de salud, métricas, lote de transacciones, envío de decisiones y reinicio de sandbox.
- Mostrar estados claros: conectado, desconectado, procesando y error.

### Fase 2 — Motor único
- Retirar la evaluación duplicada del flujo histórico del navegador.
- Enviar las transacciones al backend y mostrar exactamente `decision`, `puntaje` y `razones` devueltos por Python.
- Conservar el simulador manual, pero no presentarlo como el motor oficial.

### Fase 3 — Operación y revisión
- Tabla paginada o por lotes de transacciones evaluadas.
- Filtros por decisión, severidad y rango de puntaje.
- Vista de detalle de cada decisión con señales activadas y trazabilidad.
- Separar alertas pendientes, revisadas y decisiones del motor cuando el modelo de datos lo permita.

### Fase 4 — Reglas administrables
- Diseñar CRUD de reglas solo después de definir un esquema validado en backend.
- Validar tipos, operadores, umbrales y activación/desactivación.
- Auditar quién cambió una regla, cuándo y cuál era su versión anterior.
- No permitir que una regla modificada desde el navegador altere el motor sin validación del servidor.

### Fase 5 — Analítica y explicabilidad
- Incorporar métricas de precisión, recall/detección, falsos positivos, falsos negativos y latencia a partir de resultados reproducibles.
- Evaluar modelos predictivos y técnicas de explicabilidad como trabajo independiente; no afirmar que XGBoost o SHAP están implementados hasta tener código, dependencias, pruebas y resultados.
- No presentar cifras de latencia o cumplimiento normativo como garantías sin mediciones y revisión.

## Línea base de datos auditada (28-11-2026)

- 120.972 transacciones.
- 6.000 clientes.
- 48.281 eventos de aplicación.
- 9.687 alertas.
- Cero duplicados en las claves auditadas.
- Cero referencias foráneas faltantes en las relaciones auditadas.
- Los 9.687 IDs de transacciones alertadas recalculados coinciden con los IDs del CSV de alertas.
- Línea base de las 12 reglas: 1.066 verdaderos positivos, 8.621 falsos positivos y 638 falsos negativos; tasa de falsos positivos 89,0 % y fraude detectado 62,56 %.

Estas cifras describen la auditoría y línea base del conjunto sintético; no son resultados de la nueva integración ni del motor híbrido.

## Criterios de aceptación

- [ ] La rama principal permanece sin cambios.
- [ ] La API arranca y el endpoint de salud responde.
- [ ] El panel muestra el estado real de conexión.
- [ ] El panel obtiene lotes desde la API.
- [ ] Las decisiones mostradas coinciden exactamente con las respuestas del motor Python.
- [ ] No hay una segunda lógica de reglas que contradiga al backend.
- [ ] Las métricas visibles se calculan desde datos verificables.
- [ ] Los errores de red y respuestas inválidas se muestran sin romper el panel.
- [ ] Las pruebas cubren rutas, validación de payloads y al menos un caso de cada decisión.
- [ ] La documentación distingue claramente demo, sandbox y cualquier futura integración productiva.

## Próximo paso técnico

Incorporar a esta rama los archivos propios `escudo_yuma.py`, `mock_api.py` y `openapi.yaml` desde el proyecto local, después de comparar sus hashes y contenido con el respaldo local. Luego ejecutar pruebas de contrato antes de modificar `index.html`.
