import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from sklearn.ensemble import GradientBoostingClassifier
from alpha_platform.meta_labeling.purged_cv import PurgedGroupTimeSeriesSplit
from alpha_platform.meta_labeling.calibration import ProbabilityCalibrator
from alpha_platform.config.logging_config import logger

class MetaLabelModelTrainer:
    def __init__(self, min_confidence_threshold: float = 0.55):
        self.min_confidence_threshold = min_confidence_threshold
        self.model: Optional[Any] = None
        self.calibrator = ProbabilityCalibrator()
        self.feature_names: List[str] = []

    def train(self, X: pd.DataFrame, y: pd.Series) -> Dict[str, Any]:
        self.feature_names = list(X.columns)
        cv = PurgedGroupTimeSeriesSplit(n_splits=5, pct_embargo=0.01)
        
        oof_predictions = np.zeros(len(X))
        
        for train_idx, val_idx in cv.split(X, y):
            X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
            X_val = X.iloc[val_idx]
            
            clf = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42)
            clf.fit(X_train, y_train)
            oof_predictions[val_idx] = clf.predict_proba(X_val)[:, 1]

        # Train final model on full set
        self.model = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42)
        self.model.fit(X, y)

        # Calibrate probabilities using OOF predictions
        cal_probs, best_method, brier_score = self.calibrator.fit_and_calibrate(oof_predictions, y.values)

        logger.info(f"Meta-labeling model trained. Best calibration method: '{best_method}', Brier Score: {brier_score:.4f}")

        return {
            "brier_score": brier_score,
            "calibration_method": best_method,
            "feature_count": len(self.feature_names)
        }

    def predict_trade_quality(self, features: Dict[str, float]) -> Tuple[bool, float, float]:
        if self.model is None:
            logger.warning("[AI Meta-Labeler] Predict called on UNTRAINED model. Vetoing trade for safety.")
            return False, 0.0, 0.0

        df_feat = pd.DataFrame([features]).reindex(columns=self.feature_names, fill_value=0.0)
        raw_prob = float(self.model.predict_proba(df_feat)[0, 1])
        calibrated_prob = self.calibrator.calibrate(raw_prob)
        is_approved = calibrated_prob >= self.min_confidence_threshold

        return is_approved, raw_prob, calibrated_prob
