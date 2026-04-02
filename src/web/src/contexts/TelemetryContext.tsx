import { createContext, useContext, type ReactNode } from "react";
import { telemetryClient } from "../services/TelemetryClient";

interface TelemetryContextValue {
  track: (eventType: string, data?: Record<string, unknown>) => void;
  queueSize: number;
}

const TelemetryContext = createContext<TelemetryContextValue>({
  track: () => {},
  queueSize: 0,
});

export function TelemetryProvider({ children }: { children: ReactNode }) {
  const value: TelemetryContextValue = {
    track: (type, data) => telemetryClient.track(type, data),
    get queueSize() {
      return telemetryClient.queueSize;
    },
  };
  return (
    <TelemetryContext.Provider value={value}>
      {children}
    </TelemetryContext.Provider>
  );
}

export function useTelemetry(): TelemetryContextValue {
  return useContext(TelemetryContext);
}
