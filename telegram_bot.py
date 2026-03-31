#!/usr/bin/env python3
"""
5-Agent DEX Trading Bot — Telegram Interface
Remplace TON_TOKEN et TON_CHAT_ID avant de lancer
"""

import asyncio
import aiohttp
import json
import time
import math
import random
from datetime import datetime

# ══════════════════════════════════════════
#  CONFIGURATION — REMPLIS CES DEUX VALEURS
# ══════════════════════════════════════════
TELEGRAM_TOKEN = "TON_NOUVEAU_TOKEN_ICI"   # depuis @BotFather après /revoke
CHAT_ID        = "6946825909"              # ton chat ID

# ══════════════════════════════════════════
#  CONFIG TRADING
# ══════════════════════════════════════════
BINANCE_URL  = "https://api.binance.com/api/v3/ticker/price"
PAIRS        = {"ETH":"ETHUSDT","BTC":"BTCUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT"}
DEX_FEES     = {"Uniswap V3":0.30,"PancakeSwap":0.17,"SushiSwap":0.25}
GAS_BASE     = {"Uniswap V3":4.50,"PancakeSwap":0.08,"SushiSwap":3.80}
SLIP_BASE    = {"Uniswap V3":0.10,"PancakeSwap":0.15,"SushiSwap":0.18}
FALLBACK     = {"ETH":2020,"BTC":66800,"BNB":612,"SOL":82}
TICK_INTERVAL= 15   # secondes entre chaque analyse
WARMUP_TICKS = 22   # ticks nécessaires avant premier signal

# ══════════════════════════════════════════
#  ÉTAT DU BOT
# ══════════════════════════════════════════
STATE = {
    "running": False,
    "token": "ETH",
    "dex": "Uniswap V3",
    "capital": 1000.0,
    "init_cap": 1000.0,
    "invested": 0.0,
    "tokens": 0.0,
    "position": None,
    "trades": [],
    "wins": 0,
    "losses": 0,
    "blocked": 0,
    "total_fees": 0.0,
    "prices": [],
    "threshold": 65,
    "penalties": {"false_breakout": 0, "low_liquidity": 0, "bad_sentiment": 0},
    "autopsy_log": [],
    "cache": {"ETH": None, "BTC": None, "BNB": None, "SOL": None},
    "warmup_done": False,
    "warmup_count": 0,
}

# ══════════════════════════════════════════
#  TELEGRAM — ENVOYER UN MESSAGE
# ══════════════════════════════════════════
async def send_telegram(session, text, parse_mode="HTML"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode}
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
            return await r.json()
    except Exception as e:
        print(f"Telegram error: {e}")

