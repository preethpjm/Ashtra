import { useEffect, useState } from "react";
import type { OutlineNode } from "./api";

interface Props {
  root: OutlineNode;
  selectedPath: string | null;
  errorPaths: Map<string, number>;   // path -> own error count
  onPick: (n: OutlineNode) => void;
}

function subtreeErrors(n: OutlineNode, errs: Map<string, number>): number {
  return (errs.get(n.path) ?? 0) + n.children.reduce((a, c) => a + subtreeErrors(c, errs), 0);
}

export function Tree({ root, selectedPath, errorPaths, onPick }: Props) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  useEffect(() => {
    // open the first three levels, plus the selected element's ancestors
    const s = new Set<string>();
    const walk = (n: OutlineNode, d: number) => { if (d < 3) { s.add(n.path); n.children.forEach((c) => walk(c, d + 1)); } };
    walk(root, 0);
    setOpen((prev) => new Set([...prev, ...s]));
  }, [root.path]);
  useEffect(() => {
    if (!selectedPath) return;
    const parts = selectedPath.split("/").slice(1);
    const anc = parts.map((_, i) => "/" + parts.slice(0, i + 1).join("/"));
    setOpen((prev) => new Set([...prev, ...anc.slice(0, -1)]));
    requestAnimationFrame(() => document.querySelector(`[data-tree-path="${CSS.escape(selectedPath)}"]`)?.scrollIntoView({ block: "nearest" }));
  }, [selectedPath]);

  const render = (n: OutlineNode, depth: number) => {
    const isOpen = open.has(n.path);
    const errs = subtreeErrors(n, errorPaths);
    return (
      <li key={n.path}>
        <div className={`tree-row${selectedPath === n.path ? " selected" : ""}`} style={{ paddingLeft: 6 + depth * 12 }}
          data-tree-path={n.path} onClick={() => onPick(n)} title={`${n.path}  (line ${n.line})`}>
          <button className="twisty" aria-label={isOpen ? "Collapse" : "Expand"} disabled={!n.children.length}
            onClick={(e) => { e.stopPropagation(); setOpen((p) => { const s = new Set(p); s.has(n.path) ? s.delete(n.path) : s.add(n.path); return s; }); }}>
            {n.children.length ? (isOpen ? "▾" : "▸") : ""}
          </button>
          <span className="tree-name">{n.name}</span>
          {n.label && <span className="tree-label">{n.label}</span>}
          {errs > 0 && <span className="tree-err" title={`${errs} problem(s)`}>{errs}</span>}
        </div>
        {isOpen && n.children.length > 0 && <ul>{n.children.map((c) => render(c, depth + 1))}</ul>}
      </li>
    );
  };
  return <ul className="tree">{render(root, 0)}</ul>;
}
