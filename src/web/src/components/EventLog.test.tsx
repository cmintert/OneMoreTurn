import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import EventLog from "./EventLog";
import type { GameEvent } from "../services/types";

describe("EventLog", () => {
  it("shows 'no events' when empty", () => {
    render(<EventLog events={[]} />);
    expect(screen.getByText("No events this turn.")).toBeInTheDocument();
  });

  it("renders event entries", () => {
    const events: GameEvent[] = [
      { type: "move", description: "Fleet moved to Alpha", entity_name: "Scout1" },
      { type: "production", description: "+10 minerals", entity_name: "Earth" },
    ];
    render(<EventLog events={events} />);
    expect(screen.getByText(/Fleet moved to Alpha/)).toBeInTheDocument();
    expect(screen.getByText(/\+10 minerals/)).toBeInTheDocument();
  });

  it("limits to last 10 events", () => {
    const events: GameEvent[] = Array.from({ length: 15 }, (_, i) => ({
      type: "ev",
      description: `event-${i}`,
      entity_name: `e${i}`,
    }));
    render(<EventLog events={events} />);

    // Should show event-5 through event-14 (last 10)
    expect(screen.queryByText(/event-4/)).not.toBeInTheDocument();
    expect(screen.getByText(/event-5/)).toBeInTheDocument();
    expect(screen.getByText(/event-14/)).toBeInTheDocument();
  });
});
