/**
 * ASTHRA Document Model (ADM), editor side.
 *
 * The authoritative content is the XML source text. On top of it we keep:
 *  - a DOM (DOMParser) for structure and attribute lookups, and
 *  - exact source spans for every element and every comment / PI / CDATA node,
 *    found by a tokenizer that runs only after DOMParser has confirmed the text is
 *    well-formed.
 *
 * Element "nid" = the element's position in document order. Visual edits are only
 * allowed to change text (never structure), so nids stay stable across edits and
 * a visual edit is applied as a splice of that one element's content. Every other
 * byte of the source is preserved exactly.
 */

export interface Span {
  start: number;       // offset of "<"
  tagEnd: number;      // offset just after the start tag's ">"
  contentEnd: number;  // offset of the end tag's "<" (== tagEnd for self-closing)
  end: number;         // offset just after the element's last ">"
  selfClosing: boolean;
  qname: string;
}

export interface MiscSpan { start: number; end: number }

export interface Adm {
  text: string;
  ok: boolean;
  error?: string;               // parse error (source is not well-formed)
  visualBlocked?: string;       // reason visual editing is unavailable
  doc?: Document;
  elements: Element[];          // document order; index = nid
  spans: Span[];                // same order as elements
  misc: Node[];                 // comments / PIs / CDATA inside the root, document order
  miscSpans: MiscSpan[];
  indexOf: Map<Node, number>;   // element -> nid, misc node -> misc index
}

// ------------------------------------------------------------------ tokenizer
function tokenize(text: string): { spans: Span[]; misc: MiscSpan[]; hasInternalSubset: boolean; subset: string } {
  const spans: Span[] = [];
  const misc: MiscSpan[] = [];
  const stack: number[] = [];
  let i = 0;
  let rootSeen = false;
  let hasInternalSubset = false;
  let subset = "";
  const n = text.length;
  const skipTo = (s: string, from: number) => {
    const k = text.indexOf(s, from);
    if (k < 0) throw new Error(`unterminated construct, expected ${s}`);
    return k + s.length;
  };
  while (i < n) {
    const lt = text.indexOf("<", i);
    if (lt < 0) break;
    i = lt;
    if (text.startsWith("<!--", i)) {
      const e = skipTo("-->", i + 4);
      if (stack.length) misc.push({ start: i, end: e });
      i = e;
    } else if (text.startsWith("<![CDATA[", i)) {
      const e = skipTo("]]>", i + 9);
      if (stack.length) misc.push({ start: i, end: e });
      i = e;
    } else if (text.startsWith("<?", i)) {
      const e = skipTo("?>", i + 2);
      if (stack.length) misc.push({ start: i, end: e });
      i = e;
    } else if (text.startsWith("<!", i)) {         // DOCTYPE, possibly with [internal subset]
      let j = i + 2, depth = 0, q = "", subStart = -1;
      for (; j < n; j++) {
        const c = text[j];
        if (q) { if (c === q) q = ""; continue; }
        if (c === '"' || c === "'") q = c;
        else if (c === "[") { depth++; hasInternalSubset = true; if (subStart < 0) subStart = j + 1; }
        else if (c === "]") { depth--; if (depth === 0 && subStart >= 0) subset += text.slice(subStart, j); }
        else if (c === ">" && depth <= 0) break;
      }
      i = j + 1;
    } else if (text.startsWith("</", i)) {
      const e = skipTo(">", i + 2);
      const idx = stack.pop();
      if (idx === undefined) throw new Error("unbalanced end tag");
      spans[idx].contentEnd = i;
      spans[idx].end = e;
      i = e;
    } else {
      let j = i + 1, q = "";
      for (; j < n; j++) {
        const c = text[j];
        if (q) { if (c === q) q = ""; continue; }
        if (c === '"' || c === "'") q = c;
        else if (c === ">") break;
      }
      if (j >= n) throw new Error("unterminated start tag");
      const selfClosing = text[j - 1] === "/";
      const m = /^<([^\s/>]+)/.exec(text.slice(i, i + 256));
      const span: Span = { start: i, tagEnd: j + 1, contentEnd: j + 1, end: j + 1, selfClosing, qname: m ? m[1] : "" };
      spans.push(span);
      if (!rootSeen) rootSeen = true;
      if (!selfClosing) stack.push(spans.length - 1);
      i = j + 1;
    }
  }
  if (stack.length) throw new Error("unclosed elements");
  return { spans, misc, hasInternalSubset, subset };
}

/** True if a DOCTYPE internal subset declares entities that would be substituted into
 *  the text (general or parameter entities). Unparsed NDATA entities, which S1000D uses
 *  to declare ICN graphics, are never substituted and are safe. */
export function expandsEntities(subset: string): boolean {
  const decls = subset.match(/<!ENTITY[\s\S]*?>/g) ?? [];
  return decls.some((d) => /^<!ENTITY\s+%/.test(d) || !/\bNDATA\b/.test(d));
}

// ------------------------------------------------------------------ parse
// ------------------------------------------------------------------ named entities
// DTD-based documents (ATA iSpec 2200, OEM) use named entities such as &mdash; declared in
// the DTD. The browser parser cannot read the DTD, so each reference is swapped for a marker
// before parsing and shown as a chip; the source keeps the original reference.
const PREDEFINED = new Set(["amp", "lt", "gt", "quot", "apos"]);
const ENT_RE = /&([A-Za-z_:][\w.:-]*);/g;
export const MARK_RE = /\uE000(\d+)\uE001/g;
let ENTITY_VALUES: Record<string, string> = {};
/** Replacement texts from the validator (e.g. mdash -> "—"), display only. */
export function setEntityValues(v: Record<string, string>) { ENTITY_VALUES = { ...v }; }
function entityNames(doc: Document | null | undefined): string[] { return ((doc as any)?.__asthraEntities as string[]) ?? []; }
/** Text for display: markers become the entity's character, or &name; if unknown. */
export function displayText(s: string, doc: Document | null | undefined): string {
  const names = entityNames(doc);
  return s.replace(MARK_RE, (_, i) => ENTITY_VALUES[names[+i]] ?? `&${names[+i]};`);
}
/** Text for editing: markers become &name; again. */
export function editText(s: string, doc: Document | null | undefined): string {
  const names = entityNames(doc);
  return s.replace(MARK_RE, (_, i) => `&${names[+i]};`);
}

/** Browsers cannot load external parameter entities (e.g. %ISOEntities; importing the S1000D
 *  ISO entity sets) and stop with an error. Their declarations are only needed by the
 *  validator, so references to them are removed from the copy given to the browser.
 *  The source itself is untouched (all offsets come from the original text). */
