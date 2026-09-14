"""Transactional PostgreSQL persistence for environment-local adaptation."""

from __future__ import annotations

import json
from contextlib import contextmanager

from services.database.postgres import postgres_client


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class AdaptiveStore:
    def __init__(self, environment_id, database=postgres_client):
        self.environment_id = environment_id
        self.database = database

    @contextmanager
    def transaction(self):
        with self.database.transaction() as conn:
            # Serialize edits/training activation for this environment, across workers.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                         ("adaptive:" + self.environment_id,))
            yield conn

    def topics(self):
        return self.database.fetch_all(
            "SELECT topic, fingerprint, tags, updated_at::text AS material_version FROM adaptive_topics WHERE environment_id=%s ORDER BY topic",
            (self.environment_id,))

    def topic_fingerprint(self, topic):
        row = self.database.fetch_one("SELECT fingerprint FROM adaptive_topics WHERE environment_id=%s AND topic=%s",
                                      (self.environment_id, topic))
        return row["fingerprint"] if row else None

    def material(self):
        rows = self.database.fetch_all("""
            SELECT topic, provider_id, provider_version, entity, embedding::text, payload
            FROM adaptive_evidence WHERE environment_id=%s ORDER BY topic, provider_id, entity
        """, (self.environment_id,))
        result = {}
        for row in rows:
            if row["embedding"] is not None:
                row["embedding"] = json.loads(row["embedding"])
            result.setdefault(row["topic"], {}).setdefault(row["provider_id"], []).append(row)
        return result

    def replace_material(self, topic, tags, fingerprint, records):
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO adaptive_topics(environment_id, topic, fingerprint, tags)
                VALUES (%s,%s,%s,%s::jsonb) ON CONFLICT(environment_id,topic)
                DO UPDATE SET fingerprint=EXCLUDED.fingerprint, tags=EXCLUDED.tags, updated_at=now()
            """, (self.environment_id, topic, fingerprint, encode(tags)))
            conn.execute("DELETE FROM adaptive_evidence WHERE environment_id=%s AND topic=%s",
                         (self.environment_id, topic))
            with conn.cursor() as cursor:
                cursor.executemany("""
                    INSERT INTO adaptive_evidence(environment_id,topic,provider_id,provider_version,
                                                  entity,embedding,payload)
                    VALUES (%s,%s,%s,%s,%s,%s::vector,%s::jsonb)
                """, [(self.environment_id, topic, r["provider_id"], r["provider_version"],
                        r["entity"], encode(r["embedding"]) if r.get("embedding") is not None else None,
                        encode(r["payload"])) for r in records])

    def groups(self, conn=None):
        sql = "SELECT group_id, revision, state FROM adaptive_groups WHERE environment_id=%s ORDER BY updated_at DESC"
        rows = (conn.execute(sql, (self.environment_id,)).fetchall() if conn else
                self.database.fetch_all(sql, (self.environment_id,)))
        return [dict(row["state"], group_id=row["group_id"], revision=row["revision"]) for row in rows]

    def replace_provider(self, topic, expected_fingerprint, provider_id, version, records):
        with self.transaction() as conn:
            row = conn.execute("SELECT fingerprint FROM adaptive_topics WHERE environment_id=%s AND topic=%s FOR UPDATE",
                               (self.environment_id, topic)).fetchone()
            if not row or row["fingerprint"] != expected_fingerprint:
                return False
            conn.execute("DELETE FROM adaptive_evidence WHERE environment_id=%s AND topic=%s AND provider_id=%s",
                         (self.environment_id, topic, provider_id))
            with conn.cursor() as cursor:
                cursor.executemany("""INSERT INTO adaptive_evidence
                    (environment_id,topic,provider_id,provider_version,entity,embedding,payload)
                    VALUES (%s,%s,%s,%s,%s,%s::vector,%s::jsonb)""",
                    [(self.environment_id, topic, provider_id, version, r["entity"],
                      encode(r["embedding"]) if r.get("embedding") is not None else None, encode(r["payload"])) for r in records])
            conn.execute("UPDATE adaptive_topics SET updated_at=now() WHERE environment_id=%s AND topic=%s",
                         (self.environment_id, topic))
            return True

    def put_group(self, conn, state):
        conn.execute("""
            INSERT INTO adaptive_groups(environment_id,group_id,revision,state)
            VALUES (%s,%s,%s,%s::jsonb) ON CONFLICT(environment_id,group_id)
            DO UPDATE SET revision=EXCLUDED.revision, state=EXCLUDED.state, updated_at=now()
        """, (self.environment_id, state["group_id"], state["revision"], encode(state)))

    def event(self, conn, event):
        return conn.execute("""
            INSERT INTO adaptive_events(event_id, environment_id, group_id, action, topic,
                                        label, evidence, details)
            VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb) RETURNING sequence
        """, (event["event_id"], self.environment_id, event["group_id"], event["action"],
               event.get("topic"), event.get("label"), encode(event.get("evidence", {})),
               encode(event.get("details", {})))).fetchone()["sequence"]

    def events(self):
        return self.database.fetch_all("""
            SELECT sequence,event_id::text,group_id,action,topic,label,evidence,details,created_at
            FROM adaptive_events WHERE environment_id=%s ORDER BY sequence
        """, (self.environment_id,))

    def model(self, manifest_id):
        row = self.database.fetch_one("""
            SELECT model FROM adaptive_models WHERE environment_id=%s AND manifest_id=%s
            ORDER BY version DESC LIMIT 1
        """, (self.environment_id, manifest_id))
        return row["model"] if row else None

    def put_model(self, manifest_id, model):
        with self.transaction() as conn:
            row = conn.execute("""
                SELECT COALESCE(max(version),0)+1 AS version FROM adaptive_models
                WHERE environment_id=%s AND manifest_id=%s
            """, (self.environment_id, manifest_id)).fetchone()
            model["version"] = row["version"]
            conn.execute("""
                INSERT INTO adaptive_models(environment_id,manifest_id,version,model)
                VALUES (%s,%s,%s,%s::jsonb)
            """, (self.environment_id, manifest_id, model["version"], encode(model)))

    def classes(self, conn=None):
        sql = """
            SELECT c.class_id,c.name,c.profile_version,
                   COALESCE(array_agg(ct.topic ORDER BY ct.position)
                            FILTER(WHERE ct.topic IS NOT NULL), ARRAY[]::text[]) AS topics
            FROM classes c LEFT JOIN class_topics ct ON ct.class_name=c.name
            WHERE c.recommendation_environment=%s OR c.recommendation_environment IS NULL
            GROUP BY c.name ORDER BY c.name
        """
        return (conn.execute(sql, (self.environment_id,)).fetchall() if conn else
                self.database.fetch_all(sql, (self.environment_id,)))

    def save_class(self, conn, name, members, class_id):
        found = conn.execute("SELECT class_id,recommendation_environment FROM classes WHERE name=%s FOR UPDATE",
                             (name,)).fetchone()
        if found and (str(found["class_id"]) != class_id or
                      found["recommendation_environment"] not in (None, self.environment_id)):
            raise ValueError("A different Class already uses this name")
        conn.execute("""
            INSERT INTO classes(name,class_id,recommendation_environment) VALUES (%s,%s,%s)
            ON CONFLICT(name) DO UPDATE SET profile_version=classes.profile_version+1,
                                           recommendation_environment=EXCLUDED.recommendation_environment
        """, (name, class_id, self.environment_id))
        conn.execute("DELETE FROM class_topics WHERE class_name=%s", (name,))
        with conn.cursor() as cursor:
            cursor.executemany("INSERT INTO class_topics(class_name,topic,position) VALUES (%s,%s,%s)",
                               [(name, topic, i) for i, topic in enumerate(members)])
        return next(r for r in self.classes(conn) if r["name"] == name)

    def delete_class(self, conn, name):
        return conn.execute("""
            DELETE FROM classes WHERE name=%s AND
                (recommendation_environment=%s OR recommendation_environment IS NULL)
        """, (name, self.environment_id)).rowcount

    def bootstrap_tags(self):
        # Existing topic embeddings retain the original tags. This read-only adapter
        # migrates active input metadata, never treats old flattened vectors as topic-only.
        return self.database.fetch_all("SELECT payload FROM topic_embeddings")
