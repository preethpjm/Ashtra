import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Adm, InlineItem, addAttribute, ancestorsOf, applyTextEdits, childElements, deleteElement, diagRange, documentIds,
  editText, headerInfo, insertChild, localName, moveElement, parentOf, removeAttribute, xmlToSgml, leafDescendants, setEntityValues, elementAtOffset, kindOf, lineAt, parseAdm, readablePath, renderTarget, resolvePath, setAttributeValue, setTextContent } from "./adm";
import { api, Check, Diagnostic, Doc, Outline, OutlineNode, Pkg, Project, RenderProfile, Report, Revision, SchemaOption } from "./api";
import { SourceEditor, SrcMarker } from "./SourceEditor";
import { Tree } from "./Tree";
import { SchemaManager } from "./SchemaManager";
import { Sheet, usePrintPage } from "./Sheet";
import { AttrDialog, AttributeEditor, InsertGroup, InsertMenu } from "./StructureUI";
import { fillTemplate, idAttributes, inlineAllowed, insertable, isCompletable, isValid, SchemaModel, template, uniqueId } from "./schemaModel";
import type { TextSel } from "./VisualEditor";
import { VisualEditor } from "./VisualEditor";

type Mode = "doc" | "source" | "split";
const STAGES = ["", "File integrity", "Well-formedness", "Schema", "Business rules", "References", "Engineering coherence", "AI explanation"];
const STATUS_TEXT: Record<string, string> = {
  passed: "Passed", failed: "Failed", "not-run": "Not run", "not-implemented": "Not available yet", unsupported: "No schema",
};

// memoized parse keyed by text, so rapid visual edits always apply to the latest text
let admCache: { text: string; adm: Adm } | null = null;
const admFor = (text: string) => (admCache && admCache.text === text ? admCache.adm : (admCache = { text, adm: parseAdm(text) }).adm);

const prefersDark = () => window.matchMedia?.("(prefers-color-scheme: dark)").matches;

