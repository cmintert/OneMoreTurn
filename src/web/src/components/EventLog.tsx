import type { GameEvent } from "../services/types";

interface Props {
  events: GameEvent[];
}

export default function EventLog({ events }: Props) {
  return (
    <section data-testid="events-panel">
      <h2>Events</h2>
      <ul className="event-list" data-testid="event-list">
        {events.length === 0 ? (
          <li className="muted">No events this turn.</li>
        ) : (
          events.slice(-10).map((ev, i) => (
            <li key={i}>
              <strong>{ev.type}</strong> {ev.description}
            </li>
          ))
        )}
      </ul>
    </section>
  );
}
