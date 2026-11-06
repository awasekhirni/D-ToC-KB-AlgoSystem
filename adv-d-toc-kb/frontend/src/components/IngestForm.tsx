/** Ingest form -- paste content, route it into the tree. */

import { useState, type FormEvent } from "react";
import { useIngest } from "../hooks/useToCTree";

interface Props {
  rootId: string;
  onSuccess?: () => void;
}

export function IngestForm({ rootId, onSuccess }: Props) {
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useIngest();

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!content.trim()) {
      setError("Content is required.");
      return;
    }
    mutation.mutate(
      { root_id: rootId, content: content.trim() },
      {
        onSuccess: () => {
          setContent("");
          onSuccess?.();
        },
        onError: (err) =>
          setError(err instanceof Error ? err.message : "Ingest failed"),
      },
    );
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      <label htmlFor="ingest-content" className="block text-sm font-medium">
        Content
      </label>
      <textarea
        id="ingest-content"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={5}
        className="w-full border rounded p-2 text-sm font-mono"
        placeholder="Paste or type content..."
        disabled={mutation.isPending}
      />
      {error && <p className="text-sm text-red-600">{error}</p>}
      <button
        type="submit"
        className="px-3 py-1.5 rounded bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:opacity-50"
        disabled={mutation.isPending}
      >
        {mutation.isPending ? "Routing..." : "Ingest"}
      </button>
      {mutation.isSuccess && (
        <p className="text-sm text-green-700">
          Routed to {mutation.data.routed_path.length} node(s)
          {mutation.data.duplicate && " (duplicate -- no change)"}
          {mutation.data.pivot_triggered && " . pivot triggered"}
          {mutation.data.spillover_created && " . spillover created"}
        </p>
      )}
    </form>
  );
}
