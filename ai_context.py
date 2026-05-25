"""
AI Context Layer v5 — A/B test: GPT vs Grok.

GPT: gpt-4o-mini-search-preview (web search)
Grok: grok-4.3 (xAI, X Search + Web Search)

A/B: alternates by minute (even=GPT, odd=Grok).
Model name tagged in response for WR tracking.
"""

import os
import re
import logging
from typing import Optional
from datetime import datetime

from openai import OpenAI
from config import OPENAI_API_KEY

XAI_API_KEY = os.getenv("XAI_API_KEY", "")

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# MARKET TYPE DETECTION
# ══════════════════════════════════════════════════════════

def detect_market_type(title: str) -> str:
    t = title.lower()
    sports = [
        'nba', 'nfl', 'mlb', 'nhl', 'wnba', 'ncaa', 'epl', 'mls',
        'euroleague', 'ufc', 'tennis', 'golf', ' vs ', ' vs.',
        'champions league', 'la liga', 'serie a', 'bundesliga',
        'premier league', 'world cup', 'cricket',
    ]
    politics = [
        'president', 'election', 'vote', 'senate', 'congress',
        'governor', 'prime minister', 'parliament', 'party',
        'nomination', 'impeach', 'minister',
    ]
    crypto = [
        'bitcoin', 'ethereum', 'btc', 'eth', 'solana', 'crypto',
        'token', 'defi', 'nft', 'fdv', 'airdrop',
    ]
    geo = [
        'war', 'strike', 'invasion', 'ceasefire', 'sanctions',
        'tariff', 'iran', 'russia', 'ukraine', 'china', 'taiwan',
        'nato', 'military',
    ]
    if any(kw in t for kw in sports):
        return "sports"
    if any(kw in t for kw in politics):
        return "politics"
    if any(kw in t for kw in crypto):
        return "crypto"
    if any(kw in t for kw in geo):
        return "geopolitics"
    return "other"


# ══════════════════════════════════════════════════════════
# TYPE-SPECIFIC PROMPTS
# ══════════════════════════════════════════════════════════

SYSTEM = """Ты независимый аналитик для бота копирования ставок на prediction market.
Топ-трейдер сделал ставку. Дай рекомендацию: COPY или SKIP.

КОНТЕКСТ:
- Трейдер заработал МИЛЛИОНЫ. Он ставит потому что видит edge.
- Твоя задача: найти АКТУАЛЬНЫЕ факты и решить — поддерживают они ставку или нет.
- Ищи ТЕКУЩУЮ форму (последние 5-10 матчей), НЕ карьерную статистику.

АБСОЛЮТНЫЙ ЗАПРЕТ:
- НИКОГДА не выдумывай статистику, счета матчей или рекорды
- Если не нашёл конкретный факт — НЕ ПИШИ его
- Лучше написать "данных нет" чем выдумать цифру
- Каждый факт должен быть найден через поиск
- Если "данных нет" по обоим пунктам — пиши NO_DATA (не COPY и не SKIP)

ПРАВИЛА:
1. Выигрышный h2h рекорд = ПОДДЕРЖИВАЕТ ставку
2. Для Over/Under: последние игры между этими командами важнее сезонных средних
3. Не противоречь своим данным. Нашёл факты ЗА → пиши COPY
4. Нашёл факты ПРОТИВ → пиши SKIP
5. NO_DATA — ТОЛЬКО если событие реально неизвестно (нет такого матча, нет такого игрока)
6. Для NBA, MLB, NFL, NHL, EPL, теннис, Dota, CS2 — данные ВСЕГДА есть. Ищи лучше. НЕ ПИШИ NO_DATA для известных лиг.
7. При сомнениях → SKIP (лучше пропустить чем ошибиться)

ЯЗЫК: ТОЛЬКО РУССКИЙ. Все факты, буллиты и вердикт — на русском языке.

ФОРМАТ (СТРОГО):
Строка 1: ✅ COPY или ❌ SKIP
Строка 2: • первый ключевой факт (конкретно, с цифрами)
Строка 3: • второй ключевой факт (конкретно, с цифрами)

ПРИМЕР (COPY):
✅ COPY
• Spirit выиграли 7 из 10 последних матчей, включая 2-0 против Liquid
• H2h: Spirit ведут 3-1, последняя победа 16-9 на Mirage

ПРИМЕР (SKIP):
❌ SKIP
• Angels 3-7 в последних 10, худшая серия в сезоне
• H2h: проиграли 4 из 5 встреч с Guardians

ПРИМЕР (НЕТ ДАННЫХ):
NO_DATA
• Данных о текущей форме команды не найдено
• Матч ещё не анонсирован

НЕ ПИШИ длинные предложения. Только буллиты с фактами. Максимум 2 строки после вердикта."""

