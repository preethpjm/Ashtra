import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { STATUS_COLOR } from "./modelColors";

export interface ViewerProps {
  url: string;                                   // the GLB file
  highlight?: string[];                          // node names to show; the rest is ghosted
  status?: Record<string, { status: string }>;   // colour every node by its status (whole-model view)
  onPick?: (node: string | null) => void;
  height?: number | string;
  picked?: string | null;
}

const nameOf = (o: THREE.Object3D) => (o.userData?.name as string | undefined) ?? o.name;

/** A GLB model viewer: orbit, zoom, pick a part; highlight or colour parts by node name. */
export default function ModelViewer({ url, highlight, status, onPick, height = 360, picked }: ViewerProps) {
  const host = useRef<HTMLDivElement>(null);
  const api = useRef<{ apply: () => void; fit: (only?: boolean) => void; dispose: () => void } | null>(null);
  const props = useRef({ highlight, status, onPick, picked });
  props.current = { highlight, status, onPick, picked };
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [err, setErr] = useState("");
  const [isolate, setIsolate] = useState(false);
  const isolateRef = useRef(isolate);
  isolateRef.current = isolate;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let alive = true;
    setState("loading");
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0xf3f5f8);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(1, 1.4, 1.2);
    scene.add(sun);
    const camera = new THREE.PerspectiveCamera(40, 1, 0.0001, 1000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    let model: THREE.Object3D | null = null;
    const original = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
    let raf = 0;

    const size = () => {
      const w = el.clientWidth || 300, h = el.clientHeight || 200;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(size);
    ro.observe(el);
    size();

    // the named node (as in the GLB) a mesh belongs to: itself or its nearest named ancestor
    const ownersOf = (m: THREE.Object3D) => {
      const out: string[] = [];
      for (let o: THREE.Object3D | null = m; o && o !== model; o = o.parent) if (nameOf(o)) out.push(nameOf(o));
      return out;
    };
    const fit = (only = false) => {
      if (!model) return;
      const box = new THREE.Box3();
      const hl = new Set(props.current.highlight ?? []);
      if (only && hl.size) model.traverse((o) => { if ((o as THREE.Mesh).isMesh && ownersOf(o).some((n) => hl.has(n))) box.expandByObject(o); });
      if (box.isEmpty()) box.setFromObject(model);
      const c = box.getCenter(new THREE.Vector3());
      let r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-4);
      if (only && hl.size) {          // frame the part with its surroundings in view
        const whole = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3()).length() / 2;
        r = Math.min(Math.max(r * 2.5, whole * 0.35), whole * 1.05);
      }
      const dir = new THREE.Vector3(1, 0.7, 1.1).normalize();
      camera.position.copy(c.clone().add(dir.multiplyScalar(r / Math.sin((camera.fov * Math.PI) / 360) * 1.05)));
      camera.near = r / 100; camera.far = r * 100; camera.updateProjectionMatrix();
      controls.target.copy(c); controls.update();
    };
    const apply = () => {
      if (!model) return;
      const hl = new Set(props.current.highlight ?? []);
      const st = props.current.status;
      const pick = props.current.picked;
      model.traverse((o) => {
        const m = o as THREE.Mesh;
        if (!m.isMesh) return;
        const owners = ownersOf(m);
        const orig = original.get(m)!;
        const base = (Array.isArray(orig) ? orig[0] : orig) as THREE.MeshStandardMaterial;
        let color: string | null = null, ghost = false, glow = false;
        if (st) {
          const s = owners.map((n) => st[n]?.status).find(Boolean);
          color = s ? STATUS_COLOR[s] ?? null : null;
          ghost = !s;
          if (pick && owners.includes(pick)) glow = true;
        } else if (hl.size) {
          glow = owners.some((n) => hl.has(n));
          ghost = !glow;
        }
        m.visible = !(isolateRef.current && ghost);
        if (!color && !ghost && !glow) { m.material = orig; return; }
        const mat = new THREE.MeshStandardMaterial({
          color: color ? new THREE.Color(color) : base.color ?? new THREE.Color(0xb0b6bf),
          metalness: 0.1, roughness: 0.6, side: THREE.DoubleSide, transparent: ghost, opacity: ghost ? 0.12 : 1, depthWrite: !ghost,
          emissive: glow ? new THREE.Color(st ? 0x1a56a8 : 0xf28c28) : new THREE.Color(0), emissiveIntensity: glow ? 0.55 : 0,
        });
        if (glow && !color) mat.color = new THREE.Color(0xf28c28);
        m.material = mat;
      });
    };
    api.current = { apply, fit, dispose: () => {} };

    new GLTFLoader().load(url, (g) => {
      if (!alive) return;
      model = g.scene;
      model.traverse((o) => {
        const m = o as THREE.Mesh;
        if (!m.isMesh) return;
        if (!m.geometry.getAttribute("normal")) m.geometry.computeVertexNormals();   // some converters write no normals
        // CAD exports often mix the winding of faces: draw and pick both sides
        (Array.isArray(m.material) ? m.material : [m.material]).forEach((x) => { x.side = THREE.DoubleSide; });
        original.set(m, m.material);
      });
      scene.add(model);
      apply();
      fit(!!props.current.highlight?.length);
      setState("ready");
    }, undefined, (e) => { if (alive) { setErr(String((e as any)?.message ?? e)); setState("error"); } });

    // pick a part: a click (not a drag) on a mesh
    const ray = new THREE.Raycaster();
    let down: [number, number] | null = null;
    const onDown = (e: PointerEvent) => { down = [e.clientX, e.clientY]; };
    const onUp = (e: PointerEvent) => {
      if (!down || !model || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      const r = renderer.domElement.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
      const hit = ray.intersectObject(model, true).find((h) => h.object.visible && !((h.object as THREE.Mesh).material as THREE.Material).transparent);
      props.current.onPick?.(hit ? ownersOf(hit.object)[0] ?? null : null);
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);
    const loop = () => { raf = requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); };
    loop();
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      scene.traverse((o) => { const m = o as THREE.Mesh; if (m.isMesh) m.geometry?.dispose(); });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [url]);

  // highlight, status or picked part changed: recolour (and frame the highlighted part)
  const hlKey = (highlight ?? []).join("|");
  useEffect(() => { api.current?.apply(); if (hlKey) api.current?.fit(true); }, [hlKey]);
  useEffect(() => { api.current?.apply(); }, [status, picked, isolate]);

  return (
    <div className="mv" style={{ height }}>
      <div ref={host} className="mv-canvas" />
      <div className="mv-tools">
        <button onClick={() => api.current?.fit(false)} title="Show the whole model">Fit</button>
        {(highlight?.length || status) && <button className={isolate ? "on" : ""} onClick={() => setIsolate(!isolate)}
          title="Hide everything else">Isolate</button>}
      </div>
      {state === "loading" && <div className="mv-msg">Loading 3D model…</div>}
      {state === "error" && <div className="mv-msg err">The 3D model could not be shown: {err}</div>}
    </div>
  );
}
