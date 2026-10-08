import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api, KFinding, KImport, KPart, KSummary, Project } from "./api";
import { STATUS_COLOR, STATUS_LABEL } from "./modelColors";

const ModelViewer = lazy(() => import("./ModelViewer"));

type Section = "overview" | "breakdown" | "parts" | "tasks" | "dms" | "models" | "findings" | "sources";
type Sel = { kind: "part"; id: number } | { kind: "task"; id: string; rev: string } | { kind: "dm"; dmc: string } | null;

const SECTIONS: [Section, string][] = [
  ["overview", "Overview"], ["breakdown", "Breakdown"], ["parts", "Parts"], ["tasks", "Tasks"],
  ["dms", "Data modules"], ["models", "3D models"], ["findings", "Findings"], ["sources", "Sources"],
];
const RULES: Record<string, string> = {
  "maintenance-level": "Maintenance level differs", "task-duration": "Task time differs",
  "superseded-part": "Superseded part still used", "unknown-data-module": "Data module not in library",
  "catalogue-part": "Parts lists: part number differs", "catalogue-quantity": "Parts lists: quantity differs",
  "catalogue-indenture": "Parts lists: indenture differs", "catalogue-effectivity": "Parts lists: effectivity differs",
  "catalogue-cage": "Parts lists: CAGE differs", "catalogue-missing": "Parts lists: item missing",
  "bom-quantity": "BOM and parts list: quantity differs", "bom-missing": "In the parts list, not in the BOM",
  "catalogue-missing-bom-line": "In the BOM, not in the parts list", "identity-suggestion": "Same part? (no CAGE)",
  "3d-quantity": "3D model and MBOM: quantity differs", "3d-fuzzy": "3D item matched with doubt", "3d-ambiguous": "3D item: which BOM line?",
  "3d-unmatched": "3D item not in the MBOM", "3d-mbom-only": "MBOM lines not in the 3D model",
};
/** What one import read, in words: only the counts that apply to that kind of source. */
function importFacts(r: Record<string, any>): string {
  const n = (k: string, one: string, many = one + "s") => (r[k] ? `${r[k]} ${r[k] === 1 ? one : many}` : "");
  const out = [n("tasks", "task"), n("lines", "BOM line"), n("structure", "parent-child link"), n("resources", "tool/consumable", "tools/consumables"),
    n("safety", "warning/caution", "warnings/cautions"), n("references", "reference"), n("catalogue", "parts-list line"),
    n("properties", "engineering attribute"), n("vendors", "vendor"), n("bulletins", "service bulletin"),
    n("links", "3D item"), n("findings", "finding"), n("nodes", "3D node"), n("linked", "linked to a part", "linked to parts")].filter(Boolean);
  if (!out.length && r.parts) out.push(n("parts", "part"));
  return (out.join(", ") || "recorded; it lists no parts, tools or warnings") + (r.note ? ` (${r.note})` : "") +
    (r.warnings?.length ? ` · ${r.warnings.length} warning(s): ${r.warnings.slice(0, 3).join("; ")}` : "");
}

const SRC_LABEL: Record<string, string> = { "ATA-CMM": "ATA IPL", "S1000D-DM": "S1000D IPD", S2000M: "S2000M", "ENG-BOM": "BOM", "ENG-3D": "3D ↔ MBOM" };
const KIND_LABEL: Record<string, string> = { "support-equipment": "Support equipment", consumable: "Supplies", spare: "Spares", part: "Part",
  component: "Component" };

