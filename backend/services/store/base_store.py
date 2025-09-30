import json, os
from abc import ABC, abstractmethod
from typing import Any


class BaseStore(ABC):
    """Base persistence layer for JSON files."""

    def __init__(self, filepath: str, default: Any = None):
        self.filepath = filepath
        self._data = default if default is not None else []
        self.load()

    @abstractmethod
    def add(self, item: Any) -> Any: ...
    @abstractmethod
    def remove(self, item: Any) -> bool: ...

    def get_all(self):
        return list(self._data)

    def save(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except json.JSONDecodeError:
                self._data = []
        else:
            self._data = []


class ListStore(BaseStore):
    """Store for simple lists (e.g., topic strings)."""

    def add(self, item: str) -> str:
        if item not in self._data:
            self._data.append(item)
            self.save()
        return item

    def remove(self, item: str) -> bool:
        if item in self._data:
            self._data.remove(item)
            self.save()
            return True
        return False


class DictStore(BaseStore):
    def __init__(self, filepath: str, key_field: str = "id"):
        super().__init__(filepath, default=[])
        self.key_field = key_field

    def add(self, item: dict) -> dict:
        self._data.append(item)
        self.save()
        return item

    def remove(self, key: str) -> bool:
        for obj in self._data:
            if obj.get(self.key_field) == key:
                self._data.remove(obj)
                self.save()
                return True
        return False

    def update(self, key: str, updates: dict) -> bool:
        for obj in self._data:
            if obj.get(self.key_field) == key:
                obj.update(updates)
                self.save()
                return True
        return False