export function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [pid, setPid] = useState<string | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [pkgs, setPkgs] = useState<Pkg[]>([]);
  const [docId, setDocId] = useState<string | null>(null);
  const [meta, setMeta] = useState<Doc | null>(null);
  const [text, setText] = useState("");
  const textRef = useRef("");
  const [savedText, setSavedText] = useState("");
  const [origin, setOrigin] = useState("original");
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [gen, setGen] = useState(0);
  const pendingRebuild = useRef(false);
  const goodAdm = useRef<Adm | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [outline, setOutline] = useState<Outline | null>(null);
  const [checking, setChecking] = useState(false);
  const [mode, setMode] = useState<Mode>("doc");
  const [tags, setTags] = useState(false);
  const [render, setRender] = useState<RenderProfile>({ profile: "generic", roles: {}, labels: {}, default_text: "para" });
  const [schemaOpts, setSchemaOpts] = useState<SchemaOption[] | null>(null);
  const entitiesKey = useRef("");
  const [selected, setSelected] = useState<number | null>(null);
  const [focusReq, setFocusReq] = useState<{ nid: number; n: number } | null>(null);
  const [reveal, setReveal] = useState<{ line: number; endLine?: number; n: number } | null>(null);
  const [bottom, setBottom] = useState<"problems" | "revisions" | "stages">("problems");
  const [bottomOpen, setBottomOpen] = useState(true);
  const [sevFilter, setSevFilter] = useState<"all" | "errors">("all");
  const [toast, setToast] = useState<{ text: string; kind: "ok" | "err" | "info" } | null>(null);
  const [commitOpen, setCommitOpen] = useState(false);
  const [newProject, setNewProject] = useState<string | null>(null);
  const [schemasOpen, setSchemasOpen] = useState(false);
  const [managerOpen, setManagerOpen] = useState(false);
  const counter = useRef(0);
  const theme = prefersDark() ? "dark" : "light";

  const say = useCallback((t: string, kind: "ok" | "err" | "info" = "info") => {
    setToast({ text: t, kind });
    window.setTimeout(() => setToast((c) => (c && c.text === t ? null : c)), kind === "err" ? 7000 : 3000);
  }, []);
  const fail = useCallback((e: unknown) => say(e instanceof Error ? e.message : String(e), "err"), [say]);

  // ---- data loading ----------------------------------------------------------
  const refreshProjects = useCallback(async () => {
    const ps = await api.projects(); setProjects(ps);
    setPid((cur) => cur ?? (ps.length ? ps[ps.length - 1].id : null));
  }, []);
  const refreshDocs = useCallback(async () => { if (pid) setDocs(await api.documents(pid)); }, [pid]);
  const refreshPkgs = useCallback(async () => setPkgs(await api.packages()), []);
  useEffect(() => { refreshProjects().catch(fail); refreshPkgs().catch(fail); }, [refreshProjects, refreshPkgs, fail]);
  useEffect(() => { setDocs([]); refreshDocs().catch(fail); }, [refreshDocs, fail]);

  const adm = useMemo(() => admFor(text), [text]);
  if (adm.ok) goodAdm.current = adm;
  const visualAdm = adm.ok ? adm : goodAdm.current;
  // SGML: the document view shows OpenSP's XML normalization, read-only; Source edits the SGML
  const isSgml = meta?.syntax === "sgml";
  // SGML: the document view edits OpenSP's XML view of the file; every change is written back
  // as (normalised) SGML and re-checked by OpenSP. Source edits refresh the view from OpenSP.
  const [sgmlView, setSgmlView] = useState<string | null>(null);
  const lastOrigin = useRef<"visual" | "source" | "external">("external");
  const renderedXml = isSgml ? report?.rendered_xml ?? null : null;
  useEffect(() => {
    if (renderedXml && lastOrigin.current !== "visual") { setSgmlView(renderedXml); setGen((g) => g + 1); }
  }, [renderedXml]);
  const sgmlXml = isSgml ? sgmlView : null;
  const sgmlAdm = useMemo(() => (sgmlXml ? parseAdm(sgmlXml) : null), [sgmlXml]);
  const viewAdm = isSgml ? sgmlAdm : visualAdm;
  // ---- schema model (drives insertion, attributes, delete/move checks)
  const [model, setModel] = useState<SchemaModel | null>(null);
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [attrAsk, setAttrAsk] = useState<{ title: string; t: ReturnType<typeof template>; commit: (xml: string) => void } | null>(null);
  const selRef = useRef<TextSel | null>(null);
  const pendingFocus = useRef<number | null>(null);
  const header = useMemo(() => headerInfo(viewAdm), [viewAdm, gen]);
  usePrintPage(header, meta?.original_name ?? "ASTHRA");
  const printDoc = () => {
    if (mode === "source") setMode("doc");
    setTimeout(() => window.print(), mode === "source" ? 400 : 50);
  };

  const updateText = useCallback((t: string, source: "visual" | "source" | "external") => {
    lastOrigin.current = source;
    textRef.current = t;
    if (source !== "visual") pendingRebuild.current = true;
    setText(t);
  }, []);
  useEffect(() => {
    if (pendingRebuild.current && adm.ok) { pendingRebuild.current = false; setGen((g) => g + 1); }
  }, [adm]);

  const applyCheck = (c: Check) => {
    setReport(c.report); if (c.outline) setOutline(c.outline); setProbIdx(-1);
    const k = JSON.stringify(c.report.entities ?? {});
    if (k !== entitiesKey.current) { entitiesKey.current = k; setEntityValues(c.report.entities ?? {}); setGen((g) => g + 1); }
  };
  const loadSchemaOptions = async () => { if (docId) { try { setSchemaOpts(await api.schemaOptions(docId)); } catch (e) { fail(e); } } };
  const chooseSchema = async (o: SchemaOption) => {
    if (!docId) return;
    try {
      const st = await api.chooseSchema(docId, o.package_id, o.doc_type);
      setMeta(st.document); setRender(st.render); setSchemaOpts(null); setGen((g) => g + 1);
      api.schemaModel(docId).then(setModel).catch(() => setModel(null));
      applyCheck(await api.check(docId, textRef.current));
      say(`Now validating against ${o.standard} ${o.issue} · ${o.label}.`, "ok");
      refreshDocs();
    } catch (e) { fail(e); }
  };

  const openDoc = useCallback(async (id: string) => {
    if (textRef.current !== savedText && docId && !window.confirm("Discard unsaved changes to the current document?")) return;
    try {
      const st = await api.state(id);
      setDocId(id); setMeta(st.document); setOrigin(st.origin); setRevisions(st.revisions); setRender(st.render);
      setSchemaOpts(null); setEntityValues({}); entitiesKey.current = "";
      setSgmlView(null); lastOrigin.current = "external"; setModel(null); setMenuFor(null);
      api.schemaModel(id).then(setModel).catch(() => setModel(null));
      setSavedText(st.text); setSelected(null); setReport(null); setOutline(null); goodAdm.current = null;
      updateText(st.text, "external");
      if (st.document.syntax !== "xml" && st.document.syntax !== "sgml") setMode("source");
      if (["needs-choice", "ambiguous"].includes(st.document.identification.status)) api.schemaOptions(id).then(setSchemaOpts).catch(() => {});
    } catch (e) { fail(e); }
  }, [docId, savedText, updateText, fail]);

  // ---- live validation (debounced) ------------------------------------------------
  useEffect(() => {
    if (!docId) return;
    setChecking(true);
    const h = window.setTimeout(async () => {
      try { applyCheck(await api.check(docId, text)); } catch (e) { fail(e); } finally { setChecking(false); }
    }, 600);
    return () => window.clearTimeout(h);
  }, [docId, text, fail]);

  // ---- editing actions ---------------------------------------------------------------
  const dirty = !!docId && text !== savedText;
  const save = useCallback(async () => {
    if (!docId) return;
    try {
      const c = await api.save(docId, textRef.current);
      setSavedText(textRef.current); setOrigin("working"); applyCheck(c);
      say(c.report.statuses.structural === "passed" ? "Draft saved. Structure is valid." : "Draft saved. It still has problems to fix.", "ok");
      refreshDocs();
    } catch (e) { fail(e); }
  }, [docId, say, fail, refreshDocs]);

  const commit = async (message: string) => {
    if (!docId) return;
    try {
      if (dirty) await save();
      const r = await api.commit(docId, message);
      setCommitOpen(false);
      const st = await api.state(docId); setRevisions(st.revisions); setOrigin(st.origin);
      say(`Revision ${r.number} committed (structure ${STATUS_TEXT[r.structural_status]?.toLowerCase() ?? r.structural_status}).`, "ok");
      setBottom("revisions"); setBottomOpen(true); refreshDocs();
    } catch (e) { fail(e); }
  };

  const restore = async (r: Revision) => {
    if (!docId) return;
    if (dirty && !window.confirm("Replace your unsaved changes with revision " + r.number + "?")) return;
    try {
      const c = await api.restore(docId, r.id);
      const st = await api.state(docId);
      setSavedText(st.text); setOrigin(st.origin); updateText(st.text, "external"); applyCheck(c);
      say(`Revision ${r.number} restored into your working copy.`, "ok");
    } catch (e) { fail(e); }
  };

  const discard = async () => {
    if (!docId || !window.confirm("Discard the working copy and go back to the imported original? Committed revisions are kept.")) return;
    try {
      const st = await api.discard(docId);
      setSavedText(st.text); setOrigin(st.origin); updateText(st.text, "external"); refreshDocs();
      say("Working copy discarded. Showing the original.", "ok");
    } catch (e) { fail(e); }
  };

  const emptySet = useMemo(() => new Set(model ? Object.entries(model.elements).filter(([, d]) => d.empty).map(([n]) => n) : []), [model]);
  const sgmlViewRef = useRef<string | null>(null);
  sgmlViewRef.current = sgmlView;
  /** Write an edited SGML view back as SGML. */
  const commitSgmlView = useCallback((xml: string, rebuild: boolean) => {
    const v = parseAdm(xml);
    if (!v.ok) { fail(new Error("the edit produced an invalid view; it was not applied")); return; }
    setSgmlView(xml);
    sgmlViewRef.current = xml;
    updateText(xmlToSgml(v, textRef.current, emptySet), "visual");
    if (rebuild) setGen((g) => g + 1);
  }, [emptySet, updateText]);
  const onEdits = useCallback((edits: Map<number, InlineItem[]>) => {
    if (isSgml) {
      const v = sgmlViewRef.current ? parseAdm(sgmlViewRef.current) : null;
      if (v?.ok) commitSgmlView(applyTextEdits(v, edits), false);
      return;
    }
    const cur = admFor(textRef.current);
    if (!cur.ok) return;
    updateText(applyTextEdits(cur, edits), "visual");
  }, [updateText, isSgml, commitSgmlView]);

  /** Apply a structural change made on the model shown in the document view. */
  const applyStructure = useCallback((newText: string, focusOffset?: number) => {
    if (focusOffset !== undefined) pendingFocus.current = focusOffset;
    if (isSgml) commitSgmlView(newText, true);
    else updateText(newText, "external");
  }, [isSgml, commitSgmlView, updateText]);

  const setAttr = (name: string, value: string) => {
    const A = isSgml ? sgmlAdm : adm;
    if (selected === null || !A?.ok) return;
    try { applyStructure(setAttributeValue(A, selected, name, value)); } catch (e) { fail(e); }
  };

  // ---- navigation -----------------------------------------------------------------------
  const goTo = useCallback((nid: number | undefined, line?: number | null) => {
    const a = admFor(textRef.current);
    if (nid !== undefined && a.ok && a.spans[nid]) {
      setSelected(renderTarget(a, nid));
      setFocusReq({ nid, n: ++counter.current });
      setReveal({ line: lineAt(a.text, a.spans[nid].start), endLine: lineAt(a.text, a.spans[nid].end), n: ++counter.current });
    } else if (line) {
      setReveal({ line, n: ++counter.current });
      if (mode === "doc") setMode("split");
    }
  }, [mode]);

  const applyFix = (d: Diagnostic) => {
    if (!d.fix || !adm.ok) return;
    const k = resolvePath(adm, d.element_path);
    if (k === undefined) { say("The element has moved since validation; wait for the check to finish and try again.", "info"); return; }
    try {
      const t = d.fix.kind === "attr" && d.attribute ? setAttributeValue(adm, k, d.attribute, d.fix.value) : setTextContent(adm, k, d.fix.value);
      updateText(t, "external");
      say(`${d.fix.label} — applied. Revalidating…`, "ok");
    } catch (e) { fail(e); }
  };
  const stepProblem = (dir: 1 | -1) => {
    const list = shownDiags;
    if (!list.length) return;
    const i = (probIdx + dir + list.length) % list.length;
    setProbIdx(i); setBottom("problems"); setBottomOpen(true);
    pickDiag(list[i]);
    requestAnimationFrame(() => document.querySelector(`[data-prob="${i}"]`)?.scrollIntoView({ block: "nearest" }));
  };
  const pickDiag = (d: Diagnostic) => goTo(visualAdm ? resolvePath(visualAdm, d.element_path) : undefined, d.line);
  const pickTree = (n: OutlineNode) => {
    if (isSgml && sgmlAdm) {           // SGML: navigate in the rendered view (no source offsets)
      const k = resolvePath(sgmlAdm, n.path);
      if (k !== undefined) { setSelected(k); setFocusReq({ nid: k, n: ++counter.current }); }
      return;
    }
    goTo(visualAdm ? resolvePath(visualAdm, n.path) : undefined, n.line);
  };

  // ---- derived views ----------------------------------------------------------------
  const diags = report?.diagnostics ?? [];
  const errorPaths = useMemo(() => {
    const m = new Map<string, number>();
    for (const d of diags) if (d.element_path && d.severity !== "info") m.set(d.element_path, (m.get(d.element_path) ?? 0) + 1);
    return m;
  }, [diags]);
  const errorNids = useMemo(() => {
    const m = new Map<number, string>();
    if (!visualAdm) return m;
    for (const d of diags) {
      if (d.severity === "info") continue;
      const k = resolvePath(visualAdm, d.element_path);
      if (k === undefined) continue;
      const t = renderTarget(visualAdm, k);
      const text = d.message + (d.suggestion ? " " + d.suggestion : "");
      m.set(t, m.has(t) ? `${m.get(t)}\n${text}` : text);
    }
    return m;
  }, [diags, visualAdm]);
  // source markers with exact ranges and verified fixes (offsets only valid for the current text)
  const srcMarkers: SrcMarker[] = useMemo(() => diags.map((d) => {
    const r = adm.ok ? diagRange(adm, d) : undefined;
    let fix: SrcMarker["fix"];
    if (r && d.fix && adm.ok) {
      const k = resolvePath(adm, d.element_path)!;
      if (d.fix.kind === "attr" && d.attribute) {
        const vr = diagRange(adm, { element_path: d.element_path, attribute: d.attribute });
        if (vr) fix = { label: d.fix.label, start: vr.start, end: vr.end, text: d.fix.value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;") };
      } else if (d.fix.kind === "text" && k !== undefined) {
        const sp = adm.spans[k];
        fix = { label: d.fix.label, start: sp.tagEnd, end: sp.contentEnd, text: d.fix.value.replace(/&/g, "&amp;").replace(/</g, "&lt;") };
      }
    }
    return { diag: d, start: r?.start, end: r?.end, fix };
  }), [diags, adm]);
  const [probIdx, setProbIdx] = useState(-1);
  const elAdm = isSgml && sgmlAdm ? sgmlAdm : adm;
  const selEl = selected !== null && elAdm.ok ? elAdm.elements[selected] : null;
  const selPath = selEl ? readablePath(selEl) : null;
  // an inline element with inner structure (e.g. a quantity) is a locked chip in the visual view;
  // its inner values are edited in the inspector's Contents list
  const isChip = !isSgml && !!selEl && selEl.children.length > 0 && !!selEl.parentElement && kindOf(selEl.parentElement) === "text";
  const selDiags = selPath && adm.ok ? diags.filter((d) => {
    if (d.element_path === selPath) return true;
    const k = resolvePath(adm, d.element_path);
    return k !== undefined && renderTarget(adm, k) === selected;
  }) : [];
  const nErr = (report?.counts.error ?? 0) + (report?.counts.fatal ?? 0);
  const nWarn = report?.counts.warning ?? 0;
  const pkg = pkgs.find((p) => p.id === meta?.package_id);
  const visualEditable = isSgml ? !!sgmlAdm?.ok && !!model : (adm.ok && !adm.visualBlocked && meta?.syntax === "xml");
  const editAdm = isSgml ? sgmlAdm : (adm.ok ? adm : null);
  const docIds = useMemo(() => (editAdm && model ? documentIds(editAdm, idAttributes(model)) : []), [editAdm, model]);
  useEffect(() => {
    const off = pendingFocus.current;
    if (off === null || !editAdm?.ok) return;
    const k = editAdm.spans.findIndex((sp) => sp.start === off);
    pendingFocus.current = null;
    if (k >= 0) { setSelected(k); setFocusReq({ nid: k, n: ++counter.current }); }
  }, [editAdm]);

  const insertGroups = (k: number): InsertGroup[] => {
    const A = editAdm;
    if (!A || !model) return [];
    const el = A.elements[k];
    const name = localName(el);
    const groups: InsertGroup[] = [];
    const p = parentOf(A, k);
    if (p !== undefined) {
      const sibs = childElements(A, p);
      const names = sibs.map((i) => localName(A.elements[i]));
      const idx = sibs.indexOf(k);
      const pn = localName(A.elements[p]);
      groups.push({ key: "after", label: `After this ${name}`, names: insertable(model, pn, names, idx + 1, ancestorsOf(A, p)) });
      groups.push({ key: "before", label: `Before this ${name}`, names: insertable(model, pn, names, idx, ancestorsOf(A, p)) });
    }
    const d = model.elements[name];
    if (d && !d.empty && !d.text && !(d.mixed && kindOf(el) === "text")) {
      const kids = childElements(A, k).map((i) => localName(A.elements[i]));
      groups.push({ key: "start", label: `Inside, at the start`, names: insertable(model, name, kids, 0, ancestorsOf(A, k)) });
      if (kids.length) groups.push({ key: "end", label: `Inside, at the end`, names: insertable(model, name, kids, kids.length, ancestorsOf(A, k)) });
    }
    if (d?.mixed && selRef.current?.nid === k) groups.unshift({ key: "inline", label: "At the cursor (inline)", names: inlineAllowed(model, name, ancestorsOf(A, k)) });
    return groups;
  };

  const doInsert = (k: number, where: string, name: string) => {
    const A = editAdm;
    if (!A || !model) return;
    setMenuFor(null);
    const used = new Set(docIds.map(([i]) => i));
    const t = template(model, name, used);
    const commit = (xml: string) => {
      try {
        if (where === "inline") {
          const sel = selRef.current;
          if (!sel || sel.nid !== k) { say("Put the cursor in the text first.", "info"); return; }
          const items: InlineItem[] = [];
          let pos = 0, placed = false;
          for (const it of sel.items) {
            const len = it.kind === "text" ? it.text.length : 1;
            if (!placed && it.kind === "text" && sel.offset >= pos && sel.offset <= pos + len) {
              const cut = sel.offset - pos;
              if (cut > 0) items.push({ ...it, text: it.text.slice(0, cut) });
              items.push({ kind: "atom", raw: xml }); placed = true;
              if (cut < len) items.push({ ...it, text: it.text.slice(cut) });
            } else {
              if (!placed && sel.offset <= pos) { items.push({ kind: "atom", raw: xml }); placed = true; }
              items.push(it);
            }
            pos += len;
          }
          if (!placed) items.push({ kind: "atom", raw: xml });
          applyStructure(applyTextEdits(A, new Map([[k, items]])));
          return;
        }
        const p = parentOf(A, k);
        let res: [string, number];
        if (where === "after" || where === "before") {
          const sibs = childElements(A, p!);
          res = insertChild(A, p!, sibs.indexOf(k) + (where === "after" ? 1 : 0), xml);
        } else {
          res = insertChild(A, k, where === "start" ? 0 : childElements(A, k).length, xml);
        }
        applyStructure(res[0], res[1]);
        say(`Inserted ${name}.`, "ok");
      } catch (e) { fail(e); }
    };
    if (t.needs.length) setAttrAsk({ title: `Insert ${name}`, t, commit: (xml) => commit(xml) });
    else commit(t.xml);
  };

  const deleteSelected = () => {
    const A = editAdm;
    if (selected === null || !A || !model) return;
    const p = parentOf(A, selected);
    if (p === undefined) { say("The root element cannot be deleted.", "info"); return; }
    const pn = localName(A.elements[p]);
    const kids = childElements(A, p).map((i) => localName(A.elements[i]));
    const idx = childElements(A, p).indexOf(selected);
    const after = kids.filter((_, i) => i !== idx);
    const anc = ancestorsOf(A, p);
    if (isValid(model, pn, kids, anc) && !isValid(model, pn, after, anc)
      && !window.confirm(`<${pn}> requires this <${kids[idx]}>. Deleting it makes the document invalid until you add another. Delete anyway?`)) return;
    applyStructure(deleteElement(A, selected));
    setSelected(null);
  };

  const moveSelected = (dir: -1 | 1) => {
    const A = editAdm;
    if (selected === null || !A || !model) return;
    const p = parentOf(A, selected);
    if (p === undefined) return;
    const sibs = childElements(A, p);
    const i = sibs.indexOf(selected), j = i + dir;
    if (j < 0 || j >= sibs.length) return;
    const names = sibs.map((x) => localName(A.elements[x]));
    [names[i], names[j]] = [names[j], names[i]];
    if (!isCompletable(model, localName(A.elements[p]), names, ancestorsOf(A, p))) { say("The schema does not allow that order.", "info"); return; }
    const t = moveElement(A, selected, dir);
    if (t) applyStructure(t, dir < 0 ? A.spans[sibs[j]].start : undefined);
  };

  const onEnter = (mod: boolean): boolean => {
    const A = editAdm;
    const sel = selRef.current;
    if (!A || !model || !visualEditable) return false;
    const k = sel?.nid ?? selected;
    if (k === null || k === undefined || k < 0) return false;
    if (mod || !sel?.atEnd) { setMenuFor(k); return true; }
    const p = parentOf(A, k);
    const name = localName(A.elements[k]);
    if (p !== undefined) {
      const sibs = childElements(A, p);
      const ok = insertable(model, localName(A.elements[p]), sibs.map((i) => localName(A.elements[i])), sibs.indexOf(k) + 1, ancestorsOf(A, p));
      if (ok.includes(name)) { doInsert(k, "after", name); return true; }
    }
    setMenuFor(k);
    return true;
  };
  const shownDiags = diags.filter((d) => sevFilter === "all" || d.severity === "error" || d.severity === "fatal");

  // ---- keyboard --------------------------------------------------------------------------
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "F8" && !(e.target as HTMLElement)?.closest?.(".monaco-editor")) { e.preventDefault(); stepProblem(e.shiftKey ? -1 : 1); return; }
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key === "s") { e.preventDefault(); save(); }
      const modes: Record<string, Mode> = { "1": "doc", "2": "source", "3": "split" };
      if (e.altKey && modes[e.key]) { e.preventDefault(); setMode(modes[e.key]); }
      if (e.altKey && e.key.toLowerCase() === "t") { e.preventDefault(); setTags((t) => !t); }
    };
    window.addEventListener("keydown", h);
    const unload = (e: BeforeUnloadEvent) => { if (textRef.current !== savedText && docId) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", unload);
    return () => { window.removeEventListener("keydown", h); window.removeEventListener("beforeunload", unload); };
  });

  // ---- actions: projects, import, schemas ----------------------------------------------
  const importFiles = async (files: FileList | null) => {
    if (!files || !pid) return;
    let last: Doc | null = null;
    for (const f of Array.from(files)) {
      try { last = await api.importDocument(pid, f); } catch (e) { fail(e); }
    }
    await refreshDocs(); refreshProjects();
    if (last) {
      openDoc(last.id);
      if (last.identification.status !== "identified") say(last.identification.notes[0] ?? "Schema not identified.", "info");
    }
  };
  const loadSamples = async () => {
    try { const p = await api.loadSamples(); await refreshProjects(); await refreshPkgs(); setPid(p.id); say("Sample S-Series documents loaded.", "ok"); }
    catch (e) { fail(e); }
  };
  const createProject = async () => {
    if (!newProject?.trim()) return;
    try { const p = await api.createProject(newProject.trim()); setNewProject(null); await refreshProjects(); setPid(p.id); setDocId(null); setMeta(null); }
    catch (e) { fail(e); }
  };

  // ---- render --------------------------------------------------------------------------------
  const statusPill = (label: string, s?: string) => (
    <span className={`pill st-${s ?? "none"}`} title={`${label}: ${s ? STATUS_TEXT[s] ?? s : "—"}`}>{label} <b>{s ? STATUS_TEXT[s] ?? s : "—"}</b></span>
  );

  const visual = viewAdm ? (
    <div className="pane visual-pane">
      {isSgml && <div className="banner info">{visualEditable
        ? "SGML document. Edits here are written back as SGML and checked by OpenSP; the SGML is saved in normalised form (all end tags written, attribute values quoted)."
        : "SGML document, shown through OpenSP's conversion. Editing needs its schema model; edit the SGML in Source meanwhile."}</div>}
      {!isSgml && !adm.ok && <div className="banner warn">The source has XML errors, so the visual view is paused at the last valid version. Fix the source to continue.</div>}
      {adm.ok && adm.visualBlocked && <div className="banner info">{adm.visualBlocked}</div>}
      {meta && ["needs-choice", "ambiguous"].includes(meta.identification.status) && !meta.package_id &&
        <div className="banner info">{meta.identification.notes[0]} Pick one in the panel on the right.</div>}
      <div className="desk"><Sheet info={header} standardLine={meta?.standard ? `${meta.standard} ${meta.issue ?? ""} · ${meta.doc_type ?? ""}` : undefined}>
      <VisualEditor adm={viewAdm} generation={gen} editable={!!visualEditable} mode={tags ? "tags" : "clean"} render={render}
        errorNids={errorNids} selected={selected} focusRequest={focusReq} onEdits={onEdits} onSelect={setSelected}
        onEnter={onEnter} selectionRef={selRef}
        onBlocked={() => say(model ? "Use Insert (Ctrl+Enter) to add elements, or the Delete and move buttons in the Element panel." : "Structure editing needs the document's schema; choose or install it first.", "info")} />
      </Sheet></div>
    </div>
  ) : (isSgml ? <div className="pane visual-pane"><div className="banner info">{checking ? "Converting the SGML with OpenSP…" : "This SGML document cannot be shown yet. See Problems: its DTD set or OpenSP may be missing."}</div></div> : null);
  const source = (
    <div className="pane source-pane">
      <SourceEditor text={text} markers={srcMarkers} reveal={reveal} theme={theme}
        onChange={(t) => updateText(t, "source")}
        onCursor={(off) => { const a = admFor(textRef.current); if (a.ok) { const k = elementAtOffset(a, off); if (k !== undefined) setSelected(k); } }} />
    </div>
  );

  return (
    <div className={`app${bottomOpen ? "" : " bottom-closed"}${meta ? "" : " no-doc"}`}>
      {/* ---------------- left sidebar ---------------- */}
      <aside className="side">
        <div className="brand"><span className="brand-mark" aria-hidden>◭</span> ASTHRA</div>

        <section className="side-sec">
          <div className="sec-head"><span>Project</span>
            <button className="link" onClick={() => setNewProject(newProject === null ? "" : null)}>{newProject === null ? "New" : "Cancel"}</button></div>
          {newProject !== null ? (
            <div className="row"><input autoFocus placeholder="Project name" value={newProject}
              onChange={(e) => setNewProject(e.target.value)} onKeyDown={(e) => e.key === "Enter" && createProject()} />
              <button onClick={createProject}>Create</button></div>
          ) : projects.length ? (
            <select value={pid ?? ""} onChange={(e) => { setPid(e.target.value); setDocId(null); setMeta(null); }}>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.document_count})</option>)}
            </select>
          ) : <p className="muted small">No projects yet.</p>}
        </section>

        <section className="side-sec docs">
          <div className="sec-head"><span>Documents</span>
            {pid && <label className="link">Import<input type="file" multiple accept=".xml,.sgm,.sgml,.xsd" hidden onChange={(e) => { importFiles(e.target.files); e.target.value = ""; }} /></label>}</div>
          <ul className="doclist">
            {docs.map((d) => (
              <li key={d.id} className={d.id === docId ? "active" : ""} onClick={() => openDoc(d.id)} title={d.identity.display || d.original_name}>
                <span className={`dot st-${d.last_validation?.structural_status ?? "none"}`} />
                <span className="doc-name">{d.original_name}</span>
                <span className="doc-meta">{d.standard ?? (d.syntax === "sgml" ? "SGML" : "unidentified")}{d.doc_type ? ` · ${d.doc_type}` : ""}{d.has_working_copy ? " · edited" : ""}</span>
              </li>
            ))}
          </ul>
          {pid && !docs.length && <p className="muted small">Import an XML document to start. Its schema is identified automatically.</p>}
        </section>

        {outline && docId && (
          <section className="side-sec structure">
            <div className="sec-head"><span>Structure</span><span className="muted small">{outline.count} elements</span></div>
            <Tree root={outline.root} selectedPath={selPath} errorPaths={errorPaths} onPick={pickTree} />
          </section>
        )}

        <section className="side-sec schemas">
          <div className="sec-head"><button className="link plain" onClick={() => setSchemasOpen(!schemasOpen)}>{schemasOpen ? "▾" : "▸"} Schemas ({pkgs.filter((p) => p.enabled).length})</button>
            <button className="link" onClick={() => setManagerOpen(true)}>Manage</button></div>
          {schemasOpen && <ul className="pkglist">
            {pkgs.map((p) => (
              <li key={p.id} title={p.licence_note}>
                <label><input type="checkbox" checked={p.enabled} onChange={async () => { try { await api.setEnabled(p.id, !p.enabled); refreshPkgs(); } catch (e) { fail(e); } }} />
                  <b>{p.standard}</b> {p.issue}</label>
                {p.provenance === "synthetic" && <span className="tag synth">test schema</span>}
                <div className="muted small">{p.doc_types.map((d) => d.label).join(", ")}</div>
              </li>
            ))}
            {!pkgs.length && <li className="muted small">No schemas installed.</li>}
          </ul>}
        </section>
      </aside>

      {/* ---------------- header ---------------- */}
      <header className="top">
        {meta ? (
          <>
            <div className="doc-title">
              <div className="t1">{meta.original_name}{dirty && <span className="unsaved" title="Unsaved changes">●</span>}</div>
              <div className="t2">
                {meta.identity.display || meta.identification.status}
                {meta.standard && <> · {meta.standard} {meta.issue} · {meta.doc_type}</>}
                {pkg?.provenance === "synthetic" && <span className="tag synth">test schema</span>}
                {meta.identification.selection === "user" && <span className="tag chosen">schema chosen by you</span>}
                <span className="muted"> · {origin === "working" ? "working copy" : "original"}</span>
              </div>
            </div>
            <div className="modes" role="tablist" aria-label="View">
              {([["doc", "Document"], ["source", "Source"], ["split", "Split"]] as [Mode, string][]).map(([m, label], i) => (
                <button key={m} role="tab" aria-selected={mode === m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}
                  title={`Ctrl+Alt+${i + 1}`} disabled={m !== "source" && meta.syntax !== "xml" && meta.syntax !== "sgml"}>{label}</button>
              ))}
            </div>
            <label className={`toggle${mode === "source" ? " off" : ""}`} title="Show element tags in the document (Ctrl+Alt+T)">
              <input type="checkbox" checked={tags} onChange={(e) => setTags(e.target.checked)} disabled={mode === "source"} />
              <span className="track"><span className="thumb" /></span> Tags
            </label>
            <div className="actions">
              <button onClick={save} disabled={!dirty} title="Ctrl+S">Save draft</button>
              <button className="primary" onClick={() => setCommitOpen(true)}>Commit revision</button>
              <details className="menu"><summary>Export</summary>
                <div className="menu-body">
                  <button onClick={printDoc}>Print / Save as PDF…</button>
                  <a href={api.exportUrl(meta.id, "current")} onClick={(e) => { if (dirty) { e.preventDefault(); say("Save the draft first so the export matches what you see.", "info"); } }}>Current version</a>
                  <a href={api.exportUrl(meta.id, "original")}>Imported original</a>
                  <button onClick={() => { const b = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = `${meta.original_name}.validation.json`; a.click(); }}>Validation report (JSON)</button>
                  {origin === "working" && <button onClick={discard}>Discard working copy…</button>}
                </div>
              </details>
            </div>
          </>
        ) : <div className="doc-title"><div className="t1">No document open</div></div>}
      </header>

      {/* ---------------- centre ---------------- */}
      <main className={`center mode-${mode}`}>
        {!meta ? (
          <div className="empty">
            {!pkgs.length || !projects.length ? (
              <>
                <h1>Start with the sample S-Series set</h1>
                <p>Loads test schemas for S1000D, S2000M and S3000L and a project with Description, Procedure and illustrated parts documents, including some with deliberate errors.</p>
                <div className="row"><button className="primary big" onClick={loadSamples}>Load sample documents</button>
                  <button className="big" onClick={() => setManagerOpen(true)}>Add your schemas…</button></div>
                <p className="muted small">The sample schemas are written for testing and are not the official standards. Install official schema packages under Schemas for real work.</p>
              </>
            ) : (
              <>
                <h1>Open a document</h1>
                <p>Pick one from the list on the left, or import an XML file into this project.</p>
                <p className="muted small">Ctrl+S saves a draft. Ctrl+Alt+1–4 switches Clean, Tags, Source and Split views.</p>
              </>
            )}
          </div>
        ) : mode === "source" ? source : mode === "split" ? <div className="split">{visual}{source}</div> : visual}
      </main>

      {/* ---------------- inspector ---------------- */}
      <aside className="inspector">
        {meta && (
          <>
            <section>
              <h3>Status</h3>
              <div className="pills">
                {statusPill("Structure", checking ? "checking" : report?.statuses.structural)}
                {statusPill("Business rules", report?.statuses.business_rules)}
                {statusPill("References", report?.statuses.references)}
                {statusPill("Engineering", report?.statuses.engineering)}
              </div>
              <p className="muted small">A valid structure is not engineering approval. The other checks arrive in later milestones.</p>
            </section>
            {selEl && elAdm.ok ? (
              <section>
                <h3>Element <code>{selEl.localName}</code></h3>
                <p className="path" title={selPath ?? ""}>{selPath}</p>
                <p className="muted small">{isSgml ? "SGML · " : `Line ${lineAt(adm.text, adm.spans[selected!].start)} · `}{kindOf(selEl) === "text" ? "text content" : kindOf(selEl) === "block" ? "container" : "empty element"}</p>
                {visualEditable && model && (
                  <div className="struct-actions">
                    <button onClick={() => setMenuFor(selected!)} title="Ctrl+Enter">+ Insert…</button>
                    <button onClick={() => moveSelected(-1)} title="Move up" aria-label="Move up">↑</button>
                    <button onClick={() => moveSelected(1)} title="Move down" aria-label="Move down">↓</button>
                    <button className="danger" onClick={deleteSelected}>Delete</button>
                  </div>
                )}
                <h3>Attributes</h3>
                <AttributeEditor adm={elAdm} k={selected!} model={model} editable={!!visualEditable} ids={docIds}
                  onSet={(n, v) => setAttr(n, v)}
                  onAdd={(d) => { const A = editAdm; if (!A) return;
                    const v = d.fixed ?? d.default ?? (d.kind === "enum" ? d.values[0] : d.kind === "id" ? uniqueId(localName(A.elements[selected!]), new Set(docIds.map(([i]) => i))) : "");
                    applyStructure(addAttribute(A, selected!, d.name, v ?? "")); }}
                  onRemove={(n) => { const A = editAdm; if (A) applyStructure(removeAttribute(A, selected!, n)); }} />
                {!model && meta.package_id && <p className="muted small">Loading the schema model…</p>}
                {!meta.package_id && <p className="muted small">Choose a schema to enable structure editing.</p>}
                {isChip ? (
                  <>
                    <h3>Contents</h3>
                    <table className="contents"><tbody>
                      {leafDescendants(adm, selected!).map((k) => {
                        const el = adm.elements[k];
                        const path = readablePath(el);
                        const probs = diags.filter((d) => d.element_path === path);
                        const textOnly = Array.from(el.childNodes).every((c) => c.nodeType === Node.TEXT_NODE);
                        return (
                          <tr key={`${k}-${gen}`} className={`leaf-row${probs.length ? " bad" : ""}`}>
                            <td className="leaf-name" title={path}>{el.localName}</td>
                            <td>
                              {textOnly && (el.textContent !== "" || el.attributes.length === 0) && (
                                <input className={probs.some((d) => !d.attribute) ? "bad" : ""} defaultValue={editText(el.textContent ?? "", adm.doc)} key={el.textContent ?? ""} disabled={!visualEditable}
                                  aria-label={`${el.localName} value`}
                                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                                  onBlur={(e) => { if (e.target.value !== editText(el.textContent ?? "", adm.doc)) { try { updateText(setTextContent(adm, k, e.target.value), "external"); } catch (err) { fail(err); } } }} />
                              )}
                              {Array.from(el.attributes).filter((a) => !a.name.startsWith("xmlns")).map((a) => (
                                <div key={a.name}><span className="attr-label">{a.localName}</span>
                                  <input className={probs.some((d) => d.attribute === a.localName) ? "bad" : ""} defaultValue={editText(a.value, adm.doc)} key={a.value} disabled={!visualEditable}
                                    aria-label={`${el.localName} ${a.localName}`}
                                    onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                                    onBlur={(e) => { if (e.target.value !== editText(a.value, adm.doc)) { try { updateText(setAttributeValue(adm, k, a.name, e.target.value), "external"); } catch (err) { fail(err); } } }} /></div>
                              ))}
                              {probs.map((d, i) => <div key={i} className="leaf-err">{d.message}{d.fix && <> <button className="fix" onClick={() => applyFix(d)}>{d.fix.label}</button></>}</div>)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody></table>
                  </>
                ) : null}
                {selDiags.length > 0 && <><h3>Problems here</h3>{selDiags.map((d, i) => <div key={i} className={`diag-card sev-${d.severity}`} title={d.raw_message ?? undefined}>{d.message}{d.suggestion && <div className="hint">{d.suggestion}</div>}{d.fix && <button className="fix" onClick={() => applyFix(d)}>{d.fix.label}</button>}</div>)}</>}
                {!isSgml && <button className="link" onClick={() => goTo(selected!)}>Show in source</button>}
              </section>
            ) : (
              <section>
                <h3>Document</h3>
                <dl className="kv">
                  <dt>Identity</dt><dd>{meta.identity.display || "—"}</dd>
                  <dt>Schema</dt><dd>{pkg ? `${pkg.name}` : meta.identification.status}</dd>
                  <dt>SHA-256</dt><dd className="hash" title={meta.sha256}>{meta.sha256.slice(0, 16)}…</dd>
                  <dt>Revisions</dt><dd>{revisions.length}</dd>
                </dl>
                {meta.identification.notes.map((n, i) => <p key={i} className="muted small">{n}</p>)}
                <p className="muted small">Display profile: {render.profile}</p>
                {schemaOpts === null ? (
                  meta.syntax === "xml" && <button className="link" onClick={loadSchemaOptions}>{meta.package_id ? "Validate against a different schema…" : "Choose a schema…"}</button>
                ) : (
                  <div className="chooser">
                    <h3>Validate against</h3>
                    {schemaOpts.length === 0 && <p className="muted small">No installed schema fits this document's root element. Install its schema package under Schemas.</p>}
                    {schemaOpts.map((o) => (
                      <button key={o.package_id + o.doc_type} className={`option${o.package_id === meta.package_id && o.doc_type === meta.doc_type ? " current" : ""}`} onClick={() => chooseSchema(o)}>
                        <b>{o.standard} {o.issue}</b> · {o.label}
                        <span className="muted small">{o.declared ? "declared by the document" : "not declared by the document"}{o.provenance === "synthetic" ? " · test schema" : ""}</span>
                      </button>
                    ))}
                    <button className="link" onClick={() => setSchemaOpts(null)}>Cancel</button>
                  </div>
                )}
                <p className="muted small">Click text in the document or a node in Structure to inspect an element.</p>
              </section>
            )}
          </>
        )}
      </aside>

      {/* ---------------- bottom panel ---------------- */}
      <section className="bottom">
        <div className="bottom-tabs">
          <button className={bottom === "problems" ? "on" : ""} onClick={() => { setBottom("problems"); setBottomOpen(true); }}>
            Problems {report && <span className={`count ${nErr ? "bad" : nWarn ? "warn" : "good"}`}>{nErr + nWarn}</span>}</button>
          <button className={bottom === "revisions" ? "on" : ""} onClick={() => { setBottom("revisions"); setBottomOpen(true); }}>Revisions <span className="count">{revisions.length}</span></button>
          <button className={bottom === "stages" ? "on" : ""} onClick={() => { setBottom("stages"); setBottomOpen(true); }}>Validation stages</button>
          <span className="grow" />
          {bottom === "problems" && bottomOpen && diags.length > 0 && <span className="nav">
            <button className="icon" onClick={() => stepProblem(-1)} title="Previous problem (Shift+F8)" aria-label="Previous problem">↑</button>
            <button className="icon" onClick={() => stepProblem(1)} title="Next problem (F8)" aria-label="Next problem">↓</button></span>}
          {bottom === "problems" && bottomOpen && <select value={sevFilter} onChange={(e) => setSevFilter(e.target.value as any)} aria-label="Filter"><option value="all">All problems</option><option value="errors">Errors only</option></select>}
          <span className="muted small">{checking ? "Checking…" : report ? `${nErr} errors, ${nWarn} warnings` : ""}</span>
          <button className="icon" onClick={() => setBottomOpen(!bottomOpen)} aria-label={bottomOpen ? "Collapse panel" : "Expand panel"}>{bottomOpen ? "▾" : "▴"}</button>
        </div>
        {bottomOpen && <div className="bottom-body">
          {bottom === "problems" && (shownDiags.length ? (
            <table className="diags"><tbody>
              {shownDiags.map((d, i) => (
                <tr key={i} data-prob={i} onClick={() => { setProbIdx(i); pickDiag(d); }} className={`sev-${d.severity}${i === probIdx ? " current" : ""}`}>
                  <td className="sev"><span className={`sev-dot sev-${d.severity}`} />{d.severity}</td>
                  <td className="msg" title={d.raw_message ?? undefined}>
                    <span className="msg-main">{d.message}</span>
                    {d.suggestion && <span className="msg-hint">{d.suggestion}</span>}
                    {d.fix && <button className="fix" onClick={(e) => { e.stopPropagation(); applyFix(d); }} disabled={!adm.ok}>{d.fix.label}</button>}
                  </td>
                  <td className="where">{d.line ? `line ${d.line}` : ""}</td>
                  <td className="rule" title={`${d.rule_id}${d.reference ? "\n" + d.reference : ""}`}>{d.rule_id}</td>
                </tr>
              ))}
            </tbody></table>
          ) : <p className="muted pad">{!meta ? "Open a document to see its problems." : checking ? "Checking…" : report?.statuses.structural === "unsupported" ? "No installed schema matches this document, so only well-formedness is checked. Install its schema package under Schemas." : "No problems found by the checks that are available."}</p>)}
          {bottom === "revisions" && (revisions.length ? (
            <table className="diags"><tbody>
              {revisions.map((r) => (
                <tr key={r.id}>
                  <td className="sev"><b>r{r.number}</b></td>
                  <td className="msg">{r.message || <span className="muted">No message</span>}</td>
                  <td className="where"><span className={`dot st-${r.structural_status}`} /> {STATUS_TEXT[r.structural_status] ?? r.structural_status}</td>
                  <td className="where">{new Date(r.created_at).toLocaleString()}</td>
                  <td className="rule"><button className="link" onClick={() => restore(r)}>Restore</button> <a className="link" href={api.exportUrl(meta!.id, "revision", r.id)}>Download</a></td>
                </tr>
              ))}
            </tbody></table>
          ) : <p className="muted pad">No revisions yet. Commit revision stores the current version permanently; the imported original is never changed.</p>)}
          {bottom === "stages" && (
            <table className="diags"><tbody>
              {(report?.stages ?? []).map((s) => (
                <tr key={s.stage}><td className="sev">{s.stage}</td><td className="msg">{STAGES[s.stage]}</td>
                  <td className="where"><span className={`dot st-${s.status}`} /> {STATUS_TEXT[s.status] ?? s.status}</td><td className="rule muted">{s.note}</td></tr>
              ))}
            </tbody></table>
          )}
        </div>}
      </section>

      {commitOpen && meta && <CommitDialog status={report?.statuses.structural} errors={nErr} onCancel={() => setCommitOpen(false)} onCommit={commit} />}
      {menuFor !== null && editAdm && <InsertMenu anchorNid={menuFor} groups={insertGroups(menuFor)} onClose={() => setMenuFor(null)}
        onPick={(g, n) => doInsert(menuFor, g, n)} />}
      {attrAsk && <AttrDialog title={attrAsk.title} needs={attrAsk.t.needs} ids={docIds} onCancel={() => setAttrAsk(null)}
        onOk={(vals) => { const a = attrAsk; setAttrAsk(null); a.commit(fillTemplate(a.t.xml, vals)); }} />}
      {managerOpen && <SchemaManager onClose={() => setManagerOpen(false)} say={say}
        onChanged={() => { refreshPkgs(); refreshDocs(); if (docId) api.state(docId).then((st) => { setMeta(st.document); setRender(st.render); }).catch(() => {}); }} />}
      {toast && <div className={`toast ${toast.kind}`} role="status">{toast.text}</div>}
    </div>
  );
}

function CommitDialog({ status, errors, onCancel, onCommit }: { status?: string; errors: number; onCancel: () => void; onCommit: (m: string) => void }) {
  const [msg, setMsg] = useState("");
  return (
    <div className="modal-bg" onClick={onCancel}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="commit-h" onClick={(e) => e.stopPropagation()}>
        <h2 id="commit-h">Commit revision</h2>
        <p>The current version is validated and stored as a new, read-only revision. The imported original stays unchanged.</p>
        {status === "failed" && <p className="banner warn">Structure has {errors} error(s). You can still commit; the revision is marked as failing validation.</p>}
        <label className="field">What changed<textarea autoFocus value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="e.g. Corrected issue number and caution order" /></label>
        <div className="modal-actions"><button onClick={onCancel}>Cancel</button><button className="primary" onClick={() => onCommit(msg)}>Commit revision</button></div>
      </div>
    </div>
  );
}
