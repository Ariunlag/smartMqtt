"""Lock-discipline regression coverage for pending candidate publication."""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from services.semantic import SemanticReviewRuntime, UnknownClusterCandidate


def test_register_candidate_reads_and_writes_pending_only_under_lock():
    runtime = SemanticReviewRuntime()
    count_lock = Lock()

    class Coordinator:
        def __init__(self):
            self.notifications = 0

        def mark_changed(self):
            assert not runtime._pending_lock._is_owned()
            with count_lock:
                self.notifications += 1

    class LockGuardedPending(dict):
        def get(self, key, default=None):
            assert runtime._pending_lock._is_owned()
            return super().get(key, default)

        def __getitem__(self, key):
            assert runtime._pending_lock._is_owned()
            return super().__getitem__(key)

        def __setitem__(self, key, value):
            assert runtime._pending_lock._is_owned()
            return super().__setitem__(key, value)

    coordinator = Coordinator()
    runtime.state_coordinator = coordinator
    runtime._pending = LockGuardedPending()
    candidates = tuple(
        UnknownClusterCandidate(
            representation_name="key_value",
            candidate_index=index,
            member_topics=(f"topic/{index % 8}",),
        )
        for index in range(256)
    )

    with ThreadPoolExecutor(max_workers=16) as executor:
        tuple(executor.map(runtime.register_candidate, candidates))

    pending = runtime.list_candidates()
    assert len(pending) == 8
    assert all(
        candidate.identity.representation_name == "key_value" for candidate in pending
    )
    assert coordinator.notifications >= 8
