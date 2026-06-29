from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")


class Cfg:
    HOST            = os.getenv("HOST", "0.0.0.0")
    PORT            = int(os.getenv("PORT", "8080"))
    SCAN_INTERVAL   = int(os.getenv("SCAN_INTERVAL", "30"))
    ENABLED_BROKERS = [b.strip().lower() for b in os.getenv("ENABLED_BROKERS","demo").split(",") if b.strip()]
    ASSETS          = [a.strip().upper() for a in os.getenv("ASSETS","").split(",") if a.strip()]
    MIN_PAYOUT_PCT  = float(os.getenv("MIN_PAYOUT_PCT","80"))

    # Ollama
    OLLAMA_ENABLED  = os.getenv("OLLAMA_ENABLED","true").lower() == "true"
    OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL","llama3.2:3b")
    OLLAMA_MIN_SCORE= float(os.getenv("OLLAMA_MIN_SCORE","0.65"))

    # Telegram
    TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN","")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")

    # Brokers
    QUOTEX_EMAIL     = os.getenv("QUOTEX_EMAIL","")
    QUOTEX_PASSWORD  = os.getenv("QUOTEX_PASSWORD","")
    QUOTEX_DEMO      = os.getenv("QUOTEX_DEMO","true").lower()=="true"
    POCKET_SSID      = os.getenv("POCKET_SSID","")
    POCKET_DEMO      = os.getenv("POCKET_DEMO","true").lower()=="true"
    IQOPTION_EMAIL   = os.getenv("IQOPTION_EMAIL","")
    IQOPTION_PASSWORD= os.getenv("IQOPTION_PASSWORD","")
    IQOPTION_DEMO    = os.getenv("IQOPTION_DEMO","true").lower()=="true"

cfg = Cfg()
