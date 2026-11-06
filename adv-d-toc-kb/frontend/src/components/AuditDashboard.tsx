/** Audit dashboard -- run audits + view event timeline. */

import { useState } from "react";
import { useAuditLog, useRunAudit } from "../hooks/useAudit";
import { setAdminToken } from "../api/client";

interface Props {
  nodeId: string | null;
}

const EVENT_COLORS: Record<string, string> = {
  DRIFT_CORRECTED: "bg-amber-100 text-amber-800",
  ALIAS_CREATED: "bg-sky-100 text-sky-800",
  BROKEN_ALIAS_CHAIN: "bg-rose-100 text-rose-800",
  SUMMARY_UPDATED: "bg-violet-100 text-violet-800",
  PARADIGM_PIVOT: "bg-emerald-100 text-emerald-800",
  SPILLOVER_CREATED: "bg-gray-100 text-gray-800",
  NODE_CREATED: "bg-gray-100 text-gray-600",
  NODE_ROUTED: "bg-gray-100 text-gray-600",
};

export function AuditDashboard({ nodeId }: Props) {
  const log = useAuditLog(nodeId);
  const run = useRunAudit();
  const [token, setToken] = useState("");

  const handleToken = () => {
    setAdminToken(token || null);
    setToken("");
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <button
          onClick={() => run.mutate(nodeId ?? undefined)}
          disabled={run.isPending}
          className="px-3 py-1.5 rounded bg-emerald-600 text-white text-sm hover:bg-emerald-700 disabled:opacity-50"
        >
          {run.isPending
            ? "Running..."
            : `Run audit${nodeId ? "" : " (sweep)"}`}
        </button>
        {run.isSuccess && (
          <span className="text-sm text-emerald-700">Enqueued.</span>
        )}
        {run.isError && (
          <span className="text-sm text-rose-700">
            Failed: set admin token below.
          </span>
        )}
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer text-gray-600">Admin token</summary>
        <div className="mt-2 flex gap-2">
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Bearer token"
            className="border rounded px-2 py-1 font-mono text-xs w-64"
          />
          <button
            onClick={handleToken}
            className="px-2 py-1 border rounded text-xs"
          >
            Save
          </button>
        </div>
      </details>

      {log.isLoading && (
        <p className="text-sm text-gray-500">Loading audit log...</p>
      )}
      {log.error && (
        <p className="text-sm text-rose-600">Failed to load audit log.</p>
      )}
      {log.data && log.data.entries.length === 0 && (
        <p className="text-sm text-gray-500">No audit events yet.</p>
      )}
      {log.data && log.data.entries.length > 0 && (
        <ul className="space-y-1.5">
          {log.data.entries.map((entry) => (
            <li
              key={entry.id}
              className="border rounded p-2 text-sm bg-white"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`text-xs px-1.5 py-0.5 rounded ${
                    EVENT_COLORS[entry.event_type] ??
                    "bg-gray-100 text-gray-700"
                  }`}
                >
                  {entry.event_type}
                </span>
                <span className="text-xs text-gray-500">
                  {new Date(entry.created_at).toLocaleString()}
                </span>
                <span className="text-xs text-gray-400 ml-auto">
                  {entry.actor}
                </span>
              </div>
              <pre className="mt-1 text-xs font-mono text-gray-600 overflow-x-auto">
                {JSON.stringify(entry.payload, null, 0)}
              </pre>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
