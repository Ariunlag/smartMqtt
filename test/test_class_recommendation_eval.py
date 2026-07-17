import sys
import unittest
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = PROJECT_ROOT / "notebook"
sys.path.insert(0, str(NOTEBOOK_DIR))

from class_recommendation_eval import (  # noqa: E402
    build_pair_table,
    dataset_summary,
    evaluate_vector_recommendations,
    load_dataset,
    make_flat_representations,
    optimal_pair_similarity,
)


class DatasetValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_dataset()

    def test_dataset_has_expected_streams_and_classes(self):
        self.assertEqual(len(self.data), 29)
        self.assertEqual(self.data["topic"].nunique(), 29)
        self.assertEqual(self.data["true_class"].nunique(), 6)

    def test_every_class_spans_multiple_manufacturers(self):
        summary = dataset_summary(self.data)
        self.assertTrue((summary["manufacturers"] >= 2).all())

    def test_pair_table_preserves_all_payload_fields(self):
        pairs = build_pair_table(self.data)
        expected = sum(len(payload) for payload in self.data["payload"])
        self.assertEqual(len(pairs), expected)
        self.assertEqual(set(pairs["topic"]), set(self.data["topic"]))


class RepresentationTests(unittest.TestCase):
    def test_numeric_key_only_drops_measurement_value(self):
        representations = make_flat_representations(
            {"temperature_celsius": 22.5, "status": "active"}
        )
        text = representations["flat_numeric_key_only"]
        self.assertIn("temperature celsius", text)
        self.assertNotIn("22.5", text)
        self.assertIn("status: active", text)

    def test_boolean_is_kept_as_categorical_value(self):
        representations = make_flat_representations({"online": True})
        self.assertEqual(representations["flat_numeric_key_only"], "online: true")

    def test_optimal_matching_penalizes_unmatched_fields(self):
        left = np.asarray([[1.0, 0.0], [1.0, 0.0]])
        right = np.asarray([[1.0, 0.0]])
        self.assertAlmostEqual(optimal_pair_similarity(left, right), 0.5)


class RecommendationEvaluationTests(unittest.TestCase):
    def test_vendor_held_out_class_prototypes_can_recover_clear_classes(self):
        data = load_dataset().copy()
        classes = sorted(data["true_class"].unique())
        class_to_index = {name: index for index, name in enumerate(classes)}
        matrix = np.zeros((len(data), len(classes)))
        for row_index, class_name in enumerate(data["true_class"]):
            matrix[row_index, class_to_index[class_name]] = 1.0

        metrics, cases = evaluate_vector_recommendations(
            matrix,
            data,
            "synthetic_perfect",
        )
        self.assertEqual(metrics["top1_accuracy"], 1.0)
        self.assertEqual(metrics["macro_f1"], 1.0)
        self.assertTrue(cases["correct"].all())


if __name__ == "__main__":
    unittest.main()
