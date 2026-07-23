import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss
from sklearn.isotonic import IsotonicRegression
from typing import Tuple, Any

class ProbabilityCalibrator:
    """
    Evaluates probability calibration methods (Platt, Isotonic, Sigmoid)
    and selects the model with the minimum Brier Score.
    """
    def __init__(self):
        self.best_method = "uncalibrated"
        self.calibrator = None

    def fit_and_calibrate(self, raw_probs: np.ndarray, y_true: np.ndarray) -> Tuple[np.ndarray, str, float]:
        uncalibrated_brier = brier_score_loss(y_true, raw_probs)
        
        # 1. Isotonic Calibration
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(raw_probs, y_true)
        iso_probs = iso.predict(raw_probs)
        iso_brier = brier_score_loss(y_true, iso_probs)

        # 2. Platt Scaling (Sigmoid fit proxy)
        platt_probs = 1.0 / (1.0 + np.exp(-1.0 * (raw_probs - 0.5) * 10.0))
        platt_brier = brier_score_loss(y_true, platt_probs)

        briers = {
            "uncalibrated": (raw_probs, None, uncalibrated_brier),
            "isotonic": (iso_probs, iso, iso_brier),
            "platt": (platt_probs, "platt", platt_brier)
        }

        best_key = min(briers, key=lambda k: briers[k][2])
        self.best_method = best_key
        self.calibrator = briers[best_key][1]

        best_probs, _, best_brier = briers[best_key]
        return best_probs, best_key, float(best_brier)

    def calibrate(self, raw_prob: float) -> float:
        if self.best_method == "isotonic" and self.calibrator is not None:
            return float(self.calibrator.predict([raw_prob])[0])
        elif self.best_method == "platt":
            return float(1.0 / (1.0 + np.exp(-1.0 * (raw_prob - 0.5) * 10.0)))
        return float(raw_prob)