async def get_updates(session, offset=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        async with session.get(url, params={"offset": offset, "timeout": 5},
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            return data.get("result", [])
    except:
        return []

# ══════════════════════════════════════════
#  BINANCE — PRIX LIVE
# ══════════════════════════════════════════
async def fetch_all_prices(session):
    for sym, pair in PAIRS.items():
        try:
            async with session.get(BINANCE_URL, params={"symbol": pair},
                                   timeout=aiohttp.ClientTimeout(total=8)) as r:
                data = await r.json()
                price = float(data["price"])
                if price > 0:
                    STATE["cache"][sym] = price
                    FALLBACK[sym] = price
        except:
            if not STATE["cache"][sym]:
                STATE["cache"][sym] = FALLBACK[sym]

def cur_price():
    base = STATE["cache"][STATE["token"]] or FALLBACK[STATE["token"]]
    return base * (1 + (random.random() - 0.5) * 0.0008)

# ══════════════════════════════════════════
#  INDICATEURS TECHNIQUES
# ══════════════════════════════════════════
def calc_ema(prices, period):
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    gains, losses = 0, 0
    for i in range(1, period + 1):
        d = prices[-period - 1 + i] - prices[-period - 2 + i]
        if d > 0:
            gains += d
        else:
            losses += abs(d)
    avg_g = gains / period
    avg_l = losses / period or 0.0001
    return 100 - (100 / (1 + avg_g / avg_l))

# ══════════════════════════════════════════
#  FRAIS RÉELS AVEC FRICTIONS
# ══════════════════════════════════════════
def calc_fees(amount, liq_score=70):
    dex   = (DEX_FEES[STATE["dex"]] / 100) * amount
    cong  = 0.7 + random.random() * 1.3
    gas   = GAS_BASE[STATE["dex"]] * cong
    slip  = (SLIP_BASE[STATE["dex"]] / 100) * (3 if liq_score < 60 else 1.8 if liq_score < 75 else 1) * amount
    spread = (0.0005 + random.random() * 0.0015) * amount
    impact = (amount / 1000) ** 1.5 * 0.002 * amount
    latency = random.random() * 0.001 * amount
    total = dex + gas + slip + spread + impact + latency
    return {"dex": dex, "gas": gas, "slip": slip, "spread": spread,
            "impact": impact, "latency": latency, "total": total,
            "pct": total / amount * 100}

# ══════════════════════════════════════════
#  5 AGENTS
# ══════════════════════════════════════════
def run_agent1():
    liq_base = {"BTC": 92, "ETH": 88, "BNB": 74, "SOL": 65}
    liq  = liq_base.get(STATE["token"], 70) + (random.random() - 0.5) * 10
    vols = {"BTC": 28.4, "ETH": 14.2, "BNB": 3.1, "SOL": 5.8}
    vol  = vols.get(STATE["token"], 5) * (0.8 + random.random() * 0.4)
    score = min(100, liq * 0.5 + (vol / 30) * 30 + 10)
    return {"liq": liq, "vol": vol, "score": score}

def run_agent2():
    tw = max(0, min(100, 30 + random.random() * 70 - STATE["penalties"]["bad_sentiment"] * 10))
    rd = max(0, min(100, 25 + random.random() * 75 - STATE["penalties"]["bad_sentiment"] * 8))
    gl = tw * 0.6 + rd * 0.4
    return {"twitter": tw, "reddit": rd, "global": gl, "positive": gl >= 50}

def run_agent3(a1, a2):
    prices = STATE["prices"]
    if len(prices) < 14:
        return {"confidence": 0, "direction": "wait", "rsi": None, "ema9": None, "ema21": None}
    rsi   = calc_rsi(prices)
    ema9  = calc_ema(prices, 9)
    ema21 = calc_ema(prices, 21)
    if not all([rsi, ema9, ema21]):
        return {"confidence": 0, "direction": "wait", "rsi": rsi, "ema9": ema9, "ema21": ema21}
    conf = 0
    if rsi < 35:   conf += 25
    elif rsi > 68: conf += 20
    else:          conf += 5
    if ema9 > ema21: conf += 15
    else:            conf += 5
    if a2["positive"]: conf += 15
    else:              conf -= 10
    conf += a1["score"] * 0.15
    conf -= STATE["penalties"]["false_breakout"] * 8
    conf -= STATE["penalties"]["low_liquidity"]  * 5
    conf -= STATE["penalties"]["bad_sentiment"]  * 6
    conf += (random.random() - 0.5) * 12
    conf = max(0, min(100, conf))
    direction = "wait"
    if not STATE["position"]:
        if rsi < 40 and a2["positive"] and ema9 >= ema21:
            direction = "buy"
        elif rsi < 35:
            direction = "buy"
    else:
        if rsi > 65: direction = "sell"
        elif rsi > 72: direction = "sell"
    return {"confidence": conf, "direction": direction, "rsi": rsi, "ema9": ema9, "ema21": ema21}

def run_agent4(a3):
    conf = a3["confidence"] / 100
    kelly = max(0, conf * 2 - 1)
    kelly_pct = min(kelly * 100, 25)
    max_amt = STATE["capital"] * (kelly_pct / 100)
    drawdown = (STATE["init_cap"] - STATE["capital"]) / STATE["init_cap"] * 100
    blocked = drawdown > 20 or kelly_pct < 3 or STATE["capital"] < 50
    return {"kelly": kelly_pct, "max_amt": max_amt, "drawdown": drawdown, "blocked": blocked}

def run_agent5(trade):
    if not trade or trade.get("pnl", 0) >= 0:
        return
    lessons = []
    if trade.get("liq", 70) < 60:
        STATE["penalties"]["low_liquidity"] = min(3, STATE["penalties"]["low_liquidity"] + 1)
        lessons.append("Liquidité trop faible → pénalité appliquée")
    if trade.get("sentiment", 50) < 40:
        STATE["penalties"]["bad_sentiment"] = min(3, STATE["penalties"]["bad_sentiment"] + 1)
        lessons.append("Sentiment négatif ignoré → pénalité appliquée")
    if not lessons:
        lessons.append("Variance normale du marché — aucune pénalité")
    STATE["autopsy_log"].extend(lessons)
    STATE["autopsy_log"] = STATE["autopsy_log"][-10:]

# ══════════════════════════════════════════
//  EXECUTE TRADE
# ══════════════════════════════════════════
async def execute_trade(session, a3, a4, a1, a2):
    price  = STATE["prices"][-1]
    amount = max(10, min(a4["max_amt"], STATE["capital"] * 0.25))
    fees   = calc_fees(amount, a1["liq"])
    now    = datetime.now().strftime("%H:%M:%S")
    conf   = a3["confidence"]

    if a4["blocked"]:
        STATE["blocked"] += 1
        msg = (f"🛡 <b>AGENT 4 — BLOQUÉ</b>\n"
               f"Kelly: {a4['kelly']:.1f}% | Drawdown: {a4['drawdown']:.1f}%\n"
               f"Capital: <b>${STATE['capital']:.2f}</b>")
        await send_telegram(session, msg)
        return

    if a3["direction"] == "buy" and not STATE["position"]:
        if fees["total"] > amount * 0.08:
            await send_telegram(session, f"⚠️ Frais trop élevés (${fees['total']:.2f}) — trade annulé")
            return
        qty = (amount - fees["total"]) / price
        STATE["capital"]  -= amount
        STATE["invested"] += amount
        STATE["tokens"]   += qty
        STATE["total_fees"] += fees["total"]
        STATE["position"] = {"price": price, "qty": qty, "amount": amount,
                              "conf": conf, "liq": a1["liq"], "sentiment": a2["global"]}
        STATE["trades"].append({"time": now, "type": "BUY", "price": price,
                                 "amount": amount, "fees": fees["total"], "conf": conf})
        msg = (f"🟢 <b>SIGNAL ACHAT EXÉCUTÉ</b>\n"
               f"━━━━━━━━━━━━━━━━━━\n"
               f"🪙 Token: <b>{STATE['token']}</b>\n"
               f"💰 Montant: <b>${amount:.2f}</b>\n"
               f"📊 Prix: <b>${price:,.2f}</b>\n"
               f"🧠 Confiance: <b>{conf:.0f}%</b>\n"
               f"⛽ Frais réels: <b>${fees['total']:.2f}</b> ({fees['pct']:.2f}%)\n"
               f"  • DEX: ${fees['dex']:.2f} | Gas: ${fees['gas']:.2f}\n"
               f"  • Slippage: ${fees['slip']:.2f} | Spread: ${fees['spread']:.2f}\n"
               f"💼 Capital restant: <b>${STATE['capital']:.2f}</b>\n"
               f"🏦 DEX: {STATE['dex']}")
        await send_telegram(session, msg)

    elif a3["direction"] == "sell" and STATE["position"]:
        sell_amt = STATE["tokens"] * price
        fees2    = calc_fees(sell_amt, a1["liq"])
        net      = sell_amt - fees2["total"]
        pnl      = net - STATE["position"]["amount"]
        real_pnl = pnl * 0.90  # ~10% de friction additionnelle en vrai
        STATE["capital"]    += net
        STATE["total_fees"] += fees2["total"]
        if pnl >= 0: STATE["wins"]   += 1
        else:        STATE["losses"] += 1
        run_agent5({**STATE["position"], "pnl": pnl, "exit_price": price,
                    "liq": a1["liq"], "sentiment": a2["global"]})
        STATE["trades"].append({"time": now, "type": "SELL", "price": price,
                                 "amount": sell_amt, "fees": fees2["total"],
                                 "pnl": pnl, "real_pnl": real_pnl, "conf": conf})
        STATE["tokens"]   = 0
        STATE["position"] = None
        total = STATE["wins"] + STATE["losses"]
        wr    = (STATE["wins"] / total * 100) if total else 0
        emoji = "✅" if pnl >= 0 else "❌"
        msg = (f"{emoji} <b>VENTE EXÉCUTÉE</b>\n"
               f"━━━━━━━━━━━━━━━━━━\n"
               f"🪙 Token: <b>{STATE['token']}</b>\n"
               f"💰 Montant vendu: <b>${sell_amt:.2f}</b>\n"
               f"📊 Prix: <b>${price:,.2f}</b>\n"
               f"📈 P&L Paper: <b>{'+'if pnl>=0 else''}${pnl:.2f}</b>\n"
               f"🌍 P&L Réel estimé: <b>{'+'if real_pnl>=0 else''}${real_pnl:.2f}</b>\n"
               f"⛽ Frais: <b>${fees2['total']:.2f}</b>\n"
               f"💼 Capital: <b>${STATE['capital']:.2f}</b>\n"
               f"🏆 Win rate: <b>{wr:.0f}%</b> ({STATE['wins']}W/{STATE['losses']}L)")
        await send_telegram(session, msg)

# ══════════════════════════════════════════
#  TICK PRINCIPAL
# ══════════════════════════════════════════
async def tick(session):
    price = cur_price()
    STATE["prices"].append(price)
    if len(STATE["prices"]) > 300:
        STATE["prices"].pop(0)
    a1 = run_agent1()
    a2 = run_agent2()
    a3 = run_agent3(a1, a2)
    a4 = run_agent4(a3)
    conf = a3["confidence"]
    thresh = STATE["threshold"]
    if STATE["running"] and conf >= thresh and a3["direction"] in ("buy", "sell"):
        await execute_trade(session, a3, a4, a1, a2)

# ══════════════════════════════════════════
#  COMMANDES TELEGRAM
# ══════════════════════════════════════════
async def handle_command(session, text):
    text = text.strip().lower()

    if text == "/start":
        if STATE["running"]:
            await send_telegram(session, "⚠️ Le bot tourne déjà !")
            return
        STATE["running"]      = True
        STATE["warmup_done"]  = False
        STATE["warmup_count"] = 0
        await send_telegram(session,
            f"🚀 <b>5-Agent Bot DÉMARRÉ</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🪙 Token: <b>{STATE['token']}</b>\n"
            f"🏦 DEX: <b>{STATE['dex']}</b>\n"
            f"💼 Capital: <b>${STATE['capital']:.2f}</b>\n"
            f"🧠 Seuil confiance: <b>{STATE['threshold']}%</b>\n"
            f"⏱ Warmup en cours (22 ticks à 2s)...")

    elif text == "/stop":
        STATE["running"] = False
        total = STATE["wins"] + STATE["losses"]
        wr = (STATE["wins"] / total * 100) if total else 0
        px = STATE["prices"][-1] if STATE["prices"] else 0
        pnl = STATE["tokens"] * px + STATE["capital"] - STATE["init_cap"]
        await send_telegram(session,
            f"⏹ <b>Bot ARRÊTÉ</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💼 Capital: <b>${STATE['capital']:.2f}</b>\n"
            f"📈 P&L: <b>{'+'if pnl>=0 else''}${pnl:.2f}</b>\n"
            f"🏆 Win rate: <b>{wr:.0f}%</b> ({STATE['wins']}W/{STATE['losses']}L)\n"
            f"⛽ Frais payés: <b>${STATE['total_fees']:.2f}</b>")

    elif text == "/status":
        px  = STATE["prices"][-1] if STATE["prices"] else 0
        pv  = STATE["tokens"] * px
        pnl = pv + STATE["capital"] - STATE["init_cap"]
        pct = pnl / STATE["init_cap"] * 100
        total = STATE["wins"] + STATE["losses"]
        wr = (STATE["wins"] / total * 100) if total else 0
        real_pnl = pnl * 0.90 - total * 0.80
        pos_txt = ""
        if STATE["position"]:
            unreal = (px - STATE["position"]["price"]) * STATE["position"]["qty"]
            pos_txt = f"\n📌 Position ouverte: {'+'if unreal>=0 else''}${unreal:.2f} non réalisé"
        await send_telegram(session,
            f"📊 <b>STATUT DU BOT</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{'🟢 Actif' if STATE['running'] else '🔴 Arrêté'}\n"
            f"🪙 Token: <b>{STATE['token']}</b> @ ${px:,.2f}\n"
            f"💼 Capital: <b>${STATE['capital']:.2f}</b>\n"
            f"📈 P&L Paper: <b>{'+'if pnl>=0 else''}${pnl:.2f} ({pct:+.2f}%)</b>\n"
            f"🌍 P&L Réel estimé: <b>{'+'if real_pnl>=0 else''}${real_pnl:.2f}</b>\n"
            f"🏆 Win rate: <b>{wr:.0f}%</b> ({STATE['wins']}W/{STATE['losses']}L)\n"
            f"⛽ Frais: <b>${STATE['total_fees']:.2f}</b>\n"
            f"🧠 Seuil: <b>{STATE['threshold']}%</b>{pos_txt}")

    elif text == "/trades":
        last = STATE["trades"][-5:] if STATE["trades"] else []
        if not last:
            await send_telegram(session, "📋 Aucun trade pour l'instant.")
            return
        lines = ["📋 <b>5 DERNIERS TRADES</b>\n━━━━━━━━━━━━━━━━━━"]
        for t in reversed(last):
            e = "🟢" if t["type"]=="BUY" else ("✅" if t.get("pnl",0)>=0 else "❌")
            pnl_txt = f" | P&L: {'+'if t.get('pnl',0)>=0 else''}${t.get('pnl',0):.2f}" if t["type"]=="SELL" else ""
            lines.append(f"{e} {t['time']} {t['type']} ${t['amount']:.0f} @ ${t['price']:,.2f}{pnl_txt}")
        await send_telegram(session, "\n".join(lines))

    elif text.startswith("/seuil "):
        try:
            val = int(text.split()[1])
            if 50 <= val <= 95:
                STATE["threshold"] = val
                await send_telegram(session, f"✅ Seuil de confiance mis à jour: <b>{val}%</b>")
            else:
                await send_telegram(session, "⚠️ Le seuil doit être entre 50 et 95.")
        except:
            await send_telegram(session, "Usage: /seuil 65")

    elif text.startswith("/token "):
        tok = text.split()[1].upper()
        if tok in PAIRS:
            STATE["token"] = tok
            STATE["prices"] = []
            STATE["warmup_done"] = False
            STATE["warmup_count"] = 0
            await send_telegram(session, f"✅ Token changé: <b>{tok}</b>")
        else:
            await send_telegram(session, f"⚠️ Token invalide. Choix: {', '.join(PAIRS.keys())}")

    elif text == "/reset":
        STATE.update({"running":False,"capital":1000,"init_cap":1000,"invested":0,
                      "tokens":0,"position":None,"trades":[],"wins":0,"losses":0,
                      "blocked":0,"total_fees":0,"prices":[],"warmup_done":False,
                      "warmup_count":0,"penalties":{"false_breakout":0,"low_liquidity":0,"bad_sentiment":0},
                      "autopsy_log":[]})
        await send_telegram(session, "🔄 Bot réinitialisé — capital remis à $1000")

    elif text == "/help":
        await send_telegram(session,
            "📖 <b>COMMANDES DISPONIBLES</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "/start — Démarrer le bot\n"
            "/stop — Arrêter le bot\n"
            "/status — Voir le P&L et statut\n"
            "/trades — 5 derniers trades\n"
            "/seuil 65 — Changer le seuil (50-95)\n"
            "/token ETH — Changer de token\n"
            "/reset — Remettre à zéro\n"
            "/help — Cette aide")

# ══════════════════════════════════════════
#  BOUCLE PRINCIPALE
# ══════════════════════════════════════════
async def main():
    print("🚀 5-Agent Bot démarré — en attente de commandes Telegram...")
    async with aiohttp.ClientSession() as session:
        # Message de démarrage
        await send_telegram(session,
            "🤖 <b>5-Agent DEX Bot en ligne !</b>\n"
            "Envoie /help pour voir les commandes\n"
            "Envoie /start pour lancer le bot")

        offset = 0
        last_price_fetch = 0
        last_tick = 0
        warmup_timer = 0

        while True:
            now = time.time()

            # Récupère les commandes Telegram
            updates = await get_updates(session, offset)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                if str(msg.get("chat", {}).get("id", "")) == CHAT_ID:
                    text = msg.get("text", "")
                    if text:
                        await handle_command(session, text)

            # Rafraîchit les prix toutes les 15s
            if now - last_price_fetch > 15:
                await fetch_all_prices(session)
                last_price_fetch = now

            # Phase warmup — tick toutes les 2s jusqu'à 22 ticks
            if STATE["running"] and not STATE["warmup_done"]:
                if now - warmup_timer > 2:
                    warmup_timer = now
                    await tick(session)
                    STATE["warmup_count"] += 1
                    if STATE["warmup_count"] >= WARMUP_TICKS:
                        STATE["warmup_done"] = True
                        await send_telegram(session,
                            f"✅ <b>Warmup terminé !</b>\n"
                            f"Bot actif — analyse toutes les {TICK_INTERVAL}s\n"
                            f"Seuil confiance: {STATE['threshold']}%")

            # Mode normal — tick toutes les 15s
            elif STATE["running"] and STATE["warmup_done"]:
                if now - last_tick > TICK_INTERVAL:
                    last_tick = now
                    await tick(session)

            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
