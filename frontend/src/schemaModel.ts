/**
 * Content-model engine for schema-aware editing. Works on the model the backend builds from
 * the installed XSD, XML DTD or SGML DTD (backend/asthra/schema/model.py). Everything here is
 * deterministic: an element is offered only if the schema allows it at that position.
 */
export type Particle =
  | { k: "el"; n: string; min: number; max: number | null }
  | { k: "seq" | "choice" | "all"; items: Particle[]; min: number; max: number | null }
  | { k: "any"; min: number; max: number | null };
export interface AttrDef { name: string; required: boolean; kind: string; values: string[]; default: string | null; fixed: string | null }
export interface ElementDef {
  content: Particle | null; mixed: boolean; empty: boolean; any: boolean; text: boolean;
  attrs: AttrDef[]; inclusions: string[]; exclusions: string[];
}
export interface SchemaModel { root: string; kind: string; elements: Record<string, ElementDef> }

// ---- NFA ------------------------------------------------------------------
interface Nfa { start: number; end: number; eps: number[][]; edges: { from: number; name: string; to: number }[]; any: { from: number; to: number }[] }
const MAX_REPEAT = 12;

function build(p: Particle, nfa: Nfa): [number, number] {
  const node = () => { nfa.eps.push([]); return nfa.eps.length - 1; };
  const once = (): [number, number] => {
    const s = node(), e = node();
    if (p.k === "el") nfa.edges.push({ from: s, name: p.n, to: e });
    else if (p.k === "any") nfa.any.push({ from: s, to: e });
    else if (p.k === "seq") {
      let cur = s;
      for (const it of p.items) { const [a, b] = build(it, nfa); nfa.eps[cur].push(a); cur = b; }
      nfa.eps[cur].push(e);
    } else if (p.k === "choice") {
      if (!p.items.length) nfa.eps[s].push(e);
      for (const it of p.items) { const [a, b] = build(it, nfa); nfa.eps[s].push(a); nfa.eps[b].push(e); }
    } else {  // "all" (XSD all / SGML &): any order, each at most once — approximated as (a|b|...)*
      const hub = node();
      nfa.eps[s].push(hub); nfa.eps[hub].push(e);
      for (const it of p.items) { const [a, b] = build({ ...it, min: Math.min(it.min, 1) } as Particle, nfa); nfa.eps[hub].push(a); nfa.eps[b].push(hub); }
    }
    return [s, e];
  };
  const min = Math.min(p.min, MAX_REPEAT);
  const max = p.max === null || p.max > MAX_REPEAT ? null : p.max;
  const s = node(), e = node();
  let cur = s;
  for (let i = 0; i < min; i++) { const [a, b] = once(); nfa.eps[cur].push(a); cur = b; }
  if (max === null) {
    const [a, b] = once(); nfa.eps[cur].push(a); nfa.eps[b].push(a); nfa.eps[b].push(e); nfa.eps[cur].push(e);
  } else {
    for (let i = min; i < max; i++) { const [a, b] = once(); nfa.eps[cur].push(a); nfa.eps[cur].push(e); cur = b; }
    nfa.eps[cur].push(e);
  }
  return [s, e];
}

const cache = new WeakMap<Particle, Nfa>();
function nfaOf(p: Particle): Nfa {
  let n = cache.get(p);
  if (!n) {
    n = { start: 0, end: 0, eps: [], edges: [], any: [] };
    const [s, e] = build(p, n);
    n.start = s; n.end = e;
    cache.set(p, n);
  }
  return n;
}

/** Run the child sequence. skip=true lets required items be missing (can still be completed). */
function run(p: Particle, names: string[], skip: boolean, extra: Set<string>): boolean {
  const n = nfaOf(p);
  const closure = (set: Set<number>) => {
    const st = [...set];
    while (st.length) {
      const x = st.pop()!;
      const nexts = [...n.eps[x]];
      if (skip) for (const ed of n.edges) if (ed.from === x) nexts.push(ed.to);
      if (skip) for (const ed of n.any) if (ed.from === x) nexts.push(ed.to);
      for (const y of nexts) if (!set.has(y)) { set.add(y); st.push(y); }
    }
    return set;
  };
  let cur = closure(new Set([n.start]));
  for (const name of names) {
    if (extra.has(name)) continue;            // SGML inclusions: allowed anywhere, outside the model
    const next = new Set<number>();
    for (const ed of n.edges) if (cur.has(ed.from) && ed.name === name) next.add(ed.to);
    for (const ed of n.any) if (cur.has(ed.from)) next.add(ed.to);
    if (!next.size) return false;
    cur = closure(next);
  }
  return cur.has(n.end);
}

function namesIn(p: Particle | null, out = new Set<string>()): Set<string> {
  if (!p) return out;
  if (p.k === "el") out.add(p.n);
  else if (p.k !== "any") for (const it of p.items) namesIn(it, out);
  return out;
}

/** Inclusions and exclusions inherited from ancestors (SGML exceptions). */
function exceptions(model: SchemaModel, ancestors: string[]): { inc: Set<string>; exc: Set<string> } {
  const inc = new Set<string>(), exc = new Set<string>();
  for (const a of ancestors) {
    const d = model.elements[a];
    d?.inclusions.forEach((x) => inc.add(x));
    d?.exclusions.forEach((x) => exc.add(x));
  }
  exc.forEach((x) => inc.delete(x));
  return { inc, exc };
}

export function elementNames(model: SchemaModel): string[] { return Object.keys(model.elements); }

