import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";

import {
  getRecommendedClassCandidates,
  submitRecommendedClassFeedback,
} from "../../services/classRecommendationApi";
import { useInfluxStore } from "../../store/useInfluxStore";
import type {
  RecommendedClassCandidate,
  RecommendedClassCandidateSet,
  RecommendedClassFeedbackAction,
} from "../../types/api_models";
import type {
  GroupAction,
  GroupActionValues,
  RecommendationGroup,
  RecommendationSource,
} from "./recommendationModel";

/* Branch-local adapter: independent evidence discovery.
 *
 * This is the only recommendation file that differs between experiment
 * branches. Everything it returns is rendered by the shared panel.
 *
 * Candidates are immutable here, so the reviewed membership lives in a local
 * overlay and every change is recorded as explicit feedback against the
 * candidate version it was shown for. */

interface GroupEdit {
  action: "add" | "remove";
  topic: string;
}

interface GroupOverlay {
  topics: string[];
  confirmed: string[];
  savedClass: string | null;
  dismissed: boolean;
  lastEdit: GroupEdit | null;
}

function errorText(error: unknown) {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data.detail ?? error.message;
  }
  return error instanceof Error ? error.message : "Request failed";
}

function discoveryLabel(evidenceId: string, fallback: string) {
  switch (evidenceId) {
    case "key":
      return "Similar key";
    case "value":
      return "Shared value";
    case "key_value":
      return "Similar key + value";
    case "schema":
      return "Similar structure";
    case "stream_context":
      return "Similar stream context";
    default:
      return fallback;
  }
}

function toGroup(
  set: RecommendedClassCandidateSet,
  candidate: RecommendedClassCandidate,
  overlay: GroupOverlay | undefined,
): RecommendationGroup {
  const topics = overlay?.topics ?? candidate.member_topics;
  const labels = new Map(
    set.evidence_catalog.map((definition) => [definition.evidence_id, definition.label]),
  );
  const edited = overlay
    ? overlay.topics.join("\u0000") !== candidate.member_topics.join("\u0000")
    : false;

  return {
    id: candidate.candidate_id,
    title: `Recommended class #${candidate.rank}`,
    status: overlay?.savedClass
      ? "Saved Class"
      : edited
        ? "Your edited group"
        : "System suggestion",
    members: topics.map((topic) => {
      const discovered = (candidate.discovery_support ?? []).some((support) =>
        support.items.some((item) => item.topic === topic),
      );
      return {
        topic,
        detail: discovered ? "" : "Added during review",
        confirmed: overlay?.confirmed.includes(topic) ?? false,
        evidence: [],
      };
    }),
    // Discovery is unsupervised here: this method scores no topics outside a
    // candidate, so additions come from the Add topic control instead.
    proposals: [],
    discoveryChannels: candidate.discovery_channels.map((evidenceId) =>
      discoveryLabel(evidenceId, labels.get(evidenceId) ?? evidenceId),
    ),
    discoveryEvidence: (candidate.discovery_support ?? []).map((support) => ({
      channelId: support.evidence_id,
      channelLabel: discoveryLabel(
        support.evidence_id,
        labels.get(support.evidence_id) ?? support.evidence_id,
      ),
      items: support.items.map((item) => ({
        topic: item.topic,
        text: item.text,
        similarity: item.similarity,
        source: item.source,
      })),
    })),
    savedClass: overlay?.savedClass ?? null,
    dismissed: overlay?.dismissed ?? false,
    canUndo: overlay?.lastEdit != null,
    reviewPending: candidate.evidence.some((item) => item.duplicate_pending),
  };
}

