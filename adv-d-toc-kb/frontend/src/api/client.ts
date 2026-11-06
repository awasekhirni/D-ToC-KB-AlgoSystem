/** Typed API client. */

import type {
  IngestRequest,
  IngestResponse,
  AuditLogResponse,
  RunAuditResponse,
  TreeResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const ADMIN_TOKEN_KEY = "tockb_admin_token";

/** Error thrown when the API returns a non-2xx status. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(`API error ${status}`);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(res.status, body);
  }
  return (await res.json()) as T;
}

export function setAdminToken(token: string | null): void {
  if (token) {
    localStorage.setItem(ADMIN_TOKEN_KEY, token);
  } else {
    localStorage.removeItem(ADMIN_TOKEN_KEY);
  }
}

function adminHeaders(): Record<string, string> {
  const t = localStorage.getItem(ADMIN_TOKEN_KEY);
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export const api = {
  /** Fetch the full subtree rooted at ``rootId``. */
  getTree: (rootId: string): Promise<TreeResponse> =>
    request<TreeResponse>(`/toc/${rootId}`),

  /** Ingest content into the tree. */
  ingest: (body: IngestRequest): Promise<IngestResponse> =>
    request<IngestResponse>("/ingest", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Fetch the audit log timeline for a node. */
  getAuditLog: (nodeId: string, limit = 50): Promise<AuditLogResponse> =>
    request<AuditLogResponse>(`/audit/log/${nodeId}?limit=${limit}`, {
      headers: adminHeaders(),
    }),

  /** Trigger an audit sweep (or single-node if ``nodeId`` is given). */
  runAudit: (nodeId?: string): Promise<RunAuditResponse> =>
    request<RunAuditResponse>(
      `/audit/run${nodeId ? `?node_id=${nodeId}` : ""}`,
      { method: "POST", headers: adminHeaders() },
    ),
};
