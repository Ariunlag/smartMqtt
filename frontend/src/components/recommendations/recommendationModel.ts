/* Shared recommendation view model.
 *
 * Both recommendation experiments render the exact same panel. Only the
 * adapter that fills this model (useRecommendationSource) differs per branch,
 * so the dashboard surface stays comparable while the algorithm changes. */

export interface RecommendationMethod {
  id: string;
  label: string;
  description: string;
}

export interface RecommendationStat {
  label: string;
  value: string;
}

export interface RecommendationChannel {
  id: string;
  label: string;
  detail: string;
}

export interface EvidenceMatch {
  left: string;
  right: string;
  detail: string | null;
  leftValues: (number | null)[] | null;
  rightValues: (number | null)[] | null;
}

/* Adapters render their own numbers into `value` and `detail`: one method
 * reports a fused similarity, another reports per-channel coverage, and the
 * panel lays both out the same way. */
export interface EvidenceRow {
  channelId: string;
  channelLabel: string;
  value: string;
  detail: string | null;
  matches: EvidenceMatch[];
}

export interface GroupMember {
  topic: string;
  detail: string;
  confirmed: boolean;
  evidence: EvidenceRow[];
}

export interface GroupProposal {
  topic: string;
  detail: string;
}

export interface GroupDiscoveryEvidenceItem {
  topic: string;
  text: string | null;
  similarity: number;
  source: string | null;
}

export interface GroupDiscoveryEvidence {
  channelId: string;
  channelLabel: string;
  items: GroupDiscoveryEvidenceItem[];
}

export interface RecommendationGroup {
  id: string;
  title: string;
  status: string;
  members: GroupMember[];
  proposals: GroupProposal[];
  discoveryChannels: string[];
  discoveryEvidence?: GroupDiscoveryEvidence[];
  savedClass: string | null;
  dismissed: boolean;
  canUndo: boolean;
  reviewPending: boolean;
}

export type GroupAction =
  | "add"
  | "remove"
  | "confirm"
  | "save"
  | "undo"
  | "dismiss"
  | "useful";

export interface GroupActionValues {
  topic?: string;
  name?: string;
}

export interface RecommendationSource {
  loading: boolean;
  error: string | null;
  methods: RecommendationMethod[];
  activeMethodId: string | null;
  stats: RecommendationStat[];
  channels: RecommendationChannel[];
  details: string[];
  groups: RecommendationGroup[];
  availableTopics: string[];
  refresh: (methodId?: string) => Promise<void>;
  apply: (
    groupId: string,
    action: GroupAction,
    values?: GroupActionValues,
  ) => Promise<void>;
}

export const similarityText = (value: number | null | undefined) =>
  value === null || value === undefined ? "Insufficient evidence" : value.toFixed(3);

export const percentText = (value: number | null | undefined) =>
  value === null || value === undefined ? "N/A" : `${(value * 100).toFixed(1)}%`;

/* The panel — not the adapter — owns every user-facing string, so both
 * experiments report the same wording for the same action. */
export function actionNotice(action: GroupAction, values: GroupActionValues = {}) {
  switch (action) {
    case "add":
      return `${values.topic} added.`;
    case "remove":
      return `${values.topic} removed.`;
    case "confirm":
      return `${values.topic} confirmed.`;
    case "save":
      return `Class "${values.name}" saved.`;
    case "undo":
      return "Edit undone.";
    default:
      return "Feedback recorded.";
  }
}
