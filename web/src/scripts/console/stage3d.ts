// 3D team stage (three.js, bundled and self-hosted). Loaded with import() only on /app/, and only
// when WebGL2 works, motion is allowed and the stage is STAGE_3D_MIN_PX wide; otherwise the 2D
// portraits in Team.astro stay. A stage that later narrows hands back to the portraits and sleeps.
// Desk objects in soft morning light: no emissive glows, no chrome, no neon. Colours are read from
// tokens.css. Lamp amber (--money-fill) appears only on the packet that is money waiting for you.
import {
  CanvasTexture, Color, CylinderGeometry, DirectionalLight, DoubleSide, ExtrudeGeometry, Group, HemisphereLight,
  LatheGeometry, MathUtils, Mesh, MeshBasicMaterial, MeshPhysicalMaterial, MeshStandardMaterial, NeutralToneMapping,
  PerspectiveCamera, PlaneGeometry, PMREMGenerator, Scene, Shape, ShapeGeometry, SphereGeometry, TorusGeometry, Vector2, Vector3,
  WebGLRenderer, type BufferGeometry, type Material, type Object3D,
} from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { AGENTS, STAGE_3D_MIN_PX, type AgentId } from './agents';
import type { Mood, Stage } from './team';

const SPACING = 1.12;
const FOV = 24;
const TAN = Math.tan(MathUtils.degToRad(FOV / 2));
const TEAM_H = 1.05;    // tallest mascot in world units
const FEET_AT = 0.27;   // feet sit this far up the frame, above the name labels

interface Built { body: Group; eyes: Mesh[]; h: number; foot: number; p: Record<string, Object3D> }
interface Rig extends Built {
  id: AgentId; x: number; z: number; root: Group; dots: Group; shadow: Mesh;
  mood: Mood; since: number; phase: number;
  yaw: number; yawV: number; look: number; lookUntil: number; passDir: number;
  blinkAt: number; catchAt: number;
}
interface Flight { m: Group; a: Vector3; b: Vector3; t0: number; dur: number; arc: number; to: Rig | null }

const now = () => performance.now() / 1000;
// Critically damped spring: no overshoot, so nothing in the UI "bounces".
function spring(x: number, v: number, to: number, dt: number, w: number): [number, number] {
  const a = w * w * (to - x) - 2 * w * v;
  const nv = v + a * dt;
  return [x + nv * dt, nv];
}
const ease = (p: number) => (p < 0.5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2);

