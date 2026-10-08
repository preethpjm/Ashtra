import { Extension, Mark, Node as TNode } from "@tiptap/core";
import History from "@tiptap/extension-history";
import Text from "@tiptap/extension-text";
import { Node as PMNode } from "@tiptap/pm/model";
import { NodeSelection, Plugin, PluginKey, TextSelection } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect, useRef } from "react";
import { Adm, InlineItem, Numbering, toProseMirror } from "./adm";

export const humanize = (n: string) =>
  n.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/^./, (c) => c.toUpperCase()).replace(/ ([A-Z])(?=[a-z])/g, (_, c) => " " + c.toLowerCase());

export interface RenderProfile { profile: string; roles: Record<string, string>; labels: Record<string, string>; default_text: string;
  numbering?: Numbering | null; columns?: Record<string, string[]> }
// The active display profile (element name -> role). Node views read it when they draw.
let RENDER: RenderProfile = { profile: "generic", roles: {}, labels: {}, default_text: "para" };
const roleOf = (name: string, kind: "block" | "text" | "atom") => RENDER.roles[name] ?? (kind === "text" ? RENDER.default_text : "");
const labelOf = (name: string) => RENDER.labels[name] ?? humanize(name);

const nodeAttrs = { nid: { default: 0 }, name: { default: "" }, summary: { default: "" }, depth: { default: 0 },
  align: { default: "" }, valign: { default: "" }, grid: { default: "" }, x: { default: null } };

// publication data computed from the document (numbers, identifiers, change bars, IPL items): display only
const X_KEYS = ["num", "ns", "nd", "nl", "lead", "chg", "item", "ind", "selfnum", "cols", "ident"] as const;

function elementView(textblock: boolean) {
  return ({ node }: { node: PMNode }) => {
    const dom = document.createElement("div");
    const label = document.createElement("span");
    label.className = "x-label";
    label.contentEditable = "false";
    const content = document.createElement("div");
    content.className = "x-content";
    dom.append(label, content);
    const apply = (n: PMNode) => {
      dom.className = `x-node ${textblock ? "x-text" : "x-block"}`;
      dom.dataset.name = n.attrs.name;
      const role = roleOf(n.attrs.name, textblock ? "text" : "block");
      if (role) dom.dataset.role = role; else delete dom.dataset.role;
      dom.dataset.label = labelOf(n.attrs.name);
      dom.dataset.nid = String(n.attrs.nid);
      dom.dataset.depth = String(n.attrs.depth);
      dom.dataset.human = humanize(n.attrs.name);
      if (n.attrs.summary) dom.dataset.summary = n.attrs.summary; else delete dom.dataset.summary;
      if (n.attrs.align) dom.dataset.align = n.attrs.align; else delete dom.dataset.align;
      if (n.attrs.valign) dom.dataset.valign = n.attrs.valign; else delete dom.dataset.valign;
      // CALS tables: column widths on the tgroup, exact row/column position and spans on each entry
      const g = String(n.attrs.grid || "").split("|");
      content.style.gridTemplateColumns = g[0] === "T" ? g[1] : "";
      dom.style.gridRow = g[0] === "C" ? g[1] : "";
      dom.style.gridColumn = g[0] === "C" ? g[2] : "";
      if (g[0] === "C" && g[3]) dom.dataset.head = g[3]; else delete dom.dataset.head;
      const x = (n.attrs.x ?? {}) as Record<string, string>;
      for (const k of X_KEYS) if (x[k]) dom.dataset[k] = x[k]; else delete dom.dataset[k];
      if (x.num) content.dataset.num = x.num; else delete content.dataset.num;
      if (x.ident) label.dataset.ident = x.ident; else delete label.dataset.ident;
      label.replaceChildren(
        Object.assign(document.createElement("span"), { className: "l-raw", textContent: n.attrs.name }),
        Object.assign(document.createElement("span"), { className: "l-human", textContent: humanize(n.attrs.name) }),
      );
      if (x.cols) {
        const head = Object.assign(document.createElement("span"), { className: "x-colhead" });
        for (const c of x.cols.split("|")) head.append(Object.assign(document.createElement("span"), { textContent: c }));
        label.append(head);
      }
      label.title = n.attrs.summary || n.attrs.name;
    };
    apply(node);
    return {
      dom, contentDOM: content,
      update: (n: PMNode) => { if (n.type !== node.type) return false; const same = n.attrs === node.attrs; node = n; if (!same) apply(n); return true; },
      ignoreMutation: (m: any) => m.target === label || label.contains(m.target),
    };
  };
}

