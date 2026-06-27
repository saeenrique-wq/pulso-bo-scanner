"""Validador de señales con Ollama (IA local).

Flujo:
  1. Se genera señal técnica con score >= 78
  2. Se envía contexto completo a Ollama
  3. Ollama responde con probabilidad 0-100
  4. Solo se emite si AI score >= MIN_AI_SCORE

Modelos recomendados (en orden de preferencia):
  - llama3.2:3b   → rápido, bueno para clasificación
  - gemma2:2b     → alternativa ligera
  - mistral:7b    → más preciso pero más lento
"""
from __future__ import annotations

import json
import logging

import httpx

log = logging.getLogger(__name__)

OLLAMA_URL  = "http://localhost:11434/api/generate"
MIN_AI_SCORE = 0.70   # Ollama debe dar >= 70% confianza para aprobar

_PROMPT_TEMPLATE = """Eres un experto en análisis técnico de opciones binarias.
Analiza esta señal de trading y da tu probabilidad de éxito del 0 al 100.

ACTIVO: {symbol}
DIRECCIÓN: {direction}
MERCADO: {market_type}
EXPIRACIÓN: {expiration} minutos
PAYOUT: {payout}%
SCORE TÉCNICO: {score}/100

CONFLUENCIAS POR TIMEFRAME:
{tf_details}

INDICADORES ACTIVOS:
{reasons}

Responde ÚNICAMENTE con un número entero del 0 al 100 representando la probabilidad de ganar.
No escribas nada más. Solo el número."""


async def validate(signal, model: str = "llama3.2:3b") -> float:
    """Retorna probabilidad 0.0-1.0. Retorna 0.5 si Ollama no está disponible."""
    try:
        tf_lines = "\n".join(
            f"  {t['tf']}: {t['dir'] or 'Sin señal'} (score {t['score']}, CHOP {t.get('chop',0):.1f})"
            for t in signal.to_dict().get("tf_results", [])
        )
        reasons_text = "\n".join(f"  - {r}" for r in signal.reasons[:8])

        prompt = _PROMPT_TEMPLATE.format(
            symbol=signal.symbol,
            direction=signal.direction,
            market_type=signal.market_type,
            expiration=signal.expiration,
            payout=round(signal.payout * 100, 1),
            score=signal.score,
            tf_details=tf_lines,
            reasons=reasons_text,
        )

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(OLLAMA_URL, json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 5},
            })

        if r.status_code != 200:
            log.warning(f"[Ollama] HTTP {r.status_code}")
            return 0.5

        resp_text = r.json().get("response", "50").strip()
        # Extraer primer número de la respuesta
        import re
        nums = re.findall(r'\d+', resp_text)
        if not nums:
            return 0.5
        val = int(nums[0])
        prob = max(0, min(val, 100)) / 100.0
        log.info(f"[Ollama] {signal.symbol} {signal.direction} → AI={prob:.0%}")
        return prob

    except httpx.ConnectError:
        log.debug("[Ollama] No disponible — omitiendo validación AI")
        return 0.5   # si Ollama no está, no bloquear señales
    except Exception as e:
        log.warning(f"[Ollama] Error: {e}")
        return 0.5


async def is_available(model: str = "llama3.2:3b") -> bool:
    """Verifica si Ollama está corriendo."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get("http://localhost:11434/api/tags")
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                return any(model.split(":")[0] in m for m in models)
    except Exception:
        pass
    return False
