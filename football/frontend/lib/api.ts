// 백엔드 API 타입과 호출 함수. 시간 문자열은 모두 KST(+09:00) ISO 형식.

export type TeamRef = { id: number; name: string; name_ko: string | null; short_name: string; color: string };

export type League = {
  key: string;
  name_ko: string;
  type: "league" | "cup";
  region: "europe" | "asia";
  seasons: string[];
  current_season: string | null;
  has_match_stats: boolean;
  has_xg: boolean;
  has_standings: boolean;
  tiebreak: ("points" | "gd" | "gf")[];
  has_split: boolean;
};

export type Probabilities = {
  model: "dixon_coles" | "elo";
  home_win: number;
  draw: number;
  away_win: number;
  over_2_5: number | null;
  btts: number | null;
};

export type MatchItem = {
  id: number;
  league_key: string;
  league_name_ko: string;
  season: string;
  kickoff_kst: string;
  status: "scheduled" | "finished" | "postponed" | "cancelled";
  home: TeamRef;
  away: TeamRef;
  home_goals: number | null;
  away_goals: number | null;
  decided_by: string | null;
  prediction: Probabilities | null;
};

export type Form = { results: string; points: number; games: number; goals_for: number; goals_against: number };

export type Profile = Record<string, number | null>;

export type ComparisonSide = {
  team: TeamRef;
  form5: Form;
  form10: Form;
  profile: Profile;
  rest_days: number | null;
  matches_last_14d: number;
  elo: number | null;
};

export type MatchDetail = {
  match: MatchItem;
  venue: string | null;
  neutral_venue: boolean;
  prediction: {
    main: Probabilities;
    others: Probabilities[];
    expected_goals: { home: number; away: number } | null;
    most_likely_score: { home: number; away: number; probability: number } | null;
    score_matrix: number[][] | null;
    made_at_kst: string;
    pre_match: boolean;
  } | null;
  comparison: { home: ComparisonSide; away: ComparisonSide };
  head_to_head: {
    games: number;
    home_team_wins: number;
    draws: number;
    away_team_wins: number;
    matches: { match_id: number; kickoff_kst: string; home_team_was_home: boolean; home_team_goals: number; away_team_goals: number }[];
  };
  model_explanation: string;
  disclaimer: string;
};

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function get<T>(path: string, revalidate = 60): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { next: { revalidate } });
  if (!res.ok) {
    let detail = `요청 실패 (${res.status})`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}


export type StandingRow = {
  rank: number;
  team: TeamRef;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  goal_diff: number;
  points: number;
  form: string;
  group: "A" | "B" | null;
};

export type Standings = {
  league: League;
  season: string;
  venue: "all" | "home" | "away";
  rows: StandingRow[];
  averages: {
    matches: number;
    goals_per_match: number | null;
    home_win_rate: number | null;
    draw_rate: number | null;
    away_win_rate: number | null;
    over_2_5_rate: number | null;
    btts_rate: number | null;
    shots_per_team: number | null;
    corners_per_team: number | null;
    xg_per_team: number | null;
  };
  top_scorers: unknown[] | null;
};

export type TeamDetail = {
  team: TeamRef;
  league: League | null;
  season: string | null;
  standing: StandingRow | null;
  form5: Form;
  form10: Form;
  home: Record<string, number | string | null> | null;
  away: Record<string, number | string | null> | null;
  profile: Profile;
  goals_by_half: Profile;
  recent_matches: MatchItem[];
  upcoming_matches: MatchItem[];
  injuries: unknown[];
  players: unknown[];
  data_notes: string[];
};

export type PerformanceRow = { model: string; matches: number; log_loss: number; brier: number; accuracy: number };

export type ModelPerformance = {
  overall: PerformanceRow[];
  by_league: Record<string, PerformanceRow[]>;
  calibration: Record<string, { bin: string; predicted: number; observed: number; count: number }[]>;
  recent: { match: MatchItem; kind: "live" | "backtest"; predicted_pick: string; actual: string; hit: boolean }[];
  notes: string[];
};

export const api = {
  leagues: () => get<League[]>("/api/leagues", 300),
  matches: (params: Record<string, string | undefined>) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return get<MatchItem[]>(`/api/matches?${q}`);
  },
  match: (id: string | number) => get<MatchDetail>(`/api/matches/${id}`),
  standings: (key: string, venue = "all", season?: string) =>
    get<Standings>(`/api/leagues/${key}/standings?venue=${venue}${season ? `&season=${encodeURIComponent(season)}` : ""}`),
  team: (id: string | number) => get<TeamDetail>(`/api/teams/${id}`),
  performance: () => get<ModelPerformance>("/api/model-performance", 600),
};