const XDoc = TNode.create({ name: "doc", topNode: true, content: "block+" });
const XBlock = TNode.create({
  name: "xblock", group: "block", content: "block*", defining: true, isolating: true,
  addAttributes: () => nodeAttrs,
  renderHTML: ({ HTMLAttributes }) => ["div", { class: "x-node x-block", "data-name": HTMLAttributes.name }, 0],
  addNodeView: () => elementView(false) as any,
});
const XText = TNode.create({
  name: "xtext", group: "block", content: "inline*", marks: "xel", defining: true, isolating: true,
  addAttributes: () => nodeAttrs,
  renderHTML: ({ HTMLAttributes }) => ["div", { class: "x-node x-text", "data-name": HTMLAttributes.name }, 0],
  addNodeView: () => elementView(true) as any,
});
function atomView({ node }: { node: PMNode }) {
  const dom = document.createElement("div");
  const apply = (n: PMNode) => {
    dom.className = "x-node x-atom";
    dom.dataset.name = n.attrs.name;
    dom.dataset.nid = String(n.attrs.nid);
    const role = roleOf(n.attrs.name, "atom");
    if (role) dom.dataset.role = role; else delete dom.dataset.role;
    dom.dataset.label = labelOf(n.attrs.name);
    dom.replaceChildren(
      Object.assign(document.createElement("span"), { className: "x-label", textContent: n.attrs.name }),
      Object.assign(document.createElement("span"), { className: "x-summary", textContent: n.attrs.summary || "" }));
  };
  apply(node);
  return { dom, update: (n: PMNode) => { if (n.type !== node.type) return false; node = n; apply(n); return true; } };
}

const XAtom = TNode.create({
  name: "xatom", group: "block", atom: true, selectable: true,
  addAttributes: () => nodeAttrs,
  addNodeView: () => atomView as any,
  renderHTML: ({ HTMLAttributes }) => ["div", { class: "x-node x-atom", "data-name": HTMLAttributes.name, "data-nid": HTMLAttributes.nid },
    ["span", { class: "x-label" }, HTMLAttributes.name], ["span", { class: "x-summary" }, HTMLAttributes.summary || ""]],
});
const XInline = TNode.create({
  name: "xinline", group: "inline", inline: true, atom: true, selectable: true,
  addAttributes: () => ({ nid: { default: 0 }, name: { default: "" }, summary: { default: "" }, raw: { default: "" }, misc: { default: false } }),
  renderHTML: ({ HTMLAttributes }) => ["span", {
    class: `x-inline${HTMLAttributes.misc ? " x-misc" : ""}${HTMLAttributes.name === "entity" ? " x-entity" : ""}`, "data-name": HTMLAttributes.name, "data-nid": HTMLAttributes.nid,
    title: HTMLAttributes.raw,
  }, HTMLAttributes.misc ? HTMLAttributes.name : ["span", { class: "x-inline-text" }, HTMLAttributes.summary || HTMLAttributes.name]],
});
const XEl = Mark.create({
  name: "xel", inclusive: false, excludes: "",
  addAttributes: () => ({ nid: { default: 0 }, name: { default: "" }, unit: { default: "" } }),
  renderHTML: ({ HTMLAttributes }) => ["span", { class: "x-mark", "data-name": HTMLAttributes.name, "data-nid": HTMLAttributes.nid,
    ...(HTMLAttributes.unit ? { "data-unit": HTMLAttributes.unit } : {}) }, 0],
});

