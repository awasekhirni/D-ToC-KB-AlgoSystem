/** TanStack Query hooks for tree + ingest. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { IngestRequest } from "../api/types";

/** Fetch the subtree rooted at ``rootId``. */
export function useToCTree(rootId: string | null) {
  return useQuery({
    queryKey: ["toc", rootId],
    queryFn: () => api.getTree(rootId!),
    enabled: !!rootId,
    staleTime: 15_000,
  });
}

/** Ingest mutation; invalidates the tree on success. */
export function useIngest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: IngestRequest) => api.ingest(body),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: ["toc", variables.root_id],
      });
    },
  });
}
