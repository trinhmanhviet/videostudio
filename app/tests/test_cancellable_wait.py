import threading
import time
import unittest

from videostudio.core import Cancelled
from videostudio.providers import wait_cancellable


class CancellableWaitTests(unittest.TestCase):
    def test_cancel_interrupts_a_long_blocking_call(self):
        release = threading.Event()
        cancelled_at = time.monotonic() + 0.3

        def check():
            if time.monotonic() > cancelled_at:
                raise Cancelled()
        started = time.monotonic()
        with self.assertRaises(Cancelled):
            wait_cancellable(lambda: release.wait(30), check, poll=0.05)
        self.assertLess(time.monotonic() - started, 2)
        release.set()

    def test_returns_value_and_reraises_call_errors(self):
        self.assertEqual(wait_cancellable(lambda: 42, lambda: None), 42)
        with self.assertRaises(ValueError):
            wait_cancellable(lambda: (_ for _ in ()).throw(ValueError('boom')), lambda: None)


if __name__ == '__main__':
    unittest.main()
