"""Small checks for the all-topics publisher.

These tests intentionally derive expectations from the dataset instead of assuming a
fixed sensor count. The publisher must work the same way whether the dataset contains
1, 16, 56, or more topics.
"""
from contextlib import redirect_stdout
import io
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish


class PublisherTests(unittest.TestCase):
    def test_dataset_has_unique_valid_topics_and_variable_tags(self):
        topics = publish.load_topics()

        self.assertGreater(len(topics), 0)
        self.assertEqual(len({sensor["topic"] for sensor in topics}), len(topics))
        self.assertGreater(len({len(sensor["tags"]) for sensor in topics}), 1)

        for sensor in topics:
            self.assertEqual(set(sensor), {"topic", "tags", "fields"})
            self.assertTrue(sensor["topic"])
            self.assertFalse(any(char in sensor["topic"] for char in ("+", "#", "\0")))
            self.assertTrue(sensor["tags"])
            self.assertTrue(sensor["fields"])
            self.assertTrue(
                all(isinstance(value, str) for value in sensor["tags"].values())
            )

    def test_readings_change_but_tags_do_not(self):
        for index, sensor in enumerate(publish.load_topics()):
            first = publish.make_payload(sensor, 0, index)
            readings = [
                publish.make_payload(sensor, step, index)
                for step in (0, 10, 20, 30)
            ]
            self.assertTrue(all(row["tags"] == first["tags"] for row in readings))
            self.assertGreater(
                len({json.dumps(row["fields"]) for row in readings}),
                1,
            )
            self.assertEqual(set(first), {"tags", "fields", "timestamp"})

    def test_preview_is_offline_and_contains_every_sensor(self):
        output = io.StringIO()
        with (
            patch.object(
                publish,
                "urlopen",
                side_effect=AssertionError("dry-run must stay offline"),
            ),
            redirect_stdout(output),
        ):
            publish.main(["--dry-run"])

        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        expected_topics = [sensor["topic"] for sensor in publish.load_topics()]
        self.assertEqual([row["topic"] for row in rows], expected_topics)

    def test_every_sensor_is_subscribed_and_published(self):
        client = MagicMock()
        client.publish.return_value.is_published.return_value = True

        with (
            patch("paho.mqtt.client.Client", return_value=client),
            patch.object(publish, "urlopen") as request,
            redirect_stdout(io.StringIO()),
        ):
            publish.main(["--rounds", "1"])

        topics = publish.load_topics()
        self.assertEqual(request.call_count, len(topics))
        self.assertTrue(
            all(
                call.args[0].full_url == "http://localhost:8000/api/subscribe"
                for call in request.call_args_list
            )
        )
        self.assertEqual(
            [call.args[0] for call in client.publish.call_args_list],
            [sensor["topic"] for sensor in topics],
        )
        client.disconnect.assert_called_once()
        client.loop_stop.assert_called_once()

    def test_default_runs_continuously_until_interrupted(self):
        client = MagicMock()
        client.publish.return_value.is_published.return_value = True

        with (
            patch("paho.mqtt.client.Client", return_value=client),
            patch.object(publish, "urlopen"),
            patch.object(publish.time, "sleep", side_effect=KeyboardInterrupt),
            redirect_stdout(io.StringIO()),
        ):
            publish.main([])

        self.assertEqual(client.publish.call_count, len(publish.load_topics()))
        client.disconnect.assert_called_once()
        client.loop_stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
