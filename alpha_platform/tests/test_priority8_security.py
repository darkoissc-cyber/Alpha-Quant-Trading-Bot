import unittest
import os
from alpha_platform.security.secure_vault import (
    SecretsVault,
    SecurityAuditVerifier,
    SecureBackupManager
)
from alpha_platform.disaster_recovery.state_manager import DisasterRecoveryStateManager

class TestPriority8SecurityUpgrade(unittest.TestCase):
    def setUp(self):
        self.vault = SecretsVault(master_key="TestMasterKey123")
        self.verifier = SecurityAuditVerifier()
        self.backup_mgr = SecureBackupManager(backup_dir="test_backups")
        self.state_mgr = DisasterRecoveryStateManager(state_file_path="test_state.json")

    def tearDown(self):
        for path in ["test_state.json", "test_state.json.tmp", "test_source.txt"]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        if os.path.exists("test_backups"):
            import shutil
            try:
                shutil.rmtree("test_backups")
            except Exception:
                pass

    def test_secrets_encryption_decryption(self):
        secret = "ExnessSuperSecretPassword2026!"
        encrypted = self.vault.encrypt_secret(secret)
        self.assertNotEqual(secret, encrypted)

        decrypted = self.vault.decrypt_secret(encrypted)
        self.assertEqual(secret, decrypted)

    def test_integrity_verifier(self):
        with open("test_source.txt", "w") as f:
            f.write("Alpha Quant System Integrity Test")

        hash1 = self.verifier.compute_file_hash("test_source.txt")
        self.assertTrue(self.verifier.verify_integrity("test_source.txt", hash1))

    def test_secure_backup_and_recovery(self):
        with open("test_source.txt", "w") as f:
            f.write("Important State Data")

        backup_file = self.backup_mgr.create_backup("test_source.txt")
        self.assertIsNotNone(backup_file)
        self.assertTrue(os.path.exists(backup_file))

        # Test recovery
        res = self.backup_mgr.restore_backup(backup_file, "test_restored.txt")
        self.assertTrue(res)
        with open("test_restored.txt", "r") as f:
            content = f.read()
        self.assertEqual(content, "Important State Data")

        if os.path.exists("test_restored.txt"):
            os.remove("test_restored.txt")

    def test_state_manager_persistence(self):
        res = self.state_mgr.persist_state(equity=10500.0, open_positions=[], active_strategies=["STRAT_1"])
        self.assertTrue(res)
        
        recovered = self.state_mgr.recover_state()
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["equity"], 10500.0)

if __name__ == "__main__":
    unittest.main()
