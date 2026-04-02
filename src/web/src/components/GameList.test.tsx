import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Mock ApiClient so no real fetch occurs
vi.mock("../services/ApiClient", () => ({
  listGames: vi.fn().mockResolvedValue([
    { id: "g1", name: "TestGame", turn: 3, players: ["Alice", "Bob"] },
  ]),
  createGame: vi.fn().mockResolvedValue({ game_id: "g2", players: {}, turn: 0 }),
}));

import GameList from "./GameList";

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>{ui}</QueryClientProvider>,
  );
}

describe("GameList", () => {
  it("renders the create game form", () => {
    renderWithProviders(
      <GameList activeGameId={null} onSelectGame={vi.fn()} />,
    );

    expect(screen.getByTestId("ng-name")).toBeInTheDocument();
    expect(screen.getByTestId("ng-player1")).toBeInTheDocument();
    expect(screen.getByTestId("ng-player2")).toBeInTheDocument();
    expect(screen.getByTestId("ng-create")).toBeInTheDocument();
  });

  it("renders game list after data loads", async () => {
    renderWithProviders(
      <GameList activeGameId={null} onSelectGame={vi.fn()} />,
    );

    const item = await screen.findByText("TestGame");
    expect(item).toBeInTheDocument();
  });
});