// ---- structure guard: typing may change text, never elements --------------------
const skelCache = new WeakMap<PMNode, string>();
function skeleton(doc: PMNode): string {
  const hit = skelCache.get(doc);
  if (hit !== undefined) return hit;
  const parts: string[] = [];
  doc.descendants((n) => {
    if (n.isText) return false;
    parts.push(`${n.type.name}:${n.attrs.nid}`);
    if (n.type.name === "xtext") {
      const marks: number[] = [];
      n.forEach((c) => {
        const m = c.marks.find((x) => x.type.name === "xel");
        const k = c.isText ? (m ? m.attrs.nid : -1) : -2;
        if (marks[marks.length - 1] !== k) marks.push(k);
      });
      parts.push("m" + marks.filter((k) => k >= 0).join(","));
      return true;
    }
    return true;
  });
  const s = parts.join("|");
  skelCache.set(doc, s);
  return s;
}

export function inlineItems(n: PMNode): InlineItem[] {
  const items: InlineItem[] = [];
  n.forEach((c) => {
    if (c.isText) {
      const m = c.marks.find((x) => x.type.name === "xel");
      items.push({ kind: "text", text: c.text!, mark: m ? m.attrs.nid : undefined });
    } else items.push({ kind: "atom", raw: c.attrs.raw });
  });
  return items;
}

const decoKey = new PluginKey<{ errors: Map<number, string>; selected: number | null }>("asthra-deco");

export type KeyAction = "enter" | "menu" | "attrs" | "up" | "down" | "delete" | "tab" | "shift-tab" | "escape" | "backspace";

function makeGuard(onBlocked: () => void, onKey: (a: KeyAction) => boolean) {
  return Extension.create({
    name: "asthraGuard",
    // Keyboard-first structure editing; the app decides with the schema model.
    addKeyboardShortcuts() {
      return {
        Enter: () => onKey("enter") || (onBlocked(), true),
        "Shift-Enter": () => onKey("menu"),
        "Mod-Enter": () => onKey("menu"),
        "Alt-Enter": () => onKey("attrs"),
        "Alt-ArrowUp": () => onKey("up"),
        "Alt-ArrowDown": () => onKey("down"),
        "Alt-Backspace": () => onKey("delete"),
        Tab: () => onKey("tab"),
        "Shift-Tab": () => onKey("shift-tab"),
        Escape: () => onKey("escape"),
        Backspace: () => onKey("backspace"),
      };
    },
    addProseMirrorPlugins() {
      return [
        new Plugin({
          filterTransaction: (tr, state) => {
            if (!tr.docChanged || tr.getMeta("asthra-load")) return true;
            const ok = skeleton(tr.doc) === skeleton(state.doc);
            if (!ok) onBlocked();
            return ok;
          },
        }),
        new Plugin({
          key: decoKey,
          state: {
            init: () => ({ errors: new Map<number, string>(), selected: null as number | null }),
            apply: (tr, v) => tr.getMeta(decoKey) ?? v,
          },
          props: {
            decorations(state) {
              const v = decoKey.getState(state)!;
              if (!v.errors.size && v.selected === null) return DecorationSet.empty;
              const decos: Decoration[] = [];
              state.doc.descendants((n, pos) => {
                if (n.isText || n.type.name === "doc") return true;
                const nid = n.attrs.nid;
                const msg = v.errors.get(nid);
                const cls = [msg ? "has-error" : "", v.selected === nid ? "is-selected" : ""].filter(Boolean).join(" ");
                if (cls) decos.push(Decoration.node(pos, pos + n.nodeSize, msg ? { class: cls, title: msg } : { class: cls }));
                return true;
              });
              return DecorationSet.create(state.doc, decos);
            },
          },
        }),
      ];
    },
  });
}