function stripParameterEntityRefs(text: string): string {
  const m = /<!DOCTYPE[^\[>]*\[/i.exec(text);
  if (!m) return text;
  const start = m.index + m[0].length;
  let depth = 1, q = "", i = start;
  for (; i < text.length && depth > 0; i++) {
    const c = text[i];
    if (q) { if (c === q) q = ""; continue; }
    if (c === '"' || c === "'") q = c;
    else if (c === "[") depth++;
    else if (c === "]") depth--;
  }
  const subset = text.slice(start, i - 1).replace(/%[A-Za-z_:][\w.:-]*;/g, "");
  return text.slice(0, start) + subset + text.slice(i - 1);
}

export function parseAdm(text: string): Adm {
  const empty: Adm = { text, ok: false, elements: [], spans: [], misc: [], miscSpans: [], indexOf: new Map() };
  const names: string[] = [];
  let parseText = text;
  if (/<!DOCTYPE/i.test(text)) {
    parseText = text.replace(ENT_RE, (m, name) => {
      if (PREDEFINED.has(name)) return m;
      let i = names.indexOf(name);
      if (i < 0) { names.push(name); i = names.length - 1; }
      return `\uE000${i}\uE001`;
    });
  }
  parseText = stripParameterEntityRefs(parseText);
  const doc = new DOMParser().parseFromString(parseText, "application/xml");
  (doc as any).__asthraEntities = names;
  // Browsers report XML errors by returning a document containing <parsererror>.
  const err = doc.getElementsByTagName("parsererror")[0];
  if (err || !doc.documentElement) {
    return { ...empty, error: ((err && err.textContent) || "XML is not well-formed").trim().split("\n")[0] };
  }
  const elements = Array.from(doc.getElementsByTagName("*"));
  const misc: Node[] = [];
  const walker = doc.createTreeWalker(doc.documentElement, NodeFilter.SHOW_COMMENT | NodeFilter.SHOW_PROCESSING_INSTRUCTION | 0x8 /* CDATA */);
  for (let nd = walker.nextNode(); nd; nd = walker.nextNode()) {
    if (nd.nodeType === Node.COMMENT_NODE || nd.nodeType === Node.PROCESSING_INSTRUCTION_NODE || nd.nodeType === Node.CDATA_SECTION_NODE) misc.push(nd);
  }
  const indexOf = new Map<Node, number>();
  elements.forEach((e, k) => indexOf.set(e, k));
  misc.forEach((m, k) => indexOf.set(m, k));
  let tok;
  try {
    tok = tokenize(text);
  } catch (e) {
    return { ...empty, ok: true, doc, elements, misc, indexOf, visualBlocked: `source scan failed: ${(e as Error).message}` };
  }
  const adm: Adm = { text, ok: true, doc, elements, spans: tok.spans, misc, miscSpans: tok.misc, indexOf };
  // Entity references are shown as chips and written back verbatim, so documents whose
  // DOCTYPE declares or imports entities (ISO sets, ICNs, text entities) stay editable.
  if (tok.spans.length !== elements.length || tok.misc.length !== misc.length) adm.visualBlocked = "Source layout could not be mapped exactly; use Source mode.";
  return adm;
}

// ------------------------------------------------------------------ paths & lines
export function localName(el: Element): string { return el.localName || el.nodeName; }

export function readablePath(el: Element): string {
  const parts: string[] = [];
  let cur: Element | null = el;
  while (cur) {
    const parent: Element | null = cur.parentElement;
    const name = localName(cur);
    if (!parent) parts.push(name);
    else {
      const same = Array.from(parent.children).filter((c) => c.namespaceURI === cur!.namespaceURI && localName(c) === name);
      parts.push(same.length > 1 ? `${name}[${same.indexOf(cur) + 1}]` : name);
    }
    cur = parent;
  }
  return "/" + parts.reverse().join("/");
}

export function resolvePath(adm: Adm, path: string | null | undefined): number | undefined {
  if (!adm.ok || !adm.doc || !path || !path.startsWith("/")) return undefined;
  const segs = path.slice(1).split("/");
  let el: Element | null = adm.doc.documentElement;
  const parse = (s: string) => { const m = /^([^[]+)(?:\[(\d+)\])?$/.exec(s); return m ? { name: m[1].replace(/^\{[^}]*\}/, "").split(":").pop()!, idx: m[2] ? +m[2] : 1 } : null; };
  const first = parse(segs[0]);
  if (!first || !el || localName(el) !== first.name) return undefined;
  for (const s of segs.slice(1)) {
    const p = parse(s);
    if (!p || !el) return undefined;
    const kids: Element[] = Array.from(el.children).filter((c: Element) => localName(c) === p.name);
    el = kids[p.idx - 1] ?? null;
  }
  return el ? adm.indexOf.get(el) : undefined;
}

export function lineAt(text: string, offset: number): number {
  let line = 1;
  for (let i = 0; i < offset && i < text.length; i++) if (text.charCodeAt(i) === 10) line++;
  return line;
}

export function offsetAtLine(text: string, line: number): number {
  let l = 1, i = 0;
  while (l < line && i < text.length) { if (text.charCodeAt(i) === 10) l++; i++; }
  return i;
}

/** Innermost element whose span contains the offset. */
export function elementAtOffset(adm: Adm, offset: number): number | undefined {
  let best: number | undefined;
  adm.spans.forEach((s, k) => { if (s.start <= offset && offset < s.end) best = k; });
  return best;
}

// ------------------------------------------------------------------ classification
export type Kind = "block" | "text" | "atom";

function hasRealText(el: Element): boolean {
  for (const c of Array.from(el.childNodes)) if (c.nodeType === Node.TEXT_NODE && c.textContent!.trim() !== "") return true;
  return false;
}

/** How an element is shown in the visual editor. Without the M3 schema model this
 *  is a structural heuristic; it never changes what is saved. */
/** Attributes that only say how something is laid out (CALS / OASIS exchange tables, which S1000D and ATA both
 *  use, plus common print hints). They style the rendering; they are never shown as content. SGML parsers also
 *  write their declared defaults (morerows="0", rotate="0") into every element, so they cannot be told apart
 *  from authored values by presence alone. */
export const LAYOUT_ATTRS = new Set([
  "align", "valign", "char", "charoff", "colname", "namest", "nameend", "spanname", "morerows", "rotate",
  "rowsep", "colsep", "colnum", "colwidth", "cols", "frame", "pgwide", "orient", "tabstyle", "tgroupstyle",
  "shortentry", "tocentry", "rowheight", "outputclass", "role", "xml:space", "space", "shownow",
]);
const REF_ATTR = /^(ref|refid|idref|xrefid|internalrefid|target)$/i;
const meaningfulAttrs = (el: Element) => Array.from(el.attributes).filter((a) =>
  !LAYOUT_ATTRS.has(a.name.toLowerCase()) && !LAYOUT_ATTRS.has(a.localName.toLowerCase())
  && !a.name.startsWith("xmlns") && !a.name.startsWith("xsi:"));

export function kindOf(el: Element): Kind {
  if (hasRealText(el)) return "text";
  const elKids = el.children.length;
  const other = Array.from(el.childNodes).some((c) => c.nodeType === Node.CDATA_SECTION_NODE);
  if (other) return "text";
  if (elKids > 0) return "block";
  // <para/> and an empty table cell (<entry valign="bottom"/>) are editable text; <graphic .../> is an atom
  if (el.attributes.length === 0) return "text";
  if (/^(colspec|spanspec)$/i.test(localName(el))) return "atom";            // column definitions: never content
  return meaningfulAttrs(el).length === 0 ? "text" : "atom";
}

export function isMarkable(el: Element): boolean {
  // inline element holding only text -> shown as a mark
  return el.childNodes.length > 0 && Array.from(el.childNodes).every((c) => c.nodeType === Node.TEXT_NODE)
    && !/\uE000/.test(el.textContent ?? "");
}

const DMC_ATTRS = ["modelIdentCode", "systemDiffCode", "systemCode", "subSystemCode", "subSubSystemCode", "assyCode",
  "disassyCode", "disassyCodeVariant", "infoCode", "infoCodeVariant", "itemLocationCode"];
/** Readable one-line summaries for common identification/status elements. Display only. */
export function knownSummary(el: Element): string | null {
  const g = (a: string) => el.getAttribute(a) ?? "";
  switch (localName(el)) {
    case "dmCode": {
      if (!DMC_ATTRS.every((a) => el.hasAttribute(a))) return null;
      const v = DMC_ATTRS.map(g);
      return `DMC-${v[0]}-${v[1]}-${v[2]}-${v[3]}${v[4]}-${v[5]}-${v[6]}${v[7]}-${v[8]}${v[9]}-${v[10]}`;
    }
    case "graphic": {                 // S1000D illustration: its ICN
      const icn = g("infoEntityIdent") || g("boardno");
      return icn ? (el.children.length ? null : icn) : null;
    }
    case "toolRef": case "supplyRef": case "partRef": case "spareRef": case "supplyRqmtRef": {
      const num = g("toolNumber") || g("supplyNumber") || g("partNumberValue") || g("supplyRqmtNumber");
      const mfr = g("manufacturerCodeValue");
      return num ? `${num}${mfr ? `  (CAGE ${mfr})` : ""}` : null;
    }
    case "sheet": {                   // ATA illustration sheet: number and graphic file
      const n = g("sheetnbr"), f = g("gnbr");
      return n || f ? [n && `Sheet ${n}`, f].filter(Boolean).join("  \u00b7  ") : null;
    }
    case "issueInfo": return `Issue ${g("issueNumber")}${el.hasAttribute("inWork") ? "-" + g("inWork") : ""}`;
    case "language": return [g("languageIsoCode"), g("countryIsoCode")].filter(Boolean).join("-");
    case "issueDate": return [g("year"), g("month"), g("day")].filter(Boolean).join("-");
    case "security": return `Security classification ${g("securityClassification")}`;
    case "assert": return el.hasAttribute("applicPropertyIdent") ? `${g("applicPropertyIdent")} = ${g("applicPropertyValues")}` : null;
    case "responsiblePartnerCompany": case "originator": return el.hasAttribute("enterpriseCode") ? `${localName(el)} ${g("enterpriseCode")}` : null;
    default: return null;
  }
}

export function attrSummary(el: Element, max = 4): string {
  const known = knownSummary(el);
  if (known) return known;
  // a reference (ATA <grphcref refid>, <refint>): what it points at, not its attributes
  const ref = Array.from(el.attributes).find((a) => REF_ATTR.test(a.localName));
  if (ref) return `→ ${refLabel(el.ownerDocument, ref.value) ?? ref.value}`;
  return meaningfulAttrs(el)
    .slice(0, max).map((a) => `${a.localName}=${displayText(a.value, el.ownerDocument)}`).join("  ");
}

// ------------------------------------------------------------------ references & title block
const ID_ATTRS = ["id", "key", "ID"];
/** id -> readable label: figures and tables are numbered in document order ("Figure 2"),
 *  other targets use their title ("Remove the impeller"). Display only. */
export function refLabel(doc: Document | null | undefined, id: string | null | undefined): string | null {
  if (!doc || !id) return null;
  let map = (doc as any).__asthraRefs as Map<string, string> | undefined;
  if (!map) {
    map = new Map();
    let fig = 0, tab = 0;
    for (const el of Array.from(doc.getElementsByTagName("*"))) {
      const n = localName(el);
      const isFig = n === "figure" || (n === "graphic" && localName(el.parentElement ?? el) !== "figure" && el.parentElement?.localName !== "sheet");
      let label: string | null = null;
      if (isFig) label = `Figure ${++fig}`;            // S1000D <figure>; ATA <graphic> (sheets inside it)
      else if (n === "table") label = `Table ${++tab}`;
      const idv = ID_ATTRS.map((a) => el.getAttribute(a)).find(Boolean);
      if (!idv) continue;
      if (!label) {
        const t = Array.from(el.children).find((c) => localName(c) === "title");
        const txt = t ? displayText(t.textContent ?? "", doc).replace(/\s+/g, " ").trim() : "";
        label = txt ? (txt.length > 60 ? txt.slice(0, 59) + "…" : txt) : idv;
      }
      map.set(idv, label);
      if (!map.has(idv.toLowerCase())) map.set(idv.toLowerCase(), label);   // SGML IDs are case-insensitive
    }
    (doc as any).__asthraRefs = map;
  }
  return map.get(id) ?? map.get(id.toLowerCase()) ?? null;
}

export interface HeaderInfo {
  kind: "s1000d" | "ata" | "generic";
  code?: string; title?: string; subtitle?: string; issue?: string; date?: string;
  applic?: string; security?: string;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function niceDate(y?: string | null, m?: string | null, d?: string | null): string | undefined {
  if (!y) return undefined;
  const mi = m ? parseInt(m, 10) : NaN;
  return [d ? String(parseInt(d, 10)) : "", !isNaN(mi) && mi >= 1 && mi <= 12 ? MONTHS[mi - 1] : (m ?? ""), y].filter(Boolean).join(" ");
}

/** Data for the title block of the document view, read from the document itself. */
export function headerInfo(adm: Adm | null): HeaderInfo | null {
  if (!adm?.ok || !adm.doc) return null;
  const doc = adm.doc, root = doc.documentElement;
  const first = (n: string, within: Element = root) => within.getElementsByTagName(n)[0] as Element | undefined;
  const txt = (e?: Element) => (e ? displayText(e.textContent ?? "", doc).replace(/\s+/g, " ").trim() : "") || undefined;
  if (localName(root) === "dmodule") {
    const ident = first("identAndStatusSection");
    if (!ident) return null;
    const code = first("dmCode", ident);
    const issue = first("issueInfo", ident);
    const date = first("issueDate", ident);
    const status = first("dmStatus", ident) ?? ident;
    const applic = first("applic", status);
    const sec = first("security", status);
    return {
      kind: "s1000d", code: code ? knownSummary(code) ?? undefined : undefined,
      title: txt(first("techName", ident)), subtitle: txt(first("infoName", ident)),
      issue: issue ? `Issue ${issue.getAttribute("issueNumber") ?? "?"}${issue.hasAttribute("inWork") ? "-" + issue.getAttribute("inWork") : ""}` : undefined,
      date: date ? niceDate(date.getAttribute("year"), date.getAttribute("month"), date.getAttribute("day")) : undefined,
      applic: applic ? (txt(first("displayText", applic)) ?? Array.from(applic.getElementsByTagName("assert")).map((a) => knownSummary(a)).filter(Boolean).join(", ")) : undefined,
      security: sec?.getAttribute("securityClassification") ?? undefined,
    };
  }
  if (root.hasAttribute("chapnbr")) {           // ATA iSpec 2200 style
    const rd = root.getAttribute("revdate") ?? "";
    const titleEl = Array.from(root.children).find((c) => localName(c) === "title");
    return {
      kind: "ata", code: ["chapnbr", "sectnbr", "subjnbr"].map((a) => root.getAttribute(a)).filter(Boolean).join("-"),
      title: txt(titleEl), subtitle: root.getAttribute("model") ? `Model ${root.getAttribute("model")}` : undefined,
      date: /^\d{8}$/.test(rd) ? niceDate(rd.slice(0, 4), rd.slice(4, 6), rd.slice(6, 8)) : (rd || undefined),
      applic: txt(Array.from(root.children).find((c) => localName(c) === "effect")),
    };
  }
  const t = first("title");
  return t ? { kind: "generic", title: txt(t) } : null;
}

/** Readable text for an inline element shown as a locked chip, e.g. a quantity
 *  becomes "0.059 in / 1.5 mm". Display only; the source is never changed by this. */
export function inlineLabel(el: Element): string {
  const txt = (e: Element | null | undefined) => displayText(e?.textContent ?? "", el.ownerDocument).replace(/\s+/g, " ").trim();
  const kids = (e: Element, n: string) => Array.from(e.children).filter((c) => localName(c) === n);
  switch (localName(el)) {
    case "quantity": {
      const groups = kids(el, "quantityGroup").map((g) => {
        const parts: string[] = [];
        for (const c of Array.from(g.children)) {
          const n = localName(c);
          const unit = c.getAttribute("quantityUnitOfMeasure");
          if (n === "quantityValue") parts.push(`${txt(c)}${unit ? " " + unit : ""}`);
          else if (n === "quantityTolerance") {
            const t = c.getAttribute("quantityToleranceType");
            parts.push(`${t === "plus" ? "+" : t === "minus" ? "−" : "±"}${txt(c)}${unit ? " " + unit : ""}`);
          }
        }
        return parts.join(" ");
      }).filter(Boolean);
      return groups.length ? groups.join(" / ") : txt(el);
    }
    case "acronym": return txt(kids(el, "acronymTerm")[0]) || txt(el);
    case "internalRef": {
      const id = el.getAttribute("internalRefId");
      return refLabel(el.ownerDocument, id) ?? (id ?? "reference");
    }
    case "dmRef": {
      const c = el.getElementsByTagName("dmCode")[0];
      return c ? (knownSummary(c) ?? "DMC") : "data module reference";
    }
    default: {
      // generic: a value with a unit attribute reads "45 lbf.in"; an empty reference reads "→ target"
      const t = txt(el);
      const unit = el.getAttribute("unit") ?? el.getAttribute("uom") ?? el.getAttribute("quantityUnitOfMeasure");
      if (t) {
        const v = unit ? `${t} ${unit}` : t;
        return v.length > 60 ? v.slice(0, 59) + "…" : v;
      }
      const ref = Array.from(el.attributes).find((a) => REF_ATTR.test(a.localName));
      return ref ? (refLabel(el.ownerDocument, ref.value) ?? ref.value) : localName(el);
    }
  }
}

/** Leaf elements (no child elements) inside element k: the editable "contents" of a chip. */
export function leafDescendants(adm: Adm, k: number, max = 60): number[] {
  const out: number[] = [];
  const walk = (e: Element) => {
    for (const c of Array.from(e.children)) {
      if (out.length >= max) return;
      if (c.children.length === 0) out.push(adm.indexOf.get(c)!);
      else walk(c);
    }
  };
  walk(adm.elements[k]);
  return out;
}

// ------------------------------------------------------------------ CALS table layout
export interface CellPlace { row: number; col: number; rowSpan: number; colSpan: number; head: boolean; headEnd: boolean }
export interface CalsLayout { cols: number; template: string; cells: Map<Element, CellPlace> }

/** Width of a CALS colwidth as a relative weight ("2*" -> 2, "30mm" -> 30 (mm), "" -> 1*). */
function colWeight(w: string): { star: number; mm: number } {
  const v = (w || "").trim().toLowerCase();
  if (!v) return { star: 1, mm: 0 };
  let star = 0, mm = 0;
  for (const m of v.matchAll(/([0-9.]*)\s*\*|([0-9.]+)\s*(mm|cm|in|pt|pi|px)?/g)) {
    if (m[0].includes("*")) star += m[1] ? parseFloat(m[1]) || 1 : 1;
    else if (m[2]) {
      const n = parseFloat(m[2]) || 0, u = m[3] || "pt";
      mm += n * ({ mm: 1, cm: 10, in: 25.4, pt: 25.4 / 72, pi: 25.4 / 6, px: 25.4 / 96 } as Record<string, number>)[u];
    }
  }
  return star || mm ? { star, mm } : { star: 1, mm: 0 };
}

/** Where every entry of a CALS tgroup sits: column spans (namest/nameend, spanname), row spans
 *  (morerows), cells pushed right past cells spanning down from rows above, and column widths
 *  from colspec. Rows of thead, tbody and tfoot are numbered on one grid. */
export function calsLayout(tgroup: Element): CalsLayout {
  const kids = (e: Element, n?: string) => Array.from(e.children).filter((c) => !n || localName(c) === n);
  const specsOf = (e: Element) => {
    const names = new Map<string, number>();
    const widths: string[] = [];
    let num = 0;
    for (const c of kids(e, "colspec")) {
      num = parseInt(c.getAttribute("colnum") ?? "", 10) || num + 1;
      const n = c.getAttribute("colname");
      if (n) names.set(n, num);
      widths[num - 1] = c.getAttribute("colwidth") ?? "";
    }
    const spans = new Map<string, [string, string]>();
    for (const c of kids(e, "spanspec")) spans.set(c.getAttribute("spanname") ?? "", [c.getAttribute("namest") ?? "", c.getAttribute("nameend") ?? ""]);
    return { names, widths, spans, count: num };
  };
  const top = specsOf(tgroup);
  const sections = kids(tgroup).filter((c) => /^(thead|tbody|tfoot)$/.test(localName(c)));
  let cols = parseInt(tgroup.getAttribute("cols") ?? "", 10) || 0;
  const taken: boolean[][] = [];
  const cells = new Map<Element, CellPlace>();
  let r = 0;
  for (const sec of sections) {
    const own = specsOf(sec);
    const specs = own.names.size ? { ...top, names: own.names } : top;
    const colOf = (n: string | null) => (n ? specs.names.get(n) ?? 0 : 0);
    const head = localName(sec) === "thead";
    const rows = kids(sec, "row");
    rows.forEach((row, ri) => {
      taken[r] ??= [];
      let next = 1;
      for (const e of kids(row).filter((c) => /^(entry|entrytbl)$/.test(localName(c)))) {
        let st = 0, en = 0;
        const sp = e.getAttribute("spanname");
        if (sp && specs.spans.has(sp)) { const [a, b] = specs.spans.get(sp)!; st = colOf(a); en = colOf(b); }
        if (!st) { st = colOf(e.getAttribute("namest")); en = colOf(e.getAttribute("nameend")); }
        if (!st) { st = colOf(e.getAttribute("colname")); en = st; }
        if (!st) { st = next; while (taken[r][st]) st++; en = st; }
        if (en < st) en = st;
        const down = Math.max(0, parseInt(e.getAttribute("morerows") ?? "", 10) || 0);
        for (let y = r; y <= r + down; y++) { taken[y] ??= []; for (let x = st; x <= en; x++) taken[y][x] = true; }
        cells.set(e, { row: r + 1, col: st, rowSpan: down + 1, colSpan: en - st + 1, head, headEnd: head && ri === rows.length - 1 });
        next = en + 1;
        cols = Math.max(cols, en);
      }
      r++;
    });
  }
  cols = Math.max(cols, top.count, 1);
  const ws = Array.from({ length: cols }, (_, i) => colWeight(top.widths[i] ?? ""));
  const allAbs = ws.every((w) => !w.star && w.mm);
  const template = ws.map((w) => {
    const fr = allAbs ? w.mm : w.star || 1;
    return `minmax(min-content, ${+fr.toFixed(3)}fr)`;
  }).join(" ");
  return { cols, template, cells };
}

// ------------------------------------------------------------------ publication numbering
/** How a standard numbers its headings and steps (from the display profile). */
export interface Numbering {
  scheme: "ata" | "decimal";       // ATA iSpec 2200: 1. A. (1) (a) 1 a ; S1000D: 1 1.1 1.1.1
  elements: string[];              // numbered element names
  resets?: string[];               // numbering restarts inside each of these
  ident?: Record<string, string>;  // ATA: element -> identifier line prefix (TASK, SUBTASK)
}
export interface ViewProfile { numbering?: Numbering | null; columns?: Record<string, string[]> }

const alpha = (n: number): string => { let s = ""; for (; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s; return s; };
const roman = (n: number): string => {
  const t: [number, string][] = [[10, "x"], [9, "ix"], [5, "v"], [4, "iv"], [1, "i"]];
  let s = ""; for (const [v, r] of t) while (n >= v) { s += r; n -= v; } return s;
};
/** ATA iSpec 2200 procedure numbering by level: 1.  A.  (1)  (a)  1  a  (i) */
export function ataNumber(depth: number, n: number): string {
  switch (depth) {
    case 0: return `${n}.`;
    case 1: return `${alpha(n)}.`;
    case 2: return `(${n})`;
    case 3: return `(${alpha(n).toLowerCase()})`;
    case 4: return `${n}`;
    case 5: return alpha(n).toLowerCase();
    default: return `(${roman(n)})`;
  }
}
/** ATA task / subtask identifier, e.g. TASK 25-26-62-99F-801-A01 (from the element's attributes). */
export function ataIdent(el: Element, prefix: string): string {
  const g = (a: string) => (el.getAttribute(a) ?? "").trim();
  const [ch, se, su, seq, vn] = [g("chapnbr"), g("sectnbr"), g("subjnbr"), g("seq"), g("varnbr")];
  if (!ch || !se || !su || !seq) return "";
  const p2 = (v: string) => (/^\d$/.test(v) ? "0" + v : v);
  const p3 = (v: string) => (/^\d+$/.test(v) ? v.padStart(3, "0") : v);
  const tail = g("confltr").toUpperCase() + (vn ? p2(vn) : "");
  return `${prefix} ${[p2(ch), p2(se), p2(su), g("func").toUpperCase(), p3(seq)].filter(Boolean).join("-")}${tail ? "-" + tail : ""}`;
}

// elements whose text keeps its line breaks and spaces
const PRE_NAMES = new Set(["verbatimText", "programListing", "pre", "screen", "literallayout", "codeblock"]);
const keepsSpace = (el: Element): boolean => {
  for (let e: Element | null = el; e; e = e.parentElement) {
    const sp = e.getAttribute("xml:space");
    if (sp === "preserve") return true;
    if (sp === "default") return false;
    if (PRE_NAMES.has(localName(e))) return true;
  }
  return false;
};

// ------------------------------------------------------------------ ADM -> ProseMirror JSON
type Json = Record<string, any>;

export function toProseMirror(adm: Adm, view: ViewProfile = {}): Json {
  const nid = (n: Node) => adm.indexOf.get(n)!;
  const depthOf = (el: Element) => { let d = 0; for (let p = el.parentElement; p; p = p.parentElement) d++; return d; };
  const raw = (n: Node): string => {
    const k = adm.indexOf.get(n)!;
    if (n.nodeType === Node.ELEMENT_NODE) { const s = adm.spans[k]; return adm.text.slice(s.start, s.end); }
    const s = adm.miscSpans[k]; return adm.text.slice(s.start, s.end);
  };
  const names = entityNames(adm.doc);
  const layouts = new Map<Element, CalsLayout>();
  const gridOf = (el: Element): string => {
    const n = localName(el);
    if (n === "tgroup") { const l = calsLayout(el); layouts.set(el, l); return `T|${l.template}`; }
    if (n !== "entry" && n !== "entrytbl") return "";
    const tg = el.closest("tgroup");
    if (!tg) return "";
    const l = layouts.get(tg) ?? calsLayout(tg);
    layouts.set(tg, l);
    const p = l.cells.get(el);
    return p ? `C|${p.row} / span ${p.rowSpan}|${p.col} / span ${p.colSpan}|${p.head ? (p.headEnd ? "hend" : "h") : ""}` : "";
  };

  // ---- numbering (display only): counted in document order, restarting per numbered parent / reset element
  const nb = view.numbering && view.numbering.elements?.length ? view.numbering : null;
  const numbered = new Set(nb?.elements ?? []);
  const resets = new Set(nb?.resets ?? []);
  const counters = new Map<Element | null, Map<string, number>>();
  const numOf = new Map<Element, { label: string; depth: number }>();
  const numberedParent = (el: Element): Element | null => {
    for (let p = el.parentElement; p; p = p.parentElement) if (numbered.has(localName(p))) return p;
    return null;
  };
  const numberAttrs = (el: Element, x: Record<string, string>) => {
    if (!nb || !numbered.has(localName(el))) return;
    let scope: Element | null = null;
    for (let p = el.parentElement; p; p = p.parentElement) {
      const pn = localName(p);
      if (numbered.has(pn) || resets.has(pn)) { scope = p; break; }
    }
    const m = counters.get(scope) ?? new Map<string, number>();
    counters.set(scope, m);
    const name = localName(el);
    const n = (m.get(name) ?? 0) + 1;
    m.set(name, n);
    const parent = numberedParent(el);
    const pd = parent ? numOf.get(parent) : undefined;
    const depth = pd ? pd.depth + 1 : 0;
    const label = nb.scheme === "ata" ? ataNumber(depth, n) : (pd ? `${pd.label}.${n}` : String(n));
    numOf.set(el, { label, depth });
    x.num = label; x.ns = nb.scheme; x.nd = String(depth);
    const pre = nb.ident?.[name];
    if (pre) { const id = ataIdent(el, pre); if (id) x.ident = id; }
    // a step that opens with a warning, caution or note: the number goes on its first paragraph
    let body: Element = el;
    for (let guard = 0; guard < 4; guard++) {
      const kids = Array.from(body.children).filter((c) => !/^(revst|revend|effect)$/.test(localName(c)));
      const first = kids[0];
      if (!first) break;
      if (/^(warning|caution|note)$/.test(localName(first))) {
        const para = kids.find((c) => !/^(warning|caution|note)$/.test(localName(c)));
        if (para && kindOf(para) === "text") { leadOf.set(para, label); x.nl = "1"; }
        break;
      }
      if (first.children.length === 0 || kindOf(first) === "text" || numbered.has(localName(first))) break;
      body = first;                       // look through wrappers such as ATA <prcitem>
    }
  };
  const leadOf = new Map<Element, string>();
  // how far text is indented by numbering (places revision bars in the page margin)
  const indentOf = (el: Element): string => {
    if (!nb) return "0";
    let d = 0;
    for (let p: Element | null = el; p; p = p.parentElement) if (numbered.has(localName(p))) d++;
    return d === 0 ? "0" : nb.scheme === "ata" ? "a" + Math.min(d, 7) : "d1";
  };

  // ---- change marks: revst ... revend (ATA), changeMark="1" (S1000D)
  let inRev = false;
  const isRevStart = (e: Element) => localName(e) === "revst";
  const isRevEnd = (e: Element) => localName(e) === "revend";

  const pushText = (content: Json[], t: string) => {
    let last = 0;
    for (const m of t.matchAll(MARK_RE)) {
      if (m.index! > last) content.push({ type: "text", text: t.slice(last, m.index) });
      const name = names[+m[1]];
      content.push({ type: "xinline", attrs: { nid: -1, name: "entity", summary: ENTITY_VALUES[name] ?? `&${name};`, raw: `&${name};`, misc: false } });
      last = m.index! + m[0].length;
    }
    if (last < t.length) content.push({ type: "text", text: t.slice(last) });
  };
  // printed text: source line breaks and indentation read as one space (display only; unedited
  // elements are never rewritten, so the saved file keeps its layout)
  const tidy = (content: Json[]): Json[] => {
    for (const c of content) if (c.type === "text") c.text = c.text.replace(/[ \t\r\n]+/g, " ");
    const visible = (c: Json) => !(c.type === "xinline" && c.attrs.misc);
    const first = content.findIndex(visible), lastI = content.length - 1 - [...content].reverse().findIndex(visible);
    if (first >= 0 && content[first].type === "text") content[first].text = content[first].text.replace(/^ /, "");
    if (lastI >= 0 && lastI < content.length && content[lastI].type === "text") content[lastI].text = content[lastI].text.replace(/ $/, "");
    for (let i = 1; i < content.length; i++) {
      const a = content[i - 1], b = content[i];
      if (a.type === "text" && b.type === "text" && / $/.test(a.text) && /^ /.test(b.text)) b.text = b.text.slice(1);
    }
    return content.filter((c) => c.type !== "text" || c.text.length > 0);
  };
  const block = (el: Element): Json => {
    const kind = kindOf(el);
    const x: Record<string, string> = {};
    const name = localName(el);
    numberAttrs(el, x);
    if (name === "catalogSeqNumber" && el.hasAttribute("item")) {    // S1000D IPD line: item 050 + variant A reads "50A"
      const nil = el.getElementsByTagName("notIllustrated").length > 0;
      x.item = (nil ? "-" : "") + (el.getAttribute("item") ?? "").replace(/^0+(?=\d)/, "") + (el.getAttribute("itemVariant") ?? "");
      const ind = parseInt(el.getAttribute("indenture") ?? "", 10);
      if (ind > 1) x.ind = String(Math.min(ind - 1, 7));
    }
    if (el.hasAttribute("itemnbr")) {           // IPL item: "-" marks a part not shown in the illustration
      x.item = (el.getAttribute("illusind") === "0" ? "-" : "") + (el.getAttribute("itemnbr") ?? "");
      const ind = el.getAttribute("indent");
      if (ind && /^\d+$/.test(ind) && +ind > 0) x.ind = String(Math.min(+ind, 7));
    }
    const cols = view.columns?.[name];
    if (cols?.length) x.cols = cols.join("|");
    if (name === "title" && /^(table|figure|fig\.?)\s*[0-9]/i.test((el.textContent ?? "").trim())) x.selfnum = "1";
    if (leadOf.has(el)) x.lead = leadOf.get(el)!;
    if (isRevStart(el)) inRev = true;
    if (isRevEnd(el)) inRev = false;
    const attrs: Json = { nid: nid(el), name, summary: attrSummary(el), depth: depthOf(el),
      align: (el.getAttribute("align") ?? "").toLowerCase(), valign: (el.getAttribute("valign") ?? "").toLowerCase(),
      grid: gridOf(el), x };
    if (kind === "atom") return { type: "xatom", attrs };
    if (kind === "text") {
      let changed = inRev || el.getAttribute("changeMark") === "1";
      const content: Json[] = [];
      for (const c of Array.from(el.childNodes)) {
        if (c.nodeType === Node.TEXT_NODE) {
          pushText(content, c.textContent ?? "");
        } else if (c.nodeType === Node.ELEMENT_NODE) {
          const ce = c as Element;
          if (isRevStart(ce)) { inRev = true; changed = true; }
          if (isRevEnd(ce)) inRev = false;
          if (ce.getAttribute("changeMark") === "1") changed = true;
          if (isMarkable(ce) && ce.textContent) {
            const unit = ce.getAttribute("unit") ?? ce.getAttribute("uom") ?? ce.getAttribute("quantityUnitOfMeasure") ?? "";
            content.push({ type: "text", text: ce.textContent, marks: [{ type: "xel", attrs: { nid: nid(ce), name: localName(ce), unit } }] });
          } else {
            let summary = inlineLabel(ce);
            // "Refer to Table <refint/>": the reference reads "9", not "Table Table 9"
            const prev = content[content.length - 1];
            const w = prev?.type === "text" ? /\b(table|figure|fig\.?|step|para|sheet)\s*$/i.exec(prev.text) : null;
            if (w && summary.toLowerCase().startsWith(w[1].toLowerCase() + " ")) summary = summary.slice(w[1].length + 1);
            content.push({ type: "xinline", attrs: { nid: nid(ce), name: localName(ce), summary, raw: raw(ce), misc: false } });
          }
        } else {
          content.push({ type: "xinline", attrs: { nid: nid(c), name: c.nodeType === Node.COMMENT_NODE ? "comment" : c.nodeType === Node.CDATA_SECTION_NODE ? "CDATA" : "PI", summary: "", raw: raw(c), misc: true } });
        }
      }
      if (changed) x.chg = indentOf(el);
      return { type: "xtext", attrs, content: keepsSpace(el) ? content : tidy(content) };
    }
    if (el.getAttribute("changeMark") === "1") x.chg = indentOf(el);
    const content: Json[] = [];
    for (const c of Array.from(el.childNodes)) {
      if (c.nodeType === Node.ELEMENT_NODE) content.push(block(c as Element));
      else if (c.nodeType !== Node.TEXT_NODE) {
        content.push({ type: "xatom", attrs: { nid: -1 - nid(c), name: c.nodeType === Node.COMMENT_NODE ? "comment" : "PI", summary: (c.textContent || "").trim().slice(0, 80), depth: depthOf(el) + 1 } });
      }
    }
    return { type: "xblock", attrs, content };
  };
  return { type: "doc", content: [block(adm.doc!.documentElement)] };
}

// ------------------------------------------------------------------ edits -> source splices
export type InlineItem =
  | { kind: "text"; text: string; mark?: number }
  | { kind: "atom"; raw: string };

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function startTagRaw(adm: Adm, k: number): string {
  const s = adm.spans[k];
  return adm.text.slice(s.start, s.tagEnd);
}

/** Replace the content of textblock elements; returns the new source text. */
export function applyTextEdits(adm: Adm, edits: Map<number, InlineItem[]>): string {
  const ordered = Array.from(edits.entries()).sort((a, b) => adm.spans[b[0]].start - adm.spans[a[0]].start);
  let text = adm.text;
  for (const [k, items] of ordered) {
    const s = adm.spans[k];
    let inner = "";
    let open: number | undefined;
    const close = () => { if (open !== undefined) { inner += `</${adm.spans[open].qname}>`; open = undefined; } };
    for (const it of items) {
      if (it.kind === "atom") { close(); inner += it.raw; continue; }
      if (it.mark !== open) {
        close();
        if (it.mark !== undefined) {
          let tag = startTagRaw(adm, it.mark);
          if (adm.spans[it.mark].selfClosing) tag = tag.replace(/\s*\/>$/, ">");
          inner += tag; open = it.mark;
        }
      }
      inner += esc(it.text);
    }
    close();
    if (s.selfClosing) {
      const tag = startTagRaw(adm, k).replace(/\s*\/>$/, ">");
      text = text.slice(0, s.start) + tag + inner + `</${s.qname}>` + text.slice(s.end);
    } else {
      text = text.slice(0, s.tagEnd) + inner + text.slice(s.contentEnd);
    }
  }
  return text;
}

// Values typed in the inspector may contain entity or character references (&mdash;, &#176;): keep them.
const keepRefs = (s: string) => s.replace(/&(?!(?:[A-Za-z_:][\w.:-]*|#\d+|#x[0-9a-fA-F]+);)/g, "&amp;");
const escAttr = (s: string) => keepRefs(s).replace(/</g, "&lt;").replace(/"/g, "&quot;");

/** Change an existing attribute's value inside the start tag, preserving everything else. */
export function setAttributeValue(adm: Adm, k: number, qname: string, value: string): string {
  const s = adm.spans[k];
  const tag = adm.text.slice(s.start, s.tagEnd);
  const re = new RegExp(`(\\s${qname.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*=\\s*)(["'])([\\s\\S]*?)\\2`);
  const m = re.exec(tag);
  if (!m) throw new Error(`attribute ${qname} not found`);
  const quote = m[2];
  const v = quote === '"' ? escAttr(value) : escAttr(value).replace(/'/g, "&apos;").replace(/&quot;/g, '"');
  const newTag = tag.slice(0, m.index) + m[1] + quote + v + quote + tag.slice(m.index + m[0].length);
  return adm.text.slice(0, s.start) + newTag + adm.text.slice(s.tagEnd);
}

// ------------------------------------------------------------------ diagnostics -> source ranges
export interface DiagLike { element_path?: string | null; attribute?: string | null; value?: string | null }

/** Exact [start, end) offsets to underline: the attribute value, the element's text,
 *  or the element name. Undefined when the path cannot be mapped (fall back to line). */
export function diagRange(adm: Adm, d: DiagLike): { start: number; end: number } | undefined {
  if (!adm.ok) return undefined;
  const k = resolvePath(adm, d.element_path);
  if (k === undefined) return undefined;
  const s = adm.spans[k];
  const tag = adm.text.slice(s.start, s.tagEnd);
  if (d.attribute) {
    const re = new RegExp(`\\s((?:[\\w.-]+:)?${d.attribute.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})\\s*=\\s*(["'])([\\s\\S]*?)\\2`);
    const m = re.exec(tag);
    if (m) {
      const vStart = s.start + m.index + m[0].length - 1 - m[3].length;
      return m[3].length ? { start: vStart, end: vStart + m[3].length } : { start: s.start + m.index + 1, end: s.start + m.index + m[0].length };
    }
  }
  if (d.value && !d.attribute && !s.selfClosing) {
    const inner = adm.text.slice(s.tagEnd, s.contentEnd);
    const at = inner.indexOf(d.value);
    if (at >= 0) return { start: s.tagEnd + at, end: s.tagEnd + at + d.value.length };
  }
  return { start: s.start + 1, end: s.start + 1 + s.qname.length };
}

/** Replace the text of an element that holds only text (e.g. quantityValue). */
export function setTextContent(adm: Adm, k: number, value: string): string {
  const s = adm.spans[k];
  const el = adm.elements[k];
  if (Array.from(el.childNodes).some((c) => c.nodeType !== Node.TEXT_NODE)) throw new Error(`<${el.localName}> has child elements; edit it in Source mode`);
  const v = keepRefs(value).replace(/</g, "&lt;").replace(/>/g, "&gt;");
  if (s.selfClosing) return adm.text.slice(0, s.start) + adm.text.slice(s.start, s.tagEnd).replace(/\s*\/>$/, ">") + v + `</${s.qname}>` + adm.text.slice(s.end);
  return adm.text.slice(0, s.tagEnd) + v + adm.text.slice(s.contentEnd);
}

/** The node that represents element k in the visual editor. Elements inside an inline
 *  chip (e.g. quantityValue inside quantity) are shown by that chip; text marks are
 *  shown by their paragraph. */
export function renderTarget(adm: Adm, k: number): number {
  const chain: Element[] = [];
  for (let e: Element | null = adm.elements[k]; e; e = e.parentElement) chain.unshift(e);
  for (let i = 1; i < chain.length; i++) {
    if (kindOf(chain[i - 1]) === "text") {
      const inline = chain[i];
      return isMarkable(inline) ? adm.indexOf.get(chain[i - 1])! : adm.indexOf.get(inline)!;
    }
  }
  return k;
}

// ------------------------------------------------------------------ structural edits (source splices)
export function childElements(adm: Adm, k: number): number[] {
  return Array.from(adm.elements[k].children).map((c) => adm.indexOf.get(c)!);
}
export function parentOf(adm: Adm, k: number): number | undefined {
  const p = adm.elements[k].parentElement;
  return p ? adm.indexOf.get(p) : undefined;
}
export function ancestorsOf(adm: Adm, k: number): string[] {
  const out: string[] = [];
  for (let p = adm.elements[k].parentElement; p; p = p.parentElement) out.unshift(localName(p));
  return out;
}
function lineIndent(text: string, offset: number): string {
  const ls = text.lastIndexOf("\n", offset - 1) + 1;
  const m = /^[ \t]*/.exec(text.slice(ls, offset));
  return m && ls + m[0].length === offset ? m[0] : "";
}

/** Insert element XML as a child of `parent` at gap `gap` (0 = first). Returns [text, offset of the new element]. */
export function insertChild(adm: Adm, parent: number, gap: number, xml: string): [string, number] {
  const kids = childElements(adm, parent);
  const t = adm.text;
  const ps = adm.spans[parent];
  if (kids.length && gap < kids.length) {                 // before an existing child, same indentation
    const s = adm.spans[kids[gap]];
    const ind = lineIndent(t, s.start);
    const sep = ind || t[s.start - 1] === "\n" ? "\n" + ind : "";
    return [t.slice(0, s.start) + xml + sep + t.slice(s.start), s.start];
  }
  if (kids.length) {                                        // after the last child
    const s = adm.spans[kids[kids.length - 1]];
    const ind = lineIndent(t, s.start);
    const sep = ind || t[s.start - 1] === "\n" ? "\n" + ind : "";
    return [t.slice(0, s.end) + sep + xml + t.slice(s.end), s.end + sep.length];
  }
  if (ps.selfClosing) {                                     // <parent/> becomes <parent>xml</parent>
    const open = t.slice(ps.start, ps.tagEnd).replace(/\s*\/>$/, ">");
    return [t.slice(0, ps.start) + open + xml + `</${ps.qname}>` + t.slice(ps.end), ps.start + open.length];
  }
  return [t.slice(0, ps.tagEnd) + xml + t.slice(ps.contentEnd), ps.tagEnd];
}

/** Remove an element (and the line it stood on, if it was alone there). */
export function deleteElement(adm: Adm, k: number): string {
  const t = adm.text, s = adm.spans[k];
  let a = s.start, b = s.end;
  const ls = t.lastIndexOf("\n", a - 1) + 1;
  if (/^[ \t]*$/.test(t.slice(ls, a))) {
    const le = t.indexOf("\n", b);
    if (le >= 0 && /^[ \t]*$/.test(t.slice(b, le))) { a = ls; b = le + 1; }
  }
  return t.slice(0, a) + t.slice(b);
}

/** Swap an element with its previous (-1) or next (+1) sibling element. */
export function moveElement(adm: Adm, k: number, dir: -1 | 1): string | null {
  const p = parentOf(adm, k);
  if (p === undefined) return null;
  const kids = childElements(adm, p);
  const i = kids.indexOf(k), j = i + dir;
  if (j < 0 || j >= kids.length) return null;
  const [x, y] = dir < 0 ? [kids[j], kids[i]] : [kids[i], kids[j]];
  const t = adm.text, sx = adm.spans[x], sy = adm.spans[y];
  return t.slice(0, sx.start) + t.slice(sy.start, sy.end) + t.slice(sx.end, sy.start) + t.slice(sx.start, sx.end) + t.slice(sy.end);
}

const escA = (s: string) => s.replace(/&(?!(?:[A-Za-z_:][\w.:-]*|#\d+|#x[0-9a-fA-F]+);)/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

export function addAttribute(adm: Adm, k: number, name: string, value: string): string {
  const s = adm.spans[k], t = adm.text;
  const tag = t.slice(s.start, s.tagEnd);
  const at = tag.endsWith("/>") ? tag.length - 2 : tag.length - 1;
  const trimmedAt = tag.slice(0, at).replace(/\s+$/, "").length;
  const newTag = tag.slice(0, trimmedAt) + ` ${name}="${escA(value)}"` + tag.slice(at === tag.length - 2 ? at - (at - trimmedAt) : trimmedAt);
  return t.slice(0, s.start) + newTag + t.slice(s.tagEnd);
}

export function removeAttribute(adm: Adm, k: number, name: string): string {
  const s = adm.spans[k], t = adm.text;
  const tag = t.slice(s.start, s.tagEnd);
  const re = new RegExp(`\\s+${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*=\\s*(["'])[\\s\\S]*?\\1`);
  return t.slice(0, s.start) + tag.replace(re, "") + t.slice(s.tagEnd);
}

/** IDs present in the document, for choosing reference targets: [id, label]. */
export function documentIds(adm: Adm, idAttrs: Map<string, string[]>): [string, string][] {
  const out: [string, string][] = [];
  if (!adm.ok) return out;
  for (const el of adm.elements) {
    for (const a of idAttrs.get(localName(el)) ?? ["id"]) {
      const v = el.getAttribute(a);
      if (v) { const l = refLabel(adm.doc, v); out.push([v, l && l !== v ? `${l} (${v})` : `${localName(el)} ${v}`]); }
    }
  }
  return out;
}

// ------------------------------------------------------------------ SGML write-back
/** Offset where the root element starts in SGML/XML text (after DOCTYPE, comments, PIs). */
export function rootStart(text: string): number {
  let i = 0;
  while (i < text.length) {
    const j = text.indexOf("<", i);
    if (j < 0) return text.length;
    if (text.startsWith("<!--", j)) { i = text.indexOf("-->", j) + 3; continue; }
    if (text.startsWith("<?", j)) { i = text.indexOf(">", j) + 1; continue; }
    if (text.startsWith("<!", j)) {
      let depth = 0, k = j + 2, q = "";
      for (; k < text.length; k++) {
        const c = text[k];
        if (q) { if (c === q) q = ""; continue; }
        if (c === '"' || c === "'") q = c; else if (c === "[") depth++; else if (c === "]") depth--; else if (c === ">" && depth <= 0) break;
      }
      i = k + 1; continue;
    }
    return j;
  }
  return text.length;
}

/** SGML text from the edited XML view: the SGML document's own prolog (DOCTYPE), then the
 *  body with SGML conventions — EMPTY elements without end tag, other empty elements with
 *  an explicit end tag, and element-only content laid out one element per line. The result is
 *  normalised SGML (all end tags present), equivalent in meaning to the original. */
export function xmlToSgml(adm: Adm, sgmlSource: string, emptyElements: Set<string>): string {
  if (!adm.ok) throw new Error("the XML view is not well-formed");
  const base = adm.spans[0].start;
  let body = adm.text.slice(base, adm.spans[0].end);
  const edits: [number, number, string][] = [];
  adm.spans.forEach((s, k) => {
    const name = localName(adm.elements[k]);
    if (s.selfClosing) {
      const tag = adm.text.slice(s.start, s.tagEnd).replace(/\s*\/>$/, ">");
      edits.push([s.start - base, s.tagEnd - base, emptyElements.has(name) ? tag : tag + `</${s.qname}>`]);
    }
    // element-only content: put each child element on its own line (record ends are ignored there)
    const el = adm.elements[k];
    if (kindOf(el) === "block" && el.children.length) {
      const depth = ancestorsOf(adm, k).length + 1;
      for (const c of Array.from(el.children)) {
        const cs = adm.spans[adm.indexOf.get(c)!];
        const before = adm.text.slice(Math.max(s.tagEnd, cs.start - 200), cs.start);
        if (!/\n\s*$/.test(before)) edits.push([cs.start - base, cs.start - base, "\n" + "  ".repeat(depth)]);
      }
    }
  });
  edits.sort((a, b) => b[0] - a[0] || b[1] - a[1]);
  for (const [a, b, r] of edits) body = body.slice(0, a) + r + body.slice(b);
  body = body.replace(/&apos;/g, "'");
  const prolog = sgmlSource.slice(0, rootStart(sgmlSource));
  return prolog + body + "\n";
}

// ------------------------------------------------------------------ tables (CALS: table/tgroup/row/entry)
export interface TableCtx { entry: number; row: number; tgroup: number; col: number; rows: number[] }

/** Where the element k sits in a table, if it does. */
export function tableContext(adm: Adm, k: number): TableCtx | null {
  let entry = -1, row = -1, tgroup = -1;
  for (let el: Element | null = adm.elements[k]; el; el = el.parentElement) {
    const n = localName(el), i = adm.indexOf.get(el)!;
    if (n === "entry" && entry < 0) entry = i;
    else if (n === "row" && row < 0) row = i;
    else if (n === "tgroup") { tgroup = i; break; }
  }
  if (entry < 0 || row < 0 || tgroup < 0) return null;
  const rows = adm.elements.map((_, i) => i).filter((i) => localName(adm.elements[i]) === "row" &&
    adm.elements[i].closest("tgroup") === adm.elements[tgroup]);
  const col = childElements(adm, row).filter((i) => localName(adm.elements[i]) === "entry").indexOf(entry);
  return { entry, row, tgroup, col, rows };
}

const SPANS = ["namest", "nameend", "morerows", "spanname"];
export function hasMergedCells(adm: Adm, tgroup: number): boolean {
  return Array.from(adm.elements[tgroup].getElementsByTagName("*")).some((e) => localName(e) === "entry" && SPANS.some((a) => e.hasAttribute(a)));
}

function applyEdits(text: string, edits: [number, number, string][]): string {
  edits.sort((a, b) => b[0] - a[0] || b[1] - a[1]);
  for (const [a, b, r] of edits) text = text.slice(0, a) + r + text.slice(b);
  return text;
}

function setColsAttr(adm: Adm, tgroup: number, delta: number, edits: [number, number, string][]) {
  const s = adm.spans[tgroup], tag = adm.text.slice(s.start, s.tagEnd);
  const m = /\scols\s*=\s*(["'])(\d+)\1/.exec(tag);
  if (m) {
    const at = s.start + m.index;
    edits.push([at, at + m[0].length, ` cols="${Math.max(1, parseInt(m[2], 10) + delta)}"`]);
  }
}

/** A new row with the same number of cells as the current one, below (or above) it. */
export function tableAddRow(adm: Adm, ctx: TableCtx, entryXml: string, above = false): [string, number] {
  const n = childElements(adm, ctx.row).filter((i) => localName(adm.elements[i]) === "entry").length;
  const p = parentOf(adm, ctx.row)!;
  const sibs = childElements(adm, p);
  const rowQ = adm.spans[ctx.row].qname;
  return insertChild(adm, p, sibs.indexOf(ctx.row) + (above ? 0 : 1), `<${rowQ}>${entryXml.repeat(Math.max(1, n))}</${rowQ}>`);
}

/** A new column to the right of the current cell, in every row; cols and colspec updated. */
export function tableAddColumn(adm: Adm, ctx: TableCtx, entryXml: string): string {
  if (hasMergedCells(adm, ctx.tgroup)) throw new Error("This table has merged cells; add columns in Source mode.");
  const edits: [number, number, string][] = [];
  for (const r of ctx.rows) {
    const cells = childElements(adm, r).filter((i) => localName(adm.elements[i]) === "entry");
    const after = cells[Math.min(ctx.col, cells.length - 1)];
    const at = after !== undefined ? adm.spans[after].end : adm.spans[r].tagEnd;
    edits.push([at, at, entryXml]);
  }
  setColsAttr(adm, ctx.tgroup, 1, edits);
  const specs = childElements(adm, ctx.tgroup).filter((i) => localName(adm.elements[i]) === "colspec");
  if (specs.length) {
    const used = new Set(specs.map((i) => adm.elements[i].getAttribute("colname")).filter(Boolean) as string[]);
    let n = specs.length + 1, name = `col${n}`;
    while (used.has(name)) name = `col${++n}`;
    const after = specs[Math.min(ctx.col, specs.length - 1)];
    edits.push([adm.spans[after].end, adm.spans[after].end, `<${adm.spans[after].qname} colname="${name}"/>`]);
  }
  return applyEdits(adm.text, edits);
}

export function tableDeleteRow(adm: Adm, ctx: TableCtx): string {
  const p = parentOf(adm, ctx.row)!;
  if (childElements(adm, p).filter((i) => localName(adm.elements[i]) === "row").length <= 1)
    throw new Error("This is the only row here; a table part needs at least one row.");
  return deleteElement(adm, ctx.row);
}

export function tableDeleteColumn(adm: Adm, ctx: TableCtx): string {
  if (hasMergedCells(adm, ctx.tgroup)) throw new Error("This table has merged cells; delete columns in Source mode.");
  const cellsOf = (r: number) => childElements(adm, r).filter((i) => localName(adm.elements[i]) === "entry");
  if (cellsOf(ctx.row).length <= 1) throw new Error("This is the only column.");
  const edits: [number, number, string][] = [];
  for (const r of ctx.rows) {
    const c = cellsOf(r)[ctx.col];
    if (c !== undefined) edits.push([adm.spans[c].start, adm.spans[c].end, ""]);
  }
  setColsAttr(adm, ctx.tgroup, -1, edits);
  const specs = childElements(adm, ctx.tgroup).filter((i) => localName(adm.elements[i]) === "colspec");
  if (specs[ctx.col] !== undefined) edits.push([adm.spans[specs[ctx.col]].start, adm.spans[specs[ctx.col]].end, ""]);
  return applyEdits(adm.text, edits);
}

/** The next (or previous) cell of the table, or null at the end. */
export function nextCell(adm: Adm, ctx: TableCtx, dir: 1 | -1): number | null {
  const cells = ctx.rows.flatMap((r) => childElements(adm, r).filter((i) => localName(adm.elements[i]) === "entry"));
  const i = cells.indexOf(ctx.entry) + dir;
  return i >= 0 && i < cells.length ? cells[i] : null;
}

/** CALS table XML: rows x cols, optional header row. entryXml is one empty cell. */
export function calsTable(open: string, close: string, q: { title: boolean; colspec: boolean; head: boolean; rows: number; cols: number },
                          entryXml: string, tgroupAttrs = ""): string {
  const row = (n: number) => `<row>${entryXml.repeat(n)}</row>`;
  const specs = q.colspec ? Array.from({ length: q.cols }, (_, i) => `<colspec colname="col${i + 1}"/>`).join("") : "";
  return `${open}${q.title ? "<title></title>" : ""}<tgroup cols="${q.cols}"${tgroupAttrs}>${specs}` +
    (q.head ? `<thead>${row(q.cols)}</thead>` : "") + `<tbody>${Array.from({ length: q.rows }, () => row(q.cols)).join("")}</tbody></tgroup>${close}`;
}

// ------------------------------------------------------------------ tidy source
/** Re-indent the structure: every element that contains only elements gets one child per line,
 *  indented by depth. Text content (mixed or text-only elements) is never touched. */
export function tidy(adm: Adm, indent = "  "): string {
  if (!adm.ok) return adm.text;
  const t = adm.text, edits: [number, number, string][] = [];
  adm.spans.forEach((s, k) => {
    const el = adm.elements[k];
    if (s.selfClosing || kindOf(el) !== "block" || !el.children.length) return;
    const depth = ancestorsOf(adm, k).length;
    const kids = childElements(adm, k);
    let prev = s.tagEnd;
    for (const c of kids) {
      const cs = adm.spans[c];
      const gap = t.slice(prev, cs.start);
      if (/^\s*$/.test(gap)) edits.push([prev, cs.start, "\n" + indent.repeat(depth + 1)]);
      prev = cs.end;
    }
    const tail = t.slice(prev, s.contentEnd);
    if (/^\s*$/.test(tail)) edits.push([prev, s.contentEnd, "\n" + indent.repeat(depth)]);
  });
  return applyEdits(t, edits).replace(/[ \t]+$/gm, "");
}
