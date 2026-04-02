import type { Fleet, StarSystem, VisibleEntity } from "../services/types";

interface Props {
  starSystems: StarSystem[];
  fleets: Fleet[];
  visibleEntities: VisibleEntity[];
  selectedFleetId: string | null;
  onSelectFleet: (fleet: Fleet) => void;
}

function fleetTrianglePoints(cx: number, cy: number, size = 1.4): string {
  return `${cx},${cy - size} ${cx - size},${cy + size} ${cx + size},${cy + size}`;
}

export default function GalaxyMap({
  starSystems,
  fleets,
  visibleEntities,
  selectedFleetId,
  onSelectFleet,
}: Props) {
  return (
    <svg
      className="galaxy-map"
      viewBox="0 0 100 100"
      preserveAspectRatio="xMidYMid meet"
      data-testid="galaxy-map"
      role="img"
      aria-label="Galaxy map"
    >
      {/* Star systems */}
      <g data-testid="map-systems">
        {starSystems.map((sys) => (
          <g key={sys.id}>
            <circle
              cx={sys.position_x}
              cy={sys.position_y}
              r={1.8}
              className="sys-circle"
              data-sys-id={sys.id}
            />
            <text
              x={sys.position_x}
              y={sys.position_y - 2.4}
              className="sys-label"
              aria-label={sys.name}
            >
              {sys.name}
            </text>
          </g>
        ))}
      </g>

      {/* Own fleets */}
      <g data-testid="map-fleets">
        {fleets.map((fleet) => (
          <g key={fleet.id}>
            <polygon
              points={fleetTrianglePoints(fleet.position_x, fleet.position_y)}
              className={`fleet-own${fleet.id === selectedFleetId ? " selected-fleet" : ""}`}
              data-fleet-id={fleet.id}
              onClick={() => onSelectFleet(fleet)}
              aria-label={fleet.name}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") onSelectFleet(fleet);
              }}
            />
            <text
              x={fleet.position_x}
              y={fleet.position_y + 3.2}
              className="fleet-label"
            >
              {fleet.name}
            </text>
          </g>
        ))}
      </g>

      {/* Visible entities (other players, fog-of-war filtered) */}
      <g data-testid="map-visible">
        {visibleEntities.map((ent) => (
          <g key={ent.id}>
            <polygon
              points={fleetTrianglePoints(ent.position_x, ent.position_y)}
              className={ent.stale ? "fleet-stale" : "fleet-foe"}
            />
            <text
              x={ent.position_x}
              y={ent.position_y + 3.2}
              className="fleet-label"
            >
              {ent.stale ? `${ent.name} [?]` : ent.name}
            </text>
          </g>
        ))}
      </g>
    </svg>
  );
}
