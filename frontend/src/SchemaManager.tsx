import { useEffect, useMemo, useState } from "react";
import { api, BrexEntry, Pkg, Proposal } from "./api";

const EXT = new Set([".xsd", ".dtd", ".ent", ".mod", ".elm", ".cat", ".soc"]);
/** Same rule as the server: only schema-related files are uploaded, never manuals or images. */
function wanted(f: File): boolean {
  const name = f.name.toLowerCase();
  if (["isoentities", "catalog", "asthra-package.json"].includes(name)) return true;
  const ext = name.includes(".") ? name.slice(name.lastIndexOf(".")) : "";
  if (EXT.has(ext)) return f.size <= 20 * 1024 * 1024;
  if (ext === ".xml" && /^dmc-.+-022[a-z]-/.test(name)) return f.size <= 20 * 1024 * 1024;   // BREX data modules
  return ext === ".xml" && name.includes("catalog") && f.size <= 2 * 1024 * 1024;
}
const KIND: Record<string, string> = { package: "a ready-made ASTHRA package", s1000d: "S1000D schemas", dtd: "a DTD set (ATA iSpec 2200, ATA Spec 2300 or OEM)", sgml: "an SGML DTD set (legacy ATA iSpec 2200 or OEM)", xsd: "an XSD schema set" };
const STANDARDS = ["S1000D", "S2000M", "S3000L", "S4000P", "S5000F", "S6000T", "ATA2200", "ATA2300", "OEM"];

interface Props { onClose: () => void; onChanged: () => void; say: (t: string, k?: "ok" | "err" | "info") => void }

