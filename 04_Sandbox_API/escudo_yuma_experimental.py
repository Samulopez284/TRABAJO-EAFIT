#!/usr/bin/env python3
"""Motor antifraude explicable para el sandbox de Escudo Yuma.

El motor solo recibe transacciones sin etiquetas desde mock_api.py. Usa eventos
de la app y decisiones de analistas únicamente cuando ocurrieron antes de la
transacción evaluada. No consulta edad, departamento ni ingresos.

Uso:
    python escudo_yuma.py
    python escudo_yuma.py --reiniciar --max-transacciones 10000
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


SALIDAS = {
    "transferencia_inmediata", "pago_qr", "pago_servicios",
    "retiro_corresponsal", "retiro_cajero", "compra_tarjeta_virtual",
    "recarga_celular",
}
RETIROS = {"retiro_corresponsal", "retiro_cajero"}


def instante(valor: str) -> datetime:
    return datetime.fromisoformat(valor)


def leer_csv(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


class IndiceEventos:
    """Consulta señales de eventos en una ventana anterior al instante actual."""

    def __init__(self, ruta: Path):
        self.por_cliente: dict[str, list[tuple[datetime, dict[str, str]]]] = defaultdict(list)
        for fila in leer_csv(ruta):
            self.por_cliente[fila["id_cliente"]].append((instante(fila["fecha_hora"]), fila))
        self.tiempos: dict[str, list[datetime]] = {}
        for cliente, filas in self.por_cliente.items():
            filas.sort(key=lambda x: x[0])
            self.tiempos[cliente] = [x[0] for x in filas]

    def resumen(self, cliente: str, ahora: datetime) -> dict[str, Any]:
        filas = self.por_cliente.get(cliente, [])
        tiempos = self.tiempos.get(cliente, [])
        fin = bisect.bisect_left(tiempos, ahora)
        desde24 = bisect.bisect_left(tiempos, ahora - timedelta(hours=24), 0, fin)
        desde48 = bisect.bisect_left(tiempos, ahora - timedelta(hours=48), 0, fin)
        ultimas24 = [f for _, f in filas[desde24:fin]]
        ultimas48 = [f for _, f in filas[desde48:fin]]
        fallos = sum(f["tipo_evento"] == "inicio_sesion" and f["resultado"] == "fallido" for f in ultimas24)
        return {
            "fallos_24h": fallos,
            "cambio_clave_24h": any(f["tipo_evento"] == "cambio_clave" for f in ultimas24),
            "cambio_sim_48h": any(f["tipo_evento"] == "cambio_sim_detectado" for f in ultimas48),
        }


class IndiceRetroalimentacion:
    """Solo expone confirmaciones de fraude cuyo análisis ya terminó."""

    def __init__(self, ruta_alertas: Path, ruta_transacciones: Path):
        # El mapa usa únicamente ID, fecha y destino; ignora las columnas de etiqueta.
        transaccion: dict[str, tuple[datetime, str]] = {}
        with ruta_transacciones.open(encoding="utf-8-sig", newline="") as archivo:
            for fila in csv.DictReader(archivo):
                transaccion[fila["id_transaccion"]] = (instante(fila["fecha_hora"]), fila["id_destino"])

        destinos: dict[str, list[datetime]] = defaultdict(list)
        clientes: dict[str, list[datetime]] = defaultdict(list)
        for alerta in leer_csv(ruta_alertas):
            if alerta.get("decision_analista") != "fraude_confirmado":
                continue
            minutos = alerta.get("minutos_hasta_revision", "")
            ref = transaccion.get(alerta.get("id_transaccion", ""))
            if not minutos or not ref:
                continue
            revisado = instante(alerta["fecha_hora_alerta"]) + timedelta(minutes=int(minutos))
            # Una confirmación posterior a la operación no es información disponible entonces.
            destinos[ref[1]].append(revisado)
            clientes[alerta["id_cliente"]].append(revisado)
        self.destinos = {k: sorted(v) for k, v in destinos.items()}
        self.clientes = {k: sorted(v) for k, v in clientes.items()}

    def destino_confirmado_antes(self, destino: str, ahora: datetime) -> bool:
        fechas = self.destinos.get(destino, [])
        return bool(fechas) and fechas[0] < ahora

    def cliente_confirmado_antes(self, cliente: str, ahora: datetime) -> bool:
        fechas = self.clientes.get(cliente, [])
        return bool(fechas) and fechas[0] < ahora


class MotorEscudo:
    def __init__(self, eventos: IndiceEventos, feedback: IndiceRetroalimentacion,
                 umbral_desafio: float, umbral_retencion: float):
        self.eventos = eventos
        self.feedback = feedback
        self.umbral_desafio = umbral_desafio
        self.umbral_retencion = umbral_retencion
        self.salidas_60m: dict[str, deque[tuple[datetime, int]]] = defaultdict(deque)
        self.acumulado_dia: dict[str, tuple[object, int]] = {}
        self.clientes_por_destino: dict[str, set[str]] = defaultdict(set)

    def evaluar(self, tx: dict[str, Any]) -> dict[str, Any]:
        ahora = instante(str(tx["fecha_hora"]))
        cliente = str(tx["id_cliente"])
        monto = int(tx["monto_cop"])
        tipo = str(tx["tipo_operacion"])
        salida = tipo in SALIDAS

        ventana = self.salidas_60m[cliente]
        limite = ahora - timedelta(minutes=60)
        while ventana and ventana[0][0] < limite:
            ventana.popleft()
        conteo_60m = len(ventana) + int(salida)

        dia_actual = ahora.date()
        dia_guardado, acumulado = self.acumulado_dia.get(cliente, (dia_actual, 0))
        if dia_guardado != dia_actual:
            acumulado = 0
        acumulado += monto if salida else 0

        ev = self.eventos.resumen(cliente, ahora)
        id_destino = str(tx.get("id_destino", ""))
        clientes_previos_destino = self.clientes_por_destino[id_destino]
        pesos: list[tuple[float, str]] = []

        def senal(condicion: bool, peso: float, razon: str) -> None:
            if condicion:
                pesos.append((peso, razon))

        monto_alto = monto >= 200_000
        cambio_sim = bool(int(tx.get("cambio_sim_48h", 0))) or ev["cambio_sim_48h"]
        cambio_clave = bool(int(tx.get("cambio_clave_24h", 0))) or ev["cambio_clave_24h"]
        dispositivo_nuevo = bool(int(tx.get("dispositivo_nuevo", 0)))
        destino_nuevo = bool(int(tx.get("destino_nuevo", 0)))
        transferencia = tipo == "transferencia_inmediata"
        senal(cambio_sim, .20, "cambio de SIM en las últimas 48 horas")
        senal(cambio_clave, .12, "cambio de clave en las últimas 24 horas")
        senal(dispositivo_nuevo, .08, "dispositivo registrado recientemente")
        senal(ev["fallos_24h"] >= 3, .23, "tres o más inicios de sesión fallidos en 24 horas")
        senal(ev["fallos_24h"] == 1 or ev["fallos_24h"] == 2, .10, "inicios de sesión fallidos recientes")
        senal(destino_nuevo and monto_alto, .14, "monto alto hacia un destino nuevo")
        saldo = int(tx.get("saldo_antes_cop", 0))
        senal(transferencia and destino_nuevo and saldo > 0 and monto >= .9 * saldo and monto >= 100_000,
              .22, "R005: transferencia nueva cercana al saldo disponible")
        senal(salida and conteo_60m >= 4, .17, "R004: cuatro o más salidas en una ventana de 60 minutos")
        senal(salida and ahora.hour <= 4 and monto_alto, .08, "operación de monto alto en horario nocturno")
        senal(transferencia and monto >= 1_000_000, .09, "R001: transferencia inmediata de monto alto")
        senal(salida and dispositivo_nuevo and monto >= 150_000, .13,
              "R002: salida desde dispositivo nuevo por monto relevante")
        senal(salida and ahora.hour <= 4 and monto >= 150_000, .08,
              "R003: salida de monto relevante en horario nocturno")
        senal(transferencia and cambio_clave and monto >= 200_000, .16,
              "R006: transferencia tras un cambio reciente de clave")
        senal(salida and cambio_sim and monto >= 200_000, .24,
              "R007: salida tras cambio reciente de SIM")
        senal(tipo in RETIROS and int(tx.get("antiguedad_cuenta_dias", 9999)) < 15 and monto >= 300_000,
              .16, "R008: retiro alto desde una cuenta de menos de 15 días")
        senal(salida and acumulado >= 1_500_000, .10, "R010: salidas acumuladas de 1.500.000 COP o más en el día")
        senal(tipo == "pago_qr" and monto >= 200_000, .06, "R011: pago QR de monto alto")
        senal(tipo in RETIROS and monto >= 600_000, .08, "R012: retiro de monto alto")
        senal(tipo == "pago_qr" and destino_nuevo, .10, "pago QR a un comercio nuevo")
        senal(tipo == "pago_qr" and len(clientes_previos_destino) >= 3,
              .12, "comercio QR vinculado antes a varios clientes")
        senal(self.feedback.destino_confirmado_antes(id_destino, ahora), .55,
              "destino asociado a un fraude confirmado antes de esta operación")
        senal(self.feedback.cliente_confirmado_antes(cliente, ahora), .28,
              "antecedente de fraude confirmado para revisión humana")

        # Combina señales independientes sin permitir que el puntaje salga de [0, 1].
        riesgo = 1.0
        for peso, _ in pesos:
            riesgo *= 1.0 - peso
        riesgo = round(1.0 - riesgo, 4)

        if riesgo >= self.umbral_retencion:
            decision = "retener"
            razones = [razon for _, razon in sorted(pesos, reverse=True)[:4]]
            razones.append("retención de esta operación para revisión; no bloquea la cuenta")
        elif riesgo >= self.umbral_desafio:
            decision = "desafiar"
            razones = [razon for _, razon in sorted(pesos, reverse=True)[:4]]
        else:
            decision = "aprobar"
            razones = [razon for _, razon in sorted(pesos, reverse=True)[:2]] or ["sin señales de riesgo relevantes"]

        # Actualiza el estado después de puntuar: la operación actual no cuenta como pasado.
        if salida:
            ventana.append((ahora, monto))
            self.acumulado_dia[cliente] = (dia_actual, acumulado)
        if id_destino and salida:
            clientes_previos_destino.add(cliente)

        return {
            "id_transaccion": tx["id_transaccion"],
            "decision": decision,
            "puntaje": riesgo,
            "razones": razones,
        }


def solicitud(base: str, ruta: str, metodo: str = "GET", cuerpo: Any = None) -> Any:
    datos = None if cuerpo is None else json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + ruta, data=datos, method=metodo)
    if datos is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=15) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Sandbox respondió HTTP {exc.code}: {detalle}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se pudo conectar con el sandbox: {exc.reason}") from exc


def main() -> None:
    aqui = Path(__file__).resolve().parent
    datos = (aqui.parent / "03_Datos").resolve()
    ap = argparse.ArgumentParser(description="Evalúa transacciones del sandbox con Escudo Yuma")
    ap.add_argument("--api", default="http://127.0.0.1:8080", help="URL base del sandbox")
    ap.add_argument("--datos", type=Path, default=datos, help="Carpeta con los CSV sintéticos")
    ap.add_argument("--lote", type=int, default=25, help="Transacciones por solicitud (1 a 500)")
    ap.add_argument("--max-transacciones", type=int, default=0, help="Límite de operaciones; 0 procesa todas")
    ap.add_argument("--umbral-desafio", type=float, default=.34)
    ap.add_argument("--umbral-retencion", type=float, default=.72)
    ap.add_argument("--auditoria", type=Path, default=aqui / "auditoria_escudo_yuma.csv",
                    help="CSV local con decisión y motivos; no incluye datos personales")
    ap.add_argument("--reiniciar", action="store_true", help="Reinicia cursor y métricas del sandbox antes de empezar")
    args = ap.parse_args()
    if not 1 <= args.lote <= 500:
        ap.error("--lote debe estar entre 1 y 500")
    if not 0 <= args.umbral_desafio < args.umbral_retencion <= 1:
        ap.error("Use 0 <= umbral-desafio < umbral-retencion <= 1")

    estado = solicitud(args.api, "/v1/salud")
    if args.reiniciar:
        solicitud(args.api, "/v1/reiniciar", "POST", {})
    motor = MotorEscudo(
        IndiceEventos(args.datos / "eventos_app.csv"),
        IndiceRetroalimentacion(args.datos / "alertas.csv", args.datos / "transacciones.csv"),
        args.umbral_desafio, args.umbral_retencion,
    )
    limite = args.max_transacciones
    procesadas = 0
    args.auditoria.parent.mkdir(parents=True, exist_ok=True)
    necesita_encabezado = not args.auditoria.exists() or args.auditoria.stat().st_size == 0
    registro = args.auditoria.open("a", encoding="utf-8-sig", newline="")
    escritor = csv.writer(registro)
    if necesita_encabezado:
        escritor.writerow(["fecha_hora_transaccion", "id_transaccion", "decision", "puntaje", "razones"])
    print(f"Sandbox listo: {estado.get('transacciones', '?')} transacciones. Umbrales: desafío={args.umbral_desafio:.2f}, retención={args.umbral_retencion:.2f}.")
    try:
        while limite == 0 or procesadas < limite:
            cantidad = min(args.lote, limite - procesadas) if limite else args.lote
            lote = solicitud(args.api, "/v1/transacciones/siguiente?" + urllib.parse.urlencode({"cantidad": cantidad}))
            transacciones = lote.get("transacciones", [])
            if not transacciones:
                break
            decisiones = [motor.evaluar(tx) for tx in transacciones]
            solicitud(args.api, "/v1/decisiones", "POST", decisiones)
            for tx, decision in zip(transacciones, decisiones):
                escritor.writerow([
                    tx["fecha_hora"], decision["id_transaccion"], decision["decision"],
                    decision["puntaje"], json.dumps(decision["razones"], ensure_ascii=False),
                ])
            registro.flush()
            procesadas += len(decisiones)
            print(f"Procesadas {procesadas:,}; quedan {lote.get('restantes', '?'):,} en el sandbox.")
        print("\nMétricas del sandbox:")
        print(json.dumps(solicitud(args.api, "/v1/metricas"), ensure_ascii=False, indent=2))
        print(f"\nDecisiones y razones guardadas en: {args.auditoria}")
    finally:
        registro.close()


if __name__ == "__main__":
    main()