export function useRecommendationSource(): RecommendationSource {
  const [set, setSet] = useState<RecommendedClassCandidateSet | null>(null);
  const [overlays, setOverlays] = useState<Record<string, GroupOverlay>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (methodId?: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getRecommendedClassCandidates(methodId);
      setSet(result);
      setOverlays({});
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const apply = useCallback(
    async (groupId: string, action: GroupAction, values: GroupActionValues = {}) => {
      const candidate = set?.candidates.find((item) => item.candidate_id === groupId);
      if (!candidate || !set) return;

      const overlay: GroupOverlay = overlays[groupId] ?? {
        topics: candidate.member_topics,
        confirmed: [],
        savedClass: null,
        dismissed: false,
        lastEdit: null,
      };
      const original = new Set(candidate.member_topics);
      const shadowRunId =
        set.shadow_evaluation?.persistence?.status === "stored"
          ? set.shadow_evaluation.shadow_run_id
          : undefined;
      const liveRunId =
        set.live_ranking?.persistence?.status === "stored"
          ? set.live_ranking.live_run_id
          : undefined;

      const feedback = async (
        feedbackAction: RecommendedClassFeedbackAction,
        topic?: string,
      ) => {
        try {
          await submitRecommendedClassFeedback(candidate.candidate_id, {
            action: feedbackAction,
            candidate_version: candidate.candidate_version,
            ...(topic ? { topic } : {}),
            ...(shadowRunId ? { shadow_run_id: shadowRunId } : {}),
            ...(liveRunId ? { live_run_id: liveRunId } : {}),
          });
        } catch (requestError) {
          throw new Error(errorText(requestError));
        }
      };

      const commit = (next: Partial<GroupOverlay>) =>
        setOverlays((current) => ({ ...current, [groupId]: { ...overlay, ...next } }));

      switch (action) {
        case "remove": {
          const topic = values.topic!;
          if (overlay.topics.length <= 1) {
            throw new Error("Keep at least one topic in the working group.");
          }
          await feedback("REMOVE_TOPIC", topic);
          commit({
            topics: overlay.topics.filter((item) => item !== topic),
            lastEdit: { action: "remove", topic },
          });
          return;
        }
        case "add": {
          const topic = values.topic!;
          if (overlay.topics.includes(topic)) return;
          await feedback(original.has(topic) ? "KEEP_TOPIC" : "ADD_TOPIC", topic);
          commit({ topics: [...overlay.topics, topic], lastEdit: { action: "add", topic } });
          return;
        }
        case "confirm": {
          const topic = values.topic!;
          await feedback("KEEP_TOPIC", topic);
          commit({ confirmed: [...overlay.confirmed, topic] });
          return;
        }
        case "undo": {
          const edit = overlay.lastEdit;
          if (!edit) return;
          if (edit.action === "remove") {
            // Putting the topic back is itself a membership statement, so it
            // is recorded rather than silently reverted.
            await feedback("KEEP_TOPIC", edit.topic);
            const restored = [...overlay.topics];
            const wasAt = candidate.member_topics.indexOf(edit.topic);
            const before = restored.findIndex(
              (topic) => candidate.member_topics.indexOf(topic) > wasAt,
            );
            if (before === -1) restored.push(edit.topic);
            else restored.splice(before, 0, edit.topic);
            commit({ topics: restored, lastEdit: null });
          } else {
            await feedback("REMOVE_TOPIC", edit.topic);
            commit({
              topics: overlay.topics.filter((topic) => topic !== edit.topic),
              lastEdit: null,
            });
          }
          return;
        }
        case "useful": {
          await feedback("ACCEPT_CANDIDATE");
          return;
        }
        case "dismiss": {
          await feedback("DISMISS_CANDIDATE");
          commit({ dismissed: true });
          return;
        }
        case "save": {
          const name = values.name!;
          let saved = false;
          try {
            const store = useInfluxStore.getState();
            store.setClassNameInput(name);
            await store.setSelectedMeasurements(overlay.topics);
            await store.saveClass();
            saved = true;

            for (const topic of overlay.topics) {
              await feedback(original.has(topic) ? "KEEP_TOPIC" : "ADD_TOPIC", topic);
            }
            await feedback("ACCEPT_CANDIDATE");
          } catch (requestError) {
            if (saved) commit({ savedClass: name });
            throw new Error(
              saved
                ? `The Class was saved, but feedback recording failed: ${errorText(requestError)}`
                : errorText(requestError),
            );
          }
          commit({ savedClass: name });
          return;
        }
      }
    },
    [set, overlays],
  );

  return useMemo<RecommendationSource>(() => {
    if (!set) {
      return {
        loading,
        error,
        methods: [],
        activeMethodId: null,
        stats: [],
        channels: [],
        details: [],
        groups: [],
        availableTopics: [],
        refresh,
        apply,
      };
    }

    const isCentroid = set.strategy.strategy_id === "tag_value_centroid";
    const details: string[] = isCentroid
      ? [
          "Only tag-value embeddings participate in grouping. Values are assigned incrementally to the nearest moving centroid when they meet the centroid threshold.",
        ]
      : [
          "Key, value, key + value, schema, and stream context discover groups independently. Exact topic memberships found by multiple evidence types are merged.",
        ];

    const activeEvidenceIds = isCentroid
      ? new Set(["value"])
      : new Set(set.evidence_catalog.map((definition) => definition.evidence_id));

    return {
      loading,
      error,
      methods: set.strategy_catalog.map((strategy) => ({
        id: strategy.strategy_id,
        label: strategy.label,
        description: strategy.description,
      })),
      activeMethodId: set.strategy.strategy_id,
      stats: [
        { label: "Topics", value: String(set.available_topics.length) },
        { label: "Groups", value: String(set.candidates.length) },
      ],
      channels: set.evidence_catalog
        .filter((definition) => activeEvidenceIds.has(definition.evidence_id))
        .map((definition) => ({
          id: definition.evidence_id,
          label: discoveryLabel(definition.evidence_id, definition.label),
          detail: isCentroid ? "Centroid input" : "Independent evidence",
        })),
      details,
      groups: set.candidates.map((candidate) =>
        toGroup(set, candidate, overlays[candidate.candidate_id]),
      ),
      availableTopics: set.available_topics,
      refresh,
      apply,
    };
  }, [set, overlays, loading, error, refresh, apply]);
}
