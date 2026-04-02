import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { submitAction } from "../services/ApiClient";
import { useTelemetry } from "../contexts/TelemetryContext";
import type { Fleet, StarSystem } from "../services/types";

interface Props {
  gameId: string;
  playerName: string;
  fleet: Fleet;
  starSystems: StarSystem[];
  onClear: () => void;
}

export default function ActionForm({
  gameId,
  playerName,
  fleet,
  starSystems,
  onClear,
}: Props) {
  const queryClient = useQueryClient();
  const { track } = useTelemetry();
  const [dest, setDest] = useState(starSystems[0]?.name ?? "");
  const [feedback, setFeedback] = useState<{ msg: string; ok: boolean } | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      submitAction(gameId, playerName, "MoveFleet", {
        fleet: fleet.name,
        target: dest,
      }),
    onSuccess: (data) => {
      if (!data.valid) {
        setFeedback({ msg: data.errors.join("; "), ok: false });
        return;
      }
      setFeedback({ msg: "Move order queued.", ok: true });
      track("submit_order", { game_id: gameId, fleet: fleet.name, dest });
      queryClient.invalidateQueries({ queryKey: ["gameState"] });
      onClear();
    },
    onError: (err: Error) => setFeedback({ msg: err.message, ok: false }),
  });

  return (
    <section className="action-form" data-testid="action-form">
      <h2>Move Fleet</h2>
      <label>
        Destination:
        <select
          value={dest}
          onChange={(e) => setDest(e.target.value)}
          data-testid="dest-select"
        >
          {starSystems.map((sys) => (
            <option
              key={sys.id}
              value={sys.name}
              disabled={sys.id === fleet.system_id}
            >
              {sys.name}
            </option>
          ))}
        </select>
      </label>
      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        data-testid="submit-move"
      >
        Submit Move
      </button>
      {feedback && (
        <div
          className={`feedback ${feedback.ok ? "feedback--ok" : "feedback--err"}`}
          data-testid="action-feedback"
        >
          {feedback.msg}
        </div>
      )}
    </section>
  );
}
