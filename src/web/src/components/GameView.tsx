import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getGameState, resolveTurn } from "../services/ApiClient";
import { useTelemetry } from "../contexts/TelemetryContext";
import type { GameState } from "../services/types";
import GalaxyMap from "./GalaxyMap";
import EntityPanel from "./EntityPanel";
import ActionForm from "./ActionForm";
import EventLog from "./EventLog";
import type { Fleet, GameListItem } from "../services/types";

interface Props {
  gameId: string | null;
  playerName: string | null;
  onPlayerChange: (player: string) => void;
}

export default function GameView({ gameId, playerName, onPlayerChange }: Props) {
  const queryClient = useQueryClient();
  const { track } = useTelemetry();
  const [selectedFleet, setSelectedFleet] = useState<Fleet | null>(null);
  const [feedback, setFeedback] = useState<{ msg: string; ok: boolean } | null>(null);

  const { data: gs } = useQuery<GameState>({
    queryKey: ["gameState", gameId, playerName],
    queryFn: () => getGameState(gameId!, playerName!),
    enabled: !!gameId && !!playerName,
  });

  const resolveM = useMutation({
    mutationFn: () => resolveTurn(gameId!),
    onSuccess: (data) => {
      setFeedback({ msg: `Turn ${data.turn} started. ${data.event_count} events.`, ok: true });
      track("resolve_turn", { game_id: gameId, turn: data.turn });
      setSelectedFleet(null);
      queryClient.invalidateQueries({ queryKey: ["gameState"] });
      queryClient.invalidateQueries({ queryKey: ["games"] });
    },
    onError: (err: Error) => setFeedback({ msg: err.message, ok: false }),
  });

  if (!gameId || !playerName || !gs) {
    return (
      <main className="map-area" data-testid="game-view">
        <div className="map-header">
          <span className="turn-label">Select a game</span>
        </div>
      </main>
    );
  }

  const gamesData = queryClient.getQueryData<GameListItem[]>(["games"]);
  const gameEntry = Array.isArray(gamesData)
    ? gamesData.find((g) => g.id === gameId)
    : undefined;
  const players: string[] = gameEntry
    ? gameEntry.players
    : [gs.player_name];

  return (
    <>
      <main className="map-area" data-testid="game-view">
        <div className="map-header">
          <span className="turn-label" data-testid="turn-label">
            {gs.game_id} &middot; Turn {gs.turn} &middot; {gs.player_name}
          </span>
          <select
            value={playerName}
            onChange={(e) => {
              setSelectedFleet(null);
              onPlayerChange(e.target.value);
            }}
            data-testid="player-select"
          >
            {players.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <button
            className="primary"
            onClick={() => resolveM.mutate()}
            disabled={resolveM.isPending}
            data-testid="resolve-btn"
          >
            Resolve Turn
          </button>
        </div>

        <GalaxyMap
          starSystems={gs.star_systems}
          fleets={gs.fleets}
          visibleEntities={gs.visible_entities}
          selectedFleetId={selectedFleet?.id ?? null}
          onSelectFleet={setSelectedFleet}
        />

        {feedback && (
          <div
            className={`feedback ${feedback.ok ? "feedback--ok" : "feedback--err"}`}
            data-testid="map-feedback"
          >
            {feedback.msg}
          </div>
        )}
      </main>

      <aside className="action-panel">
        <EntityPanel fleet={selectedFleet} planets={gs.planets} />
        {selectedFleet && (
          <ActionForm
            gameId={gameId}
            playerName={playerName}
            fleet={selectedFleet}
            starSystems={gs.star_systems}
            onClear={() => setSelectedFleet(null)}
          />
        )}
        <EventLog events={gs.events} />
      </aside>
    </>
  );
}
