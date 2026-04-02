import { useEffect, useState } from "react";
import { telemetryClient } from "../services/TelemetryClient";

export default function MetricsOverlay() {
  const [queueSize, setQueueSize] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setQueueSize(telemetryClient.queueSize), 1_000);
    return () => clearInterval(id);
  }, []);

  if (import.meta.env.PROD) return null;

  return (
    <div className="metrics-overlay" data-testid="metrics-overlay">
      telemetry queue: {queueSize}
    </div>
  );
}
