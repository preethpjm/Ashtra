import type { Numbering } from "./adm";
// Thin client for the local ASTHRA API. Write calls carry X-Asthra (CSRF guard).
export interface Diagnostic {
  stage: number; severity: "fatal" | "error" | "warning" | "info"; rule_id: string; message: string;
  source_file?: string; element_path?: string | null; line?: number | null; column?: number | null;
  suggestion?: string | null; reference?: string | null;
  attribute?: string | null; value?: string | null; raw_message?: string | null;
  fix?: { label: string; kind: "attr" | "text" | "insert"; attribute?: string | null; value: string;
    element?: string | null; position?: "before" | "end" | null } | null;
  category?: string | null;
  consequence_of?: string | null;
}
export interface StageResult { stage: number; status: string; note: string }
export interface Report {
  statuses: Record<"structural" | "business_rules" | "references" | "engineering", string>;
  counts: Record<string, number>; stages: StageResult[]; diagnostics: Diagnostic[];
  package_id?: string | null;
  entities?: Record<string, string>;
  rendered_xml?: string | null;
  render_note?: string | null;
}
export interface OutlineNode { name: string; path: string; line: number; label: string; children: OutlineNode[] }
export interface Outline { root: OutlineNode; truncated: boolean; count: number }
export interface Project { id: string; name: string; document_count: number; root_path: string }
export interface Doc {
  id: string; project_id: string; original_name: string; syntax: string; standard: string | null; issue: string | null;
  doc_type: string | null; package_id: string | null; sha256: string; size_bytes: number;
  identity: { display?: string; fields?: Record<string, string>; warnings?: string[] };
  identification: { status: string; notes: string[]; selection?: string;
    candidates: { package_id: string; doc_type: string }[]; compatible?: { package_id: string; doc_type: string }[] };
  last_validation: { structural_status: string } | null; has_working_copy: boolean; revision_count: number;
}
export interface Revision { id: string; number: number; message: string; structural_status: string; created_at: string; sha256: string }
export interface Pkg {
  id: string; name: string; standard: string; issue: string; provenance: string; enabled: boolean; documents?: number; checksum?: string;
  doc_types: { id: string; label: string; content_family: string }[]; licence_note: string;
}
export interface RenderProfile { profile: string; roles: Record<string, string>; labels: Record<string, string>; default_text: string;
  numbering?: Numbering | null; columns?: Record<string, string[]> }
export interface Proposal {
  kind: "package" | "s1000d" | "dtd" | "sgml" | "xsd"; standard?: string | null; issue?: string | null; name?: string | null;
  notes: string[]; path?: string;
  folders?: { path: string; issue: string | null; doc_types: string[]; files: number; patch: string }[];
  folder?: string | null; entity_folders?: { path: string; files: number; patch: string }[]; entity_folder?: string | null;
  default_types?: string[]; types?: string[]; aliases?: string[]; missing_files?: string[];
  doc_types?: { id: string; label?: string; schema_file?: string; root?: string | null; root_candidates?: string[];
    namespace?: string | null; selected?: boolean; problem?: string | null; public_id?: string | null }[];
}
export interface Inspect { staging_id: string; proposal: Proposal; installed: string[] }

export interface DocState { document: Doc; origin: string; text: string; revisions: Revision[]; render: RenderProfile }
export interface SchemaOption { package_id: string; doc_type: string; label: string; standard: string; issue: string; provenance: string; declared: boolean }
export interface Check { report: Report; outline: Outline | null }

async function call<T>(method: string, url: string, body?: unknown, form?: FormData): Promise<T> {
  const headers: Record<string, string> = { "X-Asthra": "1" };
  let payload: BodyInit | undefined;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const r = await fetch(url, { method, headers, body: payload });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* keep */ }
    throw new Error(msg);
  }
  return r.json();
}

export interface KSummary { counts: Record<string, number>; sources: { kind: string; n: number; last: string }[]; findings: number }
export interface KPart { id: number; part_number: string; manufacturer_code: string; name: string | null; part_type: string;
  tasks: number; data_modules: number; catalogue: number; superseded_by: string | null; source: string | null }
export interface KFinding { rule: string; subject: string; message: string; values: Record<string, unknown> }
export interface KImport { imported: { file: string; dmc: string; title: string; kind?: string; note?: string; [count: string]: any }[];
  skipped: { file: string; reason: string }[] }

export interface BrexEntry { dmc: string; issue: string; title: string; schema_issue: string | null; parent_dmc: string | null;
  rules: number; sns_systems: number; file: string; source_name: string; installed_at: string }

