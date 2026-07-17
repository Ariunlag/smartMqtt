import { create } from "zustand";

export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "offline";

interface ConnectionState {
  status: ConnectionStatus;
  lastConnectedAt: number | null;
  setStatus: (status: ConnectionStatus) => void;
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  status: "connecting",
  lastConnectedAt: null,
  setStatus: (status) =>
    set(
      status === "connected"
        ? { status, lastConnectedAt: Date.now() }
        : { status }
    ),
}));
