/** TanStack Query hooks for audit log + run. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

/** Poll the audit log for a node (10s interval). */
export function useAuditLog(nodeId: string | null) {
  return useQuery({
    queryKey: ["audit", "log", nodeId],
    queryFn: () => api.getAuditLog(nodeId!, 100),
    enabled: !!nodeId,
    refetchInterval: 10_000,
  });
}

/** Run audit mutation; invalidates audit queries on success. */
export function useRunAudit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (nodeId?: string) => api.runAudit(nodeId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["audit"] });
    },
  });
}
