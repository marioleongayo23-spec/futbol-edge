"""Previa narrativa validada con Gemini → Groq.

El nombre del módulo se conserva por compatibilidad. La respuesta incluye el
proveedor real y solo se acepta si cumple unos mínimos de calidad; el dashboard
decide después si reemplaza o conserva el último resultado bueno.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .ai_client import chat

_SYSTEM = (
    "Eres un redactor de prensa deportiva de primer nivel, en español de España. "
    "Escribes la PREVIA de un partido con criterio táctico, ameno pero riguroso. "
    "Usas SOLO los datos que te doy (probabilidades, goles esperados, estadísticas "
    "esperadas, forma reciente, cara a cara). No inventas alineaciones, lesiones ni "
    "fichajes concretos que no aparezcan. NO das consejos de apuestas ni mencionas "
    "cuotas. 130-180 palabras, 2 párrafos, tono de análisis, sin titulares."
)


@dataclass(frozen=True)
class GeneratedPreview:
    text: str
    provider: str
    model: str
    quality: float


def _prompt(m: dict) -> str:
    probs = m.get("probs") or []
    xg = m.get("xg") or []
    markets = m.get("markets") or {}
    stats = m.get("stats") or {}

    def line(key, label):
        value = stats.get(key)
        return f"{label}: {value['home']}-{value['away']}" if value else None

    stats_text = " · ".join(filter(None, [
        line("shots", "remates"),
        line("sot", "remates a puerta"),
        line("corners", "córners"),
        line("fouls", "faltas"),
        line("yellows", "amarillas"),
    ]))
    parts = [
        f"Partido: {m.get('home')} (local) vs {m.get('away')} (visitante).",
        f"Competición: {m.get('league')}, jornada {m.get('matchday')}.",
        f"Probabilidad del modelo — victoria local {probs[0] if probs else '?'}%, "
        f"empate {probs[1] if len(probs) > 1 else '?'}%, victoria visitante "
        f"{probs[2] if len(probs) > 2 else '?'}%.",
        f"Goles esperados (xG): {xg[0] if xg else '?'} - {xg[1] if len(xg) > 1 else '?'}.",
        f"Marcador más probable: {markets.get('marcador', '?')}. "
        f"Prob. de más de 2.5 goles: {round((markets.get('over_2_5') or 0) * 100)}%. "
        f"Ambos marcan: {round((markets.get('btts') or 0) * 100)}%.",
    ]
    if stats_text:
        parts.append(f"Estadísticas esperadas (local-visitante): {stats_text}.")
    if m.get("form"):
        parts.append(f"Forma reciente: {m['form']}.")
    if m.get("h2h"):
        parts.append(f"Cara a cara reciente: {m['h2h']}.")
    return _SYSTEM + "\n\nDatos:\n" + "\n".join(parts) + "\n\nEscribe la previa:"


def _validate_preview(text: str, home: str, away: str) -> tuple[str | None, float]:
    """Limpia y puntúa una previa; nunca acepta texto vacío o de diagnóstico."""

    if not isinstance(text, str):
        return None, 0.0
    clean = re.sub(r"^```(?:markdown|text)?\s*|\s*```$", "", text.strip(), flags=re.I)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    words = re.findall(r"\b[\wÁÉÍÓÚÜÑáéíóúüñ'-]+\b", clean)
    lowered = clean.lower()
    forbidden = ("no puedo", "como modelo de ia", "json", "```", "error", "undefined")
    if len(words) < 90 or len(words) > 230 or any(token in lowered for token in forbidden):
        return None, 0.0
    if clean.count(".") < 3:
        return None, 0.0
    names_present = sum(name.lower() in lowered for name in (home, away) if name)
    if names_present < 2:
        return None, 0.0
    target_score = max(0.0, 1.0 - abs(len(words) - 155) / 155)
    paragraph_score = 1.0 if "\n\n" in clean else 0.8
    return clean, round(0.7 * target_score + 0.3 * paragraph_score, 2)


def generate_preview(m: dict, timeout: int = 40, retries: int = 1) -> GeneratedPreview | None:
    """Genera y valida la previa con la cadena Gemini → Groq."""

    del retries  # una llamada por proveedor; el cron controla el siguiente intento.
    response = chat(_prompt(m), max_tokens=1200, temperature=0.75, timeout=timeout)
    if not response:
        return None
    text, quality = _validate_preview(response.text, str(m.get("home", "")), str(m.get("away", "")))
    if not text:
        return None
    return GeneratedPreview(text, response.provider, response.model, quality)


def generate_statistical_preview(m: dict) -> GeneratedPreview | None:
    """Previa gratuita y determinista cuando los proveedores no responden.

    No inventa noticias ni jugadores: convierte únicamente las métricas ya
    calculadas por el modelo en una narración completa y reemplazable por IA.
    """

    home, away = str(m.get("home") or "").strip(), str(m.get("away") or "").strip()
    probs, xg = m.get("probs") or [], m.get("xg") or []
    stats, markets = m.get("stats") or {}, m.get("markets") or {}
    if not home or not away or len(probs) != 3 or len(xg) != 2:
        return None
    labels = ("la victoria local", "el empate", "la victoria visitante")
    fav_index = max(range(3), key=lambda index: probs[index])
    shots = stats.get("shots") or {}
    sot = stats.get("sot") or {}
    corners = stats.get("corners") or {}
    fouls = stats.get("fouls") or {}
    yellows = stats.get("yellows") or {}
    score = markets.get("marcador") or f"{round(xg[0])}-{round(xg[1])}"
    over = round(float(markets.get("over_2_5") or 0) * 100)
    btts = round(float(markets.get("btts") or 0) * 100)
    first = (
        f"{home} recibe a {away} en un partido que el modelo sitúa con un {probs[0]}% "
        f"de triunfo local, un {probs[1]}% de empate y un {probs[2]}% de victoria visitante. "
        f"El escenario con más peso es {labels[fav_index]}, aunque la distribución mantiene "
        f"abierto el encuentro. La producción ofensiva esperada es de {xg[0]} xG para {home} "
        f"y {xg[1]} para {away}; el marcador individual más probable es {score}."
    )
    second = (
        f"En volumen, la previsión apunta a {shots.get('home', '—')} remates del conjunto local "
        f"y {shots.get('away', '—')} del visitante, con {sot.get('home', '—')} y "
        f"{sot.get('away', '—')} tiros a puerta. También se proyectan "
        f"{corners.get('total', '—')} córners, {fouls.get('total', '—')} faltas y "
        f"{yellows.get('total', '—')} amarillas en total. La probabilidad de superar los 2,5 "
        f"goles es del {over}% y la de que marquen ambos equipos, del {btts}%. Son estimaciones "
        f"estadísticas previas al partido y deben actualizarse cuando aparezcan datos oficiales de última hora."
    )
    text = first + "\n\n" + second
    valid, quality = _validate_preview(text, home, away)
    if not valid:
        return None
    return GeneratedPreview(valid, "Motor estadístico local", "template-v1", min(quality, 0.82))
