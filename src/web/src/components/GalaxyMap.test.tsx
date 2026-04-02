import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import GalaxyMap from "./GalaxyMap";
import type { StarSystem, Fleet, VisibleEntity } from "../services/types";
import { vi } from "vitest";

const systems: StarSystem[] = [
  { id: "s1", name: "Sol", position_x: 50, position_y: 50, planet_ids: ["p1"] },
  { id: "s2", name: "Alpha", position_x: 25, position_y: 75, planet_ids: [] },
];

const fleets: Fleet[] = [
  {
    id: "f1", name: "Scout1", position_x: 50, position_y: 50,
    system_id: "s1", system_name: "Sol", destination_id: null,
    destination_name: "", turns_remaining: 0, speed: 2, resources: {},
  },
];

const visible: VisibleEntity[] = [
  { id: "v1", name: "EnemyFleet", type: "fleet", position_x: 25, position_y: 75, stale: false },
  { id: "v2", name: "OldContact", type: "fleet", position_x: 30, position_y: 30, stale: true },
];

describe("GalaxyMap", () => {
  it("renders SVG with data-testid", () => {
    render(
      <GalaxyMap
        starSystems={systems}
        fleets={fleets}
        visibleEntities={[]}
        selectedFleetId={null}
        onSelectFleet={vi.fn()}
      />,
    );

    expect(screen.getByTestId("galaxy-map")).toBeInTheDocument();
    expect(screen.getByTestId("map-systems")).toBeInTheDocument();
    expect(screen.getByTestId("map-fleets")).toBeInTheDocument();
  });

  it("renders star system labels", () => {
    render(
      <GalaxyMap
        starSystems={systems}
        fleets={[]}
        visibleEntities={[]}
        selectedFleetId={null}
        onSelectFleet={vi.fn()}
      />,
    );

    expect(screen.getByText("Sol")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
  });

  it("renders own fleets", () => {
    render(
      <GalaxyMap
        starSystems={systems}
        fleets={fleets}
        visibleEntities={[]}
        selectedFleetId={null}
        onSelectFleet={vi.fn()}
      />,
    );

    expect(screen.getByText("Scout1")).toBeInTheDocument();
  });

  it("renders visible entities with stale marker", () => {
    render(
      <GalaxyMap
        starSystems={systems}
        fleets={[]}
        visibleEntities={visible}
        selectedFleetId={null}
        onSelectFleet={vi.fn()}
      />,
    );

    expect(screen.getByText("EnemyFleet")).toBeInTheDocument();
    expect(screen.getByText("OldContact [?]")).toBeInTheDocument();
  });

  it("applies selected-fleet class when fleet is selected", () => {
    render(
      <GalaxyMap
        starSystems={systems}
        fleets={fleets}
        visibleEntities={[]}
        selectedFleetId="f1"
        onSelectFleet={vi.fn()}
      />,
    );

    const polygon = document.querySelector("[data-fleet-id='f1']");
    expect(polygon?.classList.contains("selected-fleet")).toBe(true);
  });
});