PROMPTS = {
    "sports": """Рынок: "{title}"
Трейдер ставит на: {outcome} по {odds:.0f}% (платит {odds:.0f}¢, выиграет $1 если {outcome} победит)
Сумма: ${amount:,.0f}

Найди текущую форму {outcome}: последние 5-10 матчей, h2h с соперником, травмы.
Для Over/Under: найди счёт последних 3 игр между этими командами.""",

    "politics": """Рынок: "{title}"
Трейдер ставит на: {outcome} по {odds:.0f}%
Сумма: ${amount:,.0f}

Найди последние опросы, новости, экспертные оценки. Поддерживают ли факты ставку на {outcome}?""",

    "crypto": """Рынок: "{title}"
Трейдер ставит на: {outcome} по {odds:.0f}%
Сумма: ${amount:,.0f}

Найди последние движения цены, новости, настроения рынка. Поддерживают ли факты ставку на {outcome}?""",

    "geopolitics": """Рынок: "{title}"
Трейдер ставит на: {outcome} по {odds:.0f}%
Сумма: ${amount:,.0f}

Найди последние дипломатические события, новости, экспертный анализ. Поддерживают ли факты ставку на {outcome}?""",

    "other": """Рынок: "{title}"
Трейдер ставит на: {outcome} по {odds:.0f}%
Сумма: ${amount:,.0f}

Найди любую релевантную информацию. Поддерживают ли факты ставку на {outcome}?""",
}


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def _clean_ai_response(text: str) -> str:
    """Clean markdown, URLs, and junk from AI response."""
    text = text.strip('"').strip("'").strip()
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # [text](url) → text
    text = re.sub(r'#{1,3}\s*', '', text)                   # ## headers → plain
    text = re.sub(r'https?://\S+', '', text)                # raw URLs
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)          # **bold** → plain
    text = re.sub(r'\n{2,}', '\n', text)                    # multi newlines
    text = re.sub(r'^\s*[-•]\s*', '', text, flags=re.MULTILINE)  # bullet points
    return text.strip()


