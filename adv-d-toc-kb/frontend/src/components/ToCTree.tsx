/** Recursive ToC tree renderer. */

import { useState } from "react";
import type { ToCNode } from "../api/types";

interface Props {
  node: ToCNode;
  defaultOpen?: boolean;
}

/** Renders a single node and its children recursively. */
export function ToCTree({ node, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen || node.depth < 2);
  const hasChildren = node.children.length > 0;

  return (
    <li className="my-1">
      <div className="flex items-start gap-2">
        {hasChildren ? (
          <button
            onClick={() => setOpen((o) => !o)}
            aria-label={open ? "Collapse" : "Expand"}
            className="mt-1 w-4 text-gray-500 hover:text-gray-900"
          >
            {open ? "\u25BE" : "\u25B8"}
          </button>
        ) : (
          <span className="mt-1 w-4" aria-hidden />
        )}
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-900">{node.title}</span>
            {node.is_alias && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                alias -> {node.points_to_id?.slice(0, 8)}
              </span>
            )}
            <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
              {node.categorization_paradigm}
            </span>
            <span className="text-xs text-gray-400">d={node.depth}</span>
          </div>
          {node.semantic_summary && (
            <p className="text-sm text-gray-600 mt-0.5">
              {node.semantic_summary}
            </p>
          )}
        </div>
      </div>
      {hasChildren && open && (
        <ul className="ml-6 border-l border-gray-200 pl-3">
          {node.children.map((child) => (
            <ToCTree key={child.id} node={child} />
          ))}
        </ul>
      )}
    </li>
  );
}
