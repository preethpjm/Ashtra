import { useEffect, useState } from "react";
import { api, BrexEntry } from "./api";

/** Shown when business-rule validation finds that the document's BREX is not installed:
 *  add the file, or use an installed BREX instead (remembered and reported on every result). */
export function BrexPrompt({ named, onDone, onClose, say }: {
  named: string; onDone: () => void; onClose: () => void;
  say: (t: string, k?: "ok" | "err" | "info") => void;
}) {
  const [installed, setInstalled] = useState<BrexEntry[]>([]);
  const [use, setUse] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.brexList().then((l) => { setInstalled(l); if (l.length) setUse(l[0].dmc); }).catch(() => setInstalled([]));
  }, []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  const addFile = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    try {
      const e = await api.brexAdd(file);
      say(e.dmc.toUpperCase() === named.toUpperCase()
        ? `Added the document's BREX DMC-${e.dmc} (${e.rules} rules). Checking business rules…`
        : `Added DMC-${e.dmc} (${e.rules} rules) — but the document names DMC-${named}. Choose it below to use it instead.`,
        e.dmc.toUpperCase() === named.toUpperCase() ? "ok" : "info");
      if (e.dmc.toUpperCase() === named.toUpperCase()) { onDone(); return; }
      const l = await api.brexList(); setInstalled(l); setUse(e.dmc);
    } catch (err) { say(err instanceof Error ? err.message : String(err), "err"); }
    finally { setBusy(false); }
  };
  const substitute = async () => {
    if (!use) return;
    setBusy(true);
    try {
      await api.brexSetSubstitute(named, use);
      say(`Documents naming DMC-${named} are now checked with DMC-${use}. Each result says so.`, "ok");
      onDone();
    } catch (err) { say(err instanceof Error ? err.message : String(err), "err"); }
    finally { setBusy(false); }
  };
  const chosen = installed.find((e) => e.dmc === use);

  return (
    <>
      <div className="menu-veil" onClick={onClose} />
      <div className="brex-prompt" role="dialog" aria-label="BREX not installed">
        <div className="bp-head">Business rules: BREX not installed</div>
        <p>This document names <b className="mono">DMC-{named}</b> as its business rules (BREX). It is not installed,
          so its business rules cannot be checked yet.</p>

        <div className="bp-option">
          <div className="bp-k">Add the BREX file</div>
          <label className="btn primary">Choose file…
            <input type="file" hidden accept=".xml" disabled={busy} onChange={(e) => { addFile(e.target.files?.[0]); e.target.value = ""; }} /></label>
          <span className="muted small">the data module <span className="mono">DMC-{named}_…</span>.xml</span>
        </div>

        <div className="bp-option">
          <div className="bp-k">…or use an installed BREX instead</div>
          {installed.length === 0 ? <p className="muted small">No BREX is installed yet — add one first.</p> : (<>
            <select value={use} onChange={(e) => setUse(e.target.value)} disabled={busy}>
              {installed.map((e) => <option key={e.dmc + e.issue} value={e.dmc}>DMC-{e.dmc} (S1000D {e.schema_issue ?? "?"}, {e.rules} rules) — {e.title}</option>)}
            </select>
            {chosen?.parent_dmc && !installed.some((x) => x.dmc === chosen.parent_dmc) &&
              <p className="warn-text">It builds on DMC-{chosen.parent_dmc}, which is not installed: its rules are checked only partly.</p>}
            <div className="row"><button onClick={substitute} disabled={busy || !use}>Use this BREX</button>
              <span className="muted small">for every document that names DMC-{named}; each result says it was a substitute</span></div>
          </>)}
        </div>

        <div className="bp-foot"><button className="ghost" onClick={onClose}>Not now</button></div>
      </div>
    </>
  );
}
