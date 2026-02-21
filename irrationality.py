"""
Irrational Markets Scanner — Methodology v2 Implementation

Based on Vitalik's strategy: find markets where emotion drives price away from reality,
confirm the mispricing exists, and identify the edge.

Two-step model:
1. Irrationality Detection — Is the market driven by emotion/bias?
2. Mispricing Confirmation — Does price deviate from rational estimate?
"""

import re
import json
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone
from openai import OpenAI
from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# CATEGORY CLASSIFICATION
# ══════════════════════════════════════════════════════════════════

CATEGORY_KEYWORDS = {
    'meme': [
        'kanye', 'elon', 'trump.*tweet', 'kardashian', 'pewdiepie', 'mr beast',
        'doge', 'shiba', 'pepe', 'meme', 'viral', 'tiktok', 'influencer',
        'celebrity', 'rapper', 'actor.*president', 'singer.*president'
    ],
    'conspiracy': [
        'epstein', 'alien', 'ufo', 'disclosure', 'coverup', 'deep state',
        'illuminati', 'flat earth', 'simulation', 'cia.*admit', 'fbi.*admit',
        'secret', 'classified.*release', 'whistleblow'
    ],
    'politics_far': [
        '2028', '2029', '2030', '2032', 'next.*president', 'future.*election',
        'nomination.*202[89]', 'presidential.*202[89]'
    ],
    'politics_near': [
        '2025', '2026', 'midterm', 'senate.*race', 'governor.*race',
        'special election', 'recall', 'impeach'
    ],
    'geopolitics': [
        'war', 'invasion', 'military', 'strike', 'attack', 'nato', 'nuclear',
        'ceasefire', 'treaty', 'sanction', 'china.*taiwan', 'russia.*ukraine',
        'israel', 'iran', 'north korea', 'missile'
    ],
    'macro': [
        'collapse', 'hyperinflation', 'depression', 'default', 'dollar.*crash',
        'fed.*rate', 'recession', 'bank.*fail', 'currency.*crisis', 'debt ceiling'
    ],
    'sports': [
        'nba', 'nfl', 'mlb', 'nhl', 'fifa', 'world cup', 'super bowl',
        'championship', 'playoffs', 'finals', 'mvp', ' vs ', ' vs.'
    ],
    'crypto': [
        'bitcoin', 'ethereum', 'btc', 'eth', 'crypto', 'solana', 'price.*\\$',
        'all.time.high', 'ath'
    ]
}

# Bias strength by category (how much longshots are typically overpriced)
# v2: Geopolitics and Macro upgraded — war/crisis markets are VERY emotional
CATEGORY_BIAS = {
    'meme': {'strength': 'very_high', 'typical_overpricing': 0.07, 'min_edge': 0.03},
    'conspiracy': {'strength': 'very_high', 'typical_overpricing': 0.06, 'min_edge': 0.04},
    'politics_far': {'strength': 'high', 'typical_overpricing': 0.05, 'min_edge': 0.05},
    'politics_near': {'strength': 'medium', 'typical_overpricing': 0.02, 'min_edge': 0.03},
    'geopolitics': {'strength': 'high', 'typical_overpricing': 0.05, 'min_edge': 0.05},  # UPGRADED from low!
    'macro': {'strength': 'high', 'typical_overpricing': 0.04, 'min_edge': 0.06},       # UPGRADED from low!
    'sports': {'strength': 'medium', 'typical_overpricing': 0.03, 'min_edge': 0.05},
    'crypto': {'strength': 'medium', 'typical_overpricing': 0.03, 'min_edge': 0.05},
    'other': {'strength': 'medium', 'typical_overpricing': 0.03, 'min_edge': 0.05}
}

# Base rates for probability estimation
BASE_RATES = {
    "historically_near_zero": 0.01,  # Celebrity president, dead person alive
    "rare": 0.05,                     # Unusual political outcome
    "occasional": 0.15,               # Plausible but unlikely
    "common": 0.35,                   # Genuine uncertainty — DON'T TRADE
}

# Category multipliers for probability adjustment
CATEGORY_PROBABILITY_MULT = {
    'meme': 0.8,        # Memes rarely materialize
    'conspiracy': 0.7,  # Conspiracy outcomes almost never resolve YES
    'politics_far': 1.0,
    'politics_near': 1.0,
    'geopolitics': 1.2,  # Tails are fatter than you think
    'macro': 1.3,        # Doomsday has real tail risk
    'sports': 1.0,
    'crypto': 1.0,
    'other': 1.0
}


