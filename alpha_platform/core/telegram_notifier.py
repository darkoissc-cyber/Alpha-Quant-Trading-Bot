import os
import json
import asyncio
import urllib.request
import urllib.error
from typing import Optional
from alpha_platform.config.settings import settings
from alpha_platform.config.logging_config import logger

class TelegramNotifier:
    """
    Production-grade Telegram notification service for trade alerts, 
    risk triggers, and periodic equity/drawdown heartbeat reports.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _masked_token(self) -> str:
        if not self.bot_token or len(self.bot_token) < 10:
            return "***"
        return f"{self.bot_token[:6]}...***"

    def send_message_sync(self, text: str, parse_mode: str = "Markdown") -> bool:
        if not self.is_configured():
            logger.warning("Telegram Notifier: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured.")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if res_data.get("ok"):
                    logger.info("Telegram notification sent successfully.")
                    return True
                else:
                    logger.error(f"Telegram API returned error: {res_data}")
                    return False
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else str(e)
            logger.error(f"HTTPError sending Telegram notification: {err_body}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False

    async def send_message_async(self, text: str, parse_mode: str = "Markdown") -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.send_message_sync, text, parse_mode)

    def notify_trade_opened(self, symbol: str, signal_type: str, volume: float, price: float, sl: float, tp: float):
        icon = "🟢" if signal_type.upper() == "BUY" else "🔴"
        text = (
            f"{icon} *صفقة جديدة - New Trade Alert*\n\n"
            f"• *الرمز (Symbol):* `{symbol}`\n"
            f"• *النوع (Action):* `{signal_type.upper()}`\n"
            f"• *اللوت (Volume):* `{volume}`\n"
            f"• *سعر الدخول (Price):* `{price:.4f}`\n"
            f"• *إيقاف الخسارة (SL):* `{sl:.4f}`\n"
            f"• *جني الأرباح (TP):* `{tp:.4f}`\n\n"
            f"🤖 _Alpha Quant Execution Engine_"
        )
        return self.send_message_sync(text)

    def notify_trade_closed(self, symbol: str, profit: float, pips: float):
        icon = "💰" if profit >= 0 else "🔻"
        text = (
            f"{icon} *إغلاق صفقة - Trade Closed*\n\n"
            f"• *الرمز (Symbol):* `{symbol}`\n"
            f"• *الربح/الخسارة (PnL):* `${profit:+.2f}`\n"
            f"• *النقاط (Pips):* `{pips:+.1f}`\n\n"
            f"📊 _Alpha Quant Execution Analytics_"
        )
        return self.send_message_sync(text)

    def notify_portfolio_heartbeat(self, equity: float, balance: float, drawdown_pct: float, active_positions: int):
        text = (
            f"📊 *تقرير الحالة الدوري - Portfolio Heartbeat*\n\n"
            f"• *حقوق الملكية (Equity):* `${equity:,.2f}`\n"
            f"• *الرصيد (Balance):* `${balance:,.2f}`\n"
            f"• *نسبة التراجع (Drawdown):* `{drawdown_pct:.2f}%`\n"
            f"• *الصفقات النشطة:* `{active_positions}`\n\n"
            f"🌐 _System Status: ONLINE (24/7 Monitoring)_"
        )
        return self.send_message_sync(text)

    def notify_risk_alert(self, alert_type: str, details: str):
        text = (
            f"⚠️ *تنبيه إدارة المخاطر - Risk Alert*\n\n"
            f"• *نوع التنبيه:* `{alert_type}`\n"
            f"• *التفاصيل:* {details}\n\n"
            f"🛡️ _Alpha Quant Risk Engine Authority_"
        )
        return self.send_message_sync(text)

telegram_notifier = TelegramNotifier()