export function SchemaManager({ onClose, onChanged, say }: Props) {
  const [pkgs, setPkgs] = useState<Pkg[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [staging, setStaging] = useState<string | null>(null);
  const [prop, setProp] = useState<Proposal | null>(null);
  const [installed, setInstalled] = useState<string[]>([]);
  const [conflict, setConflict] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [types, setTypes] = useState<Set<string>>(new Set());

  const [brex, setBrex] = useState<BrexEntry[]>([]);
  const [subs, setSubs] = useState<Record<string, string>>({});
  const refreshBrex = async () => { setBrex(await api.brexList().catch(() => [])); setSubs(await api.brexSubstitutes().catch(() => ({}))); };
  const refresh = async () => { setPkgs(await api.packages()); refreshBrex(); };
  const addBrex = async (files: FileList | null) => {
    if (!files?.length) return;
    for (const f of Array.from(files)) {
      try {
        const e = await api.brexAdd(f);
        say(`Added BREX DMC-${e.dmc} issue ${e.issue}: ${e.rules} rules.`, "ok");
      } catch (err) { say(`${f.name}: ${err instanceof Error ? err.message : String(err)}`, "err"); }
    }
    refreshBrex(); onChanged();
  };
  const removeBrex = async (e: BrexEntry) => {
    if (!window.confirm(`Remove BREX DMC-${e.dmc} issue ${e.issue}? Documents that name it will show business rules as not checked.`)) return;
    await api.brexRemove(e.dmc, e.issue); refreshBrex(); onChanged();
  };
  useEffect(() => { refresh().catch(() => {}); }, []);

  const folderTypes = useMemo(() => prop?.kind === "s1000d" ? (prop.folders?.find((f) => f.path === prop.folder)?.doc_types ?? []) : [], [prop]);
  useEffect(() => {
    if (prop?.kind === "s1000d") setTypes(new Set((prop.default_types ?? []).filter((t) => folderTypes.includes(t))));
  }, [prop?.folder, prop?.kind, folderTypes.join(",")]);

  const upload = async (files: FileList | null) => {
    if (!files || !files.length) return;
    const list = Array.from(files);
    const isZip = list.length === 1 && list[0].name.toLowerCase().endsWith(".zip");
    const send = isZip ? list : list.filter(wanted);
    if (!send.length) { setError("That folder contains no schema files (.xsd, .dtd, .ent, catalogs or an ASTHRA package)."); return; }
    setError(null); setConflict(null); setProp(null);
    setBusy(isZip ? "Reading the zip…" : `Reading ${send.length} schema files (of ${list.length} in the folder)…`);
    try {
      const r = await api.inspectSchemas(send);
      setStaging(r.staging_id); setProp(r.proposal); setInstalled(r.installed);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  const install = async (replace: boolean) => {
    if (!prop || !staging) return;
    const choice: Proposal = { ...prop, types: prop.kind === "s1000d" ? [...types] : undefined };
    setBusy("Building and checking every schema… this can take a minute."); setError(null);
    try {
      const r = await api.buildSchemas(staging, choice, replace);
      const added = (r as any).brex_added as BrexEntry[] | undefined;
      const hints = await api.xrHints(r.standard).catch(() => [] as string[]);
      say(`${r.action === "replaced" ? "Updated" : "Installed"} ${r.standard} ${r.issue}: ${r.doc_types.map((d) => d.id).join(", ")}.`
        + (added?.length ? ` Default BREX added: ${added.map((b) => `DMC-${b.dmc} issue ${b.issue}`).join(", ")}.` : "")
        + (hints.length ? " Still to do: " + hints.join(" ") : ""), hints.length ? "info" : "ok");
      setProp(null); setStaging(null); setConflict(null);
      await refresh(); onChanged();
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      if (m.includes("already installed")) setConflict(m); else setError(m);
    } finally { setBusy(null); }
  };

  const remove = async (p: Pkg) => {
    const n = p.documents ?? 0;
    const msg = n ? `${n} document(s) use ${p.standard} ${p.issue}. Remove it anyway? Those documents will be identified again when you open them.`
      : `Remove ${p.standard} ${p.issue} (${p.name})?`;
    if (!window.confirm(msg)) return;
    try { await api.removePackage(p.id, n > 0); say(`Removed ${p.standard} ${p.issue}.`, "ok"); await refresh(); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const importSet = async (f: File | undefined) => {
    if (!f) return;
    setBusy("Installing the schema set…");
    try {
      const r = await api.importSet(f);
      say(r.results.map((x) => `${x.id}: ${x.result}`).join(" · "), r.results.some((x) => x.result.startsWith("failed")) ? "err" : "ok");
      await refresh(); onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(null); }
  };

  const set = (patch: Partial<Proposal>) => setProp((p) => (p ? { ...p, ...patch } : p));
  const setType = (i: number, patch: object) => setProp((p) => p && { ...p, doc_types: p.doc_types!.map((t, k) => (k === i ? { ...t, ...patch } : t)) });
  const key = prop && prop.kind !== "package" && prop.issue ? `${(prop.standard ?? "OEM").toLowerCase()}/${prop.issue}/` : null;
  const willReplace = !!key && installed.some((k) => k.startsWith(key));

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal wide" role="dialog" aria-modal="true" aria-labelledby="sm-h" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head"><h2 id="sm-h">Schemas</h2><button className="icon" onClick={onClose} aria-label="Close">✕</button></div>

        <section className="sm-add">
          <h3>Add schemas</h3>
          <p className="muted small">Point ASTHRA at the folder you downloaded, or a zip. It finds the schema files, works out what they are, and asks only what it cannot read from the files. Manuals, PDFs and images are not uploaded.</p>
          <div className="row">
            <label className="btn">Choose folder…<input type="file" hidden {...({ webkitdirectory: "", directory: "" } as any)} multiple onChange={(e) => { upload(e.target.files); e.target.value = ""; }} /></label>
            <label className="btn">Choose zip…<input type="file" hidden accept=".zip" onChange={(e) => { upload(e.target.files); e.target.value = ""; }} /></label>
          </div>
          {busy && <p className="banner info">{busy}</p>}
          {error && <p className="banner warn">{error}</p>}

          {prop && (
            <div className="proposal">
              <p><b>Found {KIND[prop.kind]}.</b></p>
              {prop.notes.map((n, i) => <p key={i} className="muted small">{n}</p>)}

              {prop.kind === "package" && <p>{prop.standard} {prop.issue} — {prop.name} ({prop.doc_types?.length} document types)</p>}

              {prop.kind === "s1000d" && (<>
                <label className="field">Schema copy
                  <select value={prop.folder ?? ""} onChange={(e) => { const f = prop.folders!.find((x) => x.path === e.target.value)!; set({ folder: f.path, issue: f.issue }); }}>
                    {prop.folders!.map((f) => <option key={f.path} value={f.path}>{f.path} — issue {f.issue ?? "?"}{f.patch ? `, patch ${f.patch}` : ""} ({f.doc_types.length} types)</option>)}
                  </select></label>
                <label className="field">Issue<input value={prop.issue ?? ""} onChange={(e) => set({ issue: e.target.value })} placeholder="e.g. 4.1" /></label>
                <div className="field">Document types
                  <div className="checks">{folderTypes.map((t) => (
                    <label key={t}><input type="checkbox" checked={types.has(t)} onChange={() => setTypes((s) => { const n = new Set(s); n.has(t) ? n.delete(t) : n.add(t); return n; })} /> {t}</label>
                  ))}</div>
                  <span className="muted small">Procedure, Description and IPD are ticked by default. Add others any time with Replace.</span>
                </div>
                <label className="field">Entity files (for &amp;deg; &amp;mdash; …)
                  <select value={prop.entity_folder ?? ""} onChange={(e) => set({ entity_folder: e.target.value || null })}>
                    <option value="">None</option>
                    {prop.entity_folders!.map((f) => <option key={f.path} value={f.path}>{f.path} ({f.files} files)</option>)}
                  </select></label>
              </>)}

              {(prop.kind === "dtd" || prop.kind === "sgml" || prop.kind === "xsd") && (<>
                <div className="row">
                  <label className="field">Standard<select value={prop.standard ?? "OEM"} onChange={(e) => set({ standard: e.target.value })}>
                    {(prop.kind !== "xsd" ? ["ATA2200", "ATA2300", "S1000D", "OEM"] : STANDARDS).map((s) => <option key={s}>{s}</option>)}</select></label>
                  <label className="field">Issue / revision<input value={prop.issue ?? ""} onChange={(e) => set({ issue: e.target.value })} placeholder="required" /></label>
                </div>
                <label className="field">Name (optional)<input value={prop.name ?? ""} onChange={(e) => set({ name: e.target.value })} placeholder="e.g. ATR CMM DTD 3.2" /></label>
                {prop.kind === "sgml" && (<>
                  {prop.doc_types!.filter((t) => t.public_id).map((t) => (
                    <p key={t.id} className="muted small">Documents declaring <code>{t.public_id}</code> will be matched to <code>{t.id}</code>.</p>
                  ))}
                  <label className="field">Also accept documents that declare (optional, one public identifier per line)
                    <textarea rows={2} value={(prop.aliases ?? []).join("\n")} placeholder={"e.g. -//ATA-TEXT//DTD CMM-VER3-LEVEL2//EN"}
                      onChange={(e) => set({ aliases: e.target.value.split("\n") })} />
                    <span className="muted small">Use this for documents written for another version of this DTD. Every result for them carries a warning that they were checked against this version.</span>
                  </label>
                  {!!prop.missing_files?.length && <p className="banner warn">Missing: {prop.missing_files.join(", ")}. An empty placeholder is installed until you add the real file(s); entities they define are reported where used.</p>}
                </>)}
                <div className="field">Document types
                  <table className="dt-table"><tbody>{prop.doc_types!.map((t, i) => (
                    <tr key={t.id + i} className={t.problem && t.selected ? "bad" : ""}>
                      <td><input type="checkbox" checked={!!t.selected} onChange={(e) => setType(i, { selected: e.target.checked })} aria-label={`Use ${t.id}`} /></td>
                      <td><code>{t.id}</code><div className="muted small">{t.schema_file}</div></td>
                      <td>{prop.kind !== "xsd" && t.root_candidates && t.root_candidates.length > 1 ? (
                        <select value={t.root ?? ""} onChange={(e) => setType(i, { root: e.target.value || null, problem: null })}>
                          <option value="">choose root element…</option>{t.root_candidates.map((r) => <option key={r}>{r}</option>)}</select>
                      ) : <span>&lt;{t.root ?? "?"}&gt;</span>}
                        {t.namespace && <div className="muted small">{t.namespace}</div>}
                        {t.problem && <div className="leaf-err">{t.problem}</div>}</td>
                    </tr>))}</tbody></table>
                </div>
              </>)}

              <div className="modal-actions">
                <button onClick={() => { setProp(null); setStaging(null); }}>Cancel</button>
                {conflict ? (<><span className="muted small">{conflict}</span><button className="primary" onClick={() => install(true)}>Replace it</button></>)
                  : <button className="primary" disabled={!!busy || (prop.kind !== "package" && !prop.issue) || (prop.kind === "s1000d" && types.size === 0)} onClick={() => install(willReplace)}>{willReplace ? "Replace installed schemas" : "Install"}</button>}
              </div>
            </div>
          )}
        </section>

        <section>
          <h3>Installed</h3>
          {!pkgs.length && <p className="muted small">No schemas installed yet.</p>}
          <table className="pkg-table"><tbody>
            {pkgs.map((p) => (
              <tr key={p.id}>
                <td><label className="toggle" title={p.enabled ? "Enabled" : "Disabled"}><input type="checkbox" checked={p.enabled} onChange={async () => { await api.setEnabled(p.id, !p.enabled); refresh(); onChanged(); }} /><span className="track"><span className="thumb" /></span></label></td>
                <td><b>{p.standard} {p.issue}</b>{p.provenance === "synthetic" && <span className="tag synth">test schema</span>}<div className="muted small">{p.name}</div></td>
                <td className="small">{p.doc_types.map((d) => d.id).join(", ")}</td>
                <td className="small muted">{p.documents ?? 0} docs</td>
                <td className="actions-cell"><a className="link" href={api.exportPackageUrl(p.id)}>Export</a> <button className="link" onClick={() => remove(p)}>Remove</button></td>
              </tr>))}
          </tbody></table>
        </section>

        <section className="sm-set">
          <h3>Business rules (BREX)</h3>
          <p className="muted small">A BREX data module is a project's rule book on top of the schema (what is prohibited, required,
            which values and SNS codes). Documents name theirs in <code>brexDmRef</code>; a BREX may build on another, up to the
            S1000D default BREX of its issue. All BREX in the chain are applied.</p>
          {brex.length === 0 ? <p className="muted small">No BREX installed yet.</p> : (
            <table className="sm-table"><thead><tr><th>BREX</th><th>For</th><th>Rules</th><th>Builds on</th><th></th></tr></thead>
              <tbody>{brex.map((e) => {
                const parentInstalled = !e.parent_dmc || brex.some((x) => x.dmc === e.parent_dmc);
                return (
                  <tr key={e.dmc + e.issue}>
                    <td><b className="mono small">DMC-{e.dmc}</b> <span className="muted small">issue {e.issue}</span><div className="muted small">{e.title}</div></td>
                    <td className="small">S1000D {e.schema_issue ?? "?"}</td>
                    <td className="small">{e.rules}{e.sns_systems ? ` + SNS (${e.sns_systems})` : ""}</td>
                    <td className="small">{e.parent_dmc ? <><span className="mono">DMC-{e.parent_dmc}</span>
                      {!parentInstalled && <div className="warn-text">not installed — add it so its rules apply too</div>}</> : <span className="muted">top of its chain</span>}</td>
                    <td className="actions-cell"><button className="link" onClick={() => removeBrex(e)}>Remove</button></td>
                  </tr>);
              })}</tbody></table>
          )}
          {Object.keys(subs).length > 0 && (<>
            <h4 className="sm-sub">Substitutes</h4>
            <p className="muted small">Documents naming a BREX that is not installed are checked with the one you chose; every result says so.</p>
            <table className="sm-table"><tbody>{Object.entries(subs).map(([named, use]) => (
              <tr key={named}><td className="small">documents naming <span className="mono">DMC-{named}</span></td>
                <td className="small">are checked with <span className="mono">DMC-{use}</span></td>
                <td className="actions-cell"><button className="link" onClick={async () => { setSubs(await api.brexRemoveSubstitute(named)); onChanged(); }}>Remove</button></td></tr>
            ))}</tbody></table>
          </>)}
          <div className="row">
            <label className="btn">Add BREX…<input type="file" hidden multiple accept=".xml" onChange={(e) => { addBrex(e.target.files); e.target.value = ""; }} /></label>
          </div>
        </section>

        <section className="sm-set">
          <h3>Move to another system</h3>
          <p className="muted small">Export all installed schemas as one file, then import it on the new system. Identical packages are skipped; newer builds replace older ones.</p>
          <div className="row">
            <a className="btn" href={api.exportSetUrl()}>Export all schemas</a>
            <label className="btn">Import schema set…<input type="file" hidden accept=".zip" onChange={(e) => { importSet(e.target.files?.[0]); e.target.value = ""; }} /></label>
          </div>
        </section>
      </div>
    </div>
  );
}
