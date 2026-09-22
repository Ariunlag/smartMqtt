"""Environment-local recommendation, durable editing, and background adaptation."""

from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from collections import OrderedDict
from threading import RLock

import numpy as np

from .adaptive_evidence import CachedEncoder, ProviderRegistry, TextProvider, fingerprint, weighted_score
from .adaptive_learning import baseline, effective_labels, train
from .adaptive_store import AdaptiveStore
from .adaptive_discovery import DiscoveryConfig, discover

logger = logging.getLogger(__name__)


class RevisionConflict(ValueError):
    pass


class AdaptiveRecommendations:
    def __init__(self, model, identity_store, *, environment_id="default", store=None,
                 registry=None, model_id="BAAI/bge-small-en-v1.5", threshold=.8,
                 interval=30., min_labels=12, excluded_prefixes=("acceptance/",),
                 discovery_config=None, series_source=None, series_provider=None):
        self.store = store or AdaptiveStore(environment_id)
        self.environment_id = environment_id
        self.identity_store = identity_store
        self.registry = registry or ProviderRegistry(model_id=model_id)
        self.encoder = CachedEncoder(model)
        self.threshold = threshold
        self.interval = interval
        self.min_labels = min_labels
        self.discovery_config = discovery_config or DiscoveryConfig()
        self.discovery_metrics = {}
        self._neighbors = {}
        self.series_source = series_source
        self.series_provider = series_provider
        self._series_end = None
        self.series_error = None
        if series_provider is not None:
            self.registry.register(series_provider)
        self.excluded_prefixes = excluded_prefixes
        self._lock = RLock()
        self._fingerprints = {}
        self._material_signature = None
        self._material = {}
        self._comparisons = OrderedDict()
        self._discovery_key = None
        self._discovery_groups = []
        self._task = None
        self._bootstrapped = False
        self.last_error = None

    async def start(self):
        self._task = asyncio.create_task(self._background(), name="environment-learning")

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _background(self):
        while True:
            try:
                if not self._bootstrapped:
                    rows = await asyncio.to_thread(self.store.bootstrap_tags)
                    for row in rows:
                        payload = row["payload"]
                        if payload.get("topic"):
                            await asyncio.to_thread(self.materialize, payload["topic"], payload.get("tags", {}))
                    self._bootstrapped = True
                if self.series_source is not None:
                    try:
                        await asyncio.to_thread(self.refresh_series)
                        self.series_error = None
                    except Exception as exc:
                        self.series_error = type(exc).__name__
                        logger.exception("Time-series refresh failed; stale evidence will be masked")
                await asyncio.to_thread(self.learn)
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = type(exc).__name__
                logger.exception("Environment adaptation failed; retaining active model")
            await asyncio.sleep(self.interval)

    async def observe(self, message):
        return await asyncio.to_thread(self.materialize, message.topic, dict(message.tags))

    def refresh_series(self):
        provider = self.series_provider
        end = provider.current_end()
        if self._series_end == end:
            return False
        rows = [row for row in self.store.topics() if not any(row["topic"].startswith(p) for p in self.excluded_prefixes)]
        identities = self.identity_store.resolve_many([row["topic"] for row in rows])
        rows = [row for row in rows if identities.get(row["topic"], row["topic"]) == row["topic"]]
        # Network I/O occurs outside the editing lock. Fingerprints below reject a
        # window computed for metadata that changed during the query.
        points = self.series_source.fetch([row["topic"] for row in rows], end, provider.config)
        changed = False
        complete = True
        with self._lock:
            for row in rows:
                records = provider.window_records(row["topic"], row["tags"], points.get(row["topic"], []), end)
                success = self.store.replace_provider(row["topic"], row["fingerprint"], provider.definition.evidence_id,
                                                       provider.definition.version, records)
                complete &= success
                changed |= success
            self._series_end = end if complete else None
            if changed:
                self._material_signature = None
                self._comparisons.clear()
        return changed

    def materialize(self, topic, tags):
        with self._lock:
            if any(topic.startswith(prefix) for prefix in self.excluded_prefixes):
                return False
            if self.identity_store.resolve_canonical(topic) != topic:
                return False
            digest = fingerprint({"topic": topic, "tags": tags, "model": self.registry.model_id,
                                  "providers": self.registry.catalog()})
            if self._fingerprints.get(topic) == digest:
                return False
            if self.store.topic_fingerprint(topic) == digest:
                self._fingerprints[topic] = digest
                return False
            # Batch the built-in text channels without invoking custom materializers
            # twice or feeding them dummy vectors. Other providers own their input path.
            texts = [text for provider in self.registry.providers.values()
                     if isinstance(provider, TextProvider)
                     for _, text, _ in provider.text_records(topic, tags)]
            self.encoder(texts)
            records = []
            for key, provider in self.registry.providers.items():
                if provider is self.series_provider:
                    continue  # Refreshed from persisted numeric windows, not message metadata.
                for record in provider.materialize(topic, tags, self.encoder):
                    records.append({**record, "provider_id": key,
                                    "provider_version": self.registry.material_version(key)})
            self.store.replace_material(topic, tags, digest, records)
            self._series_end = None
            self._fingerprints[topic] = digest
            self._material_signature = None
            self._comparisons.clear()
            return True

    def _load(self):
        rows = self.store.topics()
        signature = fingerprint({"topics": [(r["topic"], r["fingerprint"], r.get("material_version")) for r in rows],
                                 "series_clock": self.series_provider.current_end() if self.series_provider else None})
        if signature != self._material_signature:
            self._material = self.store.material()
            self._fingerprints = {r["topic"]: r["fingerprint"] for r in rows}
            self._material_signature = signature
            self._comparisons.clear()
        identities = self.identity_store.resolve_many(tuple(self._material))
        return {t: material for t, material in self._material.items()
                if identities.get(t, t) == t and not any(t.startswith(p) for p in self.excluded_prefixes)}

    def _compare(self, topic, reference, material):
        key = (topic, reference)
        if key not in self._comparisons:
            self._comparisons[key] = self.registry.compare(material[topic], material[reference])
            if len(self._comparisons) > 2048:
                self._comparisons.popitem(last=False)
        return self._comparisons[key]

    def _evidence(self, topic, references, material):
        # Keep exact peer evidence for small groups, deterministically sample large
        # user Classes. Leave the target out before selecting reference topics.
        references = self._references(topic, references)
        comparisons = [self._compare(topic, ref, material) for ref in references
                       if ref != topic and ref in material and topic in material]
        evidence = {}
        for key in self.registry.providers:
            available = [(ref, row[key]) for ref, row in zip(
                [r for r in references if r != topic and r in material and topic in material],
                comparisons, strict=True) if row[key].get("status") == "available"]
            if not available:
                status = next((row[key]["status"] for row in comparisons
                               if row[key].get("status") not in (None, "missing")), "missing")
                evidence[key] = {"score": None, "status": status, "coverage": 0., "matches": []}
                continue
            best_ref, best = max(available, key=lambda item: item[1]["score"])
            coverage = float(np.mean([r.get("coverage", 1.) for _, r in available]))
            contribution = float(np.mean([r["score"] * r.get("coverage", 1.) for _, r in available]))
            evidence[key] = {"score": contribution / coverage if coverage else 0.,
                             "coverage": coverage,
                             "status": "available", "reference_topic": best_ref,
                             "matches": best.get("matches", [])[:5], "support_count": len(available)}
        return evidence

    @staticmethod
    def _references(topic, references):
        peers = [r for r in references if r != topic]
        if len(peers) > 32:
            peers = sorted(peers, key=lambda r: fingerprint(r))[:32]
        return peers

    def current_model(self):
        return self.store.model(self.registry.manifest_id) or baseline(self.registry.active_ids, self.registry.manifest_id)

    def learn(self):
        with self._lock:
            current = self.current_model()
            events = self.store.events()
            retracted = any(e["action"] == "UNDO" and e["sequence"] > current.get("trained_sequence", 0)
                            for e in events)
            if retracted:
                current = baseline(self.registry.active_ids, self.registry.manifest_id)
            candidate = train(events, self.registry.active_ids, self.registry.manifest_id,
                              current, min_labels=self.min_labels)
            if retracted and candidate is None:
                candidate = {**current, "trained_sequence": max(e["sequence"] for e in events),
                             "reset_reason": "feedback_retracted"}
            if candidate:
                self.store.put_model(self.registry.manifest_id, candidate)
            return candidate

    def _new_group(self, group_id, members, name=None):
        return {"group_id": group_id, "revision": 1, "members": sorted(set(members)),
                "name": name, "edited": False, "dismissed": False, "excluded": [],
                "history": [], "confirmed": [], "saved_class": None, "evidence": {}, "proposals": []}

    def _discover(self, material, model):
        topics = sorted(material)
        cache_key = (self._material_signature, tuple(topics), self.registry.manifest_id,
                     tuple(sorted(model["weights"].items())), self.threshold, self.discovery_config)
        if cache_key == self._discovery_key:
            return copy.deepcopy(self._discovery_groups)
        clusters, self.discovery_metrics, self._neighbors, _ = discover(
            material, self.registry, model["weights"], self.threshold, self.discovery_config,
            compare=lambda a, b: self._compare(a, b, material))
        groups = []
        for members in clusters:
            group_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                     f"adaptive:{self.environment_id}:{fingerprint(members)}"))
            groups.append(self._new_group(group_id, members))
        self._discovery_key = cache_key
        self._discovery_groups = copy.deepcopy(groups)
        return groups

    def recommendations(self):
        with self._lock:
            material = self._load()
            model = self.current_model()
            generated = self._discover(material, model)
            with self.store.transaction() as conn:
                saved = {r["group_id"]: r for r in self.store.groups(conn)}
                # Link existing manual Classes without retroactively fabricating feedback.
                classes = self.store.classes(conn)
                for cls in classes:
                    group_id = "class:" + str(cls["class_id"])
                    matching = next((r for r in saved.values() if r.get("saved_class") == cls["name"]), None)
                    state = matching or self._new_group(group_id, cls["topics"], cls["name"])
                    state.update(saved_class=cls["name"], class_id=str(cls["class_id"]), edited=True)
                    state["members"] = sorted(set(cls["topics"]))
                    saved[state["group_id"]] = state
                selected = {r["group_id"]: saved.get(r["group_id"], r) for r in generated}
                selected.update({k: v for k, v in saved.items() if v.get("edited")})
                cards = []
                for state in selected.values():
                    if state.get("deleted"):
                        continue
                    if state.get("dismissed"):
                        cards.append(self._card(state, model))
                        continue
                    canonical = self.identity_store.resolve_many(state["members"])
                    state["members"] = sorted({canonical.get(t, t) for t in state["members"]})
                    members = state["members"]
                    candidate_topics = [t for t in material if t not in members and t not in state["excluded"]]
                    if len(material) > self.discovery_config.exact_limit:
                        pool = {t for ref in self._references(None, members) for t in self._neighbors.get(ref, [])}
                        candidate_topics = [t for t in candidate_topics if t in pool][:128]
                    evidence = {t: self._evidence(t, members, material) for t in members}
                    proposals = []
                    if state["edited"]:
                        for topic in candidate_topics:
                            row = self._evidence(topic, members, material)
                            score = weighted_score(row, model["weights"])
                            if score is not None and score >= self.threshold:
                                evidence[topic] = row
                                proposals.append({"topic": topic, "score": score})
                    proposals.sort(key=lambda r: (-r["score"], r["topic"]))
                    signature = fingerprint({"members": members, "material": self._material_signature,
                                             "model": model["version"], "manifest": self.registry.manifest_id})
                    if state.get("presentation_signature") not in (None, signature):
                        state["revision"] += 1
                    state.update(evidence=evidence, proposals=proposals[:10], presentation_signature=signature,
                                 manifest_id=self.registry.manifest_id, model_version=model["version"])
                    self.store.put_group(conn, state)
                    cards.append(self._card(state, model))
            events = self.store.events()
            return {"environment_id": self.environment_id, "catalog": self.registry.catalog(),
                    "model": model, "feedback_count": len(effective_labels(events, self.registry.manifest_id)),
                    "background_error": self.last_error, "available_topics": sorted(material),
                    "discovery": self.discovery_metrics,
                    "series": {"enabled": self.series_provider is not None, "error": self.series_error,
                               "window_end": self._series_end},
                    "groups": sorted(cards, key=lambda c: (not bool(c["saved_class"]), c["group_id"])),
                    "strategy": self.discovery_metrics.get("algorithm", "complete-linkage"), "threshold": self.threshold}

    def _card(self, state, model):
        return {k: v for k, v in state.items() if k not in {"history", "presentation_signature"}} | {
            "can_undo": bool(state["history"]),
            "member_scores": {t: weighted_score(state["evidence"].get(t, {}), model["weights"])
                              for t in state["members"]}}

    def _event(self, state, action, topic, label, evidence, references, **details):
        return {"event_id": str(uuid.uuid4()), "group_id": state["group_id"], "action": action,
                "topic": topic, "label": label, "evidence": evidence,
                "details": {"manifest_id": state.get("manifest_id", self.registry.manifest_id),
                            "model_version": state.get("model_version", 0), "reference_topics": self._references(topic, references),
                            "fixture": any(t.startswith("acceptance/") for t in [topic or "", *references]),
                            **details}}

    def edit(self, group_id, action, revision, *, topic=None, name=None):
        with self._lock:
            material = self._load()
            model = self.current_model()
            with self.store.transaction() as conn:
                state = next((r for r in self.store.groups(conn) if r["group_id"] == group_id), None)
                if state is None:
                    raise LookupError("Group not found; refresh recommendations")
                if state["revision"] != revision:
                    raise RevisionConflict("This group changed. Refresh before editing.")
                if action == "undo":
                    if not state["history"]:
                        raise ValueError("No edit to undo")
                    previous = state["history"].pop()
                    state.update(previous["state"])
                    event = self._event(state, "UNDO", None, None, {}, [], undo_event=previous["event_id"])
                elif action == "save":
                    if not name or not name.strip() or not state["members"]:
                        raise ValueError("A name and at least one member are required")
                    if state.get("saved_class"):
                        raise ValueError("This group is already saved as a Class")
                    name = name.strip()
                    state.update(saved_class=name, name=name, class_id=str(uuid.uuid4()), history=[], edited=True)
                    event = self._event(state, "SAVE_CLASS", None, None, {}, state["members"])
                    # Saving confirms final selected members only once. Existing explicit
                    # member decisions remain the latest labels rather than duplicated rows.
                    for member in state["members"]:
                        if member not in state.get("confirmed", []):
                            row = state["evidence"].get(member, {})
                            self.store.event(conn, self._event(state, "KEEP", member, 1, row,
                                                              [t for t in state["members"] if t != member]))
                    state["confirmed"] = list(state["members"])
                else:
                    if action not in {"add", "remove", "confirm", "dismiss", "useful"}:
                        raise ValueError("Unknown group action")
                    if action in {"add", "remove", "confirm"}:
                        if not topic:
                            raise ValueError("Topic is required")
                        topic = self.identity_store.resolve_canonical(topic)
                        if action == "add" and topic not in material:
                            raise ValueError("Topic evidence is not available yet")
                        if action == "add" and topic in state["members"]:
                            raise ValueError("Topic is already a member")
                        if action != "add" and topic not in state["members"]:
                            raise ValueError("Topic is not a member")
                        if action == "confirm" and topic in (state.get("confirmed") or []):
                            raise ValueError("Topic is already confirmed")
                    refs = [t for t in state["members"] if t != topic]
                    evidence = state["evidence"].get(topic) or self._evidence(topic, refs, material)
                    label = (0 if action == "remove" else 1) if action in {"add", "remove", "confirm"} else None
                    event = self._event(state, action.upper(), topic, label, evidence, refs)
                    prior = {k: copy.deepcopy(state.get(k)) for k in
                             ("members", "excluded", "dismissed", "confirmed")}
                    state["history"] = [*state["history"][-49:], {"state": prior, "event_id": event["event_id"]}]
                    state["edited"] = True
                    if action == "add":
                        state["members"].append(topic)
                        state["excluded"] = [t for t in state["excluded"] if t != topic]
                    elif action == "remove":
                        state["members"].remove(topic)
                        state["confirmed"] = [t for t in (state.get("confirmed") or []) if t != topic]
                        state["excluded"] = sorted(set([*state["excluded"], topic]))
                    elif action == "dismiss":
                        state["dismissed"] = True
                    if action in {"add", "confirm"}:
                        state["confirmed"] = sorted(set([*(state.get("confirmed") or []), topic]))
                state["revision"] += 1
                state["evidence"] = {t: self._evidence(t, state["members"], material) for t in state["members"]}
                state["proposals"] = []
                state["manifest_id"] = self.registry.manifest_id
                state["model_version"] = model["version"]
                self.store.event(conn, event)
                if state.get("saved_class"):
                    self.store.save_class(conn, state["saved_class"], state["members"], state["class_id"])
                self.store.put_group(conn, state)
            return self._card(state, model)

    def manual_class(self, name, topics, *, update=False):
        if not name.strip() or not topics:
            raise ValueError("A Class needs a name and at least one topic")
        with self._lock:
            identities = self.identity_store.resolve_many(topics)
            topics = sorted({identities.get(t, t) for t in topics})
            with self.store.transaction() as conn:
                old = next((c for c in self.store.classes(conn) if c["name"] == name), None)
                if update and old is None:
                    raise LookupError("Class not found")
                if not update and old:
                    raise ValueError("Class already exists")
                class_id = str(old["class_id"]) if old else str(uuid.uuid4())
                state = next((g for g in self.store.groups(conn) if g.get("saved_class") == name), None)
                state = state or self._new_group("class:" + class_id, old["topics"] if old else [], name)
                # Saved Classes are user-owned state, not training labels. Learning
                # only uses explicit review actions performed on recommendation cards
                # (add/remove/confirm/save), never ordinary Class Builder persistence.
                state.update(manifest_id=self.registry.manifest_id,
                             model_version=self.current_model()["version"])
                state.update(members=topics, saved_class=name, class_id=class_id, edited=True,
                             history=[], revision=state["revision"] + 1, dismissed=False,
                             confirmed=topics, manifest_id=self.registry.manifest_id)
                self.store.put_group(conn, state)
                return self.store.save_class(conn, name, topics, class_id)

    def delete_class(self, name):
        with self._lock, self.store.transaction() as conn:
            if not self.store.delete_class(conn, name):
                raise LookupError("Class not found")
            for state in self.store.groups(conn):
                if state.get("saved_class") == name:
                    state.update(saved_class=None, dismissed=True, deleted=True, edited=True, history=[], revision=state["revision"]+1)
                    self.store.put_group(conn, state)
