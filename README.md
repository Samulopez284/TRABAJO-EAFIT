# Escudo Yuma · demo compartible

Este repositorio contiene solo la interfaz estática de demostración. No incluye transacciones CSV, datos de clientes, el sandbox Python ni sus logs.

## Publicación continua

GitHub Pages se publica automáticamente al hacer push a `main`, mediante el workflow en `.github/workflows/pages.yml`. Tras cada push, GitHub Actions construye y despliega la versión nueva. La primera publicación requiere habilitar GitHub Pages en la configuración del repositorio y elegir **GitHub Actions** como fuente.

La URL tendrá este formato: `https://<propietario>.github.io/<repositorio>/`.

## Qué puede probar el equipo

- Riesgo histórico de cliente de prueba, ajustable de 1 a 100 (inicial: 65).
- Preguntas de contexto con pesos editables de 1 a 100. Por ejemplo, “fuera de casa o ubicación habitual” suma 20 puntos por defecto.
- Tolerancia a falsos positivos, que mueve los umbrales de desafío y retención.
- Decisión explicada: aprobar, pedir una verificación adicional o retener la operación para revisión humana.

El cálculo es un prototipo didáctico. Las respuestas y las decisiones de este modo se quedan en el navegador; no se envían a un servidor.
