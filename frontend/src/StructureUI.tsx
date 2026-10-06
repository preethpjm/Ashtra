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

export interface AttrRow { id: string; element: string; attr: AttrDef; value: string; present: boolean; kind?: "text" }

/** Attributes inline, next to the element: required ones first, optional ones below, allowed
 *  values and ID references as lists. Tab moves between fields, Enter applies, Esc cancels,
 *  Alt+Up / Alt+Down switch to the parent / child element in the breadcrumb. */
export interface LibraryEntry { id: number; label: string; name: string; pn: string; cage: string }

export function AttrPopover({ anchorNid, title, rows, ids, okLabel, crumbs, onCrumb, onCancel, onOk, optionalOpen, library }: {
  anchorNid: number; title: string; rows: AttrRow[]; ids: [string, string][]; okLabel: string; optionalOpen?: boolean;
  library?: LibraryEntry[];
  crumbs?: { nid: number; label: string }[]; onCrumb?: (nid: number) => void;
  onCancel: () => void; onOk: (values: Record<string, string>) => void;
}) {
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(rows.map((r) => [r.id, r.value])));
  const content = rows.filter((r) => r.kind === "text");
  const required = rows.filter((r) => r.kind !== "text" && r.attr.required);
  const optional = rows.filter((r) => r.kind !== "text" && !r.attr.required);
  const [showOpt, setShowOpt] = useState(!!optionalOpen || optional.some((r) => r.present));
  const pos = usePopoverPos(anchorNid, 400, 90 + Math.min(rows.length, 9) * 38);
  const first = useRef<HTMLElement | null>(null);
  const okBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => {                              // only when the panel opens (it is re-mounted per element)
    if (first.current) { first.current.focus(); (first.current as HTMLInputElement).select?.(); }
    else okBtn.current?.focus();                 // no fields: Enter/Esc must still reach the panel
  }, []);
  const missing = required.filter((r) => !vals[r.id]);
  const set = (id: string, v: string) => setVals((x) => ({ ...x, [id]: v }));
  const at = crumbs ? crumbs.findIndex((c) => c.nid === anchorNid) : -1;
  let firstAssigned = false;
  const pickLibrary = (id: string) => {
    const e = library?.find((x) => String(x.id) === id);
    setVals((v) => {
      const next: Record<string, string> = { ...v, __lib: id };
      const nameRow = content.find((r) => r.element === "name");
      if (e && nameRow) next[nameRow.id] = e.name;
      return next;
    });
  };
  const field = (r: AttrRow) => {
    const ref = !firstAssigned ? ((el: HTMLElement | null) => { first.current = el; }) : undefined;
    firstAssigned = true;
    if (r.kind === "text") return (
      <label key={r.id} className="ap-row ap-text">
        <span className="ap-name ap-content-name" title={r.element}>{humanize(r.element)}</span>
        <input ref={ref as any} value={vals[r.id] ?? ""} onChange={(e) => set(r.id, e.target.value)} placeholder="type the text" />
      </label>
    );
    return (
      <label key={r.id} className="ap-row">
        <span className="ap-name" title={r.attr.kind}>{r.attr.name}{r.attr.required && <span className="req">*</span>}</span>
        {r.attr.kind === "enum" ? (
          <select ref={ref as any} value={vals[r.id] ?? ""} onChange={(e) => set(r.id, e.target.value)}>
            {!r.attr.required && <option value="">—</option>}
            {r.attr.values.map((v) => <option key={v}>{v}</option>)}
          </select>
        ) : r.attr.kind === "idref" || r.attr.kind === "idrefs" ? (
          <select ref={ref as any} value={vals[r.id] ?? ""} onChange={(e) => set(r.id, e.target.value)}>
            <option value="">{r.attr.required ? "choose the target…" : "—"}</option>
            {!ids.some(([i]) => i === vals[r.id]) && vals[r.id] && <option value={vals[r.id]}>{vals[r.id]} (no such ID)</option>}
            {ids.map(([id, lab]) => <option key={id} value={id}>{lab}</option>)}
          </select>
        ) : (
          <input ref={ref as any} value={vals[r.id] ?? ""} disabled={!!r.attr.fixed}
            onChange={(e) => set(r.id, e.target.value)} placeholder={r.attr.required ? "required" : "empty = not set"} />
        )}
      </label>
    );
  };
  return (
    <>
      <div className="menu-veil" onClick={onCancel} />
      <form className="attr-popover" style={{ top: pos.top, left: pos.left, width: 400 }} role="dialog" aria-label={title}
        onSubmit={(e) => { e.preventDefault(); if (!missing.length) onOk(vals); }}
        onKeyDown={(e) => {
          if (e.key === "Escape") { e.preventDefault(); onCancel(); }
          else if (e.altKey && e.key === "ArrowUp" && crumbs && at > 0) { e.preventDefault(); onCrumb?.(crumbs[at - 1].nid); }
          else if (e.altKey && e.key === "ArrowDown" && crumbs && at >= 0 && at < crumbs.length - 1) { e.preventDefault(); onCrumb?.(crumbs[at + 1].nid); }
          // Enter applies from any field, including lists (browsers do not submit a form from a <select>)
          else if (e.key === "Enter" && !e.shiftKey && !(e.target as HTMLElement).classList.contains("ap-opt-toggle")) {
            e.preventDefault(); if (!missing.length) onOk(vals);
          }
        }}>
        {crumbs && crumbs.length > 1 && (
          <div className="ap-crumbs" aria-label="Element">
            {crumbs.map((c, i) => (
              <span key={c.nid}>{i > 0 && <span className="sep">›</span>}
                <button type="button" tabIndex={-1} className={c.nid === anchorNid ? "on" : ""} onClick={() => onCrumb?.(c.nid)}>{c.label}</button>
              </span>
            ))}
          </div>
        )}
        <div className="ap-head">{title}</div>
        {library && library.length > 0 && (() => {
          const ref = !firstAssigned ? ((el: HTMLElement | null) => { first.current = el; }) : undefined;
          firstAssigned = true;
          return (
            <label className="ap-row ap-lib">
              <span className="ap-name ap-content-name">From the library</span>
              <select ref={ref as any} value={vals.__lib ?? ""} onChange={(e) => pickLibrary(e.target.value)}>
                <option value="">— type it instead —</option>
                {library.map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
              </select>
            </label>
          );
        })()}
        {content.length > 0 && <div className="ap-section">Content</div>}
        {content.map(field)}
        {content.length > 0 && required.length > 0 && <div className="ap-section">Required attributes</div>}
        {required.map(field)}
        {optional.length > 0 && (
          <>
            <button type="button" className="ap-opt-toggle" aria-expanded={showOpt} onClick={() => setShowOpt((v) => !v)}>
              {showOpt ? "▾" : "▸"} {content.length ? "Attributes" : "Optional attributes"} ({optional.length})
            </button>
            {showOpt && <div className="ap-opt">{optional.map(field)}</div>}
          </>
        )}
        {rows.length === 0 && <p className="muted small">This element has no attributes.</p>}
        <div className="ap-foot">
          <span className="muted small">Tab next · Enter {okLabel.toLowerCase()} · Esc {okLabel === "Insert" ? "cancel" : "close"}{crumbs && crumbs.length > 1 ? " · Alt+↑↓ element" : ""}</span>
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
  ["Enter", "At the end of a paragraph: another one where allowed, otherwise the next step / list item (caret in it); on an empty sub-step: move it up a level"],
  ["Alt+Enter", "Attributes of the element at the cursor (a reference or value just before it, else the paragraph); Alt+↑↓ inside switches element"],
  ["Tab / Shift+Tab", "In a table: next / previous cell (Tab in the last cell adds a row). Elsewhere: indent this step / item under the previous one, or move it up a level"],
  ["Alt+↑ / Alt+↓", "Move this element up / down"],
  ["Alt+Backspace", "Delete this element (asks if the schema requires it)"],
  ["Backspace", "In an empty element: remove it (unless required) and continue at the end of the previous text; after a reference or value: remove it"],
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
