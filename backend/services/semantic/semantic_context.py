"""Classification-context generation for cached semantic decisions."""

from __future__ import annotations

from contextlib import contextmanager
from threading import RLock


class SemanticContextGeneration:
    """Track changes that can invalidate cached scoring and decisions."""

    def __init__(self, generation: int = 0) -> None:
        self._validate(generation)
        self._generation = generation
        self._lock = RLock()
        self._restore_depth = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def advance(self) -> int:
        with self._lock:
            if not self._restore_depth:
                self._generation += 1
            return self._generation

    @contextmanager
    def restore(self, generation: int):
        """Suppress mutation increments and finish at an exact generation."""
        self._validate(generation)
        with self._lock:
            previous = self._generation
            self._restore_depth += 1
            try:
                yield
            except Exception:
                self._generation = previous
                raise
            else:
                self._generation = generation
            finally:
                self._restore_depth -= 1

    @staticmethod
    def _validate(generation: int) -> None:
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise TypeError("semantic context generation must be an integer")
        if generation < 0:
            raise ValueError("semantic context generation must be non-negative")
