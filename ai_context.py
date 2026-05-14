"""
AI Context Layer v5 — A/B test: GPT vs Grok.

GPT: gpt-4o-mini-search-preview (web search)
Grok: grok-3-mini-fast (xAI, real-time X/Twitter data)

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

SYSTEM = """You are an independent analyst for a prediction market copy-trading bot.
A top trader or suspected insider just placed a bet. You must give a recommendation: COPY, SKIP, or LEAN COPY/LEAN SKIP.

CRITICAL CONTEXT:
- This person has MILLIONS in profit. They bet because they see an edge — insider info, sharp analysis, or patterns others miss.
- Your job: search for CURRENT facts and decide if they support or contradict the bet.
- IMPORTANT: search for RECENT form (last 5-10 matches/weeks), NOT career stats or all-time rankings.
  A player ranked #99 who won her last 5 matches beats a #21 who lost 3 in a row.

REASONING RULES (follow strictly):
1. If the team/player the trader bet on has a WINNING h2h record → that SUPPORTS the bet
   Example: "X won 3 of 5 vs Y" = facts support X. Do NOT say "results favor Y"
2. For Over/Under: the most recent game between these specific teams matters MORE than season averages
   Example: last game was 239, line is 222.5 → that SUPPORTS Over
3. Do NOT contradict your own data. If you found facts that support the bet, say COPY, not SKIP
4. Season averages only matter if no h2h or recent matchup data exists

DECISION LOGIC:
- Facts clearly support the bet → ✅ COPY
- Mixed facts (some support, some don't) → 🟡 LEAN COPY (trust smart money when unclear)
- No relevant facts found → 🟡 LEAN COPY (smart money > no data)
- Facts clearly contradict the bet → ❌ SKIP

KEY RULE: When in doubt, lean toward COPY. These traders have proven track records.
Only SKIP when facts CLEARLY contradict the bet.

FORMAT (STRICT):
- PLAIN TEXT ONLY. No markdown, no headers, no links, no bullet points.
- Line 1: verdict + one-sentence key reason
- Then 1-2 sentences with supporting facts (RECENT form, not career stats)
- If SKIP: add one sentence on what could make the trader right despite the data
- Cite source in parentheses if found
- End with a clear conclusion — do NOT leave sentences unfinished

EXAMPLE (COPY):
✅ COPY — Medjedovic has beaten two seeded players this week and is in peak form.
He defeated Borges 7-6, 6-2 and de Miñaur 6-4, 6-3 to reach the semifinals. (cadenaser.com) Rublev has struggled on clay this season with a 3-4 record.

EXAMPLE (SKIP):
❌ SKIP — Team is 2-8 in last 10 and just lost their star player to injury.
They were eliminated from playoff contention last week. (espn.com) However, the trader may know about a lineup change not yet public."""

PROMPTS = {
    "sports": """Market: "{title}"
The trader is betting on: {outcome} at {odds:.0f}% odds (paid {odds:.0f}¢, wins $1 if {outcome} wins)
Bet size: ${amount:,.0f}

Search for {outcome}'s recent form, W-L record, h2h vs opponent, and injuries.
For Over/Under markets: search the last 3 games between these specific teams and their total scores.
Do the facts support this bet on {outcome}?""",

    "politics": """Market: "{title}"
The trader is betting on: {outcome} at {odds:.0f}% odds (paid {odds:.0f}¢, wins $1 if correct)
Bet size: ${amount:,.0f}

Search for latest polls, news, and expert analysis. Do the facts support betting on {outcome}?""",

    "crypto": """Market: "{title}"
The trader is betting on: {outcome} at {odds:.0f}% odds (paid {odds:.0f}¢, wins $1 if correct)
Bet size: ${amount:,.0f}

Search for recent price action, news, and sentiment. Do the facts support betting on {outcome}?""",

    "geopolitics": """Market: "{title}"
The trader is betting on: {outcome} at {odds:.0f}% odds (paid {odds:.0f}¢, wins $1 if correct)
Bet size: ${amount:,.0f}

Search for latest diplomatic developments and expert analysis. Do the facts support betting on {outcome}?""",

    "other": """Market: "{title}"
The trader is betting on: {outcome} at {odds:.0f}% odds (paid {odds:.0f}¢, wins $1 if correct)
Bet size: ${amount:,.0f}

Search for any relevant recent information. Do the facts support betting on {outcome}?""",
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
            if gpt_text and len(gpt_text) >= 8 and "NO_DATA" not in gpt_text:
                results["GPT"] = gpt_text
        except Exception as e:
            logger.warning(f"  GPT failed: {e}")
        
        # === Call Grok ===
        if XAI_API_KEY:
            try:
                client_grok = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
                resp_grok = client_grok.chat.completions.create(
                    model="grok-3-mini-fast",
                    messages=[
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=400,
                )
                grok_text = _clean_ai_response(resp_grok.choices[0].message.content.strip())
                if grok_text and len(grok_text) >= 8 and "NO_DATA" not in grok_text:
                    results["Grok"] = grok_text
            except Exception as e:
                logger.warning(f"  Grok failed: {e}")
        
        if not results:
            return None
        
        # === Determine consensus ===
        verdicts = {}
        for model, text in results.items():
            upper = text.upper()
            if "LEAN COPY" in upper:
                verdicts[model] = "COPY"  # Count lean copy as copy
            elif "COPY" in upper and "SKIP" not in upper:
                verdicts[model] = "COPY"
            elif "SKIP" in upper:
                verdicts[model] = "SKIP"
            else:
                verdicts[model] = "UNCLEAR"
        
        # Consensus tag
        v_list = list(verdicts.values())
        if len(v_list) == 2 and v_list[0] == v_list[1] and v_list[0] in ("COPY", "SKIP"):
            consensus = v_list[0]
        elif len(v_list) == 1:
            consensus = v_list[0]
        else:
            consensus = "SPLIT"
        
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
