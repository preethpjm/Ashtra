import { useCallback, useEffect, useMemo, useState } from "react";
import { api, TrBinding, TrBindingView, TrResult, TrRules, TrSchema, TrSource } from "./api";

type Say = (m: string, kind?: "ok" | "info" | "err") => void;
const lines = (s: string) => s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

/** The translator: a parts list from the engineering BOM (or from another standard's parts list) written into a
 *  document of whatever schema is installed, through a binding proposed from that schema and confirmed here. */
export function TranslateView({ pid, say, openDocument }: { pid: string | null; say: Say; openDocument: (id: string) => void }) {
  const [sources, setSources] = useState<{ assemblies: any[]; parts_lists: any[] } | null>(null);
  const [rules, setRules] = useState<TrRules | null>(null);
  const [from, setFrom] = useState<"engineering" | "catalogue">("engineering");
  const [tops, setTops] = useState<string[]>([]);
  const [plist, setPlist] = useState("");
  const [preview, setPreview] = useState<{ records: any[]; excluded: any[] } | null>(null);
  const [schemas, setSchemas] = useState<TrSchema[]>([]);
  const [targets, setTargets] = useState<any[]>([]);
  const [target, setTarget] = useState("");
  const [schemaKey, setSchemaKey] = useState("");
  const [view, setView] = useState<TrBindingView | null>(null);
  const [draft, setDraft] = useState<TrBinding | null>(null);
  const [result, setResult] = useState<TrResult | null>(null);
  const [busy, setBusy] = useState("");
  const fail = useCallback((e: unknown) => say(e instanceof Error ? e.message : String(e), "err"), [say]);

  useEffect(() => {
    api.trSources().then((s) => {
      setSources(s);
      setTops((t) => t.length ? t : s.assemblies.slice(0, 1).map((a) => a.part_number));
      setPlist((p) => p || (s.parts_lists[0] ? `${s.parts_lists[0].source_id}|${s.parts_lists[0].figure}` : ""));
      if (!s.assemblies.length && s.parts_lists.length) setFrom("catalogue");
    }).catch(fail);
    api.trRules().then(setRules).catch(fail);
    api.trSchemas().then(setSchemas).catch(fail);
  }, [fail]);
  useEffect(() => { if (pid) api.trTargets(pid).then(setTargets).catch(fail); else setTargets([]); }, [pid, fail]);

  const tgt = targets.find((t) => t.id === target);
  // the schema whose binding is shown: the target document's, or one chosen from the installed schemas
  useEffect(() => { if (tgt) setSchemaKey(`${tgt.package_id}|${tgt.doc_type}`); }, [tgt]);
  const loadBinding = useCallback((key: string, record?: string) => {
    if (!key) { setView(null); setDraft(null); return; }
    const [p, d] = key.split("|");
    api.trBinding(p, d, record).then((v) => { setView(v); setDraft(v.binding); }).catch(fail);
  }, [fail]);
  useEffect(() => loadBinding(schemaKey), [schemaKey, loadBinding]);

  const source: TrSource | null = from === "engineering"
    ? (tops.length ? { kind: "engineering", tops } : null)
    : (plist ? { kind: "catalogue", source_id: Number(plist.split("|")[0]), figure: plist.split("|")[1], renumber_figure: true } : null);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    try { await fn(); } catch (e) { fail(e); } finally { setBusy(""); }
  };
  const doPreview = () => run("preview", async () => {
    if (!source || !rules) return;
    setPreview(await api.trPreview(source, rules));
    api.trSaveRules(rules).catch(() => {});
  });
  const saveBinding = () => run("save", async () => {
    if (!view || !draft) return;
    const v = await api.trSaveBinding(view.package_id, view.doc_type, draft);
    setView(v); setDraft(v.binding);
    setSchemas(await api.trSchemas());
    say("Binding saved: ASTHRA now writes and reads this schema's parts lists this way.", "ok");
  });
  const repropose = () => run("propose", async () => {
    if (!view) return;
    if (view.saved) await api.trForgetBinding(view.package_id, view.doc_type);
    loadBinding(`${view.package_id}|${view.doc_type}`);
    setSchemas(await api.trSchemas());
  });
  const generate = () => run("generate", async () => {
    if (!source || !rules || !target) return;
    api.trSaveRules(rules).catch(() => {});
    const r = await api.trGenerate(target, source, rules, draft ?? undefined);
    setResult(r);
    if (r.document) {
      say(`${r.report.written} lines written into ${r.document.name} · structure ${r.document.structural}.`, r.document.structural === "passed" ? "ok" : "info");
      if (pid) api.trTargets(pid).then(setTargets).catch(() => {});
    } else say(r.report.problems[0] ?? "Nothing was written.", "err");
  });

  const dirty = useMemo(() => JSON.stringify(view?.binding) !== JSON.stringify(draft), [view, draft]);
  const setField = (f: string, k: "path" | "format", v: string) => setDraft((d) => {
    if (!d) return d;
    const fields = { ...d.fields };
    const cur = { ...(fields[f] ?? { path: "" }), [k]: v, confidence: undefined };
    if (k === "path" && !v) delete fields[f]; else fields[f] = cur;
    return { ...d, fields };
  });
  const R = rules;
  const setR = (patch: Partial<TrRules>) => setRules((r) => (r ? { ...r, ...patch } : r));

  return (
    <div className="tr">
      <p className="muted tr-intro">
        Build a parts list from engineering data, or take one already in the library, and write it into a document of any
        installed schema. Where each value goes is read from the schema itself; check it once, save it, and it is used for
        writing and for reading that kind of document back into the library.
      </p>

      <div className="tr-step">
        <h3><span className="tr-n">1</span> From</h3>
        <div className="tr-row">
          <label><input type="radio" checked={from === "engineering"} onChange={() => setFrom("engineering")} /> Engineering assembly</label>
          <label><input type="radio" checked={from === "catalogue"} onChange={() => setFrom("catalogue")} /> Parts list in the library</label>
        </div>
        {from === "engineering" ? (
          sources?.assemblies.length ? (
            <div className="tr-picks">
              {sources.assemblies.map((a) => (
                <label key={a.part_number} className={tops.includes(a.part_number) ? "on" : ""}>
                  <input type="checkbox" checked={tops.includes(a.part_number)}
                    onChange={(e) => setTops((t) => e.target.checked ? [...t, a.part_number] : t.filter((x) => x !== a.part_number))} />
                  <b className="mono">{a.part_number}</b> {a.name} <span className="muted">· {a.children} lines{a.cage ? ` · ${a.cage}` : ""}</span>
                </label>))}
              <p className="muted small">Several assemblies (e.g. pre- and post-SB) make one list: items 1, 1A … with effectivity codes A, B …</p>
            </div>
          ) : <p className="muted">No engineering BOM in the library yet: use “Import engineering data…”.</p>
        ) : (
          sources?.parts_lists.length ? (
            <select value={plist} onChange={(e) => setPlist(e.target.value)}>
              {sources.parts_lists.map((p) => <option key={`${p.source_id}|${p.figure}`} value={`${p.source_id}|${p.figure}`}>
                {p.kind} · {p.document} · figure {p.figure || "–"} · {p.lines} lines</option>)}
            </select>
          ) : <p className="muted">No parts lists in the library yet.</p>
        )}

        {R && (
          <details className="tr-rules">
            <summary>Rules {R.exclude.length + R.exclude_property.length > 0 && <span className="tag">{R.exclude.length + R.exclude_property.length} exclusions</span>}</summary>
            <div className="tr-grid">
              <label>Leave out part numbers or names matching (one pattern per line)
                <textarea rows={3} value={R.exclude.join("\n")} placeholder={"^MIL-PRF-\nPROCESS SPEC"} onChange={(e) => setR({ exclude: lines(e.target.value) })} /></label>
              <label>Leave out parts with property (name=value per line)
                <textarea rows={3} value={R.exclude_property.join("\n")} placeholder="Make/Buy=Process" onChange={(e) => setR({ exclude_property: lines(e.target.value) })} /></label>
              <label>CAGEs not written as vendor codes
                <input value={R.omit_cage.join(", ")} placeholder="own CAGE, 96906 …" onChange={(e) => setR({ omit_cage: lines(e.target.value.toUpperCase()) })} /></label>
              <label>Units not written
                <input value={R.omit_unit.join(", ")} onChange={(e) => setR({ omit_unit: lines(e.target.value.toUpperCase()) })} /></label>
              <label>Item numbers
                <select value={R.numbering} onChange={(e) => setR({ numbering: e.target.value })}>
                  <option value="find_no">from the BOM find numbers</option><option value="step10">10, 20, 30 …</option></select></label>
              <label>Figure
                <input value={R.figure} onChange={(e) => setR({ figure: e.target.value })} style={{ width: "6em" }} /></label>
              <label className="tr-check"><input type="checkbox" checked={R.skip_zero_quantity} onChange={(e) => setR({ skip_zero_quantity: e.target.checked })} /> Leave out quantity 0 (alternates)</label>
              <label className="tr-check"><input type="checkbox" checked={R.uppercase_names} onChange={(e) => setR({ uppercase_names: e.target.checked })} /> Names in capitals (ATA)</label>
            </div>
          </details>
        )}
        <div className="tr-row"><button onClick={doPreview} disabled={!source || !!busy}>{busy === "preview" ? "Building…" : "Preview the list"}</button></div>
        {preview && (
          <div className="tr-preview">
            <table className="kn-table compact">
              <thead><tr><th>Fig</th><th>Item</th><th>Ind</th><th>Part number</th><th>CAGE</th><th>Name</th><th>Qty</th><th>Eff</th></tr></thead>
              <tbody>{preview.records.map((r, i) => (
                <tr key={i}><td>{r.figure}</td><td className="mono">{r.item}{r.item_variant}</td><td>{".".repeat(Math.max(0, (r.indenture ?? 1) - 1))}{r.indenture}</td>
                  <td className="mono">{r.part_number}</td><td className="mono">{r.cage}</td><td>{r.name}</td><td>{r.top ? "RF" : r.quantity}</td><td>{r.effectivity}</td></tr>))}</tbody>
            </table>
            {preview.excluded.length > 0 && (<>
              <h4>Left out ({preview.excluded.length})</h4>
              <ul className="tr-excluded">{preview.excluded.map((e, i) => <li key={i}><b className="mono">{e.part_number}</b> {e.name} — <span className="muted">{e.reason}</span></li>)}</ul>
            </>)}
          </div>
        )}
      </div>

      <div className="tr-step">
        <h3><span className="tr-n">2</span> Into</h3>
        <div className="tr-row">
          <label>Document
            <select value={target} onChange={(e) => { setTarget(e.target.value); setResult(null); }}>
              <option value="">{pid ? "— choose a document of the project —" : "— open a project first —"}</option>
              {targets.map((t) => <option key={t.id} value={t.id}>{t.name} · {t.standard} {t.doc_type}</option>)}
            </select></label>
          <label>or a schema, to check its binding
            <select value={schemaKey} onChange={(e) => { setTarget(""); setSchemaKey(e.target.value); }}>
              <option value="">—</option>
              {schemas.map((s) => <option key={`${s.package_id}|${s.doc_type}`} value={`${s.package_id}|${s.doc_type}`}>
                {s.standard} {s.issue} · {s.label}{s.saved ? " ✓" : s.record ? "" : " (no parts list)"}</option>)}
            </select></label>
        </div>

        {view && draft && (
          <div className="tr-binding">
            <div className="tr-bhead">
              <span className={`tag ${view.saved && !dirty ? "ok" : "warn"}`}>{view.saved && !dirty ? "Saved binding" : dirty ? "Edited, not saved" : "Proposed from the schema"}</span>
              <span className="muted small">{view.schema_kind?.toUpperCase()} · {view.package_id} · {view.doc_type}</span>
            </div>
            {!draft.record ? <p className="muted">{(draft.problems ?? []).join(" ")}</p> : (<>
              <div className="tr-row">
                <label>One line is
                  <select value={draft.record} onChange={(e) => loadBinding(`${view.package_id}|${view.doc_type}`, e.target.value)}>
                    {view.candidates.map((c) => <option key={c.record} value={c.record}>&lt;{c.record}&gt; · {c.fields} fields found</option>)}
                  </select></label>
                <span className="mono small tr-path">{(draft.container ?? []).join(" / ")} / <b>{draft.record}</b></span>
              </div>
              <table className="kn-table compact tr-fields">
                <thead><tr><th>Field</th><th>Written in</th><th>As</th><th></th></tr></thead>
                <tbody>
                  {!draft.fields.figure && (
                  <tr><td>Figure (on a parent)</td>
                    <td colSpan={2}>{(
                      <select value={draft.group ? `${draft.group.level}|${draft.group.attr}` : ""} onChange={(e) => {
                        const v = e.target.value; const [lv, at] = v.split("|");
                        setDraft({ ...draft, group: v ? { level: Number(lv), element: (draft.container ?? [])[Number(lv)], attr: at, field: "figure" } : null });
                      }}>
                        <option value="">— one list, no figures —</option>
                        {view.group_options.map((o) => <option key={`${o.level}|${o.attr}`} value={`${o.level}|${o.attr}`}>{o.element}/@{o.attr}</option>)}
                      </select>)}</td><td>{draft.group?.confidence != null && <Conf c={draft.group.confidence} />}</td></tr>)}
                  {view.concept.fields.filter((f) => !(f.id === "figure" && draft.group && !draft.fields.figure)).map((f) => {
                    const spec = draft.fields[f.id];
                    return (
                      <tr key={f.id} className={spec ? "" : "tr-unset"}>
                        <td>{f.label}</td>
                        <td><input className="mono" list={`tr-slots`} value={spec?.path ?? ""} placeholder="not written"
                          onChange={(e) => setField(f.id, "path", e.target.value)} /></td>
                        <td><select value={spec?.format ?? ""} disabled={!spec} onChange={(e) => setField(f.id, "format", e.target.value)}>
                          {view.formats.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select></td>
                        <td>{spec?.confidence != null && <Conf c={spec.confidence} />}</td>
                      </tr>);
                  })}
                </tbody>
              </table>
              <datalist id="tr-slots">{view.slots.map((s) => <option key={s.path} value={s.path}>{s.required ? "required" : ""}</option>)}</datalist>
              {view.check.length > 0 && <ul className="tr-problems">{view.check.map((p, i) => <li key={i}>{p}</li>)}</ul>}
              <div className="tr-row">
                <button onClick={saveBinding} disabled={!!busy || (view.saved && !dirty)}>Save binding</button>
                <button className="ghost" onClick={repropose} disabled={!!busy}>{view.saved ? "Forget and propose again" : "Propose again"}</button>
                <span className="muted small">Saved bindings also let “Import from project” read this kind of document.</span>
              </div>
            </>)}
          </div>
        )}
      </div>

      <div className="tr-step">
        <h3><span className="tr-n">3</span> Generate</h3>
        <p className="muted small">The document's parts list is replaced (per figure); everything else stays exactly as it was. The result is a new document
          next to the original, validated against its schema.</p>
        <div className="tr-row"><button className="primary" onClick={generate} disabled={!source || !target || !draft?.record || !!busy}>
          {busy === "generate" ? "Writing…" : "Generate"}</button></div>
        {result && (
          <div className="tr-result">
            <p><b>{result.report.written}</b> of {result.records} lines written
              {result.report.groups.map((g) => <span key={g.figure} className="tag">figure {g.figure || "–"}: {g.lines} (was {g.replaced})</span>)}</p>
            {result.report.problems.length > 0 && <ul className="tr-problems">{result.report.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>}
            {result.report.warnings.length > 0 && <details><summary>{result.report.warnings.length} warnings</summary>
              <ul className="small">{result.report.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
            {result.document && (
              <p className="tr-doc">
                <span className={`tag ${result.document.structural === "passed" ? "ok" : "warn"}`}>structure {result.document.structural}</span>
                <b>{result.document.name}</b>
                <button onClick={() => openDocument(result.document!.id)}>Open</button>
              </p>)}
            {result.document && result.document.errors.length > 0 && <ul className="tr-problems">{result.document.errors.map((p, i) => <li key={i}>{p}</li>)}</ul>}
          </div>
        )}
      </div>
    </div>
  );
}

function Conf({ c }: { c: number }) {
  return <span className={`tr-conf ${c >= 0.9 ? "hi" : c >= 0.6 ? "mid" : "lo"}`} title="How sure the proposal is, from the names in the schema">{Math.round(c * 100)}%</span>;
}
