"""Checks for the continuous random-noise MQTT publisher."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish

HERE = Path(__file__).resolve().parent
DATASETS = (
    HERE / "dataset.json",
    HERE / "dataset_old_synthetic.json",
    HERE / "dataset_ahmed_real_mix.json",
)


class PublisherTests(unittest.TestCase):
    def test_all_bundled_datasets_are_valid(self):
        for dataset in DATASETS:
            with self.subTest(dataset=dataset.name):
                topics = publish.load_topics(dataset)
                self.assertGreater(len(topics), 0)
                self.assertEqual(
                    len({sensor["topic"] for sensor in topics}),
                    len(topics),
                )
                for sensor in topics:
                    self.assertEqual(set(sensor), {"topic", "tags", "fields"})
                    self.assertTrue(sensor["topic"])
                    self.assertFalse(
                        any(char in sensor["topic"] for char in ("+", "#", "\0"))
                    )
                    self.assertTrue(sensor["tags"])
                    self.assertTrue(sensor["fields"])

    def test_random_noise_changes_numeric_values_but_not_metadata(self):
        for dataset in DATASETS:
            with self.subTest(dataset=dataset.name):
                for index, sensor in enumerate(publish.load_topics(dataset)):
                    first = publish.make_payload(sensor, 0, index)
                    later = publish.make_payload(sensor, 1, index)

                    self.assertEqual(first["tags"], sensor["tags"])
                    self.assertEqual(later["tags"], sensor["tags"])
                    self.assertEqual(set(first), {"tags", "fields", "timestamp"})
                    self.assertEqual(set(later), {"tags", "fields", "timestamp"})

                    numeric_names = [
                        name
                        for name, value in sensor["fields"].items()
                        if type(value) in (int, float)
                    ]
                    if numeric_names:
                        self.assertTrue(
                            any(
                                first["fields"][name] != later["fields"][name]
                                for name in numeric_names
                            )
                        )

    def test_same_seed_reproduces_same_noise(self):
        sensor = publish.load_topics(DATASETS[0])[0]
        left = publish.make_payload(sensor, 7, 0, seed=123)["fields"]
        right = publish.make_payload(sensor, 7, 0, seed=123)["fields"]
        different = publish.make_payload(sensor, 7, 0, seed=456)["fields"]

        self.assertEqual(left, right)
        self.assertNotEqual(left, different)

    def test_preview_uses_selected_dataset_and_stays_offline(self):
        dataset = HERE / "dataset_ahmed_real_mix.json"
        output = io.StringIO()

        with (
            patch.object(
                publish,
                "urlopen",
                side_effect=AssertionError("dry-run must stay offline"),
            ),
            redirect_stdout(output),
        ):
            publish.main(
                [
                    "--dataset",
                    str(dataset),
                    "--seed",
                    "77",
                    "--dry-run",
                ]
            )

        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        expected_topics = [
            sensor["topic"] for sensor in publish.load_topics(dataset)
        ]
        self.assertEqual([row["topic"] for row in rows], expected_topics)

    def test_every_sensor_is_subscribed_and_published(self):
        dataset = HERE / "dataset_old_synthetic.json"
        client = MagicMock()
        client.publish.return_value.is_published.return_value = True

        with (
            patch("paho.mqtt.client.Client", return_value=client),
            patch.object(publish, "urlopen") as request,
            redirect_stdout(io.StringIO()),
        ):
            publish.main(
                [
                    "--dataset",
                    str(dataset),
                    "--rounds",
                    "1",
                ]
            )

        topics = publish.load_topics(dataset)
        self.assertEqual(request.call_count, len(topics))
        self.assertTrue(
            all(
                call.args[0].full_url
                == "http://localhost:8000/api/subscribe"
                for call in request.call_args_list
            )
        )
        self.assertEqual(
            [call.args[0] for call in client.publish.call_args_list],
            [sensor["topic"] for sensor in topics],
        )
        client.disconnect.assert_called_once()
        client.loop_stop.assert_called_once()

    def test_default_runs_until_ctrl_c(self):
        client = MagicMock()
        client.publish.return_value.is_published.return_value = True

        with (
            patch("paho.mqtt.client.Client", return_value=client),
            patch.object(publish, "urlopen"),
            patch.object(
                publish.time,
                "sleep",
                side_effect=KeyboardInterrupt,
            ),
            redirect_stdout(io.StringIO()),
        ):
            publish.main([])

        self.assertEqual(
            client.publish.call_count,
            len(publish.load_topics()),
        )
        client.disconnect.assert_called_once()
        client.loop_stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
