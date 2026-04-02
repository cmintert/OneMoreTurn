import type { Fleet, Planet } from "../services/types";

interface Props {
  fleet: Fleet | null;
  planets: Planet[];
}

function mergeResources(items: { resources: Record<string, number> }[]): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const item of items) {
    for (const [k, v] of Object.entries(item.resources)) {
      totals[k] = (totals[k] ?? 0) + v;
    }
  }
  return totals;
}

export default function EntityPanel({ fleet, planets }: Props) {
  const totals = mergeResources([...planets]);

  return (
    <>
      <section data-testid="entity-panel">
        <h2>Selection</h2>
        {fleet ? (
          <div className="selection-detail" data-testid="selection-detail">
            <strong>{fleet.name}</strong> &middot; speed {fleet.speed}
            {fleet.turns_remaining > 0
              ? ` → ${fleet.destination_name} (${fleet.turns_remaining} turns)`
              : ` · at ${fleet.system_name || "transit"}`}
          </div>
        ) : (
          <div className="selection-detail muted">Click a fleet to act.</div>
        )}
      </section>

      <section data-testid="player-panel">
        <h2>Resources</h2>
        <div className="resource-table">
          {Object.entries(totals).map(([k, v]) => (
            <span key={k}>{k}: {Math.round(v)}</span>
          ))}
        </div>
        <div className="planet-list">
          {planets.map((p) => (
            <p key={p.id}>
              <strong>{p.name}</strong>{" "}
              pop {p.population} |{" "}
              {Object.entries(p.resources)
                .map(([k, v]) => `${k}:${Math.round(v)}`)
                .join(" ")}
            </p>
          ))}
        </div>
      </section>
    </>
  );
}
