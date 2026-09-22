import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";

import {
  editAdaptiveGroup,
  getAdaptiveRecommendations,
} from "../../services/adaptiveRecommendationApi";
import type {
  AdaptiveEvidence,
  AdaptiveGroup,
  AdaptiveResponse,
  GroupAction as ApiGroupAction,
} from "../../services/adaptiveRecommendationApi";
import { useInfluxStore } from "../../store/useInfluxStore";
import { percentText, similarityText } from "./recommendationModel";
import type {
  EvidenceMatch,
  EvidenceRow,
  GroupAction,
  GroupActionValues,
  RecommendationGroup,
  RecommendationSource,
} from "./recommendationModel";

/* Branch-local adapter: adaptive weighted evidence.
 *
 * This is the only recommendation file that differs between experiment
 * branches. Everything it returns is rendered by the shared panel. */

const METHOD = {
  id: "adaptive_weighted",
  label: "Adaptive weighted evidence",
  description:
    "Combines the available evidence channels with weights, forms groups with complete-link style discovery, and can learn new weights from explicit recommendation interactions.",
};

function errorText(error: unknown) {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data.detail ?? error.message;
  }
  return error instanceof Error ? error.message : "Request failed";
}

function payloadText(payload: { text?: string }) {
  return payload.text ?? JSON.stringify(payload);
}

function evidenceRows(
  response: AdaptiveResponse,
  rows: Record<string, AdaptiveEvidence> | undefined,
): EvidenceRow[] {
  return response.catalog
    .map((channel) => {
      const row = rows?.[channel.evidence_id];
      const weight = response.model.weights[channel.evidence_id] ?? 0;
      if (
        !channel.active ||
        weight <= 0 ||
        row?.status !== "available" ||
        row.score === null ||
        row.coverage <= 0
      ) {
        return null;
      }

      const contribution = weight * row.score * row.coverage;
      const matches: EvidenceMatch[] = (row.matches ?? []).map((match) => ({
        left: payloadText(match.left),
        right: payloadText(match.right),
        detail: `${percentText(match.similarity)} semantic similarity`,
        leftValues: match.left.values ?? null,
        rightValues: match.right.values ?? null,
      }));

      return {
        row: {
          channelId: channel.evidence_id,
          channelLabel: channel.label,
          value: percentText(row.score),
          detail:
            `Weight ${percentText(weight)} · coverage ${percentText(row.coverage)} · weighted support ${percentText(contribution)}`,
          matches,
        } satisfies EvidenceRow,
        contribution,
      };
    })
    .filter(
      (
        item,
      ): item is {
        row: EvidenceRow;
        contribution: number;
      } => item !== null,
    )
    .sort((left, right) => right.contribution - left.contribution)
    .map((item) => item.row);
}

function groupDiscoveryChannels(
  response: AdaptiveResponse,
  group: AdaptiveGroup,
): string[] {
  return response.catalog
    .map((channel) => {
      const weight = response.model.weights[channel.evidence_id] ?? 0;
      if (!channel.active || weight <= 0) return null;

      const contributions = group.members
        .map((topic) => group.evidence[topic]?.[channel.evidence_id])
        .filter(
          (row): row is AdaptiveEvidence =>
            row?.status === "available" &&
            row.score !== null &&
            row.coverage > 0,
        )
        .map((row) => weight * (row.score ?? 0) * row.coverage);

      if (contributions.length === 0) return null;
      const average =
        contributions.reduce((sum, value) => sum + value, 0) /
        contributions.length;

      return {
        label: `${channel.label} · ${percentText(weight)} weight`,
        contribution: average,
      };
    })
    .filter(
      (item): item is { label: string; contribution: number } => item !== null,
    )
    .sort((left, right) => right.contribution - left.contribution)
    .map((item) => item.label);
}

