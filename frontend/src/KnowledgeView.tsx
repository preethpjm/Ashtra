import { useCallback, useEffect, useState } from "react";
import { api, KFinding, KImport, KPart, KSummary, Project } from "./api";

type Section = "overview" | "breakdown" | "parts" | "tasks" | "dms" | "findings" | "sources";
type Sel = { kind: "part"; id: number } | { kind: "task"; id: string; rev: string } | { kind: "dm"; dmc: string } | null;

const SECTIONS: [Section, string][] = [
  ["overview", "Overview"], ["breakdown", "Breakdown"], ["parts", "Parts"], ["tasks", "Tasks"],
  ["dms", "Data modules"], ["findings", "Findings"], ["sources", "Sources"],
];
const RULES: Record<string, string> = {
  "maintenance-level": "Maintenance level differs", "task-duration": "Task time differs",
  "superseded-part": "Superseded part still used", "unknown-data-module": "Data module not in library",
};
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
          <div className="t2">One store of product facts shared by S1000D, S2000M and S3000L — every value keeps its source.</div></div>
        <div className="kn-actions">
          {busy && <span className="muted small">{busy}</span>}
          <button className="primary" onClick={importProject} disabled={!pid || !!busy}
            title="Read the project's valid S1000D data modules into the library">
            Add {project ? `“${project.name}”` : "project"} to library</button>
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
                      <td><button className="link" onClick={() => openDm(r.dmc)}>{r.dmc}</button>
                        <span className="muted"> · {r.resources} resources, {r.safety} warnings/cautions, {r.references} references{r.catalogue ? `, ${r.catalogue} IPD lines` : ""}</span></td></tr>)}
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
      <Sec title="Illustrated parts catalogue" n={imp.catalogue?.length}>{(imp.catalogue ?? []).map((c: any, i: number) => (
        <div key={i} className="small">Figure {c.figure} item {c.item} · indenture {c.indenture} · qty {c.qty_per_next_assy} · SMR <span className="mono">{c.smr_code}</span></div>))}</Sec>
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
