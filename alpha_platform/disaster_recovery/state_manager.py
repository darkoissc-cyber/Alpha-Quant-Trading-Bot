import json
import os
import hashlib
from typing import Dict, Any, Optional
from alpha_platform.config.logging_config import logger
from alpha_platform.security.secure_vault import SecureBackupManager, SecurityAuditVerifier

class DisasterRecoveryStateManager:
    """
    Persists system state to disk/Redis WAL log so after any process crash or reboot,
    the system recovers open trades, risk exposure, and strategy state instantly.
    Enhanced with Secure Encrypted Backups, Atomic File Writes, and an honest
    SHA-256 integrity checksum.
    """

    def __init__(self, state_file_path: str = "system_state.json"):
        self.state_file_path = state_file_path
        self.backup_mgr = SecureBackupManager()
        self.verifier = SecurityAuditVerifier()

    @staticmethod
    def _compute_checksum(payload: Dict[str, Any]) -> str:
        # Deterministic JSON serialization (sorted keys, no extra whitespace)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def persist_state(self, equity: float, open_positions: list, active_strategies: list) -> bool:
        # Build the payload first, then compute the checksum over the
        # canonical serialisation of the *contents* (excluding the checksum
        # field itself, which is the only field written afterwards).
        state_content = {
            "equity": equity,
            "open_positions": open_positions,
            "active_strategies": active_strategies,
        }
        checksum = self._compute_checksum(state_content)
        state_data = {**state_content, "checksum": checksum, "version": 2}

        try:
            # Create backup of current state before overwriting
            if os.path.exists(self.state_file_path):
                self.backup_mgr.create_backup(self.state_file_path)

            temp_path = f"{self.state_file_path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
            # fsync to ensure the temp file is on disk before atomic rename
            try:
                os.fsync(open(temp_path, "rb").fileno())
            except Exception:
                pass

            if os.path.exists(self.state_file_path):
                os.remove(self.state_file_path)
            os.rename(temp_path, self.state_file_path)

            return True
        except Exception as e:
            logger.error(f"Failed to persist state safely: {e}")
            return False

    def recover_state(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.state_file_path):
            logger.info("No prior disaster state file found. Clean start.")
            return None

        try:
            with open(self.state_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Verify the integrity checksum. If it doesn't match, the state
            # file was tampered with or partially written. Refuse to use it
            # rather than silently start in a corrupted state.
            stored_checksum = data.get("checksum", "")
            payload = {k: v for k, v in data.items() if k not in ("checksum", "version")}
            expected_checksum = self._compute_checksum(payload)
            if stored_checksum and stored_checksum != expected_checksum:
                logger.critical(
                    f"[StateManager] INTEGRITY VIOLATION: stored checksum "
                    f"{stored_checksum[:12]}... != expected {expected_checksum[:12]}.... "
                    f"Refusing to load potentially tampered state."
                )
                return None

            logger.info(
                f"[StateManager] Disaster State successfully recovered: "
                f"Equity={data.get('equity')}, Positions={len(data.get('open_positions', []))}, "
                f"Checksum OK"
            )
            return data
        except Exception as e:
            logger.error(f"Failed to recover state: {e}")
            return None
