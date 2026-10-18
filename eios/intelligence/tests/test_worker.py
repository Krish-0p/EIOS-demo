"""Kafka commit failures must preserve replay and continue group polling."""
import unittest
from unittest.mock import MagicMock

from confluent_kafka import KafkaError, KafkaException
from intelligence.main import commit_pending


class CommitTests(unittest.TestCase):
    def test_transient_coordination_failure_is_retried_until_acknowledged(self):
        consumer=MagicMock()
        consumer.commit.side_effect=[KafkaException(KafkaError(KafkaError.NOT_COORDINATOR)),None]
        self.assertFalse(commit_pending(consumer))
        self.assertTrue(commit_pending(consumer))
        self.assertEqual(consumer.commit.call_count,2)

    def test_no_assigned_offset_is_not_a_worker_failure(self):
        consumer=MagicMock()
        consumer.commit.side_effect=KafkaException(KafkaError(KafkaError._NO_OFFSET))
        self.assertTrue(commit_pending(consumer))

    def test_permanent_authorization_failure_is_not_hidden(self):
        consumer=MagicMock()
        consumer.commit.side_effect=KafkaException(KafkaError(KafkaError.GROUP_AUTHORIZATION_FAILED))
        with self.assertRaises(KafkaException):
            commit_pending(consumer)


if __name__=='__main__':
    unittest.main()