def generate_trade_context(
    market_title: str,
    outcome: str,
    odds_pct: float,
    trader_rank: int = 0,
    amount: float = 0,
) -> Optional[str]:
    """
    Generate binary COPY/SKIP recommendation.
    Returns None on error or if GPT has no useful context.
    """
    if not market_title or not OPENAI_API_KEY:
        return None

    market_type = detect_market_type(market_title)

    prompt_template = PROMPTS.get(market_type, PROMPTS["other"])
    prompt = prompt_template.format(
        title=market_title,
        outcome=outcome,
        odds=odds_pct,
        amount=amount,
    )

    try:
        results = {}
        
        # === Call GPT ===
        try:
            client_gpt = OpenAI(api_key=OPENAI_API_KEY)
            resp_gpt = client_gpt.chat.completions.create(
                model="gpt-4o-mini-search-preview",
                web_search_options={"search_context_size": "low"},
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=400,
            )
            gpt_text = _clean_ai_response(resp_gpt.choices[0].message.content.strip())
            if gpt_text and len(gpt_text) >= 8:
                results["GPT"] = gpt_text
        except Exception as e:
            print(f"  ❌ GPT failed: {e}")
        
        # === Call Grok with X Search + Web Search ===
        if XAI_API_KEY:
            try:
                import requests as req
                grok_payload = {
                    "model": "grok-4.3",
                    "input": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "tools": [
                        {"type": "x_search"},
                        {"type": "web_search"},
                    ],
                }
                print(f"  🔍 Grok: calling grok-4.3 with x_search+web_search...")
                grok_response = req.post(
                    "https://api.x.ai/v1/responses",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {XAI_API_KEY}",
                    },
                    json=grok_payload,
                    timeout=60,  # Search needs more time
                )
                
                if grok_response.status_code == 200:
                    grok_data = grok_response.json()
                    # Debug: show response structure
                    output = grok_data.get("output", [])
                    output_types = [b.get("type") for b in output]
                    print(f"  🔍 Grok response: {len(output)} blocks, types={output_types}")
                    
                    # Extract text from ALL possible block types
                    grok_text_parts = []
                    for block in output:
                        btype = block.get("type")
                        if btype == "message":
                            for content in block.get("content", []):
                                ctype = content.get("type")
                                if ctype in ("output_text", "text"):
                                    grok_text_parts.append(content.get("text", ""))
                        elif btype == "output_text":
                            grok_text_parts.append(block.get("text", ""))
                        elif btype == "text":
                            grok_text_parts.append(block.get("text", ""))
                    
                    grok_text = _clean_ai_response("\n".join(grok_text_parts).strip())
                    
                    if not grok_text:
                        # Fallback: try output_text at top level
                        grok_text = _clean_ai_response(grok_data.get("output_text", ""))
                    
                    if grok_text and len(grok_text) >= 8:
                        results["Grok"] = grok_text
                        print(f"  ✅ Grok: {grok_text[:60]}")
                    else:
                        print(f"  ⚠️ Grok empty after parsing. Raw output keys: {list(grok_data.keys())}")
                        if output:
                            print(f"  ⚠️ First block: {str(output[0])[:200]}")
                else:
                    print(f"  ❌ Grok HTTP {grok_response.status_code}: {grok_response.text[:200]}")
            except Exception as e:
                print(f"  ❌ Grok exception: {e}")
        else:
            print(f"  ⚠️ XAI_API_KEY not set — Grok skipped")
        
        if not results:
            return None
        
        # === Determine consensus ===
        verdicts = {}
        for model, text in results.items():
            upper = text.upper()
            lower = text.lower()
            if "NO_DATA" in upper or "НЕТ ДАННЫХ" in upper:
                verdicts[model] = "NO_DATA"
            elif "данных нет" in lower or "не найдено" in lower:
                verdicts[model] = "NO_DATA"
            elif "LEAN COPY" in upper:
                verdicts[model] = "COPY"
            elif "COPY" in upper and "SKIP" not in upper:
                verdicts[model] = "COPY"
            elif "SKIP" in upper:
                verdicts[model] = "SKIP"
            else:
                verdicts[model] = "UNCLEAR"
        
        # Consensus tag
        real_verdicts = [v for v in verdicts.values() if v in ("COPY", "SKIP")]
        if len(real_verdicts) == 2 and real_verdicts[0] == real_verdicts[1]:
            consensus = real_verdicts[0]
        elif len(real_verdicts) == 1:
            consensus = real_verdicts[0]
        elif len(real_verdicts) == 2:
            consensus = "SPLIT"
        else:
            consensus = "NO_DATA"
        
        # Build combined response
        parts = []
        for model, text in results.items():
            # Truncate each model to ~200 chars
            if len(text) > 200:
                cut = text[:200].rfind('.')
                text = text[:cut+1] if cut > 80 else text[:197] + "..."
            parts.append(f"[{model}] {text}")
        
        combined = "\n".join(parts)
        
        # Add consensus header
        combined = f"[CONSENSUS:{consensus}] {combined}"
        
        logger.info(f"  AI dual [{market_type}]: GPT={verdicts.get('GPT','?')} Grok={verdicts.get('Grok','?')} → {consensus}")
        return combined

    except Exception as e:
        logger.warning(f"AI context failed: {e}")
        return None