export interface VisualProps {
  adm: Adm;                  // current (well-formed) model
  generation: number;        // bump to rebuild from adm (external changes only)
  editable: boolean;
  mode: "clean" | "tags";
  render: RenderProfile;
  errorNids: Map<number, string>;      // node -> problem text (shown on hover)
  selected: number | null;
  focusRequest: { nid: number; n: number; offset?: number; focus?: boolean } | null;
  onEdits: (edits: Map<number, InlineItem[]>) => void;
  onSelect: (nid: number | null) => void;
  onBlocked: () => void;
  onKey?: (a: KeyAction) => boolean;
  selectionRef?: { current: TextSel | null };
  apiRef?: { current: { focus: () => void } | null };
}

/** Where the cursor is inside a text element (for inline insertion and Enter). */
export interface TextSel {
  nid: number; offset: number; atEnd: boolean; items: InlineItem[];
  inlineNid?: number;       // inline element at the caret: selected, just before the caret, or around it
}

export function VisualEditor(p: VisualProps) {
  RENDER = p.render;
  const props = useRef(p);
  props.current = p;
  const last = useRef(new Map<number, string>());   // nid -> serialized inline items
  const suppressSelect = useRef(false);             // selection moved by us, not the user

  const snapshot = (doc: PMNode) => {
    const m = new Map<number, string>();
    doc.descendants((n) => { if (n.type.name === "xtext") m.set(n.attrs.nid, JSON.stringify(inlineItems(n))); return true; });
    return m;
  };

  // the first content is converted once (the editor reads it only when it is created)
  const initial = useRef<ReturnType<typeof toProseMirror> | null>(null);
  if (!initial.current) initial.current = toProseMirror(p.adm, p.render);
  const editor = useEditor({
    extensions: [XDoc, Text, XBlock, XText, XAtom, XInline, XEl, History.configure({ depth: 200 }),
      makeGuard(() => props.current.onBlocked(), (a) => props.current.onKey?.(a) ?? false)],
    content: initial.current,
    editable: p.editable,
    onCreate: ({ editor }) => { last.current = snapshot(editor.state.doc); },
    onUpdate: ({ editor, transaction }) => {
      if (transaction.getMeta("asthra-load")) return;
      const edits = new Map<number, InlineItem[]>();
      const now = new Map<number, string>();
      editor.state.doc.descendants((n) => {
        if (n.type.name !== "xtext") return true;
        const items = inlineItems(n);
        const s = JSON.stringify(items);
        now.set(n.attrs.nid, s);
        if (last.current.get(n.attrs.nid) !== s) edits.set(n.attrs.nid, items);
        return false;
      });
      last.current = now;
      if (edits.size) props.current.onEdits(edits);
    },
    onSelectionUpdate: ({ editor, transaction }) => {
      if (transaction.getMeta("asthra-load")) return;
      const sel = editor.state.selection;
      if (props.current.selectionRef) {
        const $p = sel.$from;
        const tb = $p.parent;
        let inlineNid: number | undefined;
        if (sel instanceof NodeSelection && sel.node.type.name === "xinline" && !sel.node.attrs.misc && sel.node.attrs.nid >= 0)
          inlineNid = sel.node.attrs.nid;
        else if ($p.nodeBefore?.type.name === "xinline" && !$p.nodeBefore.attrs.misc && $p.nodeBefore.attrs.nid >= 0)
          inlineNid = $p.nodeBefore.attrs.nid;
        else {
          const mk = ($p.nodeBefore?.marks ?? $p.marks()).find((m) => m.type.name === "xel");
          if (mk && mk.attrs.nid >= 0) inlineNid = mk.attrs.nid;
        }
        if (sel instanceof NodeSelection && sel.node.type.name === "xatom" && sel.node.attrs.nid >= 0)
          props.current.selectionRef.current = { nid: sel.node.attrs.nid, offset: 0, atEnd: false, items: [] };
        else
          props.current.selectionRef.current = tb.type.name === "xtext"
            ? { nid: tb.attrs.nid, offset: $p.parentOffset, atEnd: $p.parentOffset === tb.content.size, items: inlineItems(tb), inlineNid }
            : null;
      }
      if (suppressSelect.current) { suppressSelect.current = false; return; }
      if (sel instanceof NodeSelection) { props.current.onSelect(sel.node.attrs.nid >= 0 ? sel.node.attrs.nid : null); return; }
      const $f = sel.$from;
      const mark = $f.marks().find((m) => m.type.name === "xel") ?? $f.nodeAfter?.marks.find((m) => m.type.name === "xel");
      if (mark) { props.current.onSelect(mark.attrs.nid); return; }
      for (let d = $f.depth; d > 0; d--) {
        const n = $f.node(d);
        if (typeof n.attrs.nid === "number" && n.attrs.nid >= 0) { props.current.onSelect(n.attrs.nid); return; }
      }
      props.current.onSelect(null);
    },
  });

  // rebuild on external change
  useEffect(() => {
    if (!editor) return;
    const json = toProseMirror(p.adm, p.render);
    const doc = PMNode.fromJSON(editor.schema, json);
    const tr = editor.state.tr.replaceWith(0, editor.state.doc.content.size, doc.content).setMeta("asthra-load", true).setMeta("addToHistory", false);
    editor.view.dispatch(tr);
    last.current = snapshot(editor.state.doc);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, p.generation, p.render]);

  useEffect(() => { editor?.setEditable(p.editable); }, [editor, p.editable]);

  useEffect(() => {
    if (!editor) return;
    editor.view.dispatch(editor.state.tr.setMeta(decoKey, { errors: p.errorNids, selected: p.selected }));
  }, [editor, p.errorNids, p.selected]);

  // scroll to / select a node on request (tree, diagnostics)
  useEffect(() => {
    if (!editor || !p.focusRequest) return;
    const target = p.focusRequest.nid;
    let found = -1, node: PMNode | null = null;
    editor.state.doc.descendants((n, pos) => {
      if (found >= 0) return false;
      if (!n.isText && n.attrs.nid === target && n.type.name !== "doc") { found = pos; node = n; return false; }
      if (n.isText && n.marks.some((m) => m.type.name === "xel" && m.attrs.nid === target)) { found = pos; return false; }
      return true;
    });
    if (found < 0) return;
    const n = node as PMNode | null;
    const off = p.focusRequest.offset;
    const sel = n && n.type.name === "xtext" && off !== undefined
      ? TextSelection.create(editor.state.doc, found + 1 + Math.min(off, n.content.size))     // caret at a text offset
      : n && (n.isAtom || n.type.name === "xblock")
        ? (n.isAtom ? NodeSelection.create(editor.state.doc, found) : TextSelection.near(editor.state.doc.resolve(found + 1)))
        : TextSelection.near(editor.state.doc.resolve(n ? found + 1 : found));
    suppressSelect.current = true;
    editor.view.dispatch(editor.state.tr.setSelection(sel).scrollIntoView());
    suppressSelect.current = false;
    if (p.focusRequest.focus) editor.view.focus();
    const dom = editor.view.nodeDOM(found) as HTMLElement | null;
    dom?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, p.focusRequest]);

  // lets the app put the caret back where the user was typing (after a popover closes)
  useEffect(() => {
    if (!p.apiRef) return;
    p.apiRef.current = { focus: () => { editor?.commands.focus(); } };
    return () => { if (p.apiRef) p.apiRef.current = null; };
  }, [editor, p.apiRef]);
  return <div className={`visual mode-${p.mode}${p.editable ? "" : " readonly"}`}><EditorContent editor={editor} /></div>;
}
