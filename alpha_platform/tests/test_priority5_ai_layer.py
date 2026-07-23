import unittest
import numpy as np
import pandas as pd
from alpha_platform.meta_labeling.advanced_ai import (
    DatasetValidator,
    DataDriftDetector,
    FeatureImportanceExplainer,
    AutoRetrainingPipeline
)
from alpha_platform.meta_labeling.model_trainer import MetaLabelModelTrainer

class TestPriority5AILayerUpgrade(unittest.TestCase):
    def setUp(self):
        self.validator = DatasetValidator()
        self.drift_detector = DataDriftDetector()
        self.pipeline = AutoRetrainingPipeline()

    def test_dataset_validation(self):
        df_valid = pd.DataFrame({"f1": [1.0] * 40, "f2": [2.0] * 40})
        res = self.validator.validate_dataset(df_valid)
        self.assertTrue(res.is_valid)

        df_invalid = pd.DataFrame({"f1": [1.0, np.nan, 3.0], "f2": [2.0, np.inf, 4.0]})
        res_inv = self.validator.validate_dataset(df_invalid)
        self.assertFalse(res_inv.is_valid)
        self.assertGreater(len(res_inv.errors), 0)

    def test_drift_detection(self):
        ref_df = pd.DataFrame({"f1": np.random.normal(0, 1, 100)})
        curr_df_normal = pd.DataFrame({"f1": np.random.normal(0, 1, 100)})
        curr_df_drift = pd.DataFrame({"f1": np.random.normal(5, 1, 100)})

        res_no_drift = self.drift_detector.detect_drift(ref_df, curr_df_normal)
        self.assertFalse(res_no_drift.is_drift_detected)

        res_drift = self.drift_detector.detect_drift(ref_df, curr_df_drift)
        self.assertTrue(res_drift.is_drift_detected)

    def test_auto_retraining_pipeline(self):
        X = pd.DataFrame({
            "f1": np.random.normal(0, 1, 50),
            "f2": np.random.normal(1, 2, 50)
        })
        y = pd.Series([1 if i % 2 == 0 else 0 for i in range(50)])

        res = self.pipeline.run_retraining_cycle(X, y)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertIn("model_id", res)
        self.assertIn("brier_score", res)

if __name__ == "__main__":
    unittest.main()
