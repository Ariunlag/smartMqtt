from services.duplicate.canonicalization_service import DuplicateCanonicalizationService


class CapturingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((" ".join(sql.split()), params))


def test_duplicate_reconciliation_does_not_write_retired_tag_groups():
    conn = CapturingConnection()

    DuplicateCanonicalizationService._reconcile_relations(conn, "canonical", ("alias",))

    sql = " ".join(statement for statement, _ in conn.statements)
    assert "tag_group_topics" not in sql
    assert "INSERT INTO class_topics" in sql
    assert "DELETE FROM class_topics" in sql
    assert "DELETE FROM streams" in sql
