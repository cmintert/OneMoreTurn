import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import EntityPanel from "./EntityPanel";
import type { Fleet, Planet } from "../services/types";

const planet: Planet = {
  id: "p1", name: "Earth", system_id: "s1", system_name: "Sol",
  position_x: 50, position_y: 50,
  resources: { minerals: 100, energy: 50 },
  population: 10, morale: 80, growth_rate: 1.2,
};

const fleet: Fleet = {
  id: "f1", name: "Scout1", position_x: 50, position_y: 50,
  system_id: "s1", system_name: "Sol",
  destination_id: "s2", destination_name: "Alpha",
  turns_remaining: 2, speed: 3, resources: {},
};

describe("EntityPanel", () => {
  it("shows prompt when no fleet selected", () => {
    render(<EntityPanel fleet={null} planets={[]} />);
    expect(screen.getByText("Click a fleet to act.")).toBeInTheDocument();
  });

  it("shows fleet details when selected", () => {
    render(<EntityPanel fleet={fleet} planets={[planet]} />);
    expect(screen.getByText(/Scout1/)).toBeInTheDocument();
    expect(screen.getByText(/Alpha/)).toBeInTheDocument();
    expect(screen.getByText(/2 turns/)).toBeInTheDocument();
  });

  it("renders planet resource totals", () => {
    render(<EntityPanel fleet={null} planets={[planet]} />);
    expect(screen.getByText(/minerals: 100/)).toBeInTheDocument();
    expect(screen.getByText(/energy: 50/)).toBeInTheDocument();
  });

  it("renders planet entries", () => {
    render(<EntityPanel fleet={null} planets={[planet]} />);
    expect(screen.getByText("Earth")).toBeInTheDocument();
    expect(screen.getByText(/pop 10/)).toBeInTheDocument();
  });
});
