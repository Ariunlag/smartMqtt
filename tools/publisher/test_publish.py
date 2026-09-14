"""Small checks for the all-topics publisher."""
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
    def test_simple_dataset_has_unique_topics_and_variable_tags(self):
        topics = publish.load_topics()
        self.assertEqual(len(topics), 56)
        self.assertGreater(len({len(s["tags"]) for s in topics}), 1)
        for sensor in topics:
            self.assertEqual(set(sensor), {"topic", "tags", "fields"})
            self.assertTrue(all(isinstance(value, str) for value in sensor["tags"].values()))

    def test_readings_change_but_tags_do_not(self):
        for i, sensor in enumerate(publish.load_topics()):
            first = publish.make_payload(sensor, 0, i)
            readings = [publish.make_payload(sensor, step, i) for step in (0, 10, 20, 30)]
            self.assertTrue(all(row["tags"] == first["tags"] for row in readings))
            self.assertGreater(len({json.dumps(row["fields"]) for row in readings}), 1)
            self.assertEqual(set(first), {"tags", "fields", "timestamp"})

    def test_role_swap_keeps_key_and_value_sets_but_changes_associations(self):
        topics = publish.load_topics()
        left, right = topics[40]["tags"], topics[44]["tags"]
        self.assertEqual(set(left), set(right))
        self.assertEqual(sorted(left.values()), sorted(right.values()))
        self.assertNotEqual(left, right)

    def test_preview_is_offline_and_contains_every_sensor(self):
        output = io.StringIO()
        with patch.object(publish, "urlopen", side_effect=AssertionError("offline")), redirect_stdout(output):
            publish.main(["--dry-run"])
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r["topic"] for r in rows], [s["topic"] for s in publish.load_topics()])

    def test_every_sensor_is_subscribed_and_published(self):
        client = MagicMock()
        client.publish.return_value.is_published.return_value = True
        with patch("paho.mqtt.client.Client", return_value=client), patch.object(publish, "urlopen") as request, redirect_stdout(io.StringIO()):
            publish.main(["--rounds", "1"])
        topics = publish.load_topics()
        self.assertEqual(request.call_count, 56)
        self.assertTrue(all(c.args[0].full_url == "http://localhost:8000/api/subscribe" for c in request.call_args_list))
        self.assertEqual([c.args[0] for c in client.publish.call_args_list], [s["topic"] for s in topics])
        client.disconnect.assert_called_once()
        client.loop_stop.assert_called_once()

    def test_default_runs_until_ctrl_c(self):
        client = MagicMock()
        with patch("paho.mqtt.client.Client", return_value=client), patch.object(publish, "urlopen"), patch.object(publish.time, "sleep", side_effect=KeyboardInterrupt), redirect_stdout(io.StringIO()):
            publish.main([])
        self.assertEqual(client.publish.call_count, 56)
        client.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
