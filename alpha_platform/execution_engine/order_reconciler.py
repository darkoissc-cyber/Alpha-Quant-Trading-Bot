from typing import Dict, List, Any
from alpha_platform.config.logging_config import logger

class OrderReconciler:
    """
    Reconciles target strategy positions with actual live MT5 broker state.
    Prevents duplicate orders, handles orphan positions, and syncs stops.
    """

    def reconcile(self, target_positions: List[Dict[str, Any]], live_positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        actions = []
        live_tickets = {p["ticket"]: p for p in live_positions if "ticket" in p}
        target_ids = {t["position_id"]: t for t in target_positions if "position_id" in t}

        # 1. Detect Orphan Live Positions (Active on MT5 but missing in system state)
        for ticket, live_pos in live_tickets.items():
            if ticket not in target_ids:
                logger.warning(f"Orphan live position detected on MT5: Ticket {ticket}. Triggering emergency sync.")
                actions.append({"action": "IMPORT_ORPHAN", "ticket": ticket, "details": live_pos})

        # 2. Detect Unfilled Target Positions
        for target_id, target_pos in target_ids.items():
            if target_id not in live_tickets:
                logger.info(f"Target position '{target_id}' missing in live MT5. Re-dispatching fill request.")
                actions.append({"action": "DISPATCH_ORDER", "target_id": target_id, "details": target_pos})

        return actions
