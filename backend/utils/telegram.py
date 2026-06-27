from __future__ import annotations
import os
import httpx

TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


async def send(signal) -> bool:
    if not TOKEN or not CHAT_ID:
        return False
    d = signal.direction
    arrow = "🟢 CALL ▲" if d == "CALL" else "🔴 PUT ▼"
    stars = "⭐" * max(1, signal.score // 20)
    ai_txt = f"🤖 AI Score: *{signal.ai_score*100:.0f}%*\n" if signal.ai_score > 0 else ""
    kelly_txt = f"💼 Kelly sizing: *{signal.kelly_pct*100:.1f}%*\n" if signal.kelly_pct > 0 else ""
    reasons = "\n".join(f"  • {r}" for r in signal.reasons[:5])
    text = (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 *{signal.symbol}* — {signal.broker}\n"
        f"{arrow} | `{signal.market_type}`\n"
        f"⏱ Exp: *{signal.expiration}min* | 💰 *{signal.payout*100:.0f}%*\n"
        f"🎯 Score: *{signal.score}/100* {stars}\n"
        f"{ai_txt}{kelly_txt}"
        f"📈 Win hist: *{signal.win_rate_hist*100:.0f}%*\n"
        f"\n*Confluencias:*\n{reasons}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
            )
        return r.status_code == 200
    except Exception:
        return False
