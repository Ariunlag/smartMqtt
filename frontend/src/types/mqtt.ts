export interface MqttMessage {
  topic: string;
  tags: Record<string, string>;
  fields: Record<string, number | string>;
  timestamp: string;
  value?: number | string;
  payload?: number | string;
}

export interface MqttMessagesResponse {
  messages: MqttMessage[];
}