/** Is this child sequence exactly valid for the element? */
export function isValid(model: SchemaModel, parent: string, children: string[], ancestors: string[] = []): boolean {
  const d = model.elements[parent];
  if (!d) return true;
  if (d.any) return true;
  if (d.empty || d.text) return children.length === 0;
  if (!d.content) return children.length === 0;
  const { inc } = exceptions(model, [...ancestors, parent]);
  return run(d.content, children, false, inc);
}

/** Can this child sequence still be made valid by adding elements? */
export function isCompletable(model: SchemaModel, parent: string, children: string[], ancestors: string[] = []): boolean {
  const d = model.elements[parent];
  if (!d || d.any) return true;
  if (d.empty || d.text) return children.length === 0;
  if (!d.content) return children.length === 0;
  const { inc } = exceptions(model, [...ancestors, parent]);
  return run(d.content, children, true, inc);
}

/** Elements that may be inserted at gap `gap` (0 = before the first child). */
export function insertable(model: SchemaModel, parent: string, children: string[], gap: number, ancestors: string[] = []): string[] {
  const d = model.elements[parent];
  if (!d || d.empty || d.text) return [];
  const { inc, exc } = exceptions(model, [...ancestors, parent]);
  const cands = d.any ? new Set(elementNames(model)) : namesIn(d.content);
  inc.forEach((x) => cands.add(x));
  const out: string[] = [];
  for (const c of cands) {
    if (exc.has(c)) continue;
    const seq = [...children.slice(0, gap), c, ...children.slice(gap)];
    if (inc.has(c) || d.any || (d.content && run(d.content, seq.filter((n) => !inc.has(n) || n === c), true, new Set([...inc].filter((x) => x !== c))))) out.push(c);
  }
  return out.sort();
}

/** Inline elements allowed in the text of a mixed-content element. */
export function inlineAllowed(model: SchemaModel, parent: string, ancestors: string[] = []): string[] {
  const d = model.elements[parent];
  if (!d || !d.mixed) return [];
  const { inc, exc } = exceptions(model, [...ancestors, parent]);
  const s = namesIn(d.content);
  inc.forEach((x) => s.add(x));
  return [...s].filter((x) => !exc.has(x)).sort();
}

// ---- minimal content for a new element ------------------------------------------
export interface Template { xml: string; needs: { element: string; attr: AttrDef; id: string }[] }

function minimalChildren(model: SchemaModel, p: Particle | null): string[] {
  if (!p || p.min === 0) return [];
  const one = (q: Particle): string[] => {
    if (q.k === "el") return [q.n];
    if (q.k === "any") return [];
    if (q.k === "seq" || q.k === "all") return q.items.flatMap((it) => minimalChildren(model, it));
    // choice: the alternative that needs the least
    let best: string[] | null = null;
    for (const it of q.items) {
      const c = it.min === 0 ? [] : one(it);
      if (best === null || c.length < best.length) best = c;
    }
    return best ?? [];
  };
  const out: string[] = [];
  for (let i = 0; i < Math.max(1, Math.min(p.min, MAX_REPEAT)); i++) out.push(...one(p));
  return out;
}

const escAttr = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

/** XML for a new, minimally valid element: required children and attributes filled in.
 *  IDs are generated unique; enumerations take their default or first value; any other
 *  required attribute is returned in `needs` for the user to fill in. */
export function template(model: SchemaModel, name: string, usedIds: Set<string>, depth = 0): Template {
  const d = model.elements[name];
  const needs: Template["needs"] = [];
  const token = `a${Math.random().toString(36).slice(2, 8)}`;
  const attrs: string[] = [];
  for (const a of d?.attrs ?? []) {
    if (!a.required) continue;
    let v = a.fixed ?? a.default ?? "";
    if (!v && a.kind === "id") v = uniqueId(name, usedIds);
    if (!v && a.kind === "enum" && a.values.length) v = a.values[0];
    const id = `${token}-${a.name}`;
    if (!v || a.kind === "idref" || a.kind === "idrefs") needs.push({ element: name, attr: a, id });
    attrs.push(` ${a.name}="${v ? escAttr(v) : `@@${id}@@`}"`);
  }
  if (!d || d.empty) return { xml: `<${name}${attrs.join("")}/>`, needs };
  const kids = depth > 6 ? [] : minimalChildren(model, d.content);
  let inner = "";
  for (const k of kids) {
    const t = template(model, k, usedIds, depth + 1);
    inner += t.xml;
    needs.push(...t.needs);
  }
  return { xml: `<${name}${attrs.join("")}>${inner}</${name}>`, needs };
}

export function uniqueId(name: string, used: Set<string>): string {
  const base = name.replace(/[^A-Za-z0-9]/g, "").slice(0, 8).toLowerCase() || "id";
  for (let i = 1; i < 100000; i++) {
    const id = `${base}-${String(i).padStart(4, "0")}`;
    if (!used.has(id)) { used.add(id); return id; }
  }
  return `${base}-${Date.now()}`;
}

/** Fill the placeholders a template left for required attributes. */
export function fillTemplate(xml: string, values: Record<string, string>): string {
  return xml.replace(/@@([\w-]+)@@/g, (_, id) => escAttr(values[id] ?? ""));
}

/** Attribute names of kind "id" per element, to collect the IDs used in a document. */
export function idAttributes(model: SchemaModel): Map<string, string[]> {
  const m = new Map<string, string[]>();
  for (const [n, d] of Object.entries(model.elements)) {
    const ids = d.attrs.filter((a) => a.kind === "id").map((a) => a.name);
    if (ids.length) m.set(n, ids);
  }
  return m;
}