def classify_category(market_question: str) -> str:
    """
    Classify market into category based on keywords.
    Returns the category with most matching keywords.
    """
    if not market_question:
        return 'other'
    
    question_lower = market_question.lower()
    
    # Count matches per category
    category_scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if re.search(keyword, question_lower):
                score += 1
        if score > 0:
            category_scores[category] = score
    
    if not category_scores:
        return 'other'
    
    # Return category with highest score
    return max(category_scores, key=category_scores.get)


# ══════════════════════════════════════════════════════════════════
# STEP 1: IRRATIONALITY DETECTION
# ══════════════════════════════════════════════════════════════════

def calculate_irrationality_score(
    market_question: str,
    yes_price: float,
    volume_24h: float = 0,
    volume_avg_30d: float = 0,
    price_change_24h: float = 0,
    edge_percent: float = 0  # NEW: edge from mispricing analysis
) -> Dict:
    """
    Step 1 from Methodology v2: Is there evidence that market participants
    are pricing based on emotion rather than probability?
    
    v2.1: Added edge-based irrationality and expanded longshot thresholds
    
    Returns:
        Dict with irrationality_score (0-100), flags, and category
    """
    score = 0
    flags = []
    
    category = classify_category(market_question)
    category_info = CATEGORY_BIAS.get(category, CATEGORY_BIAS['other'])
    
    # 1. Longshot detection with CATEGORY-SPECIFIC thresholds
    # Geopolitics/macro: expand threshold to 30% (fear-driven markets have higher "longshots")
    longshot_threshold = 0.15  # default
    if category in ['geopolitics', 'macro']:
        longshot_threshold = 0.30  # war/crisis markets: 30% is still a "longshot"
    elif category in ['meme', 'conspiracy']:
        longshot_threshold = 0.25  # meme markets: 25% threshold
    
    if yes_price < longshot_threshold:
        if category_info['strength'] == 'very_high':
            score += 35
            flags.append(f"Longshot ({yes_price*100:.0f}%) in very high bias category ({category})")
        elif category_info['strength'] == 'high':
            score += 25
            flags.append(f"Longshot ({yes_price*100:.0f}%) in high bias category ({category})")
        elif category_info['strength'] == 'medium':
            score += 15
            flags.append(f"Longshot ({yes_price*100:.0f}%) in medium bias category ({category})")
        else:
            score += 5
            flags.append(f"Longshot ({yes_price*100:.0f}%) — but category has low bias")
    
    # 2. Volume spike without proportional news (hype/fear cycle)
    if volume_avg_30d > 0 and volume_24h > 0:
        volume_ratio = volume_24h / volume_avg_30d
        if volume_ratio > 3.0:
            score += 25
            flags.append(f"Volume spike {volume_ratio:.1f}x above average")
        elif volume_ratio > 2.0:
            score += 15
            flags.append(f"Elevated volume {volume_ratio:.1f}x")
    
    # 3. Category is structurally prone to bias
    category_bias_score = {
        'very_high': 20,
        'high': 15,
        'medium': 10,
        'low': 5
    }
    bias_points = category_bias_score.get(category_info['strength'], 5)
    score += bias_points
    if bias_points >= 15:
        flags.append(f"Category structurally prone to longshot bias")
    
    # 4. Extreme price movement (panic or euphoria)
    if abs(price_change_24h) > 0.10:  # >10% move in 24h
        score += 15
        direction = "up" if price_change_24h > 0 else "down"
        flags.append(f"Extreme price move ({price_change_24h*100:+.0f}% {direction})")
    elif abs(price_change_24h) > 0.05:
        score += 8
    
    # 5. Meme/conspiracy/crisis keywords boost
    question_lower = market_question.lower()
    meme_boosters = ['meme', 'viral', 'trending', 'hype', 'moon', 'crazy']
    crisis_boosters = ['war', 'strike', 'attack', 'invasion', 'nuclear', 'collapse', 'crash']
    
    for booster in meme_boosters:
        if booster in question_lower:
            score += 5
            flags.append(f"Meme language detected ('{booster}')")
            break
    
    # NEW: Crisis keywords get extra points (fear-driven pricing)
    for booster in crisis_boosters:
        if booster in question_lower:
            score += 10
            flags.append(f"Crisis keyword detected ('{booster}')")
            break
    
    # 6. NEW: Edge-based irrationality boost
    # If edge is large, the market IS irrational by definition
    if edge_percent > 0:
        if edge_percent >= 15:
            score += 25
            flags.append(f"Large mispricing edge (+{edge_percent:.1f}%)")
        elif edge_percent >= 10:
            score += 15
            flags.append(f"Significant mispricing edge (+{edge_percent:.1f}%)")
        elif edge_percent >= 5:
            score += 8
            flags.append(f"Moderate mispricing edge (+{edge_percent:.1f}%)")
    
    # Cap at 100
    score = min(score, 100)
    
    # Lower threshold for "irrational" classification
    return {
        'irrationality_score': score,
        'flags': flags,
        'category': category,
        'category_info': category_info,
        'is_irrational': score >= 30  # Lowered from 40
    }