export function mount(stageEl: HTMLElement, onLost: () => void): Stage {
  const css = getComputedStyle(document.documentElement);
  const tok = (name: string) => new Color(css.getPropertyValue(name).trim() || 'gray');
  const C = {
    tin: tok('--mat-tin'), kraft: tok('--mat-kraft'), walnut: tok('--mat-walnut'), tissue: tok('--mat-tissue'),
    dusk: tok('--mat-dusk'), graphite: tok('--mat-graphite'), sage: tok('--mat-sage'),
    ink: tok('--m-ink'), ink3: tok('--m-ink-3'), money: tok('--money-fill'), bad: tok('--m-bad'),
    sky: tok('--m-s1'), ground: tok('--m-s3'),
  };
  const WHITE = new Color(1, 1, 1);

  const renderer = new WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.toneMapping = NeutralToneMapping;
  renderer.setClearColor(0x000000, 0);
  const canvas = renderer.domElement;
  canvas.className = 'stage-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); onLost(); });

  const scene = new Scene();
  const pmrem = new PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.5;
  pmrem.dispose();
  scene.add(new HemisphereLight(C.sky, C.ground, 1.1));
  const key = new DirectionalLight(WHITE, 1.6);  // the morning window: soft, from above and the left
  key.position.set(-3, 6, 5);
  const rim = new DirectionalLight(C.sky, 0.9);  // separates the silhouettes from the backdrop
  rim.position.set(4, 3, -6);
  scene.add(key, rim);

  // ---------- materials: felt, satin, pewter, glass ----------
  const felt = (c: Color, sheen = 0.6) => new MeshPhysicalMaterial({ color: c, roughness: 0.8, sheen, sheenRoughness: 0.5, sheenColor: c.clone().lerp(WHITE, 0.5) });
  const satin = (c: Color) => new MeshPhysicalMaterial({ color: c, roughness: 0.42, clearcoat: 0.35, clearcoatRoughness: 0.35 });
  const metal = (c: Color) => new MeshStandardMaterial({ color: c, metalness: 0.7, roughness: 0.3 });
  const glass = (c: Color) => new MeshPhysicalMaterial({ color: c, roughness: 0.1, clearcoat: 1, clearcoatRoughness: 0.05 });
  const M = {
    eye: new MeshStandardMaterial({ color: C.ink, roughness: 0.25 }),
    eyeLight: new MeshStandardMaterial({ color: C.tissue, roughness: 0.35 }),
    glint: new MeshBasicMaterial({ color: WHITE }),
    dot: new MeshStandardMaterial({ color: C.ink3, roughness: 0.6 }),
    paper: satin(C.kraft.clone().lerp(WHITE, 0.25)),
    paperFlap: satin(C.kraft.clone().multiplyScalar(0.86)),
    money: satin(C.money),
    moneyFlap: satin(C.money.clone().multiplyScalar(0.8)),
  };
  const EYE = new SphereGeometry(1, 20, 14);
  const PACKET = new RoundedBoxGeometry(0.24, 0.165, 0.03, 2, 0.014);
  const FLAP = (() => { // envelope flap on the packet's face
    const v = new Shape();
    v.moveTo(-0.112, 0.076); v.lineTo(0.112, 0.076); v.lineTo(0, -0.012); v.closePath();
    return new ShapeGeometry(v);
  })();
  function packet(money: boolean) {
    const g = new Group();
    g.add(new Mesh(PACKET, M.paper), new Mesh(FLAP, M.paperFlap));
    g.children[1].position.z = 0.0158;
    paint(g, money);
    return g;
  }
  function paint(g: Group, money: boolean) {
    (g.children[0] as Mesh).material = money ? M.money : M.paper;
    (g.children[1] as Mesh).material = money ? M.moneyFlap : M.paperFlap;
  }

  const add = (parent: Object3D, geo: BufferGeometry, mat: Material, x = 0, y = 0, z = 0) => {
    const m = new Mesh(geo, mat);
    m.position.set(x, y, z);
    parent.add(m);
    return m;
  };
  function eyes(parent: Object3D, y: number, z: number, gap: number, light: boolean, r = 0.048, dx = 0) {
    return [-1, 1].map((s) => {
      const e = add(parent, EYE, light ? M.eyeLight : M.eye, (s * gap) / 2 + dx, y, z);
      e.scale.set(r, r * 1.3, r * 0.6);
      e.userData.sy = r * 1.3;
      add(e, EYE, M.glint, 0.36, 0.42, 0.8).scale.setScalar(0.3);
      return e;
    });
  }

  // ---------- the cast: one desk object per real module ----------
  const BUILD: Record<AgentId, () => Built> = {
    guard() { // a service-desk bell: it rings when an email tries to give orders
      const body = new Group();
      const tin = metal(C.tin);
      add(body, new CylinderGeometry(0.43, 0.45, 0.09, 48), metal(C.tin.clone().multiplyScalar(0.6)), 0, 0.045, 0);
      const prof: Vector2[] = [];
      for (let i = 0; i <= 20; i++) { const a = (i / 20) * (Math.PI / 2); prof.push(new Vector2(Math.cos(a) * 0.395 + 0.0001, Math.sin(a) * 0.37)); }
      add(body, new LatheGeometry(prof, 56), tin, 0, 0.09, 0);
      const plunger = new Group();
      plunger.position.y = 0.46;
      body.add(plunger);
      add(plunger, new CylinderGeometry(0.026, 0.026, 0.1, 16), tin, 0, 0.04, 0);
      add(plunger, new SphereGeometry(0.07, 24, 16), tin, 0, 0.1, 0);
      const ring = new Group(); // "((  ))" marks around the knob while it rings
      ring.position.set(0, 0.56, 0.06);
      ring.visible = false;
      body.add(ring);
      for (const side of [0, Math.PI]) {
        for (let j = 0; j < 2; j++) {
          const arc = new Mesh(new TorusGeometry(0.13 + j * 0.09, 0.009, 6, 20, 1.1), new MeshBasicMaterial({ color: C.bad, transparent: true, depthWrite: false }));
          arc.rotation.z = side - 0.55;
          arc.userData.j = j;
          ring.add(arc);
        }
      }
      return { body, eyes: eyes(body, 0.29, 0.322, 0.17, false), h: 0.66, foot: 0.5, p: { plunger, ring } };
    },
    router() { // a felt pebble with a signpost: in scope points on, declined points back
      const body = new Group();
      const g = satin(C.graphite);
      add(body, new SphereGeometry(0.36, 48, 32), felt(C.tissue, 0.8), 0, 0.3, 0).scale.set(1.08, 0.86, 0.96);
      add(body, new CylinderGeometry(0.02, 0.024, 0.26, 12), g, 0, 0.7, 0);
      const sign = new Group();
      sign.position.y = 0.86;
      body.add(sign);
      const s = new Shape();
      s.moveTo(-0.16, -0.048); s.lineTo(0.05, -0.048); s.lineTo(0.05, -0.1); s.lineTo(0.18, 0);
      s.lineTo(0.05, 0.1); s.lineTo(0.05, 0.048); s.lineTo(-0.16, 0.048); s.closePath();
      const geo = new ExtrudeGeometry(s, { depth: 0.03, bevelEnabled: true, bevelThickness: 0.012, bevelSize: 0.012, bevelSegments: 3, curveSegments: 1 });
      geo.center();
      add(sign, geo, g, 0.03, 0, 0);
      return { body, eyes: eyes(body, 0.33, 0.335, 0.17, false), h: 1.0, foot: 0.42, p: { sign } };
    },
    planner() { // a kraft notebook with an elastic band and a pencil tucked in the top
      const body = new Group();
      const g = satin(C.graphite);
      add(body, new RoundedBoxGeometry(0.6, 0.84, 0.34, 4, 0.1), felt(C.kraft, 0.5), 0, 0.42, 0);
      add(body, new RoundedBoxGeometry(0.036, 0.852, 0.356, 2, 0.016), g, 0.17, 0.42, 0);
      const pencil = new Group();
      pencil.position.set(-0.17, 0.78, -0.04);
      body.add(pencil);
      add(pencil, new CylinderGeometry(0.027, 0.027, 0.34, 6), new MeshPhysicalMaterial({ color: C.tissue, roughness: 0.45, flatShading: true }), 0, 0.17, 0);
      add(pencil, new CylinderGeometry(0.002, 0.027, 0.07, 6), g, 0, 0.375, 0);
      return { body, eyes: eyes(body, 0.58, 0.168, 0.17, false, 0.048, -0.04), h: 0.86, foot: 0.4, p: { pencil } };
    },
    forecaster() { // a dusk-glass globe on a stand, with an orbit that spins while it forecasts
      const body = new Group();
      const g = satin(C.graphite);
      add(body, new CylinderGeometry(0.2, 0.25, 0.1, 40), g, 0, 0.05, 0);
      add(body, new CylinderGeometry(0.075, 0.11, 0.09, 32), g, 0, 0.145, 0);
      add(body, new SphereGeometry(0.32, 56, 40), glass(C.dusk), 0, 0.49, 0);
      const orbit = new Group();
      orbit.position.y = 0.49;
      orbit.rotation.set(1.2, 0.32, 0);
      body.add(orbit);
      const spin = new Group();
      orbit.add(spin);
      add(spin, new TorusGeometry(0.41, 0.013, 10, 80), satin(C.tissue));
      add(spin, new SphereGeometry(0.036, 16, 12), felt(C.kraft), 0.41, 0, 0);
      return { body, eyes: eyes(body, 0.53, 0.305, 0.17, false), h: 0.83, foot: 0.36, p: { spin } };
    },
    validator() { // a rubber stamp: it stamps every step it checks
      const body = new Group();
      const gs = satin(C.graphite);
      add(body, new RoundedBoxGeometry(0.52, 0.045, 0.36, 2, 0.015), satin(C.graphite.clone().multiplyScalar(0.55)), 0, 0.0225, 0);
      add(body, new RoundedBoxGeometry(0.58, 0.15, 0.42, 4, 0.045), gs, 0, 0.12, 0);
      add(body, new CylinderGeometry(0.085, 0.12, 0.2, 32), gs, 0, 0.29, 0);
      add(body, new SphereGeometry(0.24, 48, 32), felt(C.graphite, 0.35), 0, 0.6, 0).scale.y = 0.94;
      return { body, eyes: eyes(body, 0.62, 0.225, 0.16, true), h: 0.84, foot: 0.44, p: {} };
    },
    judge() { // a tall sage egg in reading glasses: it reviews, it cannot approve
      const body = new Group();
      const prof: Vector2[] = [];
      for (let i = 0; i <= 32; i++) {
        const u = i / 32;
        prof.push(new Vector2(Math.max(0.0001, 0.335 * Math.sqrt(Math.max(0, 1 - (2 * u - 1) ** 2)) * (1 - 0.2 * u)), 0.98 * u));
      }
      add(body, new LatheGeometry(prof, 56), felt(C.sage, 0.7), 0, 0, 0);
      const specs = new Group();
      specs.position.set(0, 0.62, 0.274);
      body.add(specs);
      const rim = metal(C.graphite);
      for (const sx of [-1, 1]) add(specs, new TorusGeometry(0.083, 0.011, 10, 40), rim, sx * 0.098, 0, 0);
      add(specs, new CylinderGeometry(0.008, 0.008, 0.04, 8), rim, 0, 0.01, 0.01).rotation.z = Math.PI / 2;
      return { body, eyes: eyes(body, 0.62, 0.262, 0.196, false, 0.042), h: 0.98, foot: 0.36, p: { specs } };
    },
    executor() { // a walnut desk drawer that prints a receipt for every step it runs
      const body = new Group();
      add(body, new RoundedBoxGeometry(0.84, 0.6, 0.5, 4, 0.11), satin(C.walnut), 0, 0.3, 0);
      const drawer = new Group();
      drawer.position.set(0, 0.175, 0.235);
      body.add(drawer);
      add(drawer, new RoundedBoxGeometry(0.6, 0.17, 0.07, 3, 0.03), satin(C.walnut.clone().multiplyScalar(0.72)));
      add(drawer, new SphereGeometry(0.032, 16, 12), metal(C.tin), 0, 0, 0.045);
      add(body, new RoundedBoxGeometry(0.3, 0.03, 0.09, 2, 0.012), satin(C.graphite), 0.16, 0.6, -0.02);
      const paper = new PlaneGeometry(0.24, 1, 1, 12);
      paper.translate(0, 0.5, 0);
      const pos = paper.attributes.position;
      for (let i = 0; i < pos.count; i++) pos.setZ(i, -0.3 * pos.getY(i) ** 2); // curls back as it grows
      paper.computeVertexNormals();
      const receipt = add(body, paper, new MeshPhysicalMaterial({ color: C.tissue, roughness: 0.9, side: DoubleSide }), 0.16, 0.6, -0.02);
      receipt.visible = false;
      return { body, eyes: eyes(body, 0.42, 0.25, 0.18, true), h: 0.64, foot: 0.52, p: { drawer, receipt } };
    },
  };

  // ---------- soft contact shadows ----------
  const blob = document.createElement('canvas');
  blob.width = blob.height = 64;
  const g2 = blob.getContext('2d')!;
  const grad = g2.createRadialGradient(32, 32, 0, 32, 32, 32);
  const shade = css.getPropertyValue('--n-bg-rgb').trim().split(/\s+/).join(',') || '0,0,0';
  grad.addColorStop(0, `rgba(${shade},0.5)`);
  grad.addColorStop(0.55, `rgba(${shade},0.18)`);
  grad.addColorStop(1, `rgba(${shade},0)`);
  g2.fillStyle = grad;
  g2.fillRect(0, 0, 64, 64);
  const shadowTex = new CanvasTexture(blob);
  const SHADOW = new PlaneGeometry(1, 1);
  SHADOW.rotateX(-Math.PI / 2);
  const DOT = new SphereGeometry(1, 12, 8);

  const rigs: Rig[] = AGENTS.map((a, i) => {
    const b = BUILD[a.id]();
    const root = new Group();
    const x = (i - (AGENTS.length - 1) / 2) * SPACING;
    const z = -0.32 * ((i - 3) / 3) ** 2; // a gentle arc, as if around a desk
    root.position.set(x, 0, z);
    root.add(b.body);
    scene.add(root);
    const shadow = new Mesh(SHADOW, new MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false }));
    shadow.position.set(x, 0.002, z);
    scene.add(shadow);
    const dots = new Group();
    dots.position.y = b.h + 0.16;
    dots.visible = false;
    for (let j = 0; j < 3; j++) add(dots, DOT, M.dot, (j - 1) * 0.075, 0, 0).scale.setScalar(0.028);
    b.body.add(dots);
    return { ...b, id: a.id, x, z, root, dots, shadow, mood: 'idle', since: 0, phase: i * 1.7,
      yaw: 0, yawV: 0, look: x, lookUntil: 0, passDir: 1, blinkAt: now() + 1 + Math.random() * 3, catchAt: -9 };
  });
  const rig = (id: AgentId) => rigs.find((r) => r.id === id)!;
  const ex = rig('executor');
  const held = packet(true);
  held.position.set(0, ex.h + 0.3, 0.05);
  held.visible = false;
  ex.root.add(held);
  let receiptLen = 0, receiptTo = 0, drawerZ = 0;

  // ---------- camera: frames the whole team, and leans in when the team turns to you ----------
  const camera = new PerspectiveCamera(FOV, 1, 0.1, 60);
  const probe = new PerspectiveCamera(FOV, 1, 0.1, 60);
  let W = 1, H = 1, fits = false, facing = false;
  const cam = { x: 0, d: 9, y: 0.7, vx: 0, vd: 0, vy: 0 };
  const ptr = { x: 0, y: 0, sx: 0, sy: 0 };
  function target() {
    const half = SPACING * 3 + 0.5; // content half-width, mascots included
    const fit = Math.max(half / (TAN * (W / H)), TEAM_H / (2 * TAN * 0.52));
    const d = fit * (facing ? 1.01 : 1.08); // the team leans in when it turns to you, never cropped
    return { x: 0, d, y: (0.5 - FEET_AT) * 2 * d * TAN };
  }
  const aim = (c: PerspectiveCamera, x: number, y: number, d: number, ox = 0, oy = 0) => {
    c.position.set(x + ox, y + d * 0.13 + oy, d); // a little above the desk, looking slightly down
    c.lookAt(x, y, 0);
  };
  const px = (v: Vector3, c: PerspectiveCamera) => {
    v.project(c);
    return { x: ((v.x + 1) / 2) * W, y: ((1 - v.y) / 2) * H };
  };
  function probeAt(t: { x: number; y: number; d: number }) {
    probe.aspect = W / H;
    probe.updateProjectionMatrix();
    aim(probe, t.x, t.y, t.d);
    probe.updateMatrixWorld();
  }
  const members = new Map(AGENTS.map((a) => [a.id, stageEl.querySelector<HTMLElement>(`[data-agent="${a.id}"]`)]));
  const feet = new Vector3();
  /** Names under the feet, from the live camera (minus pointer parallax), so they ride along while it eases. */
  function placeLabels() {
    probeAt(cam);
    for (const r of rigs) {
      const p = px(feet.set(r.x, 0, r.z), probe);
      const li = members.get(r.id);
      li?.style.setProperty('--x', `${p.x.toFixed(1)}px`);
      li?.style.setProperty('--y', `${(p.y + 14).toFixed(1)}px`);
    }
  }
  function resize() {
    W = stageEl.clientWidth;
    H = stageEl.clientHeight;
    if (!W || !H) return;
    renderer.setSize(W, H, false);
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
    placeLabels();
    const fit = stageEl.getBoundingClientRect().width >= STAGE_3D_MIN_PX; // unrounded, like the container query
    if (fit !== fits) { fits = fit; show(fits); sync(); }
  }

  // ---------- 2D <-> 3D hand-over: data-gl / data-mode on the stage, styled in page-console.css ----------
  // In: the canvas fades in while the 2D portraits fade out in place; when that fade really ends (a slow GPU can
  // block the first frames for seconds, so no timer), the names move under the 3D feet.
  // Out (the stage narrowed below STAGE_3D_MIN_PX): straight back to the portraits, and the loop sleeps.
  function show(on: boolean) {
    stageEl.toggleAttribute('data-gl', on);
    if (!on) stageEl.dataset.mode = '2d';
  }
  canvas.addEventListener('transitionend', () => { if (stageEl.hasAttribute('data-gl')) stageEl.dataset.mode = '3d'; });

  // ---------- packets ----------
  const flights: Flight[] = [];
  const pool: Group[] = [];
  function spot(who: AgentId | 'you', out: Vector3) {
    if (who === 'you') return out.set(cam.x, -0.4, 2.4); // from the request bar, below the stage
    const r = rig(who);
    return out.set(r.x, r.h * 0.36, r.z + 0.3); // chest height, so a packet never covers a face
  }

  // ---------- per-frame motion ----------
  function moveRig(r: Rig, T: number, dt: number, camX: number, camZ: number) {
    const k = T - r.since;
    let sy = 1 + 0.014 * Math.sin(T * 1.8 + r.phase); // breathing
    let lift = 0, rz = 0, rx = 0;
    switch (r.mood) {
      case 'think': rz = 0.055 * Math.sin(T * 2.4 + r.phase); rx = -0.03; break;
      case 'talk': sy += 0.035 * Math.max(0, Math.sin(k * 14)) * Math.max(0.25, 1 - k / 1.8); break;
      case 'pass': rz = -r.passDir * 0.13 * Math.sin(Math.min(k / 0.5, 1) * Math.PI); break;
      case 'alarm': rz = 0.15 * Math.sin(k * 42) * Math.exp(-k * 2.8); sy -= 0.05 * Math.exp(-k * 1.5) + 0.015; break;
      case 'wait': rx = 0.07 + 0.015 * Math.sin(T * 1.7 + r.phase); break;
      case 'done': rx = 0.1 * Math.sin(Math.min(k / 0.55, 1) * Math.PI); break;
      case 'cheer': if (k < 1.9) { const s = Math.sin(k * 7); lift = 0.2 * Math.max(0, s); sy += s < 0 ? 0.07 * s : 0.03; } break;
      case 'work': sy += 0.02 * Math.sin(k * 11); rx = 0.04; break;
      default: break;
    }
    if (r.id === 'validator' && (r.mood === 'talk' || r.mood === 'alarm')) { // stamp: up, then down hard
      if (k < 0.32) lift += 0.11 * Math.sin((k / 0.32) * Math.PI);
      else sy -= 0.09 * Math.exp(-(k - 0.32) * 14);
    }
    if (facing) rx += 0.04;
    const c = T - r.catchAt;
    if (c >= 0 && c < 0.45) sy -= 0.08 * Math.sin((c / 0.45) * Math.PI); // caught a packet
    const sx = 1 + (1 - sy) * 0.6; // keep the volume
    r.body.scale.set(sx, sy, sx);
    r.body.position.y = lift;
    r.body.rotation.set(rx, 0, rz);

    const toCam = Math.atan2(camX - r.x, camZ - r.z);
    const idleLook = r.mood === 'idle' ? 0.06 * Math.sin(T * 0.45 + r.phase * 2) + ptr.sx * 0.22 : 0;
    const want = T < r.lookUntil ? MathUtils.clamp(Math.atan2(r.look - r.x, 0.9), -0.8, 0.8) : toCam * (facing ? 1 : 0.7) + idleLook;
    [r.yaw, r.yawV] = spring(r.yaw, r.yawV, want, dt, 9);
    r.root.rotation.y = r.yaw;

    let ey = 1;
    if (T > r.blinkAt) {
      if (T - r.blinkAt < 0.13) ey = 0.12;
      else r.blinkAt = T + 1.8 + Math.random() * 4.2;
    }
    if (r.mood === 'alarm' && k < 0.8) ey = 1.25;
    for (const e of r.eyes) e.scale.y = e.userData.sy * ey;
    if (r.dots.visible) r.dots.children.forEach((d, j) => { d.position.y = 0.035 * Math.max(0, Math.sin(T * 6 - j * 0.9)); });
    const s = 1 - lift * 1.4;
    r.shadow.scale.set(r.foot * 2.3 * s, 1, r.foot * 1.5 * s);
    (r.shadow.material as MeshBasicMaterial).opacity = 0.9 * (1 - lift * 1.8);
  }

  function moveProps(T: number, dt: number) {
    const gd = rig('guard'), kg = T - gd.since, ring = gd.mood === 'alarm';
    gd.p.plunger.position.y = 0.46 - (ring ? 0.035 * Math.abs(Math.sin(kg * 16)) * Math.exp(-kg * 2.2) : 0);
    gd.p.ring.visible = ring && kg < 1.6;
    if (gd.p.ring.visible) for (const a of gd.p.ring.children as Mesh[]) {
      const p = (kg * 1.6 + 0.35 * (1 - a.userData.j)) % 1;
      a.scale.setScalar(0.85 + p * 0.45);
      (a.material as MeshBasicMaterial).opacity = 0.85 * (1 - p) * Math.min(1, (1.6 - kg) * 2);
    }
    const ro = rig('router');
    const signTo = ro.mood === 'think' ? 0.28 * Math.sin(T * 3.2) : ro.mood === 'alarm' ? Math.PI : 0;
    ro.p.sign.rotation.z += (signTo - ro.p.sign.rotation.z) * Math.min(1, dt * 8);
    const pl = rig('planner');
    pl.p.pencil.rotation.z = 0.42 + (pl.mood === 'think' || pl.mood === 'talk' ? 0.12 * Math.sin(T * 8) : 0);
    const fc = rig('forecaster');
    fc.p.spin.rotation.z += dt * (fc.mood === 'think' || fc.mood === 'talk' ? 2.6 : 0.35);
    const jd = rig('judge');
    jd.p.specs.position.y = 0.62 + (jd.mood === 'think' || jd.mood === 'talk' ? 0.012 * Math.sin(T * 5) : 0);
    drawerZ += ((ex.mood === 'work' ? 0.085 : 0) - drawerZ) * Math.min(1, dt * 7);
    ex.p.drawer.position.z = 0.235 + drawerZ;
    receiptLen += (receiptTo - receiptLen) * Math.min(1, dt * 5);
    ex.p.receipt.visible = receiptLen > 0.01;
    ex.p.receipt.scale.set(1, Math.max(0.001, receiptLen), Math.max(0.001, receiptLen));
    if (held.visible) { held.position.y = ex.h + 0.3 + 0.03 * Math.sin(T * 2.4); held.rotation.set(0.12, 0.3 * Math.sin(T * 0.9), 0.05 * Math.sin(T * 1.7)); }
  }

  function moveFlights(T: number) {
    for (let i = flights.length - 1; i >= 0; i--) {
      const f = flights[i];
      const p = (T - f.t0) / f.dur;
      if (p >= 1) {
        f.m.visible = false;
        pool.push(f.m);
        flights.splice(i, 1);
        if (f.to) f.to.catchAt = T;
        continue;
      }
      f.m.position.lerpVectors(f.a, f.b, ease(p));
      f.m.position.y += 4 * f.arc * p * (1 - p);
      f.m.scale.setScalar(p < 0.82 ? 1 : 1 - ((p - 0.82) / 0.18) * 0.7); // tucked away on arrival
      f.m.rotation.set(0.35 * Math.sin(p * Math.PI), 0, (1 - p) * 0.5 * Math.sign(f.b.x - f.a.x || 1));
    }
  }

  // ---------- loop, frame-time log, visibility ----------
  const DTS = new Float32Array(900); // rAF to rAF gaps, drawn or skipped
  const CPU = new Float32Array(900); // main-thread ms per drawn frame: our update + three's draw submission
  let frames = 0, drawn = 0, last = 0, lastRaf = 0, ema = 16.7, tunes = 0, draw = false;
  (window as unknown as { __stageStats: () => object }).__stageStats = () => {
    const n = Math.min(frames, DTS.length);
    const a = Array.from(DTS.subarray(0, n)).sort((p, q) => p - q);
    const avg = a.reduce((s, v) => s + v, 0) / (n || 1);
    const m = Math.min(drawn, CPU.length);
    const c = Array.from(CPU.subarray(0, m)).sort((p, q) => p - q);
    return { frames, drawn, avgMs: +avg.toFixed(2), fps: +(1000 / (avg || 1)).toFixed(1), p95Ms: +(a[Math.floor(n * 0.95)] ?? 0).toFixed(2),
      maxMs: +(a[n - 1] ?? 0).toFixed(2), over20ms: a.filter((v) => v > 20).length,
      cpuAvgMs: +(c.reduce((s, v) => s + v, 0) / (m || 1)).toFixed(2), cpuP95Ms: +(c[Math.floor(m * 0.95)] ?? 0).toFixed(2),
      drawCalls: renderer.info.render.calls, triangles: renderer.info.render.triangles, pixelRatio: renderer.getPixelRatio(), size: [W, H] };
  };
  if (new URLSearchParams(location.search).has('fps')) {
    window.setInterval(() => console.info('[stage]', (window as unknown as { __stageStats: () => object }).__stageStats()), 5000);
  }

  const camMoving = () => Math.abs(cam.vx) + Math.abs(cam.vd) + Math.abs(cam.vy) > 1e-3;
  function frame(ms: number) {
    const c0 = performance.now();
    const T = ms / 1000;
    if (lastRaf) {
      const gap = (T - lastRaf) * 1000;
      DTS[frames % DTS.length] = gap;
      frames += 1;
      ema = ema * 0.95 + gap * 0.05;
      // Weak GPU: drop resolution a notch, at most twice, never below 1x.
      if (frames % 120 === 0 && ema > 26 && tunes < 2 && renderer.getPixelRatio() > 1) {
        tunes += 1;
        renderer.setPixelRatio(Math.max(1, renderer.getPixelRatio() - 0.5));
        resize();
      }
    }
    lastRaf = T;
    // Calm (no packet in the air, camera and pointer still, nobody changed mood in 2 s): every other frame, ~30 fps.
    const busy = flights.length > 0 || camMoving() || Math.abs(ptr.x - ptr.sx) + Math.abs(ptr.y - ptr.sy) > 1e-3
      || rigs.some((r) => T - r.since < 2 || T - r.catchAt < 0.5);
    draw = busy || !draw;
    if (!draw) return;
    const dt = last ? Math.min(0.05, T - last) : 1 / 60;
    last = T;
    const t = target();
    [cam.x, cam.vx] = spring(cam.x, cam.vx, t.x, dt, 4.2);
    [cam.d, cam.vd] = spring(cam.d, cam.vd, t.d, dt, 4.2);
    [cam.y, cam.vy] = spring(cam.y, cam.vy, t.y, dt, 4.2);
    if (camMoving()) placeLabels(); // 7 projections, CSSOM only: the names stay under the feet while the camera eases
    ptr.sx += (ptr.x - ptr.sx) * Math.min(1, dt * 3);
    ptr.sy += (ptr.y - ptr.sy) * Math.min(1, dt * 3);
    aim(camera, cam.x, cam.y, cam.d, ptr.sx * 0.3, -ptr.sy * 0.12); // pointer parallax on desktop
    for (const r of rigs) moveRig(r, T, dt, camera.position.x, camera.position.z);
    moveProps(T, dt);
    moveFlights(T);
    renderer.render(scene, camera);
    CPU[drawn % CPU.length] = performance.now() - c0;
    drawn += 1;
  }

  let visible = true, running = false;
  function sync() {
    const on = visible && fits && !document.hidden;
    if (on === running) return;
    running = on;
    last = 0; lastRaf = 0;
    renderer.setAnimationLoop(on ? frame : null);
  }
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; sync(); });
  const ro = new ResizeObserver(resize);
  const onPtr = (e: PointerEvent) => {
    const r = stageEl.getBoundingClientRect();
    ptr.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    ptr.y = ((e.clientY - r.top) / r.height) * 2 - 1;
  };
  const offPtr = () => { ptr.x = 0; ptr.y = 0; };
  const fine = matchMedia('(pointer: fine)').matches;
  if (fine) { stageEl.addEventListener('pointermove', onPtr); stageEl.addEventListener('pointerleave', offPtr); }
  document.addEventListener('visibilitychange', sync);

  stageEl.prepend(canvas);
  resize(); // sizes everything; on a wide enough stage it starts the hand-over
  const t0 = target();
  Object.assign(cam, { x: t0.x, d: t0.d, y: t0.y });
  placeLabels();
  frame(performance.now()); // first frame drawn before the canvas starts to fade in
  last = 0; lastRaf = 0;
  io.observe(stageEl);
  ro.observe(stageEl);
  sync();

  return {
    mood(id, m) {
      const r = rig(id);
      if (r.mood === m) return;
      r.mood = m;
      r.since = now();
      r.dots.visible = m === 'think';
    },
    toss(from, to, money) {
      const m = pool.pop() ?? packet(money);
      paint(m, money);
      m.scale.setScalar(1);
      m.visible = true;
      scene.add(m);
      const a = spot(from, new Vector3()), b = spot(to, new Vector3());
      const dist = a.distanceTo(b);
      const T = now();
      flights.push({ m, a, b, t0: T, dur: 0.42 + dist * 0.07, arc: 0.3 + dist * 0.08, to: to === 'you' ? null : rig(to) });
      if (from !== 'you') { const r = rig(from); r.look = b.x; r.lookUntil = T + 0.9; r.passDir = Math.sign(b.x - a.x) || 1; }
      if (to !== 'you') { const r = rig(to); r.look = a.x; r.lookUntil = T + 0.9; }
    },
    hold(_id, money) {
      held.visible = money !== null;
      paint(held, !!money);
    },
    faceYou(on) { facing = on; }, // the camera eases in; frame() keeps the names under the feet
    receipt(n) { receiptTo = n ? Math.min(0.66, 0.1 + 0.1 * n) : 0; },
    anchor(id) {
      if (!fits) return null; // the 2D portraits are showing: team.ts measures those instead
      probeAt(target()); // where the camera is heading: the bubble is placed once per line
      const r = rig(id);
      return px(new Vector3(r.x, r.h + 0.12, r.z), probe);
    },
    dispose() {
      renderer.setAnimationLoop(null);
      show(false);
      io.disconnect();
      ro.disconnect();
      document.removeEventListener('visibilitychange', sync);
      if (fine) { stageEl.removeEventListener('pointermove', onPtr); stageEl.removeEventListener('pointerleave', offPtr); }
      scene.traverse((o) => {
        const m = o as Mesh;
        m.geometry?.dispose();
        (Array.isArray(m.material) ? m.material : m.material ? [m.material] : []).forEach((x) => x.dispose());
      });
      shadowTex.dispose();
      scene.environment?.dispose();
      renderer.dispose();
      canvas.remove();
    },
  };
}
