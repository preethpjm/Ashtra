import { useEffect, useMemo, useRef, useState } from "react";
import { Adm, localName } from "./adm";
import type { AttrDef, SchemaModel, Template } from "./schemaModel";
import { humanize } from "./VisualEditor";

export interface InsertGroup { key: string; label: string; names: string[]; labels?: Record<string, string> }

/** Where to open a popover: at the text caret if it is in the editor, else next to the element. */
function anchorRect(nid: number): DOMRect | null {
  const sel = window.getSelection();
  if (sel && sel.rangeCount) {
    const r = sel.getRangeAt(0);
    const host = (r.startContainer instanceof Element ? r.startContainer : r.startContainer.parentElement)?.closest(`.visual [data-nid="${nid}"]`);
    if (host) {
      const rect = r.getBoundingClientRect();
      if (rect.width || rect.height || rect.top) return rect;
    }
  }
  const el = document.querySelector(`.visual [data-nid="${nid}"]`) as HTMLElement | null;
  return el?.getBoundingClientRect() ?? null;
}

function usePopoverPos(nid: number, w = 340, h = 380) {
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 120, left: 400 });
  useEffect(() => {
    const r = anchorRect(nid);
    if (r) {
      const below = r.bottom + 6;
      const top = below + h > window.innerHeight ? Math.max(8, r.top - h - 6) : below;
      setPos({ top, left: Math.max(12, Math.min(r.left, window.innerWidth - w - 12)) });
    }
  }, [nid, w, h]);
  return pos;
}

/** The insert menu: only what the schema allows, fully keyboard driven. */
export function InsertMenu({ anchorNid, groups, onPick, onClose }: {
  anchorNid: number; groups: InsertGroup[]; onPick: (group: string, name: string) => void; onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const pos = usePopoverPos(anchorNid);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { box.current?.querySelector("input")?.focus(); }, []);
  const label = (g: InsertGroup, n: string) => g.labels?.[n] ?? humanize(n);
  const shown = groups.map((g) => ({ ...g, names: g.names.filter((n) => !q || n.toLowerCase().includes(q.toLowerCase())
    || label(g, n).toLowerCase().includes(q.toLowerCase())) }));
  const flat = shown.flatMap((g) => g.names.map((n) => ({ g: g.key, n })));
  useEffect(() => { setActive(0); }, [q]);
  useEffect(() => { box.current?.querySelector(".im-item.active")?.scrollIntoView({ block: "nearest" }); }, [active]);
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(flat.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(flat.length - 1); }
    else if (e.key === "Enter") { e.preventDefault(); const it = flat[active]; if (it) onPick(it.g, it.n); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };
  let i = -1;
  return (
    <>
      <div className="menu-veil" onClick={onClose} />
      <div ref={box} className="insert-menu" style={{ top: pos.top, left: pos.left }} role="dialog" aria-label="Insert element">
        <input placeholder="Type to filter…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={key}
          aria-activedescendant={flat[active] ? `im-${active}` : undefined} />
        <div className="im-body" role="listbox">
          {shown.map((g) => g.names.length > 0 && (
            <div key={g.key} className="im-group">
              <div className="im-label">{g.label}</div>
              {g.names.map((n) => { i += 1; const idx = i; return (
                <button key={n} id={`im-${idx}`} role="option" aria-selected={idx === active}
                  className={`im-item${idx === active ? " active" : ""}`} onMouseEnter={() => setActive(idx)} onClick={() => onPick(g.key, n)}>
                  <span>{label(g, n)}</span>{!g.labels && <code>{n}</code>}
                </button>); })}
            </div>
          ))}
          {flat.length === 0 && <p className="muted small pad">{q ? "No allowed element matches." : "The schema allows nothing to be inserted here."}</p>}
        </div>
        <div className="im-foot muted small">↑ ↓ choose · Enter insert · Esc back to typing · only what the schema allows</div>
      </div>
    </>
  );
}

export interface AttrRow { id: string; element: string; attr: AttrDef; value: string; present: boolean }

/** Attributes inline, next to the element: required ones first, allowed values and ID
 *  references as lists. Tab moves between fields, Enter applies, Esc cancels. */
