import { useCallback, useEffect, useMemo, useState } from "react";
import { api, XrCoverageRow, XrItem, XrOverview, XrReview, XrRow, XrTerm, XrView, XrWaiting } from "./api";

type Say = (m: string, kind?: "ok" | "info" | "err") => void;
const VIEW_KEY = "asthra.xr.view";

/** Cross-reference: every value ASTHRA knows about an item, whatever standard it came from, kept under one
 *  generic name (S-Series common data model) and shown in the words of the standard you choose. */
export function CrossrefView({ say, openSchemas, openDocument, docsChanged }: { say: Say; openSchemas: () => void; openDocument: (id: string) => void;
  docsChanged?: () => void }) {
  const [ov, setOv] = useState<XrOverview | null>(null);
  const [tab, setTab] = useState<"coverage" | "items" | "terms">("coverage");
  const [reviewView, setReviewView] = useState<string | null>(null);
  const [covKey, setCovKey] = useState(0);
  const [view, setView] = useState<string>(() => { try { return localStorage.getItem(VIEW_KEY) ?? ""; } catch { return ""; } });
  const [busy, setBusy] = useState(false);
  const fail = useCallback((e: unknown) => say(e instanceof Error ? e.message : String(e), "err"), [say]);
  const load = useCallback(() => api.xrOverview().then((o) => {
    setOv(o);
    setView((v) => (v && o.views.some((x) => x.id === v)) ? v : (o.views[0]?.id ?? ""));
  }).catch(fail), [fail]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { try { if (view) localStorage.setItem(VIEW_KEY, view); } catch { /* private mode */ } }, [view]);

  const addModels = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      for (const f of Array.from(files)) {
        const m = await api.xrAddModel(f);
        say(`${m.label}: ${m.classes} classes, ${m.attributes} attributes${m.common ? ` (${m.common} from the common data model)` : ""}.`
          + (m.hints?.length ? " Still to do: " + m.hints.join(" ") : ""), m.hints?.length ? "info" : "ok");
      }
      await load();
      setCovKey((k) => k + 1);
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  const groups = useMemo(() => {
    const g: Record<string, XrView[]> = {};
    for (const v of ov?.views ?? []) (g[v.kind] ??= []).push(v);
    return g;
  }, [ov]);

  return (
    <div className="xr">
      <div className="xr-head">
        <div className="xr-models">
          {ov?.models.length ? ov.models.map((m) => (
            <span key={m.label} className="xr-model" title={`${m.file} · ${m.classes} classes · ${m.attributes} attributes`}>
              <b>{m.label}</b> <span className="muted">data model · {m.classes} classes</span>
              <button className="icon" aria-label={`Remove ${m.label}`} title="Remove this data model"
                onClick={async () => { if (window.confirm(`Remove the ${m.label} data model?`)) { await api.xrDeleteModel(m.label); load(); } }}>×</button>
            </span>)) : <span className="muted">No S-Series data model loaded: S1000D, ATA and BOM names come from ASTHRA's crosswalk only.</span>}
          <label className={`btn${busy ? " disabled" : ""}`} title="An S-Series UML data model exported as XMI (SX000i, S3000L, S2000M …). Its XML names connect each term to the tags of that specification.">
            {busy ? "Reading…" : "Add data model (XMI)…"}
            <input type="file" accept=".xmi,.xml" multiple hidden disabled={busy} onChange={(e) => { addModels(e.target.files); e.target.value = ""; }} />
          </label>
        </div>
        <label className="xr-view">Show as
          <select value={view} onChange={(e) => setView(e.target.value)}>
            {Object.entries(groups).map(([kind, vs]) => (
              <optgroup key={kind} label={kind === "data model" ? "S-Series data models" : kind === "crosswalk" ? "Standards (ASTHRA crosswalk)" : "Installed schemas"}>
                {vs.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
              </optgroup>))}
          </select>
        </label>
      </div>
      <div className="xr-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "coverage"} className={tab === "coverage" ? "on" : ""} onClick={() => setTab("coverage")}>Coverage</button>
        <button role="tab" aria-selected={tab === "items"} className={tab === "items" ? "on" : ""} onClick={() => setTab("items")}>Items</button>
        <button role="tab" aria-selected={tab === "terms"} className={tab === "terms" ? "on" : ""} onClick={() => setTab("terms")}>
          Generic names {ov && <em>{ov.terms}</em>}</button>
      </div>
      {tab === "coverage" ? (reviewView
          ? <Review view={reviewView} fail={fail} say={say} onClose={() => { setReviewView(null); setCovKey((k) => k + 1); }} />
          : <Coverage key={covKey} fail={fail} openSchemas={openSchemas} openDocument={openDocument} docsChanged={docsChanged} addModels={addModels} busy={busy}
            onReview={setReviewView} say={say} />)
        : tab === "items" ? <Items view={view} viewLabel={ov?.views.find((v) => v.id === view)?.label ?? view} fail={fail} />
        : <Terms ov={ov} view={view} fail={fail} />}
    </div>
  );
}

function Items({ view, viewLabel, fail }: { view: string; viewLabel: string; fail: (e: unknown) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ subject: string; key: string; label: string; name: string; detail?: string }[]>([]);
  const [sel, setSel] = useState<{ subject: string; key: string } | null>(null);
  const [item, setItem] = useState<XrItem | null>(null);
  useEffect(() => {
    const t = setTimeout(() => { if (q.trim().length >= 2) api.xrSubjects(q).then(setHits).catch(fail); else setHits([]); }, 200);
    return () => clearTimeout(t);
  }, [q, fail]);
  useEffect(() => {
    if (!sel) { setItem(null); return; }
    api.xrItem(sel.subject, sel.key, view).then(setItem).catch((e) => { setItem(null); fail(e); });
  }, [sel, view, fail]);
  return (
    <div className="xr-items">
      <div className="xr-search">
        <input placeholder="Part number, breakdown element, task, data module…" value={q} onChange={(e) => setQ(e.target.value)} />
        <ul className="xr-hits">
          {hits.map((h) => (
            <li key={`${h.subject}|${h.key}`} className={sel?.subject === h.subject && sel?.key === h.key ? "on" : ""}
              onClick={() => setSel({ subject: h.subject, key: h.key })}>
              <span className="tag">{h.subject}</span> <b className="mono">{h.label}</b>{h.detail && <span className="muted mono"> {h.detail}</span>}
              {h.name && <div className="muted small">{h.name}</div>}
            </li>))}
          {q.trim().length >= 2 && !hits.length && <li className="muted">Nothing in the library matches.</li>}
        </ul>
      </div>
      <div className="xr-item">
        {!item ? <p className="muted">Choose an item: its data from every source is listed under the field names of <b>{viewLabel || "the chosen standard"}</b>.</p> : (<>
          <h3><span className="tag">{item.subject_label}</span> <span className="mono">{item.key.replace("|", "  ·  CAGE ")}</span></h3>
          <table className="kn-table xr-table">
            <thead><tr><th>{viewLabel}</th><th>Generic name</th><th>Value</th><th>From</th></tr></thead>
            <tbody>{item.rows.map((r) => <Row key={r.term} r={r} />)}</tbody>
          </table>
          {item.not_in_view.length > 0 && (<>
            <h4 className="xr-none">Known, but {viewLabel} has no place for it</h4>
            <table className="kn-table xr-table compact"><tbody>{item.not_in_view.map((r) => <Row key={r.term} r={r} />)}</tbody></table>
          </>)}
        </>)}
      </div>
    </div>
  );
}

function Row({ r }: { r: XrRow }) {
  return (
    <tr className={r.conflict ? "xr-conflict" : ""}>
      <td className="mono">{r.name ? <span title={r.name.path ? `${r.name.path}\n(${r.name.from})` : r.name.from}>{r.name.tag}</span> : <span className="muted">—</span>}
        {r.name && <div className="muted small xr-from">{r.name.from}</div>}</td>
      <td title={r.doc}><div>{r.label}</div><div className="muted small mono">{r.term}</div></td>
      <td>{r.values.map((v, i) => <div key={i} className="xr-val">{v.value}{v.context && <span className="muted small"> · {v.context}</span>}</div>)}
        {r.conflict && <div className="xr-warn small">Sources disagree</div>}</td>
      <td>{r.values.map((v, i) => (
        <div key={i} className="xr-src small" title={v.source.document}>
          <span className="tag">{v.source.kind}</span>{v.read_as && <> read from <span className="mono">{v.read_as}</span></>}
          <span className="muted"> {v.source.document.length > 28 ? v.source.document.slice(0, 27) + "…" : v.source.document}</span>
        </div>))}</td>
    </tr>
  );
}

function Terms({ ov, view, fail }: { ov: XrOverview | null; view: string; fail: (e: unknown) => void }) {
  const [q, setQ] = useState("");
  const [core, setCore] = useState(true);
  const [rows, setRows] = useState<XrTerm[]>([]);
  const [open, setOpen] = useState<any | null>(null);
  useEffect(() => {
    const t = setTimeout(() => api.xrTerms(q, core).then(setRows).catch(fail), 200);
    return () => clearTimeout(t);
  }, [q, core, fail]);
  const cols = (ov?.views ?? []).filter((v) => v.kind !== "installed schema").map((v) => v.id);
  const show = (id: string) => api.xrTerm(id).then(setOpen).catch(fail);
  const confirm = async (s: any, path: string) => {
    const [pid, dt] = s.view.slice(4).split("|");
    try { setOpen(await api.xrConfirm(pid, dt, open.id, path)); } catch (e) { fail(e); }
  };
  return (
    <div className="xr-terms">
      <div className="tr-row">
        <input placeholder="Search generic names, tags or definitions (e.g. part number, pnr, beId)…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 520 }} />
        <label className="tr-check"><input type="checkbox" checked={core} onChange={(e) => setCore(e.target.checked)} /> Only what the library holds</label>
      </div>
      <div className="xr-matrix">
        <table className="kn-table compact">
          <thead><tr><th>Generic name</th>{cols.map((c) => <th key={c} className={c === view ? "xr-col-on" : ""}>{c}</th>)}</tr></thead>
          <tbody>{rows.map((t) => (
            <tr key={t.id} onClick={() => show(t.id)} className={open?.id === t.id ? "on" : ""} title={t.doc}>
              <td><div>{t.label}{t.key && <span className="tag">key</span>}{t.common && !t.id.startsWith("ASTHRA:") && <span className="tag">common</span>}</div>
                <div className="muted small mono">{t.id}</div></td>
              {cols.map((c) => <td key={c} className={`mono${c === view ? " xr-col-on" : ""}`}>{t.names[c] ?? <span className="muted">—</span>}</td>)}
            </tr>))}</tbody>
        </table>
      </div>
      {open && (
        <aside className="xr-term">
          <button className="icon kn-close" aria-label="Close" onClick={() => setOpen(null)}>×</button>
          <h3>{open.label}</h3>
          <p className="mono small">{open.id}</p>
          {open.doc && <p>{open.doc}</p>}
          {open.uof && <p className="muted small">{open.uof}{open.class_doc ? ` — ${open.class_doc}` : ""}</p>}
          <h4>In each standard</h4>
          <table className="kn-table compact"><tbody>
            {Object.entries(open.names as Record<string, any>).map(([k, n]) => (
              <tr key={k}><td>{k}</td><td className="mono">{n.path || (n.all ?? [n.tag]).join("  |  ")}</td><td className="muted small">{n.from}</td></tr>))}
          </tbody></table>
          <h4>In the installed schemas</h4>
          <table className="kn-table compact"><tbody>
            {open.schemas.map((s: any) => (
              <tr key={s.view}><td>{s.label}</td>
                <td className="mono">{s.path ?? <span className="muted">no place found</span>}</td>
                <td className="small">{s.path ? <span className="muted">{s.from}</span> : null}
                  <button className="link" onClick={() => { const p = window.prompt(`Path of “${open.label}” in ${s.label} (from the root, e.g. a/b/@c). Empty to clear.`, s.path ?? ""); if (p !== null) confirm(s, p.trim()); }}>
                    {s.from === "confirmed" ? "change" : "set"}</button></td></tr>))}
          </tbody></table>
        </aside>
      )}
    </div>
  );
}

const STATUS_TEXT = { ok: "Ready", review: "Check placements", missing: "Something missing" } as const;

function Coverage({ fail, openSchemas, openDocument, addModels, busy, onReview, say, docsChanged }: {
  fail: (e: unknown) => void; openSchemas: () => void; openDocument: (id: string) => void; docsChanged?: () => void;
  addModels: (f: FileList | null) => void; busy: boolean; onReview: (view: string) => void; say: Say;
}) {
  const [cov, setCov] = useState<{ standards: XrCoverageRow[]; waiting: XrWaiting[] } | null>(null);
  const [working, setWorking] = useState(false);
  const reload = useCallback(() => api.xrCoverage().then(setCov).catch(fail), [fail]);
  useEffect(() => { reload(); }, [reload]);
  const assign = async (ids: string[], package_id: string, doc_type: string, text: string) => {
    setWorking(true);
    try {
      const r = await api.xrAssignSchemas(ids.map((doc_id) => ({ doc_id, package_id, doc_type })));
      say(`${r.assigned} document(s) now use ${text}.` + (r.failed.length ? ` ${r.failed.length} could not: ${r.failed[0].error}` : ""),
        r.failed.length ? "err" : "ok");
      await reload();
    } catch (e) { fail(e); } finally { setWorking(false); }
  };
  const remove = async (w: XrWaiting) => {
    const where = w.ids.length > 1 ? `all ${w.ids.length} copies of ${w.name} (${w.projects.join(", ")})` : `${w.name} (${w.projects.join(", ")})`;
    if (!window.confirm(`Remove ${where} from ${w.projects.length > 1 ? "their projects" : "its project"}?\n\n` +
      "Its working copy, revisions and validation history go too. What the knowledge library already learned from it stays.")) return;
    setWorking(true);
    try {
      const r = await api.deleteDocuments(w.ids);
      say(`Removed ${r.deleted.length} document(s).` + (r.failed.length ? ` ${r.failed.length} could not be removed: ${r.failed[0].error}` : ""),
        r.failed.length ? "err" : "ok");
      docsChanged?.();
      await reload();
    } catch (e) { fail(e); } finally { setWorking(false); }
  };
  if (!cov) return <p className="muted">Checking what is installed…</p>;
  return (
    <div className="xr-cov">
      <p className="muted xr-cov-intro">Every standard ASTHRA has met — in installed schemas, data models, the library or your projects' documents —
        with what it needs to validate documents and to place and read their data.</p>
      <table className="kn-table xr-cov-table">
        <thead><tr><th>Standard</th><th>Schema (XSD / DTD)</th><th>Data model (XMI)</th><th>Data</th><th>To do</th></tr></thead>
        <tbody>{cov.standards.map((r) => (
          <tr key={r.standard} className={`xr-cov-${r.status}`}>
            <td><b>{r.label}</b><div className={`xr-pill ${r.status}`}>{STATUS_TEXT[r.status]}</div></td>
            <td>{r.schemas.length ? r.schemas.map((s) => (
              <div key={s.view} className="small">{s.label}{s.error ? <span className="xr-warn"> · {s.error}</span>
                : <span className="muted"> · places {s.placed} of {s.of} library names{s.confirmed ? `, ${s.confirmed} confirmed` : ""}</span>}
                {!!s.review && <button className="link" onClick={() => onReview(s.view)}> · review {s.review}</button>}
                {!s.review && !s.error && <button className="link" onClick={() => onReview(s.view)}> · open</button>}</div>))
              : r.standard === "ENGINEERING BOM" ? <span className="muted small">not needed (CSV / Excel / JSON)</span>
              : r.hub ? <span className="muted small">optional — only to exchange {r.label} data itself</span>
              : <span className="xr-warn small">not installed</span>}
              {r.unidentified.length > 0 && r.schemas.length > 0 && <div className="xr-warn small">No installed schema fits {r.unidentified.join(", ")}</div>}
              {(r.unchosen?.length ?? 0) > 0 && <div className="muted small">No schema chosen yet for {r.unchosen!.join(", ")}</div>}</td>
            <td>{r.model ? <span className="small">{r.model.label} · {r.model.classes} classes
                {r.hub && <div className="xr-hub">Reference model: its common data model (SX002D) is the generic layer every standard is translated through</div>}</span>
              : r.s_series ? <span className="xr-warn small">not loaded</span>
              : <span className="muted small">{r.crosswalk ? "none published — ASTHRA crosswalk" : "none"}</span>}</td>
            <td className="small">{r.documents ? `${r.documents} document(s)` : ""}{r.documents && r.library ? " · " : ""}{r.library ? `${r.library} library source(s)` : ""}
              {!r.documents && !r.library && <span className="muted">—</span>}</td>
            <td>{r.actions.map((a, i) => (
              <div key={i} className="xr-action">
                {a.do === "choose_schema" ? <button className={a.certain ? "primary" : ""} disabled={working}
                    onClick={() => assign(a.ids ?? [], a.package_id!, a.doc_type!, a.label.replace(/^Use | for \d+ document\(s\)$/g, ""))}>{a.label}</button>
                  : a.do === "install_schema" ? <button onClick={openSchemas}>{a.label}</button>
                  : a.do === "add_model" ? <label className={`btn${busy ? " disabled" : ""}`}>{a.label}
                      <input type="file" accept=".xmi,.xml" multiple hidden disabled={busy} onChange={(e) => { addModels(e.target.files); e.target.value = ""; }} /></label>
                  : <button onClick={() => a.view && onReview(a.view)}>{a.label}</button>}
                {a.why && <span className="muted small"> {a.why}</span>}
              </div>))}
              {r.actions.some((a) => a.do !== "review") && r.where && (
                <div className="small"><a href={r.where.url} target="_blank" rel="noreferrer noopener">Where to get {r.where.what} ↗</a></div>)}
              {!r.actions.length && <span className="muted small">nothing</span>}</td>
          </tr>))}</tbody>
      </table>
      {cov.waiting.length > 0 && (<>
        <h4>Documents waiting for a schema or data model</h4>
        <ul className="xr-waiting">{cov.waiting.map((w) => (
          <li key={w.id}><button className="link" onClick={() => openDocument(w.id)}>{w.name}</button>
            <span className="muted small"> ({w.projects.join(", ")}{w.ids.length > w.projects.length ? ` · ${w.ids.length} copies` : ""})</span>
            <div className="small">{w.message}
              {w.choose && <> <button className="link" disabled={working} onClick={() => assign(w.ids, w.choose!.package_id, w.choose!.doc_type, w.choose!.text)}>
                Use {w.choose.text}{w.ids.length > 1 ? ` for all ${w.ids.length}` : ""}</button></>}
              {" · "}<button className="link danger" disabled={working} onClick={() => remove(w)}>
                Remove{w.ids.length > 1 ? ` all ${w.ids.length}` : ""}</button></div></li>))}</ul>
      </>)}
    </div>
  );
}

function Review({ view, fail, say, onClose }: { view: string; fail: (e: unknown) => void; say: Say; onClose: () => void }) {
  const [rv, setRv] = useState<XrReview | null>(null);
  const [pick, setPick] = useState<Record<string, string>>({});
  const [showMissing, setShowMissing] = useState(false);
  useEffect(() => { api.xrReview(view).then((r) => { setRv(r); setPick({}); }).catch(fail); }, [view, fail]);
  if (!rv) return <p className="muted">Reading the schema…</p>;
  const [pid, dt] = view.slice(4).split("|");
  const chosen = (r: XrReview["rows"][number]) => pick[r.term] ?? r.placement?.path ?? r.candidates[0] ?? "";
  const save = async (items: { term: string; path: string }[]) => {
    if (!items.length) return;
    try {
      const r = await api.xrConfirmMany(pid, dt, items); setRv(r); setPick({});
      say(`${items.length} placement(s) saved for ${rv.label}` + (r.applied_elsewhere ? ` and applied to ${r.applied_elsewhere} other schema(s) of the same standard where the place exists.` : "."), "ok");
    }
    catch (e) { fail(e); }
  };
  const toReview = rv.rows.filter((r) => r.status === "review");
  const missing = rv.rows.filter((r) => r.status === "missing");
  const suggested = missing.filter((r) => r.candidates.length);
  const done = rv.rows.filter((r) => ["confirmed", "ok", "none"].includes(r.status));
  const line = (r: XrReview["rows"][number], hint: string) => (
    <tr key={r.term}>
      <td><div>{r.label}</div><div className="muted small">{r.group} · <span className="mono">{r.term}</span></div></td>
      <td><select className="mono" value={chosen(r)} onChange={(e) => setPick({ ...pick, [r.term]: e.target.value })}>
        {[...new Set([r.placement?.path, ...(r.placement?.others ?? []), ...r.candidates].filter(Boolean) as string[])].map((p) => <option key={p} value={p}>{p}</option>)}
        <option value="-">— not in this schema —</option></select>
        <div className="muted small">{hint}</div></td>
      <td className="xr-review-btns"><button onClick={() => save([{ term: r.term, path: chosen(r) }])} disabled={!chosen(r)}>Confirm</button>
        <button className="ghost" onClick={() => save([{ term: r.term, path: "-" }])}>Not here</button></td>
    </tr>);
  return (
    <div className="xr-review">
      <div className="tr-row"><button className="ghost" onClick={onClose}>← Coverage</button>
        <h3 style={{ margin: 0 }}>{rv.label}</h3>
        <span className="muted small">Confirmations also apply to the other issues and document types of this standard where the same place exists. ·
          {" "}{rv.counts.confirmed} confirmed · {rv.counts.ok} sure · {rv.counts.review} to review · {rv.counts.missing} not found · {rv.counts.none} not in this schema</span></div>
      {toReview.length > 0 ? (<>
        <h4>Found by name only, or in several places — please check</h4>
        <table className="kn-table compact"><tbody>{toReview.map((r) => line(r, r.placement?.from ?? ""))}</tbody></table>
        <div className="tr-row"><button className="primary" onClick={() => save(toReview.map((r) => ({ term: r.term, path: chosen(r) })))}>Confirm all {toReview.length} as shown</button></div>
      </>) : <p className="muted">Nothing to review: every placement found is certain or confirmed.</p>}
      {suggested.length > 0 && (<>
        <h4>Not found, but these places look likely</h4>
        <table className="kn-table compact"><tbody>{suggested.map((r) => line(r, "suggested from similar names"))}</tbody></table>
      </>)}
      <button className="link" onClick={() => setShowMissing(!showMissing)}>{showMissing ? "Hide" : "Show"} placed and confirmed ({done.length})</button>
      {showMissing && <table className="kn-table compact"><tbody>{done.map((r) => (
        <tr key={r.term}><td>{r.label}</td><td className="mono small">{r.status === "none" ? "— not in this schema —" : r.placement?.path}</td>
          <td className="muted small">{r.status === "none" ? "confirmed" : r.placement?.from}</td></tr>))}</tbody></table>}
    </div>
  );
}
