import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listGames, createGame } from "../services/ApiClient";
import { useTelemetry } from "../contexts/TelemetryContext";
import type { GameListItem } from "../services/types";

interface Props {
  activeGameId: string | null;
  onSelectGame: (gameId: string, player: string) => void;
}

export default function GameList({ activeGameId, onSelectGame }: Props) {
  const queryClient = useQueryClient();
  const { track } = useTelemetry();

  const { data: games = [], error: gamesError } = useQuery<GameListItem[]>({
    queryKey: ["games"],
    queryFn: listGames,
    retry: 1,
  });

  const [name, setName] = useState("");
  const [player1, setPlayer1] = useState("Player1");
  const [player2, setPlayer2] = useState("Player2");
  const [feedback, setFeedback] = useState<{ msg: string; ok: boolean } | null>(null);

  const mutation = useMutation({
    mutationFn: () => createGame(name.trim(), player1.trim(), player2.trim()),
    onSuccess: (data) => {
      setFeedback({ msg: `Created "${data.game_id}".`, ok: true });
      setName("");
      track("create_game", { game_id: data.game_id });
      queryClient.invalidateQueries({ queryKey: ["games"] });
    },
    onError: (err: Error) => {
      setFeedback({ msg: err.message, ok: false });
    },
  });

  const handleCreate = () => {
    if (!name.trim()) {
      setFeedback({ msg: "Game name is required.", ok: false });
      return;
    }
    mutation.mutate();
  };

  return (
    <>
      <section data-testid="new-game-panel">
        <h2>New Game</h2>
        <input
          type="text"
          placeholder="Game name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          data-testid="ng-name"
        />
        <input
          type="text"
          placeholder="Player 1"
          value={player1}
          onChange={(e) => setPlayer1(e.target.value)}
          data-testid="ng-player1"
        />
        <input
          type="text"
          placeholder="Player 2"
          value={player2}
          onChange={(e) => setPlayer2(e.target.value)}
          data-testid="ng-player2"
        />
        <button onClick={handleCreate} data-testid="ng-create">
          Create Game
        </button>
        {feedback && (
          <div className={`feedback ${feedback.ok ? "feedback--ok" : "feedback--err"}`} data-testid="ng-feedback">
            {feedback.msg}
          </div>
        )}
      </section>

      <section data-testid="game-list-panel">
        <h2>Games</h2>
        {gamesError && (
          <div className="feedback feedback--err" data-testid="games-error">
            {(gamesError as Error)?.message ?? "Could not reach server"}
          </div>
        )}
        <ul className="game-list" data-testid="game-list">
          {games.map((g) => (
            <li
              key={g.id}
              className={g.id === activeGameId ? "active" : ""}
              onClick={() => {
                const player = g.players[0] ?? "Player1";
                onSelectGame(g.id, player);
              }}
            >
              <span>{g.name}</span>
              <span className="game-turn">T{g.turn}</span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