export function AttrPopover({ anchorNid, title, rows, ids, okLabel, onCancel, onOk }: {
  anchorNid: number; title: string; rows: AttrRow[]; ids: [string, string][]; okLabel: string;
  onCancel: () => void; onOk: (values: Record<string, string>) => void;
}) {
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(rows.map((r) => [r.id, r.value])));
  const pos = usePopoverPos(anchorNid, 380, 60 + rows.length * 44);
  const first = useRef<HTMLElement | null>(null);
  const okBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (first.current) { first.current.focus(); (first.current as HTMLInputElement).select?.(); }
    else okBtn.current?.focus();                 // no fields: Enter/Esc must still reach the panel
  }, []);
  const missing = rows.filter((r) => r.attr.required && !vals[r.id]);
  const set = (id: string, v: string) => setVals((x) => ({ ...x, [id]: v }));
  const ordered = [...rows].sort((a, b) => Number(b.attr.required) - Number(a.attr.required));
  return (
    <>
      <div className="menu-veil" onClick={onCancel} />
      <form className="attr-popover" style={{ top: pos.top, left: pos.left }} role="dialog" aria-label={title}
        onSubmit={(e) => { e.preventDefault(); if (!missing.length) onOk(vals); }}
        onKeyDown={(e) => {
          if (e.key === "Escape") { e.preventDefault(); onCancel(); }
          // Enter applies from any field, including lists (browsers do not submit a form from a <select>)
          else if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!missing.length) onOk(vals); }
        }}>
        <div className="ap-head">{title}</div>
        {ordered.map((r, n) => (
          <label key={r.id} className="ap-row">
            <span className="ap-name">{r.attr.name}{r.attr.required && <span className="req">*</span>}</span>
            {r.attr.kind === "enum" ? (
              <select ref={n === 0 ? (el) => { first.current = el; } : undefined} value={vals[r.id]} onChange={(e) => set(r.id, e.target.value)}>
                {!r.attr.required && <option value="">—</option>}
                {r.attr.values.map((v) => <option key={v}>{v}</option>)}
              </select>
            ) : r.attr.kind === "idref" || r.attr.kind === "idrefs" ? (
              <select ref={n === 0 ? (el) => { first.current = el; } : undefined} value={vals[r.id]} onChange={(e) => set(r.id, e.target.value)}>
                <option value="">{r.attr.required ? "choose the target…" : "—"}</option>
                {ids.map(([id, lab]) => <option key={id} value={id}>{lab}</option>)}
              </select>
            ) : (
              <input ref={n === 0 ? (el) => { first.current = el; } : undefined} value={vals[r.id]} disabled={!!r.attr.fixed}
                onChange={(e) => set(r.id, e.target.value)} placeholder={r.attr.required ? "required" : "optional"} />
            )}
          </label>
        ))}
        {rows.length === 0 && <p className="muted small">This element has no attributes.</p>}
        <div className="ap-foot">
          <span className="muted small">Tab next field · Enter {okLabel.toLowerCase()} · Esc cancel</span>
          <button ref={okBtn} type="submit" className="primary" disabled={missing.length > 0}>{okLabel}</button>
        </div>
      </form>
    </>
  );
}

export interface TableSpec { rows: number; cols: number; head: boolean; title: boolean }

/** Rows x columns for a new table. */
export function TablePopover({ anchorNid, canHead, canTitle, onCancel, onOk }: {
  anchorNid: number; canHead: boolean; canTitle: boolean; onCancel: () => void; onOk: (s: TableSpec) => void;
}) {
  const [s, setS] = useState<TableSpec>({ rows: 3, cols: 3, head: canHead, title: canTitle });
  const pos = usePopoverPos(anchorNid, 300, 220);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => { first.current?.focus(); first.current?.select(); }, []);
  const num = (v: string) => Math.max(1, Math.min(50, parseInt(v, 10) || 1));
  return (
    <>
      <div className="menu-veil" onClick={onCancel} />
      <form className="attr-popover" style={{ top: pos.top, left: pos.left, width: 300 }} role="dialog" aria-label="New table"
        onSubmit={(e) => { e.preventDefault(); onOk(s); }}
        onKeyDown={(e) => {
          if (e.key === "Escape") { e.preventDefault(); onCancel(); }
          else if (e.key === "Enter") { e.preventDefault(); onOk(s); }
        }}>
        <div className="ap-head">New table</div>
        <label className="ap-row"><span className="ap-name">Columns</span>
          <input ref={first} type="number" min={1} max={50} value={s.cols} onChange={(e) => setS({ ...s, cols: num(e.target.value) })} /></label>
        <label className="ap-row"><span className="ap-name">Rows</span>
          <input type="number" min={1} max={200} value={s.rows} onChange={(e) => setS({ ...s, rows: num(e.target.value) })} /></label>
        {canHead && <label className="ap-check"><input type="checkbox" checked={s.head} onChange={(e) => setS({ ...s, head: e.target.checked })} /> Header row</label>}
        {canTitle && <label className="ap-check"><input type="checkbox" checked={s.title} onChange={(e) => setS({ ...s, title: e.target.checked })} /> Title</label>}
        <div className="ap-foot"><span className="muted small">Enter create · Esc cancel</span><button type="submit" className="primary">Create</button></div>
      </form>
    </>
  );
}

export const SHORTCUTS: [string, string][] = [
  ["Shift+Enter", "Insert: what the schema allows here (also Ctrl+Enter)"],
  ["Enter", "At the end of a paragraph: another one, where allowed"],
  ["Alt+Enter", "Edit the attributes of this element"],
  ["Tab / Shift+Tab", "Next / previous table cell (Tab in the last cell adds a row)"],
  ["Alt+↑ / Alt+↓", "Move this element up / down"],
  ["Alt+Backspace", "Delete this element (asks if the schema requires it)"],
  ["Esc", "Select the parent element (then Alt+↑↓ or Alt+Backspace act on it)"],
  ["Ctrl+Z / Ctrl+Y", "Undo / redo"],
  ["Ctrl+S", "Save draft"],
];

export function ShortcutHelp({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <>
      <div className="menu-veil" onClick={onClose} />
      <div className="shortcut-help" role="dialog" aria-label="Keyboard shortcuts">
        <div className="ap-head">Keyboard</div>
        <table><tbody>{SHORTCUTS.map(([k, v]) => <tr key={k}><th><kbd>{k}</kbd></th><td>{v}</td></tr>)}</tbody></table>
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
