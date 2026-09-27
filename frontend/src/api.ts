// Thin client for the local ASTHRA API. Write calls carry X-Asthra (CSRF guard).
export interface Diagnostic {
  stage: number; severity: "fatal" | "error" | "warning" | "info"; rule_id: string; message: string;
  source_file?: string; element_path?: string | null; line?: number | null; column?: number | null;
  suggestion?: string | null; reference?: string | null;
  attribute?: string | null; value?: string | null; raw_message?: string | null;
  fix?: { label: string; kind: "attr" | "text"; attribute?: string | null; value: string } | null;
}
export interface StageResult { stage: number; status: string; note: string }
export interface Report {
  statuses: Record<"structural" | "business_rules" | "references" | "engineering", string>;
  counts: Record<string, number>; stages: StageResult[]; diagnostics: Diagnostic[];
  package_id?: string | null;
  entities?: Record<string, string>;
  rendered_xml?: string | null;
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
export interface RenderProfile { profile: string; roles: Record<string, string>; labels: Record<string, string>; default_text: string }
export interface Proposal {
  kind: "package" | "s1000d" | "dtd" | "sgml" | "xsd"; standard?: string | null; issue?: string | null; name?: string | null;
  notes: string[]; path?: string;
  folders?: { path: string; issue: string | null; doc_types: string[]; files: number; patch: string }[];
  folder?: string | null; entity_folders?: { path: string; files: number; patch: string }[]; entity_folder?: string | null;
  default_types?: string[]; types?: string[];
  doc_types?: { id: string; label?: string; schema_file?: string; root?: string | null; root_candidates?: string[];
    namespace?: string | null; selected?: boolean; problem?: string | null }[];
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

export const api = {
  projects: () => call<Project[]>("GET", "/api/projects"),
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
