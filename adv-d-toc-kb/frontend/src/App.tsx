/** Main app -- tree visualizer + ingest form + audit dashboard. */

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useToCTree } from "./hooks/useToCTree";
import { IngestForm } from "./components/IngestForm";
import { ToCTree } from "./components/ToCTree";
import { AuditDashboard } from "./components/AuditDashboard";

const queryClient = new QueryClient();

function Dashboard() {
  const [rootId, setRootId] = useState<string>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("root") ?? "";
  });

  const { data, isLoading, error } = useToCTree(rootId || null);

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Adv-D-ToC-KB Console</h1>
        <div className="mt-2 flex gap-2 items-center">
          <label htmlFor="root-input" className="text-sm">
            Root ID:
          </label>
          <input
            id="root-input"
            value={rootId}
            onChange={(e) => setRootId(e.target.value)}
            placeholder="UUID"
            className="border rounded px-2 py-1 text-sm font-mono w-80"
          />
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <section className="lg:col-span-2 bg-white rounded shadow p-4">
          <h2 className="font-semibold mb-3">Tree</h2>
          {isLoading && <p className="text-sm text-gray-500">Loading...</p>}
          {error && (
            <p className="text-sm text-red-600">Failed to load tree.</p>
          )}
          {data && (
            <>
              <ul>
                <ToCTree node={data.root} defaultOpen />
              </ul>
              {data.truncated && (
                <p className="mt-2 text-sm text-amber-600">
                  Tree truncated at 5,000 nodes.
                </p>
              )}
            </>
          )}
        </section>

        <section className="bg-white rounded shadow p-4">
          <h2 className="font-semibold mb-3">Ingest</h2>
          {rootId ? (
            <IngestForm rootId={rootId} />
          ) : (
            <p className="text-sm text-gray-500">Enter a root ID first.</p>
          )}
        </section>

        <section className="bg-white rounded shadow p-4">
          <h2 className="font-semibold mb-3">Audit</h2>
          <AuditDashboard nodeId={rootId || null} />
        </section>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
    </QueryClientProvider>
  );
}
