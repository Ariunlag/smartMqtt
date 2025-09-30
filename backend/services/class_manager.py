from .store.relation_store import class_store

class ClassManager:
    def __init__(self, store=class_store):
        self.store = store

    def list_classes(self):
        return self.store.get_all()

    def create_class(self, name: str, measurements: list[str]):
        existing = next((c for c in self.store.get_all() if c["name"] == name), None)
        if existing:
            raise ValueError(f"Class '{name}' already exists")
        return self.store.add({"name": name, "topics": measurements})

    def update_class(self, name: str, measurements: list[str]):
        updated = self.store.update("name", name, {"topics": measurements})
        if not updated:
            raise ValueError(f"Class '{name}' not found")
        return True

    def delete_class(self, name: str):
        removed = self.store.remove("name", name)
        if not removed:
            raise ValueError(f"Class '{name}' not found")
        return True

# Singleton
class_manager = ClassManager()
