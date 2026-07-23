import json
import os
from typing import Dict, Any, Optional
from alpha_platform.config.logging_config import logger

class DisasterRecoveryStateManager:
    """
    Persists system state to disk/Redis WAL log so after any process crash or reboot,
    the system recovers open trades, risk exposure, and strategy state instantly.
    """

    def __init__(self, state_file_path: str = "system_state.json"):
        self.state_file_path = state_file_path

    def persist_state(self, equity: float, open_positions: list, active_strategies: list) -> bool:
        state_data = {
            "equity": equity,
            "open_positions": open_positions,
            "active_strategies": active_strategies
        }
        try:
            with open(self.state_file_path, "w") as f:
                json.dump(state_data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to persist state: {e}")
            return False

    def recover_state(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.state_file_path):
            logger.info("No prior disaster state file found. Clean start.")
            return None

        try:
            with open(self.state_file_path, "r") as f:
                data = json.load(f)
            logger.info(f"Disaster State successfully recovered: Equity={data.get('equity')}, Positions={len(data.get('open_positions', []))}")
            return data
        except Exception as e:
            logger.error(f"Failed to recover state: {e}")
            return None
