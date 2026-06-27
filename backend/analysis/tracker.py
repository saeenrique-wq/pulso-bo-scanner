"""Win Rate tracker — SQLite."""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB = Path(__file__).parent.parent.parent / "data" / "signals.db"

@contextmanager
def _db():
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    try:
        yield con; con.commit()
    finally:
        con.close()

def init():
    with _db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS signals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, broker TEXT, direction TEXT,
            score INTEGER, ai_score REAL, payout REAL,
            expiration INTEGER, market_type TEXT, category TEXT,
            kelly_pct REAL, timestamp REAL,
            outcome TEXT DEFAULT NULL,
            created_at REAL DEFAULT(unixepoch()))""")
        con.execute("CREATE INDEX IF NOT EXISTS ix_sym ON signals(symbol)")

def save(sig) -> int:
    with _db() as con:
        c = con.execute("""INSERT INTO signals
            (symbol,broker,direction,score,ai_score,payout,expiration,
             market_type,category,kelly_pct,timestamp)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (sig.symbol, sig.broker, sig.direction, sig.score, sig.ai_score,
             sig.payout, sig.expiration, sig.market_type, sig.category,
             sig.kelly_pct, sig.timestamp))
        return c.lastrowid

def mark(signal_id: int, outcome: str):
    with _db() as con:
        con.execute("UPDATE signals SET outcome=? WHERE id=?",
                    (outcome.upper(), signal_id))

def win_rate(symbol: str | None = None, direction: str | None = None) -> float:
    where, params = ["outcome IS NOT NULL"], []
    if symbol:   where.append("symbol=?");    params.append(symbol)
    if direction: where.append("direction=?"); params.append(direction)
    with _db() as con:
        r = con.execute(
            f"SELECT COUNT(*) t, SUM(outcome='WIN') w FROM signals WHERE {' AND '.join(where)}",
            params).fetchone()
    return (r["w"] or 0) / r["t"] if r and r["t"] else 0.0

def stats() -> dict:
    with _db() as con:
        r = con.execute("""SELECT COUNT(*) t,
            SUM(outcome='WIN') w, SUM(outcome='LOSS') l,
            SUM(outcome IS NULL) p FROM signals""").fetchone()
        recent = con.execute("""SELECT symbol,direction,score,ai_score,
            payout,outcome,market_type,timestamp FROM signals
            ORDER BY id DESC LIMIT 25""").fetchall()
    t = r["t"] or 0; w = r["w"] or 0
    return {"total":t,"wins":w,"losses":r["l"] or 0,"pending":r["p"] or 0,
            "win_rate": round(w/t*100,1) if t else 0,
            "recent": [dict(x) for x in recent]}

def load_recent(limit: int = 100) -> list[dict]:
    """Carga las últimas señales de la BD para recuperar historial al reiniciar."""
    with _db() as con:
        rows = con.execute("""SELECT id,symbol,broker,direction,score,ai_score,
            payout,expiration,market_type,category,kelly_pct,timestamp,outcome
            FROM signals ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.setdefault("entry_time", 0.0)
        d.setdefault("expiry_time", 0.0)
        d.setdefault("reasons", [])
        d.setdefault("tf_results", [])
        d.setdefault("volatility", 0.0)
        d.setdefault("win_rate_hist", 0.0)
        d["payout"] = round((d.get("payout") or 0) * 100, 1)
        d["ai_score"] = round((d.get("ai_score") or 0) * 100, 1)
        d["kelly_pct"] = round((d.get("kelly_pct") or 0) * 100, 1)
        result.append(d)
    return result

def reset():
    """Borra todo el historial de señales."""
    with _db() as con:
        con.execute("DELETE FROM signals")
        con.execute("DELETE FROM sqlite_sequence WHERE name='signals'")

init()