export const api = {
  projects: () => call<Project[]>("GET", "/api/projects"),
  brexList: () => call<BrexEntry[]>("GET", "/api/brex"),
  brexAdd: (file: File) => { const f = new FormData(); f.append("file", file); return call<BrexEntry>("POST", "/api/brex", undefined, f); },
  brexSubstitutes: () => call<Record<string, string>>("GET", "/api/brex/substitutes"),
  brexSetSubstitute: (named: string, use: string) => call<Record<string, string>>("POST", "/api/brex/substitutes", { named, use }),
  brexRemoveSubstitute: (named: string) => call<Record<string, string>>("DELETE", `/api/brex/substitutes/${encodeURIComponent(named)}`),
  brexRemove: (dmc: string, issue: string) => call<{ ok: boolean }>("DELETE", `/api/brex/${encodeURIComponent(dmc)}/${encodeURIComponent(issue)}`),
  kSummary: () => call<KSummary>("GET", "/api/knowledge/summary"),
  kImportProject: (pid: string) => call<KImport>("POST", `/api/knowledge/import-project/${pid}`),
  kEngineeringSet: (files: File[]) => {
    const f = new FormData();
    for (const x of files) f.append("files", x, (x as any).webkitRelativePath || x.name);
    return call<KImport>("POST", "/api/knowledge/engineering-set", undefined, f);
  },
  kEngineering: (file: File) => { const f = new FormData(); f.append("file", file); return call<KImport>("POST", "/api/knowledge/engineering", undefined, f); },
  kModels: () => call<any[]>("GET", "/api/knowledge/models"),
  kAddModel: (file: File) => { const f = new FormData(); f.append("file", file); return call<{ id: number; name: string; nodes: number; linked: number }>("POST", "/api/knowledge/models", undefined, f); },
  kDeleteModel: (id: number) => call<{ ok: boolean }>("DELETE", `/api/knowledge/models/${id}`),
  kModelStatus: (id: number) => call<Record<string, any>>("GET", `/api/knowledge/models/${id}/status`),
  kLocate: (pn: string) => call<{ model_id: number; model: string; nodes: string[] }[]>("GET", `/api/knowledge/locate?pn=${encodeURIComponent(pn)}`),
  kBike: () => call<{ loaded: boolean; reason?: string }>("POST", "/api/knowledge/examples/bike"),
  kReset: () => call<{ ok: boolean }>("DELETE", "/api/knowledge"),
  kParts: (q = "", kind = "") => call<KPart[]>("GET", `/api/knowledge/parts?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}`),
  kPart: (id: number) => call<any>("GET", `/api/knowledge/parts/${id}`),
  kBreakdown: () => call<any[]>("GET", "/api/knowledge/breakdown"),
  kTasks: () => call<any[]>("GET", "/api/knowledge/tasks"),
  kTask: (id: string, rev: string) => call<any>("GET", `/api/knowledge/tasks/${encodeURIComponent(id)}/${encodeURIComponent(rev)}`),
  kDataModules: (q = "") => call<any[]>("GET", `/api/knowledge/data-modules?q=${encodeURIComponent(q)}`),
  kDataModule: (dmc: string) => call<any>("GET", `/api/knowledge/data-modules/${encodeURIComponent(dmc)}`),
  kFindings: () => call<KFinding[]>("GET", "/api/knowledge/findings"),
  kSources: () => call<any[]>("GET", "/api/knowledge/sources"),
  createProject: (name: string) => call<Project>("POST", "/api/projects", { name }),
  documents: (pid: string) => call<Doc[]>("GET", `/api/projects/${pid}/documents`),
  importDocument: (pid: string, file: File) => { const f = new FormData(); f.append("file", file); return call<Doc>("POST", `/api/projects/${pid}/documents`, undefined, f); },
  state: (did: string) => call<DocState>("GET", `/api/documents/${did}/state`),
  check: (did: string, text: string) => call<Check>("POST", `/api/documents/${did}/check`, { text }),
  save: (did: string, text: string) => call<Check>("PUT", `/api/documents/${did}/working`, { text }),
  discard: (did: string) => call<DocState>("DELETE", `/api/documents/${did}/working`),
  commit: (did: string, message: string) => call<Revision>("POST", `/api/documents/${did}/revisions`, { message }),
  restore: (did: string, rid: string) => call<Check>("POST", `/api/documents/${did}/revisions/${rid}/restore`),
  schemaModel: (did: string) => call<import("./schemaModel").SchemaModel>("GET", `/api/documents/${did}/schema-model`),
  schemaOptions: (did: string) => call<SchemaOption[]>("GET", `/api/documents/${did}/schema-options`),
  chooseSchema: (did: string, package_id: string, doc_type_id: string) => call<DocState>("PUT", `/api/documents/${did}/schema`, { package_id, doc_type_id }),
  packages: () => call<Pkg[]>("GET", "/api/registry/packages"),
  installPackage: (file: File) => { const f = new FormData(); f.append("file", file); return call<Pkg>("POST", "/api/registry/packages", undefined, f); },
  setEnabled: (id: string, enabled: boolean) => call<Pkg>("POST", `/api/registry/packages/${id}/enabled`, { enabled }),
  inspectSchemas: (files: File[]) => {
    const f = new FormData();
    for (const file of files) f.append("files", file, (file as any).webkitRelativePath || file.name);
    return call<Inspect>("POST", "/api/registry/inspect", undefined, f);
  },
  buildSchemas: (staging_id: string, choice: Proposal, replace: boolean) =>
    call<Pkg & { action: string }>("POST", "/api/registry/build", { staging_id, choice, replace }),
  removePackage: (key: string, force: boolean) => call<{ unlinked_documents: number }>("DELETE", `/api/registry/packages/${key}?force=${force}`),
  importSet: (file: File) => { const f = new FormData(); f.append("file", file); return call<{ results: { id: string; result: string }[] }>("POST", "/api/registry/import-set", undefined, f); },
  exportPackageUrl: (key: string) => `/api/registry/packages/${key}/export`,
  exportSetUrl: () => "/api/registry/export-set",
  loadSamples: () => call<Project>("POST", "/api/samples"),
  exportUrl: (did: string, what: "current" | "original" | "revision", rid?: string) =>
    `/api/documents/${did}/export?what=${what}${rid ? `&rid=${rid}` : ""}`,
};
