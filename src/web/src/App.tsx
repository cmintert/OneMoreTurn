import { useState } from "react";
import GameList from "./components/GameList";
import GameView from "./components/GameView";
import MetricsView from "./components/MetricsView";
import MetricsOverlay from "./components/MetricsOverlay";

type View = "game" | "metrics";

export default function App() {
  const [view, setView] = useState<View>("game");
  const [gameId, setGameId] = useState<string | null>(null);
  const [playerName, setPlayerName] = useState<string | null>(null);

  return (
    <>
      {view === "game" ? (
        <div className="app-layout">
          <aside className="sidebar">
            <h1>OneMoreTurn</h1>
            <GameList
              activeGameId={gameId}
              onSelectGame={(id, player) => {
                setGameId(id);
                setPlayerName(player);
              }}
            />
            <span className="nav-link" onClick={() => setView("metrics")} data-testid="nav-metrics">
              Metrics
            </span>
          </aside>

          <GameView
            gameId={gameId}
            playerName={playerName}
            onPlayerChange={setPlayerName}
          />
        </div>
      ) : (
        <div className="app-layout--metrics">
          <MetricsView onBack={() => setView("game")} />
        </div>
      )}
      <MetricsOverlay />
    </>
  );
}