/** The knowledge library: one store of product facts that S1000D, S2000M and S3000L share. */
export function KnowledgeView({ projects, pid, say }: { projects: Project[]; pid: string | null;
  say: (m: string, kind?: "ok" | "info" | "err") => void }) {
  const [section, setSection] = useState<Section>("overview");
  const [summary, setSummary] = useState<KSummary | null>(null);
  const [listed, setListed] = useState<{ key: string; rows: any[] }>({ key: "", rows: [] });
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [sel, setSel] = useState<Sel>(null);
  const [loaded, setLoaded] = useState<{ key: string; data: any } | null>(null);
  const [busy, setBusy] = useState("");
  const [lastImport, setLastImport] = useState<KImport | null>(null);
  const project = projects.find((p) => p.id === pid);

  const refreshSummary = useCallback(() => api.kSummary().then(setSummary).catch(() => setSummary(null)), []);
  useEffect(() => { refreshSummary(); }, [refreshSummary]);

  // lists: rows are shown only for the section (and filter) they were loaded for
  const listKey = `${section}|${q}|${kind}`;
  const rows = listed.key === listKey ? listed.rows : [];
  useEffect(() => {
    let alive = true;
    const set = (r: any[]) => { if (alive) setListed({ key: listKey, rows: r }); };
    if (section === "parts") api.kParts(q, kind).then(set);
    else if (section === "breakdown") api.kBreakdown().then(set);
    else if (section === "tasks") api.kTasks().then(set);
    else if (section === "dms") api.kDataModules(q).then(set);
    else if (section === "findings") api.kFindings().then(set);
    else if (section === "sources") api.kSources().then(set);
    else if (section === "models") api.kModels().then(set);
    else set([]);
    return () => { alive = false; };
  }, [section, q, kind, summary]); // eslint-disable-line react-hooks/exhaustive-deps

  // detail: shown only when it belongs to the current selection (never another item's data in the wrong layout)
  const selKey = !sel ? "" : sel.kind === "part" ? `part:${sel.id}` : sel.kind === "task" ? `task:${sel.id}:${sel.rev}` : `dm:${sel.dmc}`;
  useEffect(() => {
    if (!sel) return;
    let alive = true;
    const p = sel.kind === "part" ? api.kPart(sel.id) : sel.kind === "task" ? api.kTask(sel.id, sel.rev) : api.kDataModule(sel.dmc);
    p.then((data) => { if (alive) setLoaded({ key: selKey, data }); })
     .catch(() => { if (alive) setLoaded({ key: selKey, data: { missing: true } }); });
    return () => { alive = false; };
  }, [selKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const detail = loaded && loaded.key === selKey ? loaded.data : null;

  const go = (s: Section) => { setSection(s); setQ(""); setKind(""); setSel(null); };
  const openPart = (id: number) => { setSection("parts"); setSel({ kind: "part", id }); };
  const openPartByNumber = async (pn: string) => {
    const hit = (await api.kParts(pn)).find((p) => p.part_number === pn);
    if (hit) openPart(hit.id); else say(`${pn} is not in the library.`, "info");
  };
  const openDm = (dmc: string) => { setSection("dms"); setSel({ kind: "dm", dmc }); };
  const openTask = (id: string, rev: string) => { setSection("tasks"); setSel({ kind: "task", id, rev }); };

  const importProject = async () => {
    if (!pid) return;
    setBusy("Reading the project's data modules…");
    try {
      const r = await api.kImportProject(pid);
      setLastImport(r);
      say(`Added ${r.imported.length} data module(s) to the library${r.skipped.length ? `; ${r.skipped.length} skipped (see Overview)` : ""}.`, r.imported.length ? "ok" : "info");
      await refreshSummary();
    } catch (e) { say(String(e), "err"); } finally { setBusy(""); }
  };
  /** One or more engineering files, or a whole folder (BOM, reconciliation JSON, GLB …). Only the file types ASTHRA
   *  reads are sent: a folder may also hold STEP files or drawings that are large and not needed here. */
  const importEngineering = async (list: FileList | null) => {
    const all = Array.from(list ?? []);
    const files = all.filter((f) => /\.(csv|tsv|txt|xlsx|xlsm|json|glb|zip)$/i.test(f.name));
    if (!files.length) { say(all.length ? "No BOM, JSON or GLB file in that selection." : "Nothing selected.", "info"); return; }
    const mb = files.reduce((n, f) => n + f.size, 0) / 1e6;
    setBusy(`Reading ${files.length} file(s)${mb > 5 ? ` (${mb.toFixed(0)} MB)` : ""}…`);
    try {
      const r = await api.kEngineeringSet(files);
      setLastImport(r); setSection("overview");
      const n3d = r.imported.filter((x) => x.kind === "3D model").length;
      say(`Imported ${r.imported.length} file(s)${n3d ? `, ${n3d} 3D model(s)` : ""}${r.skipped.length ? `; ${r.skipped.length} skipped (see Overview)` : ""}.`,
        r.imported.length ? "ok" : "info");
      await refreshSummary();
    } catch (e) { say(String(e), "err"); } finally { setBusy(""); }
  };
  const loadBike = async () => {
    setBusy("Loading the S-Series Bike example…");
    try {
      const r = await api.kBike();
      say(r.loaded ? "Bike example (S-Series UF2024) added to the library." : `Bike example: ${r.reason}.`, r.loaded ? "ok" : "info");
      await refreshSummary();
    } finally { setBusy(""); }
  };
  const reset = async () => {
    if (!window.confirm("Remove everything from the knowledge library? Documents in your projects are not affected.")) return;
    await api.kReset(); setSel(null); setLastImport(null); await refreshSummary(); say("Knowledge library emptied.", "info");
  };

  const counts = summary?.counts ?? {};
  const empty = summary && Object.entries(counts).every(([k, v]) => k === "sources" || v === 0);

  return (
    <div className="knowledge">
      <header className="kn-top">
        <div className="kn-title"><div className="t1">Knowledge library</div>
          <div className="t2">One store of product facts shared by S1000D, ATA iSpec 2200, S2000M, S3000L and engineering BOMs — every value keeps its source.</div></div>
        <div className="kn-actions">
          {busy && <span className="muted small">{busy}</span>}
          <button className="primary" onClick={importProject} disabled={!pid || !!busy}
            title="Read the project's S1000D data modules, ATA manuals (SGML or XML) and S2000M data into the library">
            Add {project ? `“${project.name}”` : "project"} to library</button>
          <span className="kn-split">
            <label className={`btn${busy ? " disabled" : ""}`}
              title="Engineering files: BOM (CSV, Excel, JSON), STEP ↔ MBOM reconciliation (JSON), 3D model (GLB), or a zip of them. Select several at once.">
              Import engineering data…
              <input type="file" multiple accept=".csv,.tsv,.txt,.xlsx,.xlsm,.json,.glb,.zip" hidden disabled={!!busy}
                onChange={(e) => { const f = e.target.files; importEngineering(f); e.target.value = ""; }} /></label>
            <label className={`btn${busy ? " disabled" : ""}`} title="A whole folder, e.g. the one the STEP→GLB / MBOM tool writes (GLB + JSON); other files in it are ignored">
              Folder…
              <input type="file" hidden disabled={!!busy} {...({ webkitdirectory: "", directory: "" } as any)}
                onChange={(e) => { const f = e.target.files; importEngineering(f); e.target.value = ""; }} /></label>
          </span>
          <button onClick={loadBike} disabled={!!busy} title="The S-Series User Forum 2024 Bike example, front brake system">Load Bike example</button>
          <button className="ghost" onClick={reset} disabled={!!busy}>Empty library…</button>
        </div>
      </header>

      <nav className="kn-nav" aria-label="Library sections">
        {SECTIONS.map(([s, label]) => (
          <button key={s} className={section === s ? "on" : ""} onClick={() => go(s)}>
            <span>{label}</span>
            {s === "parts" && <em>{counts["parts"] ?? 0}</em>}
            {s === "breakdown" && <em>{counts["breakdown elements"] ?? 0}</em>}
            {s === "tasks" && <em>{counts["tasks"] ?? 0}</em>}
            {s === "dms" && <em>{counts["data modules"] ?? 0}</em>}
            {s === "findings" && <em className={summary?.findings ? "warn" : ""}>{summary?.findings ?? 0}</em>}
          </button>
        ))}
      </nav>

      <section className={`kn-main${sel ? " with-detail" : ""}`}>
        {section === "overview" && (
          <div className="kn-overview">
            {empty && (
              <div className="kn-empty">
                <h3>The library is empty</h3>
                <p>Add a project's S1000D data modules (only structurally valid ones are read), or load the S-Series
                  Bike example to see how procedures, parts, tasks and the IPC connect.</p>
              </div>
            )}
            <div className="kn-cards">
              {Object.entries(counts).filter(([k]) => k !== "sources").map(([k, v]) => (
                <div key={k} className="kn-card"><div className="n">{v}</div><div className="l">{k}</div></div>
              ))}
              <button className={`kn-card link${summary?.findings ? " warn" : ""}`} onClick={() => go("findings")}>
                <div className="n">{summary?.findings ?? 0}</div><div className="l">consistency findings</div></button>
            </div>
            {!!summary?.sources.length && (
              <><h4>Sources</h4>
                <table className="kn-table compact"><thead><tr><th>Kind</th><th>Imports</th><th>Last</th></tr></thead>
                  <tbody>{summary.sources.map((s) => <tr key={s.kind}><td>{s.kind}</td><td>{s.n}</td><td className="muted">{s.last?.replace("T", " ").slice(0, 16)}</td></tr>)}</tbody></table></>
            )}
            {lastImport && (
              <><h4>Last import</h4>
                <table className="kn-table compact"><thead><tr><th>File</th><th>Result</th></tr></thead>
                  <tbody>
                    {lastImport.imported.map((r) => <tr key={r.file}><td>{r.file}</td>
                      <td>{r.kind && <span className="kn-kind">{r.kind}</span>}
                        {(!r.kind || r.kind === "S1000D" || r.kind === "ATA iSpec 2200")
                          ? <button className="link" onClick={() => openDm(r.dmc)}>{r.dmc}</button> : <span>{r.dmc}</span>}
                        <span className="muted"> · {importFacts(r)}</span></td></tr>)}
                    {lastImport.skipped.map((r) => <tr key={r.file} className="skipped"><td>{r.file}</td><td className="muted">skipped: {r.reason}</td></tr>)}
                  </tbody></table></>
            )}
          </div>
        )}

        {(section === "parts" || section === "dms") && (
          <div className="kn-filter">
            <input placeholder={section === "parts" ? "Search part number or name…" : "Search DMC or title…"} value={q} onChange={(e) => setQ(e.target.value)} />
            {section === "parts" && (
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="">All kinds</option><option value="spare">Parts and spares</option>
                <option value="consumable">Supplies</option><option value="support-equipment">Support equipment</option>
              </select>
            )}
          </div>
        )}

        {section === "parts" && (
          <table className="kn-table"><thead><tr><th>Part number</th><th>CAGE</th><th>Name</th><th>Kind</th><th>Tasks</th><th>DMs</th><th>IPC</th><th></th></tr></thead>
            <tbody>{(rows as KPart[]).map((p) => (
              <tr key={p.id} className={sel?.kind === "part" && sel.id === p.id ? "on" : ""} onClick={() => setSel({ kind: "part", id: p.id })}>
                <td className="mono">{p.part_number}</td><td className="mono">{p.manufacturer_code || <span className="muted">—</span>}</td>
                <td>{p.name}</td><td className="muted">{KIND_LABEL[p.part_type] ?? p.part_type}</td>
                <td>{p.tasks || ""}</td><td>{p.data_modules || ""}</td><td>{p.catalogue || ""}</td>
                <td>{p.superseded_by && <span className="tag warn">→ {p.superseded_by}</span>}</td></tr>))}</tbody></table>
        )}

        {section === "breakdown" && (
          <table className="kn-table"><thead><tr><th>BEI</th><th>Name</th><th>Type</th><th>LSA</th><th>Realised by</th><th>DMs</th><th>Tasks</th></tr></thead>
            <tbody>{rows.map((b) => (
              <tr key={b.bei + b.revision}><td className="mono" style={{ paddingLeft: 8 + depthOf(b, rows) * 16 }}>{b.bei}</td>
                <td>{b.name}</td><td className="muted">{b.be_type}</td><td>{b.lsa_candidate && <span className={`tag ${b.lsa_candidate}`}>{b.lsa_candidate}</span>}</td>
                <td className="mono small">{(b.parts ?? "").split(", ").filter(Boolean).map((p: string) => (
                  <button key={p} className="link" onClick={() => openPartByNumber(p.split(" (")[0])}>{p}</button>))}</td>
                <td>{b.data_modules || ""}</td><td>{b.tasks || ""}</td></tr>))}</tbody></table>
        )}

        {section === "tasks" && (
          <table className="kn-table"><thead><tr><th>Task</th><th>Rev</th><th>Name</th><th>Type</th><th>ML</th><th>Subtasks</th><th>Covers</th><th>Source</th></tr></thead>
            <tbody>{rows.map((t) => (
              <tr key={t.id + t.revision} className={sel?.kind === "task" && sel.id === t.id && sel.rev === t.revision ? "on" : ""}
                onClick={() => openTask(t.id, t.revision)}>
                <td className="mono">{t.id}</td><td>{t.revision}</td><td>{t.name}</td><td className="muted">{t.task_type}</td>
                <td>{t.maintenance_level}</td><td>{t.subtasks}</td><td className="mono small">{t.requirements}</td><td className="muted small">{t.source}</td></tr>))}</tbody></table>
        )}

        {section === "dms" && (
          <table className="kn-table"><thead><tr><th>Data module code</th><th>Title</th><th>Info code</th><th>Resources</th><th>Safety</th><th>Refs</th></tr></thead>
            <tbody>{rows.map((d) => (
              <tr key={d.dmc} className={sel?.kind === "dm" && sel.dmc === d.dmc ? "on" : ""} onClick={() => setSel({ kind: "dm", dmc: d.dmc })}>
                <td className="mono">{d.dmc}</td><td>{d.title}</td><td>{d.info_code}</td><td>{d.resources || ""}</td><td>{d.safety || ""}</td><td>{d.refs || ""}</td></tr>))}</tbody></table>
        )}

        {section === "findings" && (
          <div className="kn-findings">
            {!rows.length && <p className="muted">No inconsistencies between the sources in the library.</p>}
            {(rows as KFinding[]).map((f, i) => (
              <div key={i} className="kn-finding">
                <div className="rule">{RULES[f.rule] ?? f.rule}</div>
                <div className="msg">{f.message}</div>
                {Object.keys(f.values).length > 0 && <div className="vals">{Object.entries(f.values).map(([k, v]) => <span key={k}><b>{k.toUpperCase()}</b> {String(v)}</span>)}</div>}
              </div>))}
          </div>
        )}

        {section === "models" && <ModelsSection rows={rows} say={say} reload={refreshSummary} openPart={openPart} busy={!!busy} />}
        {section === "sources" && (
          <table className="kn-table"><thead><tr><th>Kind</th><th>Document</th><th>Issue</th><th>Schema</th><th>Imported</th><th>Note</th></tr></thead>
            <tbody>{rows.map((s) => <tr key={s.id}><td>{s.kind}</td><td className="mono small">{s.document}</td><td>{s.issue}</td><td className="small">{s.schema}</td>
              <td className="muted small">{s.imported_at?.replace("T", " ").slice(0, 16)}</td><td className="muted small">{s.note}</td></tr>)}</tbody></table>
        )}
      </section>

      {sel && (
        <aside className="kn-detail">
          <button className="icon kn-close" aria-label="Close" onClick={() => setSel(null)}>×</button>
          {!detail ? <p className="muted">Loading…</p> : detail.missing ? <p className="muted">Not in the library.</p>
            : sel.kind === "part" ? <PartDetail d={detail} openDm={openDm} openTask={openTask} openPart={openPartByNumber} />
            : sel.kind === "task" ? <TaskDetail d={detail} openDm={openDm} />
            : <DmDetail d={detail} openDm={openDm} openPart={openPart} openTask={openTask} />}
        </aside>
      )}
    </div>
  );
}

function depthOf(b: any, all: any[]): number {
  let d = 0, p = b.parent_bei;
  while (p && d < 8) { d += 1; p = all.find((x) => x.bei === p)?.parent_bei; }
  return d;
}

function Sec({ title, children, n }: { title: string; children: React.ReactNode; n?: number }) {
  if (n === 0) return null;
  return <div className="kd-sec"><h5>{title}{n !== undefined && <em>{n}</em>}</h5>{children}</div>;
}

function PartDetail({ d, openDm, openTask, openPart }: { d: any; openDm: (s: string) => void; openTask: (i: string, r: string) => void; openPart: (pn: string) => void }) {
  const p = d.part, imp = d.impact ?? {};
  return (
    <>
      <div className="kd-head"><div className="kd-k">{KIND_LABEL[p.part_type] ?? p.part_type}</div>
        <div className="kd-t mono">{p.part_number}</div><div className="kd-s">{p.name}</div>
        <div className="kd-meta"><span>CAGE <b className="mono">{p.manufacturer_code || "—"}</b></span>
          {p.source_kind && <span>from {p.source_kind} · {p.source_document}</span>}</div></div>
      {(imp.superseded_by ?? []).map((s: any) => (
        <div key={s.part_number} className="kd-alert">Superseded by <button className="link mono" onClick={() => openPart(s.part_number)}>{s.part_number}</button>
          {s.change_id && <> under change <b>{s.change_id}</b></>}</div>))}
      <Sec title="Breakdown elements" n={imp.breakdown_elements?.length}>{(imp.breakdown_elements ?? []).map((b: string) => <div key={b} className="mono small">{b}</div>)}</Sec>
      <Sec title="Tasks that use it" n={imp.tasks?.length}>{(imp.tasks ?? []).map((t: any) => (
        <button key={t.id + t.revision} className="kd-row" onClick={() => openTask(t.id, t.revision)}><span className="mono">{t.id} rev {t.revision}</span><span>{t.name}</span></button>))}</Sec>
      <Sec title="Required by data modules" n={d.impact?.required_by_dms?.length}>{(d.impact?.required_by_dms ?? []).map((r: any) => (
        <button key={r.dmc + r.kind} className="kd-row" onClick={() => openDm(r.dmc)}><span className="mono">{r.dmc}</span><span className="muted">{KIND_LABEL[r.kind] ?? r.kind}</span></button>))}</Sec>
      <Sec title="Data modules affected if it changes" n={imp.data_modules?.length}>{(imp.data_modules ?? []).map((m: string) => (
        <button key={m} className="kd-row" onClick={() => openDm(m)}><span className="mono">{m}</span></button>))}</Sec>
      {imp.catalogue_lines ? (
        <Sec title="Parts lists" n={imp.catalogue_lines.length}>{imp.catalogue_lines.map((c: any, i: number) => (
          <div key={i} className="small"><span className="kn-kind">{SRC_LABEL[c.kind] ?? c.kind}</span> Figure {c.figure} item {String(c.item).replace(/^0+/, "")}{c.item_variant}
            {" "}· indenture {c.indenture} · qty {c.qty_per_next_assy}{c.usable_on_code ? ` · effectivity ${c.usable_on_code}` : ""}
            <span className="muted"> · {c.document}</span></div>))}</Sec>
      ) : (
        <Sec title="Illustrated parts catalogue" n={imp.catalogue?.length}>{(imp.catalogue ?? []).map((c: any, i: number) => (
          <div key={i} className="small">Figure {c.figure} item {c.item} · indenture {c.indenture} · qty {c.qty_per_next_assy} · SMR <span className="mono">{c.smr_code}</span></div>))}</Sec>
      )}
      {(d.models ?? []).length > 0 && <Part3D models={d.models} />}
      {(imp.cad ?? []).length > 0 && (
        <Sec title="3D model items" n={imp.cad.length}>{imp.cad.map((c: any, i: number) => (
          <div key={i} className="small"><span className="kn-dot" style={{ background: STATUS_COLOR[cadStatus(c)] }} />
            <span className="mono">{c.cad_name}</span> · {c.cad_label} · × {c.cad_qty}
            <span className="muted"> · {STATUS_LABEL[cadStatus(c)]}{c.confidence != null && c.confidence < 1 ? ` (${Math.round(c.confidence * 100)} %)` : ""}</span></div>))}</Sec>
      )}
      <Sec title="Same part number elsewhere" n={imp.same_number?.length}>{(imp.same_number ?? []).map((u: any) => (
        <div key={u.id} className="small">CAGE <b className="mono">{u.manufacturer_code || "none"}</b> · {u.name}
          <span className="muted"> · {SRC_LABEL[u.kind] ?? u.kind} {u.document}</span></div>))}</Sec>
      <Sec title="Engineering attributes" n={imp.properties?.length}>{(imp.properties ?? []).map((u: any) => (
        <div key={u.name + u.document} className="small">{u.name}: <b>{u.value}</b><span className="muted"> · {u.document}</span></div>))}</Sec>
      <Sec title="Used in" n={imp.used_in?.length}>{(imp.used_in ?? []).map((u: any) => (
        <button key={u.part_number} className="kd-row" onClick={() => openPart(u.part_number)}><span className="mono">{u.part_number}</span><span className="muted">× {u.quantity}</span></button>))}</Sec>
      <Sec title="Contains" n={d.impact?.contains?.length}>{(d.impact?.contains ?? []).map((u: any) => (
        <button key={u.part_number} className="kd-row" onClick={() => openPart(u.part_number)}><span className="mono">{u.part_number}</span><span className="muted">{u.name} × {u.quantity}</span></button>))}</Sec>
      <Sec title="Training" n={imp.training?.length}>{(imp.training ?? []).map((t: any, i: number) => <div key={i} className="small">{t.task_id}: {t.objective}</div>)}</Sec>
    </>
  );
}

function TaskDetail({ d, openDm }: { d: any; openDm: (s: string) => void }) {
  const p = d.procedure;
  const ref = (s: string) => {
    const m = /^(.*) \(refer to ([^)]+)\)$/.exec(s);
    return m ? <>{m[1]} <button className="link mono small" onClick={() => openDm(m[2])}>{m[2]}</button></> : s;
  };
  return (
    <>
      <div className="kd-head"><div className="kd-k">Task (S3000L)</div><div className="kd-t">{p.task}</div>
        <div className="kd-meta"><span>Maintenance level <b>{p.maintenance_level}</b></span><span>{p.persons} person(s)</span>
          <span>{p.skill_levels.join(", ")} · {p.trades.join(", ")}</span><span>{p.duration_minutes} min</span></div></div>
      {!!d.documented_by?.length && <Sec title="Documented by">{d.documented_by.map((x: any) => (
        <button key={x.dmc} className="kd-row" onClick={() => openDm(x.dmc)}><span className="mono">{x.dmc}</span><span>{x.title}</span></button>))}</Sec>}
      <p className="muted small">The procedure's preliminary requirements and steps, derived from the task analysis:</p>
      <Sec title="Support equipment" n={p.support_equipment.length}><ul>{p.support_equipment.map((x: string) => <li key={x}>{x}</li>)}</ul></Sec>
      <Sec title="Supplies" n={p.supplies.length}><ul>{p.supplies.map((x: string) => <li key={x}>{x}</li>)}</ul></Sec>
      <Sec title="Spares" n={p.spares.length}><ul>{p.spares.map((x: string) => <li key={x}>{x}</li>)}</ul></Sec>
      <Sec title="Conditions" n={p.conditions.length}><ul>{p.conditions.map((x: string) => <li key={x}>{x}</li>)}</ul></Sec>
      {p.warnings.map((w: string) => <div key={w} className="kd-adm warning"><b>WARNING</b>{w}</div>)}
      {p.cautions.map((w: string) => <div key={w} className="kd-adm caution"><b>CAUTION</b>{w}</div>)}
      <Sec title="Steps" n={p.steps.length}><ol>{p.steps.map((x: string, i: number) => <li key={i}>{ref(x)}</li>)}</ol></Sec>
    </>
  );
}

function DmDetail({ d, openDm, openPart, openTask }: { d: any; openDm: (s: string) => void; openPart: (id: number) => void; openTask: (i: string, r: string) => void }) {
  const props = Object.fromEntries((d.properties ?? []).map((p: any) => [p.name, p.value]));
  const byKind = (k: string) => (d.resources ?? []).filter((r: any) => r.kind === k);
  return (
    <>
      <div className="kd-head"><div className="kd-k">Data module (S1000D) · info code {d.item.info_code}</div>
        <div className="kd-t mono">{d.item.dmc}</div><div className="kd-s">{d.item.title}</div>
        <div className="kd-meta"><span>Issue {d.item.issue}</span><span>BEI <b className="mono">{d.item.bei}</b></span>
          {d.breakdown?.[0] && <span>{d.breakdown[0].name}</span>}</div></div>
      {Object.keys(props).length > 0 && <div className="kd-meta boxed">
        {props.maintenance_level && <span>Maintenance level <b>{props.maintenance_level}</b></span>}
        {props.persons && <span>{props.persons} person(s)</span>}
        {props.skill_level && <span>Skill <b>{props.skill_level}</b></span>}
        {props.trade && <span>Trade <b>{props.trade}</b></span>}
        {props.estimated_minutes && <span>{props.estimated_minutes} min</span>}</div>}
      <Sec title="Documents" n={d.documents?.length}>{(d.documents ?? []).map((x: any) => (
        <button key={x.kind + x.id} className="kd-row" onClick={() => x.kind === "task" && x.revision && openTask(x.id, x.revision)}>
          <span className="mono">{x.kind === "task" ? `task ${x.id}${x.revision ? " rev " + x.revision : ""}` : `${x.kind} ${x.id}`}</span><span>{x.name}</span></button>))}</Sec>
      {(["support-equipment", "consumable", "spare"] as const).map((k) => (
        <Sec key={k} title={KIND_LABEL[k]} n={byKind(k).length}>{byKind(k).map((r: any, i: number) => (
          <div key={i} className="kd-row static"><span>{r.name}{r.quantity ? ` × ${r.quantity}${r.unit ? " " + r.unit : ""}` : ""}</span>
            {r.part_id ? <button className="link mono small" onClick={() => openPart(r.part_id)}>{r.manufacturer_code ? r.manufacturer_code + " · " : ""}{r.part_number}</button>
              : <span className="muted small">no part number</span>}</div>))}</Sec>))}
      {(d.safety ?? []).map((s: any, i: number) => <div key={i} className={`kd-adm ${s.kind}`}><b>{s.kind.toUpperCase()}</b>{s.text}</div>)}
      <Sec title="Refers to" n={d.references?.length}>{(d.references ?? []).map((r: any) => (
        <button key={r.ref_dmc} className="kd-row" onClick={() => openDm(r.ref_dmc)}><span className="mono">{r.ref_dmc}</span><span>{r.title ?? <span className="muted">not in library</span>}</span></button>))}</Sec>
      <Sec title="Referred to by" n={d.referenced_by?.length}>{(d.referenced_by ?? []).map((r: any, i: number) => {
        const m = /^task (\S+) rev (\S+)$/.exec(r.dmc);
        return <button key={i} className="kd-row" onClick={() => (m ? openTask(m[1], m[2]) : openDm(r.dmc))}><span className="mono">{r.dmc}</span><span>{r.title}</span></button>;
      })}</Sec>
      <Sec title="Illustrated parts data" n={d.catalogue?.length}>{(d.catalogue ?? []).map((c: any, i: number) => (
        <div key={i} className="small">Fig {c.figure} item {c.item} · <span className="mono">{c.part_number}</span> {c.name} · qty {c.qty_per_next_assy}</div>))}</Sec>
    </>
  );
}

const cadStatus = (c: any) => (c.quantity_match === 0 ? "quantity" : c.status === "matched" ? "matched" : c.status === "unmatched" ? "unmatched" : "fuzzy");

/** The part in its 3D model(s), highlighted. */
function Part3D({ models }: { models: { model_id: number; model: string; nodes: string[] }[] }) {
  const [i, setI] = useState(0);
  const m = models[Math.min(i, models.length - 1)];
  return (
    <div className="kd-sec"><h5>3D <em>{m.nodes.length}</em></h5>
      {models.length > 1 && <select value={i} onChange={(e) => setI(+e.target.value)}>{models.map((x, k) => <option key={k} value={k}>{x.model}</option>)}</select>}
      <Suspense fallback={<div className="mv-msg">Loading 3D viewer…</div>}>
        <ModelViewer url={`/api/knowledge/models/${m.model_id}/file`} highlight={m.nodes} height={230} />
      </Suspense>
      <div className="muted small">{m.model}: {m.nodes.slice(0, 6).join(", ")}{m.nodes.length > 6 ? " …" : ""}</div>
    </div>
  );
}

/** 3D models (GLB) in the library: upload, view coloured by how each item matches the BOM, pick a part. */
function ModelsSection({ rows, say, reload, openPart, busy }: { rows: any[]; say: (m: string, k?: "ok" | "info" | "err") => void;
  reload: () => void; openPart: (id: number) => void; busy: boolean }) {
  const [cur, setCur] = useState<number | null>(null);
  const [status, setStatus] = useState<Record<string, any> | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const model = rows.find((r) => r.id === cur) ?? rows[0];
  useEffect(() => {
    setStatus(null); setPicked(null);
    if (model) api.kModelStatus(model.id).then(setStatus).catch(() => setStatus({}));
  }, [model?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const upload = async (f: File) => {
    setUploading(true);
    try {
      const r = await api.kAddModel(f);
      say(`${f.name}: ${r.nodes} item(s), ${r.linked} linked to parts in the library.`, "ok");
      setCur(r.id); reload();
    } catch (e) { say(String(e), "err"); } finally { setUploading(false); }
  };
  const counts: Record<string, number> = {};
  Object.values(status ?? {}).forEach((v: any) => { counts[v.status] = (counts[v.status] ?? 0) + 1; });
  const info = picked && status ? status[picked] : null;
  return (
    <div className="kn-models">
      <div className="kn-models-bar">
        <label className={`btn${busy || uploading ? " disabled" : ""}`} title="A 3D model as GLB (binary glTF), e.g. converted from STEP">
          {uploading ? "Reading…" : "Add 3D model (GLB)…"}
          <input type="file" accept=".glb" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload(f); }} /></label>
        {rows.length > 0 && <select value={model?.id ?? ""} onChange={(e) => setCur(+e.target.value)}>
          {rows.map((r) => <option key={r.id} value={r.id}>{r.name} · {r.nodes} items{r.reconciliation ? ` · coloured by ${r.reconciliation}` : ""}</option>)}</select>}
        {model && <button className="ghost" onClick={async () => { if (window.confirm(`Remove the 3D model ${model.name} from the library?`)) {
          await api.kDeleteModel(model.id); setCur(null); reload(); } }}>Remove</button>}
      </div>
      {!model ? <p className="muted">No 3D model yet. Add a GLB here, or import the reconciliation tool's folder (GLB + JSON) with Import engineering data → Folder…; the model's items are then linked to parts and coloured by how they match the BOM.</p> : (
        <div className="kn-model-grid">
          <Suspense fallback={<div className="mv-msg">Loading 3D viewer…</div>}>
            <ModelViewer key={model.id} url={`/api/knowledge/models/${model.id}/file`} status={status ?? {}} picked={picked} onPick={setPicked} height="62vh" />
          </Suspense>
          <div className="kn-model-side">
            <h5>Items</h5>
            {Object.keys(STATUS_COLOR).filter((k) => counts[k]).map((k) => (
              <div key={k} className="small"><span className="kn-dot" style={{ background: STATUS_COLOR[k] }} />{STATUS_LABEL[k]} <b>{counts[k]}</b></div>))}
            <div className="small muted"><span className="kn-dot" style={{ background: "#c9ced6" }} />Not linked {Math.max(0, model.nodes - Object.keys(status ?? {}).length)}</div>
            <h5>Picked</h5>
            {!picked ? <p className="muted small">Click a part in the model.</p> : (
              <div className="small"><div className="mono"><b>{picked}</b></div>
                {info ? <>{info.part_number && <div>Part <span className="mono">{info.part_number}</span> · {info.name}</div>}
                  <div className="muted">{STATUS_LABEL[info.status]}</div>
                  {info.part_id && <button className="link" onClick={() => openPart(info.part_id)}>Open the part</button>}</>
                  : <div className="muted">Not linked to a part in the library.</div>}
              </div>)}
          </div>
        </div>
      )}
    </div>
  );
}
