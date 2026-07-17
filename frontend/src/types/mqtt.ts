export interface MqttMessage {
  topic: string;
  tags: Record<string, string>;
  fields: Record<string, number | string>;
  timestamp: string;
  value?: number | string;
  payload?: number | string;
  /** Reliable per-event identifier (from the WS envelope, or client-assigned). */
  event_id?: string;
}

export interface MqttMessagesResponse {
  messages: MqttMessage[];
}
