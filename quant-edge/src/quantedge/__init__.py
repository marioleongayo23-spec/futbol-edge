"""quantedge — marco reproducible de investigación y validación de estrategias.

Objetivo del paquete: **demostrar (o refutar) una ventaja estadística fuera de
muestra** con honestidad metodológica, no maximizar el resultado de un backtest.

Principios no negociables (ver ESTUDIO.md):
  1. El conjunto de test final NUNCA se usa para elegir parámetros.
  2. Toda métrica va acompañada de corrección por pruebas múltiples e intervalos
     de confianza por bootstrap.
  3. Los costes (comisión, diferencial, deslizamiento, impacto, latencia,
     impuestos) se restan SIEMPRE antes de juzgar.
  4. Todas las operaciones son SHADOW_ONLY: nunca se toca beta/capital real.
  5. La conclusión es binaria y auditable: SUPERADO o NO DEMOSTRADO.
"""

__version__ = "0.1.0"