function toGroup(response: AdaptiveResponse, group: AdaptiveGroup): RecommendationGroup {
  return {
    id: group.group_id,
    title: group.name ?? "Suggested group",
    status: group.saved_class
      ? "Saved Class"
      : group.edited
        ? "Your edited group"
        : "System suggestion",
    members: group.members.map((topic) => ({
      topic,
      detail: `Combined similarity: ${percentText(group.member_scores[topic])}`,
      confirmed: group.confirmed?.includes(topic) ?? false,
      evidence: evidenceRows(response, group.evidence[topic]),
    })),
    proposals: group.proposals.map((proposal) => ({
      topic: proposal.topic,
      detail: `Combined similarity: ${percentText(proposal.score)}`,
    })),
    discoveryChannels: groupDiscoveryChannels(response, group),
    savedClass: group.saved_class,
    dismissed: group.dismissed,
    canUndo: group.can_undo,
    reviewPending: false,
  };
}

export function useRecommendationSource(): RecommendationSource {
  const [result, setResult] = useState<AdaptiveResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setResult(await getAdaptiveRecommendations());
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
      const group = result?.groups.find((item) => item.group_id === groupId);
      if (!group) return;

      let updated: AdaptiveGroup;
      try {
        updated = await editAdaptiveGroup(group, action as ApiGroupAction, values);
      } catch (requestError) {
        throw new Error(errorText(requestError));
      }

      setResult((previous) =>
        previous
          ? {
              ...previous,
              groups: previous.groups.map((item) =>
                item.group_id === groupId ? updated : item,
              ),
            }
          : previous,
      );
      void useInfluxStore.getState().getClasses();
    },
    [result],
  );

  return useMemo<RecommendationSource>(() => {
    if (!result) {
      return {
        loading,
        error,
        methods: [METHOD],
        activeMethodId: METHOD.id,
        stats: [],
        channels: [],
        details: [],
        groups: [],
        availableTopics: [],
        refresh,
        apply,
      };
    }

    const details: string[] = [
      `${result.feedback_count} distinct membership labels. Updates run in the background when there is enough diverse positive and negative feedback.`,
      `Model version ${result.model.version} · ${
        result.model.updated_at
          ? `Last evaluation: ${new Date(result.model.updated_at).toLocaleString()}`
          : "No learned update yet"
      }`,
      "Membership similarity includes matched-tag coverage. It is not a probability of correctness.",
    ];

    if (result.model.evaluation) {
      details.push(
        `Held-out log loss: candidate ${result.model.evaluation.candidate_loss.toFixed(3)}, baseline ${result.model.evaluation.baseline_loss.toFixed(3)}. ${
          result.model.last_update_accepted
            ? "Update accepted."
            : "Previous weights retained."
        }`,
      );
    }
    if (result.background_error) {
      details.push("Learning is temporarily unavailable. Existing weights are retained.");
    }
    if (result.discovery) {
      details.push(
        `${result.discovery.mode === "approximate" ? "Approximate search" : "Exact search"}: ${result.discovery.scored_pairs.toLocaleString()} of ${result.discovery.possible_pairs.toLocaleString()} topic pairs checked · ${result.discovery.elapsed_seconds.toFixed(2)}s.${
          result.discovery.mode === "approximate"
            ? " Approximate search can miss matching topics."
            : ""
        }`,
      );
    }
    if (result.series?.enabled) {
      details.push(
        `Time-series compares synchronized changes in shape, independent of scale or units. ${
          result.series.error
            ? "Window refresh unavailable; stale windows are excluded."
            : result.series.window_end
              ? `Window ending ${new Date(result.series.window_end * 1000).toLocaleString()}.`
              : "Waiting for numeric windows."
        }`,
      );
    }

    return {
      loading,
      error,
      methods: [METHOD],
      activeMethodId: METHOD.id,
      stats: [
        { label: "Environment", value: result.environment_id },
        { label: "Topics", value: String(result.available_topics.length) },
        { label: "Groups", value: String(result.groups.length) },
        {
          label: "Weights",
          value: result.model.status === "learned" ? "Learned" : "Baseline",
        },
      ],
      channels: result.catalog.map((channel) => ({
        id: channel.evidence_id,
        label: channel.label,
        detail: channel.active
          ? percentText(result.model.weights[channel.evidence_id] ?? 0)
          : "Shadow",
      })),
      details,
      groups: result.groups.map((group) => toGroup(result, group)),
      availableTopics: result.available_topics,
      refresh,
      apply,
    };
  }, [result, loading, error, refresh, apply]);
}
