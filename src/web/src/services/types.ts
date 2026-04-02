/* TypeScript types mirroring the JSON shapes from export_game_state. */

export interface GameListItem {
  id: string;
  name: string;
  turn: number;
  players: string[];
}

export interface Fleet {
  id: string;
  name: string;
  position_x: number;
  position_y: number;
  system_id: string | null;
  system_name: string;
  destination_id: string | null;
  destination_name: string;
  turns_remaining: number;
  speed: number;
  resources: Record<string, number>;
}

export interface Planet {
  id: string;
  name: string;
  system_id: string | null;
  system_name: string;
  position_x: number;
  position_y: number;
  resources: Record<string, number>;
  population: number;
  morale: number;
  growth_rate: number;
}

export interface StarSystem {
  id: string;
  name: string;
  position_x: number;
  position_y: number;
  planet_ids: string[];
}

export interface VisibleEntity {
  id: string;
  name: string;
  type: "fleet" | "planet" | "unknown";
  position_x: number;
  position_y: number;
  stale: boolean;
}

export interface GameEvent {
  type: string;
  description: string;
  entity_name: string;
}

export interface Research {
  active_tech: string | null;
  progress: number;
  required_progress: number;
  unlocked: string[];
}

export interface GameState {
  turn: number;
  game_id: string;
  player_name: string;
  player_id: string;
  fleets: Fleet[];
  planets: Planet[];
  star_systems: StarSystem[];
  visible_entities: VisibleEntity[];
  events: GameEvent[];
  research: Research | null;
}

export interface CreateGameResponse {
  game_id: string;
  players: Record<string, string>;
  turn: number;
}

export interface SubmitActionResponse {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface ActionResult {
  action_type: string;
  status: string;
  errors: string[];
}

export interface ResolveTurnResponse {
  turn: number;
  action_results: ActionResult[];
  event_count: number;
}

export interface RouteSummary {
  route: string;
  method: string;
  count: number;
  avg_ms: number;
  p95_ms: number;
  error_count: number;
}

export interface RequestEntry {
  request_id: string;
  route: string;
  method: string;
  status: number;
  duration_ms: number;
  ts: number;
}

export interface TelemetryEntry {
  request_id: string;
  event_type: string;
  ts_ms: number;
  data: Record<string, unknown>;
}

export interface MetricsResponse {
  routes: RouteSummary[];
  recent_requests: RequestEntry[];
  telemetry_events: TelemetryEntry[];
}

export interface ApiError {
  error: string;
}
