import { useMemo, useState } from "react";

import type { ServiceGraph as Graph, ServiceHealth } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { STATUS, type StatusKey } from "@/components/serviceStatus";
import { cn } from "@/lib/utils";

const NODE_W = 132;
const NODE_H = 34;
const COL_GAP = 74;
const ROW_GAP = 14;
const PAD = 16;

interface Placed {
  name: string;
  x: number;
  y: number;
  depth: number;
}

/** Longest-path layering: a node sits one column right of its deepest caller.
 *
 * The demo's graph has cycles in practice (a service calling back through
 * flagd, say), so the walk carries the path it came from and refuses to
 * revisit it. Without that guard a cycle recurses until the stack gives out.
 */
function layout(nodes: string[], edges: Graph["edges"]) {
  const callers = new Map<string, string[]>();
  for (const node of nodes) callers.set(node, []);
  for (const edge of edges) {
    if (callers.has(edge.target)) callers.get(edge.target)!.push(edge.source);
  }

  const depths = new Map<string, number>();
  const depthOf = (name: string, path: Set<string>): number => {
    if (depths.has(name)) return depths.get(name)!;
    if (path.has(name)) return 0;
    const parents = callers.get(name) ?? [];
    const next = new Set(path).add(name);
    const depth = parents.length
      ? Math.max(...parents.map((parent) => depthOf(parent, next) + 1))
      : 0;
    // A node reached through a cycle gets the clamped depth cached too. That is
    // arbitrary but deterministic, which is what a layout needs; the columns
    // stay stable across refreshes rather than shuffling.
    depths.set(name, depth);
    return depth;
  };
  for (const node of nodes) depthOf(node, new Set());

  const columns = new Map<number, string[]>();
  for (const node of nodes) {
    const depth = depths.get(node) ?? 0;
    if (!columns.has(depth)) columns.set(depth, []);
    columns.get(depth)!.push(node);
  }

  const placed = new Map<string, Placed>();
  let tallest = 0;
  for (const [depth, members] of [...columns.entries()].sort((a, b) => a[0] - b[0])) {
    members.sort();
    tallest = Math.max(tallest, members.length);
    members.forEach((name, index) => {
      placed.set(name, {
        name,
        depth,
        x: PAD + depth * (NODE_W + COL_GAP),
        y: PAD + index * (NODE_H + ROW_GAP),
      });
    });
  }

  return {
    placed,
    width: PAD * 2 + columns.size * NODE_W + Math.max(0, columns.size - 1) * COL_GAP,
    height: PAD * 2 + tallest * NODE_H + Math.max(0, tallest - 1) * ROW_GAP,
  };
}

export function ServiceGraph({
  graph,
  health,
  selected,
  onSelect,
}: {
  graph: Graph;
  health: Map<string, ServiceHealth>;
  selected: string | null;
  onSelect: (name: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const compactNodes = useMemo(() => {
    const linked = new Set(graph.edges.flatMap(edge => [edge.source, edge.target]));
    return graph.nodes.filter(name => {
      const entry = health.get(name);
      // Keep request-serving services even when Jaeger has no dependency edge.
      // Offline services and active faults must remain visible for diagnosis.
      return linked.has(name) || name === selected || entry?.rate_per_sec != null ||
        !!entry?.injected_fault || ["offline", "degraded", "critical"].includes(entry?.status ?? "");
    });
  }, [graph, health, selected]);
  const visibleGraph = useMemo(() => {
    const nodes = showAll ? graph.nodes : compactNodes;
    const included = new Set(nodes);
    return { nodes, edges: graph.edges.filter(edge => included.has(edge.source) && included.has(edge.target)) };
  }, [graph, compactNodes, showAll]);
  const { placed, width, height } = useMemo(
    () => layout(visibleGraph.nodes, visibleGraph.edges),
    [visibleGraph],
  );

  if (!graph.available) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        Jaeger did not answer, so the call graph is unavailable.
        {graph.reason ? (
          <span className="mt-1 block font-mono text-xs">{graph.reason}</span>
        ) : null}
      </p>
    );
  }

  if (graph.nodes.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No dependencies yet. Jaeger builds this from stored traces, so give the
        load generator a few minutes.
      </p>
    );
  }

  const busiest = Math.max(...visibleGraph.edges.map((edge) => edge.calls), 1);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {visibleGraph.nodes.length} of {graph.nodes.length} services shown.
          {!showAll && " Request traffic, dependencies, and active issues."}
        </p>
        {compactNodes.length < graph.nodes.length && (
          <Button type="button" variant="outline" size="sm" aria-pressed={showAll}
            onClick={() => setShowAll(value => !value)}>
            {showAll ? "Hide unrelated services" : `Show all ${graph.nodes.length} services`}
          </Button>
        )}
      </div>
      {visibleGraph.nodes.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          No request traffic or dependencies observed yet. Show all services to inspect registered workloads.
        </p>
      ) : (
    // The SVG keeps its intrinsic pixel width and scrolls inside this box,
    // rather than scaling down until the labels are unreadable.
    <div className="scrollbar-themed w-full overflow-x-auto">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Call graph of ${visibleGraph.nodes.length} services`}
        className="block"
      >
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 8 4 L 0 7 z" className="fill-border" />
          </marker>
        </defs>

        {visibleGraph.edges.map((edge) => {
          const from = placed.get(edge.source);
          const to = placed.get(edge.target);
          if (!from || !to) return null;
          const x1 = from.x + NODE_W;
          const y1 = from.y + NODE_H / 2;
          const x2 = to.x;
          const y2 = to.y + NODE_H / 2;
          const bend = Math.max(24, (x2 - x1) / 2);
          const touched =
            selected === edge.source || selected === edge.target || selected === null;
          return (
            <path
              key={`${edge.source}->${edge.target}`}
              d={`M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`}
              fill="none"
              markerEnd="url(#arrow)"
              className={cn("stroke-border", touched ? "opacity-100" : "opacity-20")}
              strokeWidth={1 + (edge.calls / busiest) * 2.5}
            >
              <title>{`${edge.source} → ${edge.target}: ${edge.calls} calls`}</title>
            </path>
          );
        })}

        {[...placed.values()].map((node) => {
          const entry = health.get(node.name);
          const style = STATUS[(entry?.status ?? "unknown") as StatusKey];
          const isSelected = selected === node.name;
          return (
            <g
              key={node.name}
              transform={`translate(${node.x}, ${node.y})`}
              onClick={() => onSelect(node.name)}
              className="cursor-pointer"
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(node.name);
                }
              }}
            >
              <title>
                {`${node.name} — ${style.label}${entry ? `, ${entry.reason}` : ""}`}
              </title>
              <rect
                width={NODE_W}
                height={NODE_H}
                rx={6}
                className={cn(
                  "fill-card stroke-border",
                  isSelected && "stroke-ring",
                )}
                strokeWidth={isSelected ? 2 : 1}
              />
              {/* Status is a stripe plus the tooltip label, never colour alone. */}
              <rect width={4} height={NODE_H} rx={2} className={style.fill} />
              <text
                x={14}
                y={NODE_H / 2 + 4}
                className="fill-foreground text-[11px] font-medium"
              >
                {node.name.length > 16 ? `${node.name.slice(0, 15)}…` : node.name}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
      )}
    </div>
  );
}
