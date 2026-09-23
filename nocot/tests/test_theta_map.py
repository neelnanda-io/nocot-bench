"""Regression checks for the bounded MAP, including non-concave posteriors.

Run offline with either pytest or python -m nocot.tests.test_theta_map.
"""
import math
import random
import unittest

from nocot import place as P


def log_posterior(theta, counts, table, prior_sd=3.0):
    """Direct evaluation of the documented objective, independent of the solver."""
    value = -theta * theta / (2 * prior_sd * prior_sd)
    for rid, (k, n) in counts.items():
        b, c, w, _size, _domain = table[rid]
        p = c + (1 - c) / (1 + math.exp(b - theta))
        value += w * (k * math.log(p) + (n - k) * math.log1p(-p))
    return value


def golden_maximum(fn, lo, hi):
    """Independent local reference, used only on a specified unimodal bracket."""
    ratio = (math.sqrt(5) - 1) / 2
    left, right = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
    fl, fr = fn(left), fn(right)
    while hi - lo > 1e-8:
        if fl > fr:
            hi, right, fr = right, left, fl
            left = hi - ratio * (hi - lo)
            fl = fn(left)
        else:
            lo, left, fl = left, right, fr
            right = lo + ratio * (hi - lo)
            fr = fn(right)
    return (lo + hi) / 2


class ThetaMapTests(unittest.TestCase):
    def test_frozen_rungs_can_have_a_better_second_mode(self):
        # Synthetic responses, using unmodified published rung parameters.
        counts = {
            "sudoku:d3": (14, 21), "recon:t4hard": (7, 20),
            "shortpath:tier3_12n": (25, 25), "cemc:d3": (3, 10),
        }
        table = {rid: P.RUNGS[rid] for rid in counts}
        objective = lambda t: log_posterior(t, counts, table)
        reference = golden_maximum(objective, 3.0, 4.5)
        theta, domains = P.theta_map(counts, table=table)
        self.assertAlmostEqual(theta, reference, places=6)
        self.assertEqual(domains, {"sudoku", "recon", "shortpath", "cemc"})
        # The old single bisection converged to this inferior local maximum.
        self.assertGreater(objective(theta) - objective(-1.45379221484734), 8.9)
        self.assertGreaterEqual(
            objective(theta), max(objective(-12 + i / 100) for i in range(2401))
        )

    def test_zero_floor_and_nondefault_prior(self):
        counts = {"r": (7, 20)}
        table = {"r": (1.25, 0.0, 0.7, 20, "test")}
        for prior_sd in (0.5, 3.0, 10.0):
            with self.subTest(prior_sd=prior_sd):
                objective = lambda t: log_posterior(t, counts, table, prior_sd)
                reference = golden_maximum(objective, -12, 12)
                theta, _ = P.theta_map(counts, prior_sd=prior_sd, table=table)
                self.assertAlmostEqual(theta, reference, places=6)

    def test_both_parameter_boundaries_remain_available(self):
        table = {"r": (0.0, 0.25, 1.0, 1000000, "test")}
        for k, expected in ((0, -12.0), (1000000, 12.0)):
            with self.subTest(k=k):
                theta, _ = P.theta_map({"r": (k, 1000000)}, table=table)
                self.assertEqual(theta, expected)

    def test_nothing_measured_is_not_zero_ability(self):
        self.assertEqual(P.theta_map({"unknown": (1, 1)}), (None, set()))
        self.assertEqual(P.theta_map({"sudoku:d3": (0, 0)}), (None, set()))

    def test_synthetic_response_patterns_beat_an_independent_dense_grid(self):
        rng = random.Random(12022)
        for trial in range(30):
            ids = rng.sample(list(P.RUNGS), rng.randint(1, 5))
            table = {rid: P.RUNGS[rid] for rid in ids}
            counts = {rid: (rng.randrange(table[rid][3] + 1), table[rid][3])
                      for rid in ids}
            with self.subTest(trial=trial):
                theta, _ = P.theta_map(counts, table=table)
                objective = lambda t: log_posterior(t, counts, table)
                grid_best = max(objective(-12 + i / 50) for i in range(1201))
                self.assertGreaterEqual(objective(theta) + 1e-9, grid_best)


if __name__ == "__main__":
    unittest.main()
