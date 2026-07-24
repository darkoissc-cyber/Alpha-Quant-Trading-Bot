from datetime import datetime, timezone
from typing import Tuple, Dict, Any, List, Optional
from alpha_platform.core.types import TradeCandidate, SignalType
from alpha_platform.config.logging_config import logger

class InstitutionalSelfCriticValidator:
    """
    Hedge Fund Self-Critic & Composite Confidence Evaluator.
    Acts as a skeptical Risk Director that evaluates setups, assigns a Composite Score (0-100),
    grades candidates (A+, B, C), and rejects any setup below A+ Quality (Score < 75).
    """

    def __init__(self, min_composite_score: float = 75.0):
        self.min_composite_score = min_composite_score

    def evaluate_and_critique(
        self,
        candidate: TradeCandidate,
        ai_calibrated_prob: float,
        current_spread_pips: float,
        active_positions: List[Dict[str, Any]],
        recent_trade_results: List[float]
    ) -> Tuple[bool, float, str, str]:
        score = 0.0
        reasons: List[str] = []
        critique_notes: List[str] = []

        # 1. Risk/Reward Ratio Check (Max 25 pts)
        risk_dist = abs(candidate.entry_price - candidate.stop_loss)
        reward_dist = abs(candidate.take_profit - candidate.entry_price)
        rr_ratio = reward_dist / max(1e-5, risk_dist)

        if rr_ratio >= 2.0:
            score += 25.0
            reasons.append(f"Strong R:R ({rr_ratio:.2f} >= 2.0) [+25pts]")
        elif rr_ratio >= 1.5:
            score += 15.0
            reasons.append(f"Moderate R:R ({rr_ratio:.2f}) [+15pts]")
        else:
            critique_notes.append(f"Low R:R ratio ({rr_ratio:.2f} < 1.5)")

        # 2. AI Calibrated Probability (Max 25 pts)
        if ai_calibrated_prob >= 0.60:
            score += 25.0
            reasons.append(f"High AI Conviction ({ai_calibrated_prob:.2f}) [+25pts]")
        elif ai_calibrated_prob >= 0.50:
            score += 15.0
            reasons.append(f"Moderate AI Conviction ({ai_calibrated_prob:.2f}) [+15pts]")
        else:
            critique_notes.append(f"Weak AI probability ({ai_calibrated_prob:.2f} < 0.50)")

        # 3. Market Structure / SMC BOS Feature Confirmation (Max 25 pts)
        has_bos = candidate.features_snapshot.get("has_bos", 0.0) > 0
        has_choch = candidate.features_snapshot.get("has_choch", 0.0) > 0
        if has_bos or has_choch:
            score += 25.0
            reasons.append("Structural SMC BOS/CHoCH Alignment [+25pts]")
        else:
            score += 10.0
            reasons.append("Base Moving Average Trend Alignment [+10pts]")

        # 4. Low Spread & Execution Quality Guard (Max 15 pts)
        max_spread = 3.0 if "XAU" in candidate.symbol else 2.0
        if current_spread_pips <= max_spread:
            score += 15.0
            reasons.append(f"Optimal Low Spread ({current_spread_pips:.1f} pips) [+15pts]")
        else:
            critique_notes.append(f"Elevated Spread ({current_spread_pips:.1f} pips > {max_spread})")

        # 5. Session & Liquidity Check (Max 10 pts)
        now = datetime.now(timezone.utc)
        hour = now.hour
        # London (7-15 UTC) & New York (13-21 UTC) Overlap Peak Liquidity
        if 7 <= hour <= 20:
            score += 10.0
            reasons.append("Peak Institutional Session Liquidity [+10pts]")
        else:
            critique_notes.append("Off-peak Asian session liquidity")

        # Grade Assignment
        if score >= 75.0:
            grade = "A+"
        elif score >= 60.0:
            grade = "B"
        else:
            grade = "C"

        candidate.composite_score = score
        candidate.quality_grade = grade

        # Self-Critic Adversarial Vetoes
        # Veto 1: Reject B and C grade setups (Only A+ trade setups allowed)
        if grade != "A+":
            justification = f"REJECTED [Grade {grade} Score {score:.0f}/100]: Setup quality is below A+ institutional threshold ({self.min_composite_score}). Flaws: {', '.join(critique_notes)}"
            candidate.self_critic_justification = justification
            logger.info(f"🛡️ [Self-Critic Veto] {candidate.candidate_id}: {justification}")
            return False, score, grade, justification

        # Veto 2: Anti-Stacking & Correlation Veto
        for pos in active_positions:
            if pos.get("symbol") == candidate.symbol:
                pos_type = pos.get("type", 0)
                cand_type = 0 if candidate.signal_type == SignalType.BUY else 1
                if pos_type == cand_type:
                    justification = f"REJECTED [Anti-Stacking Veto]: Active position already exists on {candidate.symbol} in direction {candidate.signal_type.name}."
                    candidate.self_critic_justification = justification
                    logger.info(f"🛡️ [Self-Critic Veto] {candidate.candidate_id}: {justification}")
                    return False, score, grade, justification

        # Veto 3: Recent Loss Streak Protection (Revenge Trading Guard)
        if len(recent_trade_results) >= 2 and sum(recent_trade_results[-2:]) < 0:
            if ai_calibrated_prob < 0.65:
                justification = f"REJECTED [Revenge Trade Guard]: Recent loss streak detected. Requires AI conviction >= 0.65 (Current: {ai_calibrated_prob:.2f})."
                candidate.self_critic_justification = justification
                logger.info(f"🛡️ [Self-Critic Veto] {candidate.candidate_id}: {justification}")
                return False, score, grade, justification

        justification = f"APPROVED [Grade A+ Score {score:.0f}/100]: High-conviction setup passed all institutional gates ({', '.join(reasons)})"
        candidate.self_critic_justification = justification
        logger.info(f"✅ [Self-Critic Approval] {candidate.candidate_id}: {justification}")
        return True, score, grade, justification
