import { useEffect, useMemo, useRef, useState } from "react";
import { Adm, localName } from "./adm";
import type { AttrDef, SchemaModel, Template } from "./schemaModel";
import { humanize } from "./VisualEditor";

export interface InsertGroup { key: string; label: string; names: string[] }

/** The + handle and insert menu next to the selected element. Only allowed elements are listed. */
export function InsertMenu({ anchorNid, groups, onPick, onClose }: {
  anchorNid: number; groups: InsertGroup[]; onPick: (group: string, name: string) => void; onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 120, left: 400 });
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = document.querySelector(`.visual [data-nid="${anchorNid}"]`) as HTMLElement | null;
    const r = el?.getBoundingClientRect();
    if (r) setPos({ top: Math.min(r.top + 4, window.innerHeight - 380), left: Math.max(12, Math.min(r.left + 24, window.innerWidth - 340)) });
    box.current?.querySelector("input")?.focus();
  }, [anchorNid]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const shown = groups.map((g) => ({ ...g, names: g.names.filter((n) => !q || n.toLowerCase().includes(q.toLowerCase()) || humanize(n).toLowerCase().includes(q.toLowerCase())) }));
  const total = shown.reduce((a, g) => a + g.names.length, 0);
  return (
    <>
      <div className="menu-veil" onClick={onClose} />
      <div ref={box} className="insert-menu" style={{ top: pos.top, left: pos.left }} role="dialog" aria-label="Insert element">
        <input placeholder="Filter elements…" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { const g = shown.find((x) => x.names.length); if (g) onPick(g.key, g.names[0]); } }} />
        <div className="im-body">
          {shown.map((g) => g.names.length > 0 && (
            <div key={g.key} className="im-group">
              <div className="im-label">{g.label}</div>
              {g.names.map((n) => (
                <button key={n} className="im-item" onClick={() => onPick(g.key, n)}>
                  <span>{humanize(n)}</span><code>{n}</code>
                </button>
              ))}
            </div>
          ))}
          {total === 0 && <p className="muted small pad">{q ? "No allowed element matches." : "The schema allows nothing to be inserted here."}</p>}
        </div>
        <div className="im-foot muted small">Only elements the schema allows at this position are listed.</div>
      </div>
    </>
  );
}

/** Asks for required attributes a new element cannot fill in by itself. */
export function AttrDialog({ title, needs, ids, onCancel, onOk }: {
  title: string; needs: Template["needs"]; ids: [string, string][];
  onCancel: () => void; onOk: (values: Record<string, string>) => void;
}) {
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(needs.map((n) => [n.id, n.attr.values[0] ?? ""])));
  const missing = needs.filter((n) => !vals[n.id]);
  return (
    <div className="modal-bg" onClick={onCancel}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="ad-h" onClick={(e) => e.stopPropagation()}>
        <h2 id="ad-h">{title}</h2>
        <p>The schema requires these values.</p>
        {needs.map((n) => (
          <label key={n.id} className="field">
            <span><code>{n.element}</code> · {n.attr.name} <span className="req">*</span></span>
            {n.attr.kind === "enum" ? (
              <select value={vals[n.id]} onChange={(e) => setVals({ ...vals, [n.id]: e.target.value })}>
                {n.attr.values.map((v) => <option key={v}>{v}</option>)}
              </select>
            ) : n.attr.kind === "idref" || n.attr.kind === "idrefs" ? (
              <select value={vals[n.id]} onChange={(e) => setVals({ ...vals, [n.id]: e.target.value })}>
                <option value="">choose the target…</option>
                {ids.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
              </select>
            ) : (
              <input autoFocus value={vals[n.id]} onChange={(e) => setVals({ ...vals, [n.id]: e.target.value })} />
            )}
          </label>
        ))}
        <div className="modal-actions">
          <button onClick={onCancel}>Cancel</button>
          <button className="primary" disabled={missing.length > 0} onClick={() => onOk(vals)}>Insert</button>
        </div>
      </div>
    </div>
  );
}

/** Attributes of the selected element, driven by the schema: required ones marked, optional
 *  ones removable, missing ones addable, enumerations and ID references as lists. */
export function AttributeEditor({ adm, k, model, editable, ids, onSet, onAdd, onRemove }: {
  adm: Adm; k: number; model: SchemaModel | null; editable: boolean; ids: [string, string][];
  onSet: (name: string, value: string) => void; onAdd: (def: AttrDef) => void; onRemove: (name: string) => void;
}) {
  const el = adm.elements[k];
  const defs = model?.elements[localName(el)]?.attrs ?? [];
  const byName = useMemo(() => new Map(defs.map((d) => [d.name, d])), [defs]);
  const present = Array.from(el.attributes).filter((a) => !a.name.startsWith("xmlns") && !a.name.startsWith("xsi:"));
  const missing = defs.filter((d) => !el.hasAttribute(d.name));
  const commit = (name: string, v: string, old: string) => { if (v !== old) onSet(name, v); };
  return (
    <div className="attr-editor">
      {present.length === 0 && missing.length === 0 && <p className="muted small">No attributes.</p>}
      <table className="attrs"><tbody>
        {present.map((a) => {
          const d = byName.get(a.name);
          return (
            <tr key={a.name + a.value}>
              <th title={d ? `${d.kind}${d.required ? ", required" : ""}` : "not in the schema"}>
                {a.name}{d?.required && <span className="req">*</span>}{!d && model && <span className="unknown" title="not declared by the schema">?</span>}
              </th>
              <td>
                {d?.kind === "enum" ? (
                  <select value={a.value} disabled={!editable || !!d.fixed} onChange={(e) => commit(a.name, e.target.value, a.value)}>
                    {!d.values.includes(a.value) && <option value={a.value}>{a.value} (not allowed)</option>}
                    {d.values.map((v) => <option key={v}>{v}</option>)}
                  </select>
                ) : d?.kind === "idref" ? (
                  <select value={a.value} disabled={!editable} onChange={(e) => commit(a.name, e.target.value, a.value)}>
                    {!ids.some(([i]) => i === a.value) && <option value={a.value}>{a.value} (no such ID)</option>}
                    {ids.map(([i, label]) => <option key={i} value={i}>{label}</option>)}
                  </select>
                ) : (
                  <input defaultValue={a.value} disabled={!editable || !!d?.fixed}
                    onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                    onBlur={(e) => commit(a.name, e.target.value, a.value)} />
                )}
              </td>
              <td className="x-cell">{editable && !d?.required && <button className="icon" title={`Remove ${a.name}`} aria-label={`Remove ${a.name}`} onClick={() => onRemove(a.name)}>✕</button>}</td>
            </tr>
          );
        })}
      </tbody></table>
      {editable && missing.length > 0 && (
        <select className="add-attr" value="" onChange={(e) => { const d = byName.get(e.target.value); if (d) onAdd(d); }}>
          <option value="">+ Add attribute…</option>
          {missing.map((d) => <option key={d.name} value={d.name}>{d.name}{d.required ? " (required)" : ""}</option>)}
        </select>
      )}
      {!model && <p className="muted small">No schema model loaded: attribute rules are not available.</p>}
    </div>
  );
}
