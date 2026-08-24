/*
 * The JSON shape of a `mcpcheckup ci --json` report, mirrored from the Pydantic models in
 * mcpcheckup/model/. Two things about that JSON drive every optional here:
 *
 *  - it is snake_case, because it is the protocol-facing form, and
 *  - it is produced by `canonical_json`, which drops nulls -- so any field the Python model
 *    defaults to None is simply absent, not present-and-null. `eval_score` absent means a
 *    lint-only score; `selected` absent on a confusion cell means the model called nothing;
 *    `eval` and `history` absent mean that half of the run did not happen.
 *
 * These are read, never written, so everything the renderer does not use is left off.
 */

export type Severity = "error" | "warning" | "info";

export interface ServerInfo {
  name?: string | null;
  version?: string | null;
  protocol_version?: string | null;
  instructions?: string | null;
}

export interface Finding {
  rule: string;
  severity: Severity;
  message: string;
  suggestion: string;
  tool?: string | null;
  parameter?: string | null;
  related?: string[];
}

export interface LintResult {
  target: string;
  server: ServerInfo;
  tool_count: number;
  findings?: Finding[];
}

export interface HealthScore {
  overall: number;
  lint_score: number;
  eval_score?: number | null;
  errors?: number;
  warnings?: number;
}

export interface HealthPoint {
  recorded_at: string;
  label?: string | null;
  health: HealthScore;
}

export interface ToolScore {
  tool: string;
  correct: number;
  total: number;
}

export interface ConfusionCell {
  expected: string;
  selected?: string | null;
  count: number;
  share: number;
}

export interface EvalScores {
  selection_correct?: number;
  selection_total?: number;
  positive_correct?: number;
  positive_total?: number;
  sibling_correct?: number;
  sibling_total?: number;
  abstention_correct?: number;
  abstention_total?: number;
  argument_correct?: number;
  argument_total?: number;
  per_tool?: ToolScore[];
  confusion?: ConfusionCell[];
}

export interface EvalResult {
  target: string;
  server: ServerInfo;
  model: string;
  tool_digest: string;
  scores: EvalScores;
  cached_count?: number;
  called_count?: number;
  cost_usd?: number;
}

export interface CiReport {
  target: string;
  server: ServerInfo;
  health: HealthScore;
  lint: LintResult;
  eval?: EvalResult | null;
  history?: HealthPoint[] | null;
}
