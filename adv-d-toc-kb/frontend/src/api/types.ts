/** Shared API types. */

export interface ToCNode {
  id: string;
  title: string;
  semantic_summary: string | null;
  depth: number;
  categorization_paradigm: string;
  is_alias: boolean;
  points_to_id: string | null;
  children: ToCNode[];
}

export interface TreeResponse {
  root: ToCNode;
  truncated: boolean;
}

export interface IngestRequest {
  root_id: string;
  content: string;
  title_hint?: string;
  summary_hint?: string;
}

export interface IngestResponse {
  node_id: string;
  routed_path: string[];
  spillover_created: boolean;
  pivot_triggered: boolean;
  duplicate: boolean;
  tokens_in_node: number;
}

export interface AuditLogEntry {
  id: number;
  node_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  actor: string;
  created_at: string;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
}

export interface RunAuditResponse {
  total: number;
  processed: number;
  errors: number;
}
