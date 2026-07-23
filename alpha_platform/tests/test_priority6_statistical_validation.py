import unittest
import numpy as np
from alpha_platform.statistical_validation.advanced_validation import (
    ExpectancyCalculator,
    BootstrapResampler,
    WalkForwardOOSEfficiencyAnalyzer
)

class TestPriority6StatisticalValidationUpgrade(unittest.TestCase):
    def setUp(self):
        self.expectancy_calc = ExpectancyCalculator()
        self.bootstrap = BootstrapResampler(num_bootstraps=500)
        self.wf_analyzer = WalkForwardOOSEfficiencyAnalyzer()

    def test_expectancy_and_ratios_calculation(self):
        returns = np.array([10.0, -5.0, 15.0, -5.0, 20.0, -10.0, 12.0])
        metrics = self.expectancy_calc.compute_metrics(returns, initial_capital=10000.0)

        self.assertGreater(metrics.expectancy_per_trade, 0.0)
        self.assertGreater(metrics.profit_factor, 1.0)
        self.assertGreater(metrics.win_rate, 0.5)
        self.assertGreaterEqual(metrics.max_drawdown_dollars, 0.0)

    def test_bootstrap_confidence_intervals(self):
        returns = np.random.normal(2.0, 5.0, 50)
        boot_res = self.bootstrap.run_bootstrap(returns)

        self.assertIsNotNone(boot_res)
        self.assertLessEqual(boot_res.expectancy_ci_lower, boot_res.expectancy_ci_upper)

    def test_walk_forward_oos_efficiency(self):
        is_rets = np.array([10.0, 12.0, -4.0, 8.0] * 10)
        oos_rets = np.array([8.0, 10.0, -5.0, 6.0] * 10)
        res = self.wf_analyzer.compute_oos_efficiency(is_rets, oos_rets)

        self.assertIn("wf_efficiency_ratio", res)
        self.assertIn("passed", res)

if __name__ == "__main__":
    unittest.main()