# ══════════════════════════════════════════════════════════════════
# CLAUDE FACTOR ANALYSIS
# ══════════════════════════════════════════════════════════════════

def get_claude_factors(market_question: str, yes_price: float, end_date: str = None) -> Optional[Dict]:
    """
    Use Claude/GPT to decompose the question into scoreable factors.
    
    Claude is NOT a probability oracle. Its role is to identify:
    - Base rate class
    - Structural feasibility
    - Number of independent conditions required
    - Confidence in analysis
    """
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        end_date_str = end_date if end_date else "Unknown"
        
        prompt = f"""You are a prediction market analyst. 
Do NOT output a probability number.
Instead, decompose the question into structural factors.

Market: {market_question}
Current YES price: {yes_price*100:.0f}¢
End date: {end_date_str}

Analyze this market and return ONLY valid JSON (no markdown, no explanation):
{{
  "base_rate_class": "historically_near_zero | rare | occasional | common",
  "structural_feasibility": {{
    "independent_conditions_required": <number 1-5>,
    "conditions": ["condition 1", "condition 2"],
    "weakest_link": "description of least likely condition"
  }},
  "category": "meme | conspiracy | politics_far | politics_near | geopolitics | macro | sports | crypto | other",
  "narrative_drivers": ["driver 1", "driver 2"],
  "confidence_in_analysis": "high | medium | low"
}}

Rules:
- "historically_near_zero": events that essentially never happen (celebrity becomes president, dead person alive)
- "rare": unusual but has precedent (~5% base rate)
- "occasional": plausible but unlikely (~15% base rate)  
- "common": genuine uncertainty (~35%+ base rate)
- Be conservative: if uncertain, use higher base_rate_class
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean up response (remove markdown if present)
        if content.startswith('```'):
            content = re.sub(r'^```json?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
        
        factors = json.loads(content)
        
        # Validate required fields
        required = ['base_rate_class', 'structural_feasibility', 'category', 'confidence_in_analysis']
        for field in required:
            if field not in factors:
                logger.warning(f"Missing field in Claude response: {field}")
                return None
        
        return factors
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error getting Claude factors: {e}")
        return None


def get_factors_with_fallback(market_question: str, yes_price: float, category: str) -> Dict:
    """
    Get factors from Claude, or use heuristic fallback if API fails.
    """
    # Try Claude first
    factors = get_claude_factors(market_question, yes_price)
    
    if factors:
        return factors
    
    # Fallback: heuristic-based factors
    logger.info("Using heuristic fallback for factor analysis")
    
    # Estimate base rate from price and category
    if yes_price < 0.05:
        base_rate_class = "historically_near_zero"
    elif yes_price < 0.12:
        base_rate_class = "rare"
    elif yes_price < 0.25:
        base_rate_class = "occasional"
    else:
        base_rate_class = "common"
    
    # Adjust for category
    if category in ['meme', 'conspiracy'] and base_rate_class != "common":
        # These categories are almost always near-zero
        base_rate_class = "historically_near_zero"
    
    return {
        'base_rate_class': base_rate_class,
        'structural_feasibility': {
            'independent_conditions_required': 2,
            'conditions': ['Unknown'],
            'weakest_link': 'Unknown'
        },
        'category': category,
        'narrative_drivers': ['Unknown'],
        'confidence_in_analysis': 'low'  # Low confidence for fallback
    }


# ══════════════════════════════════════════════════════════════════
# STEP 2: MISPRICING CONFIRMATION
# ══════════════════════════════════════════════════════════════════

def calculate_mispricing(
    market_question: str,
    yes_price: float,
    factors: Dict
) -> Dict:
    """
    Step 2 from Methodology v2: Does the market price deviate from rational estimate?
    
    Key insight: A market can be irrational WITHOUT being mispriced.
    We only trade when irrationality has produced a measurable deviation.
    """
    # Get base rate from factors
    base_rate_class = factors.get('base_rate_class', 'occasional')
    base = BASE_RATES.get(base_rate_class, 0.10)
    
    # Structural penalty: each independent unlikely condition reduces probability
    feasibility = factors.get('structural_feasibility', {})
    n_conditions = feasibility.get('independent_conditions_required', 1)
    if n_conditions >= 3:
        base *= 0.5  # Compound improbability
    elif n_conditions == 2:
        base *= 0.75
    
    # Category adjustment
    category = factors.get('category', 'other')
    category_mult = CATEGORY_PROBABILITY_MULT.get(category, 1.0)
    base *= category_mult
    
    # Confidence discount: low confidence → widen estimate toward market
    confidence = factors.get('confidence_in_analysis', 'medium')
    if confidence == 'low':
        base = base * 0.6 + yes_price * 0.4  # Blend toward market
    elif confidence == 'medium':
        base = base * 0.8 + yes_price * 0.2
    
    # Cap rational estimate at 50% (we only trade longshots)
    rational_estimate = min(base, 0.50)
    
    # Calculate edge
    edge = yes_price - rational_estimate
    
    # Get minimum edge threshold for this category
    category_info = CATEGORY_BIAS.get(category, CATEGORY_BIAS['other'])
    min_edge = category_info['min_edge']
    
    # Determine if mispriced
    is_mispriced = edge > min_edge
    
    # Edge quality assessment
    if edge > min_edge * 2:
        edge_quality = "STRONG"
    elif edge > min_edge:
        edge_quality = "MODERATE"
    elif edge > 0:
        edge_quality = "WEAK"
    else:
        edge_quality = "NONE"
    
    return {
        'rational_estimate': rational_estimate,
        'market_price': yes_price,
        'edge': edge,
        'edge_percent': edge * 100,
        'min_edge_required': min_edge,
        'is_mispriced': is_mispriced,
        'edge_quality': edge_quality,
        'base_rate_class': base_rate_class,
        'confidence': confidence
    }


# ══════════════════════════════════════════════════════════════════
# COMBINED SIGNAL: INSIDER + IRRATIONALITY
# ══════════════════════════════════════════════════════════════════

def get_combined_signal(
    insider_score: int,
    insider_position: str,  # "YES" or "NO"
    irrationality_data: Dict,
    mispricing_data: Dict
) -> Dict:
    """
    Combine insider activity with irrationality/mispricing analysis.
    
    Signal types:
    - ALPHA: Insider NO + mispricing confirmed (strongest)
    - CONFLICT: Insider YES + market overpriced (informational)
    - INSIDER_CONFIRMED: Insider YES + market underpriced (real info)
    - INSIDER_ONLY: Insider activity without clear mispricing
    """
    position = insider_position.upper() if insider_position else "YES"
    is_mispriced = mispricing_data.get('is_mispriced', False)
    edge = mispricing_data.get('edge', 0)
    irrationality_score = irrationality_data.get('irrationality_score', 0)
    
    signal_type = None
    signal_strength = 0
    interpretation = ""
    action_suggestion = ""
    
    if position == "NO" and is_mispriced:
        # 🔥 ALPHA — Smart money confirms mispricing
        signal_type = "ALPHA"
        signal_strength = insider_score + irrationality_score
        interpretation = "Smart money (NO) confirms YES is overpriced"
        action_suggestion = "High conviction: insider + statistics aligned"
        
    elif position == "YES" and is_mispriced:
        # ⚠️ CONFLICT — Insider bullish on overpriced market
        signal_type = "CONFLICT"
        signal_strength = insider_score  # Don't add irrationality (conflicting)
        interpretation = "Insider buying YES despite statistical overpricing"
        action_suggestion = "Requires manual analysis: insider may have real info OR is part of irrational crowd"
        
    elif position == "YES" and edge < 0:
        # 🚨 INSIDER_CONFIRMED — YES underpriced + insider buying
        signal_type = "INSIDER_CONFIRMED"
        signal_strength = insider_score + 20  # Boost for alignment
        interpretation = "Insider + underpricing aligned — likely real information"
        action_suggestion = "Follow the insider: market may be underpricing the event"
        
    elif position == "NO" and edge < 0:
        # ❓ STRANGE — Insider selling underpriced YES
        signal_type = "CONTRARIAN_INSIDER"
        signal_strength = insider_score
        interpretation = "Insider buying NO on potentially underpriced market"
        action_suggestion = "Unusual: insider may see risk not reflected in price"
        
    else:
        # Default: insider activity without clear mispricing signal
        signal_type = "INSIDER_ONLY"
        signal_strength = insider_score
        interpretation = "Insider activity detected, no clear mispricing"
        action_suggestion = "Monitor: insider signal only, no statistical edge"
    
    # Determine emoji
    emoji_map = {
        'ALPHA': '🔥',
        'CONFLICT': '⚠️',
        'INSIDER_CONFIRMED': '🚨',
        'CONTRARIAN_INSIDER': '❓',
        'INSIDER_ONLY': '👁️'
    }
    
    return {
        'signal_type': signal_type,
        'signal_emoji': emoji_map.get(signal_type, '📊'),
        'signal_strength': signal_strength,
        'interpretation': interpretation,
        'action_suggestion': action_suggestion,
        'insider_score': insider_score,
        'insider_position': position,
        'irrationality_score': irrationality_score,
        'is_irrational': irrationality_data.get('is_irrational', False),
        'is_mispriced': is_mispriced,
        'edge': edge,
        'edge_percent': mispricing_data.get('edge_percent', 0)
    }


# ══════════════════════════════════════════════════════════════════
# MAIN ANALYSIS FUNCTION
# ══════════════════════════════════════════════════════════════════

def analyze_market_irrationality(
    market_question: str,
    yes_price: float,
    end_date: str = None,
    volume_24h: float = 0,
    volume_avg_30d: float = 0,
    price_change_24h: float = 0,
    insider_score: int = 0,
    insider_position: str = "YES"
) -> Dict:
    """
    Full analysis pipeline: Irrationality → Factors → Mispricing → Combined Signal
    
    v2.1: Two-pass irrationality calculation — first without edge, then with edge
    """
    logger.info(f"Analyzing market irrationality: {market_question[:60]}...")
    
    # Step 1a: Initial Irrationality Detection (without edge)
    irrationality_initial = calculate_irrationality_score(
        market_question=market_question,
        yes_price=yes_price,
        volume_24h=volume_24h,
        volume_avg_30d=volume_avg_30d,
        price_change_24h=price_change_24h,
        edge_percent=0  # First pass without edge
    )
    
    # Get factors (Claude or fallback)
    factors = get_factors_with_fallback(
        market_question=market_question,
        yes_price=yes_price,
        category=irrationality_initial['category']
    )
    
    # Step 2: Mispricing Confirmation
    mispricing = calculate_mispricing(
        market_question=market_question,
        yes_price=yes_price,
        factors=factors
    )
    
    # Step 1b: RECALCULATE Irrationality WITH edge (if edge exists)
    edge_percent = mispricing.get('edge_percent', 0)
    if edge_percent > 0:
        irrationality = calculate_irrationality_score(
            market_question=market_question,
            yes_price=yes_price,
            volume_24h=volume_24h,
            volume_avg_30d=volume_avg_30d,
            price_change_24h=price_change_24h,
            edge_percent=edge_percent  # Second pass WITH edge
        )
    else:
        irrationality = irrationality_initial
    
    # Combined Signal
    combined = get_combined_signal(
        insider_score=insider_score,
        insider_position=insider_position,
        irrationality_data=irrationality,
        mispricing_data=mispricing
    )
    
    return {
        'irrationality': irrationality,
        'factors': factors,
        'mispricing': mispricing,
        'combined_signal': combined
    }
