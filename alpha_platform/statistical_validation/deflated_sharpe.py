import numpy as np
from scipy.stats import norm, skew, kurtosis

class DeflatedSharpeRatioCalculator:
    """
    Marcos Lopez de Prado's Deflated Sharpe Ratio (DSR).
    Calculates DSR taking into account:
    - Number of trials N (strategy iterations tested)
    - Variance of trials
    - Non-normality (skewness & kurtosis)
    - Sample length T
    """

    @staticmethod
    def calculate_dsr(
        returns: np.ndarray,
        num_trials: int = 100,
        benchmark_sr: float = 0.0,
        annualization_factor: float = 252.0
    ) -> float:
        if len(returns) < 30:
            return 0.0

        std = np.std(returns)
        if std == 0:
            return 0.0

        mean = np.mean(returns)
        sr = (mean / std) * np.sqrt(annualization_factor)

        n = len(returns)
        sk = skew(returns)
        kt = kurtosis(returns)

        # Expected maximum Sharpe Ratio under Null Hypothesis of zero alpha across N trials
        euler_mascheroni = 0.5772156649
        expected_max_sr = benchmark_sr + np.sqrt(2.0 * np.log(num_trials)) - (euler_mascheroni / np.sqrt(2.0 * np.log(num_trials)))

        # Variance of Sharpe Ratio under non-normal returns
        var_sr = (1.0 + (0.5 * sr**2) - (sk * sr) + ((kt / 4.0) * sr**2)) / (n - 1)

        # DSR Statistic
        dsr_stat = (sr - expected_max_sr) / np.sqrt(var_sr)
        dsr_prob = norm.cdf(dsr_stat)

        return float(dsr_stat)
