import { useLayoutEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { CHANNELS, clamp, depthAt, lerp, mulberry32, reef, sunElevation } from "../reef";

/* ---------------------------------- helpers --------------------------------- */

function makeLinearGradientTexture(): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = 64;
  c.height = 256;
  const ctx = c.getContext("2d")!;
  const g = ctx.createLinearGradient(0, 0, 0, 256);
  g.addColorStop(0, "rgba(255,255,255,0.9)");
  g.addColorStop(0.5, "rgba(200,230,255,0.25)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 256);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeGlowTexture(): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = 128;
  c.height = 128;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
  g.addColorStop(0, "rgba(255,255,255,0.85)");
  g.addColorStop(0.4, "rgba(255,255,255,0.25)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makePlaqueTexture(text: string): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 128;
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = "#1b2433";
  ctx.fillRect(0, 0, 512, 128);
  ctx.strokeStyle = "#d4af37";
  ctx.lineWidth = 6;
  ctx.strokeRect(10, 10, 492, 108);
  ctx.fillStyle = "#e8d9a0";
  ctx.font = "bold 44px Georgia, serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 256, 68);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/* ------------------------------- camera + mood ------------------------------- */

const NIGHT_SKY = new THREE.Color("#0b1230");
const DAY_SKY = new THREE.Color("#8ec9e8");
const DUSK_SKY = new THREE.Color("#f2a05a");
const ABYSS = new THREE.Color("#02060e");
const SHALLOW = new THREE.Color("#0a2c44");

function Rig() {
  const { camera, scene } = useThree();
  const bg = useMemo(() => new THREE.Color(), []);
  const sky = useMemo(() => new THREE.Color(), []);
  const water = useMemo(() => new THREE.Color(), []);
  const fog = useMemo(() => new THREE.FogExp2("#0a2036", 0.0), []);

  useLayoutEffect(() => {
    scene.fog = fog;
  }, [scene, fog]);

  useFrame((_, dt) => {
    const t = reef.scroll;
    const y = depthAt(t);
    const sway = Math.sin(t * Math.PI * 3) * 0.6;
    const d = Math.min(dt, 0.05);
    camera.position.x = THREE.MathUtils.damp(camera.position.x, sway, 2.5, d);
    camera.position.y = THREE.MathUtils.damp(camera.position.y, y, 4, d);
    camera.position.z = 7;
    camera.lookAt(sway * 0.4, camera.position.y - 1.1, -3);

    const el = sunElevation(reef.sun);
    const day = clamp(el, 0, 1);
    const dusk = clamp(1 - Math.abs(el) * 3.5, 0, 1);
    sky.copy(NIGHT_SKY).lerp(DAY_SKY, day).lerp(DUSK_SKY, dusk * 0.65);
    water.copy(ABYSS).lerp(SHALLOW, 0.25 + day * 0.75);

    const depth01 = clamp(-camera.position.y / 44, 0, 1);
    const under = camera.position.y < 0.4;
    if (under) {
      bg.copy(water).lerp(ABYSS, Math.pow(depth01, 0.8));
      fog.density = lerp(0.026, 0.055, depth01);
    } else {
      bg.copy(sky);
      fog.density = 0.004;
    }
    scene.background = bg;
    fog.color.copy(bg);
  });
  return null;
}

const SUN_NIGHT = new THREE.Color("#6f8fce");
const SUN_DAWN = new THREE.Color("#ff9a4d");
const SUN_NOON = new THREE.Color("#fff2dc");

function SunLight() {
  const ref = useRef<THREE.DirectionalLight>(null!);
  const col = useMemo(() => new THREE.Color(), []);
  useFrame(() => {
    const h = reef.sun;
    const el = sunElevation(h);
    const day = clamp(el, 0, 1);
    const dawn = clamp(1 - Math.abs(el) * 3.5, 0, 1);
    ref.current.position.set(Math.cos((h / 24) * Math.PI * 2) * 12, 9 + el * 6, 5);
    ref.current.intensity = 0.35 + day * 2.2;
    col.copy(SUN_NIGHT).lerp(SUN_NOON, day).lerp(SUN_DAWN, dawn * 0.7);
    ref.current.color.copy(col);
  });
  return (
    <>
      <hemisphereLight args={["#bfe3ff", "#0a1e33", 0.7]} />
      <directionalLight ref={ref} position={[6, 12, 5]} />
      <ambientLight intensity={0.18} />
    </>
  );
}

/* ---------------------------------- water ----------------------------------- */

const WATER_VERT = /* glsl */ `
uniform float uTime;
varying vec3 vPos;
void main() {
  vec3 p = position;
  float w = sin(p.x * 0.25 + uTime * 0.9) * 0.18
          + sin(p.y * 0.35 - uTime * 0.7) * 0.14
          + sin((p.x + p.y) * 0.12 + uTime * 0.5) * 0.22;
  p.z += w;
  vec4 world = modelMatrix * vec4(p, 1.0);
  vPos = world.xyz;
  gl_Position = projectionMatrix * viewMatrix * world;
}
`;

const WATER_FRAG = /* glsl */ `
uniform float uSunEl;
uniform vec3 uSunColor;
varying vec3 vPos;
void main() {
  vec3 n = normalize(cross(dFdx(vPos), dFdy(vPos)));
  vec3 viewDir = normalize(cameraPosition - vPos);
  if (dot(n, viewDir) < 0.0) n = -n;
  float fres = pow(1.0 - abs(dot(n, viewDir)), 2.0);
  float day = clamp(uSunEl, 0.06, 1.0);
  vec3 deep = vec3(0.02, 0.13, 0.22) * day;
  vec3 shallow = vec3(0.10, 0.45, 0.55) * day;
  vec3 col = mix(deep, shallow, fres);
  vec3 sunDir = normalize(vec3(0.3, 1.0, 0.4));
  float spec = pow(max(dot(reflect(-sunDir, n), -viewDir), 0.0), 60.0);
  col += uSunColor * spec * day * 0.9;
  gl_FragColor = vec4(col, 0.88);
}
`;

function Water() {
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSunEl: { value: 1 },
      uSunColor: { value: new THREE.Color("#ffe8c0") },
    }),
    []
  );
  const col = useMemo(() => new THREE.Color(), []);
  useFrame((s) => {
    uniforms.uTime.value = s.clock.elapsedTime;
    const el = sunElevation(reef.sun);
    uniforms.uSunEl.value = el;
    const dawn = clamp(1 - Math.abs(el) * 3.5, 0, 1);
    col.copy(SUN_NOON).lerp(SUN_DAWN, dawn * 0.8);
    uniforms.uSunColor.value.copy(col);
  });
  return (
    <mesh rotation-x={-Math.PI / 2} position-y={0}>
      <planeGeometry args={[240, 240, 110, 110]} />
      <shaderMaterial
        vertexShader={WATER_VERT}
        fragmentShader={WATER_FRAG}
        uniforms={uniforms}
        transparent
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

/* ----------------------------- god rays + snow ------------------------------- */

function GodRays() {
  const tex = useMemo(makeLinearGradientTexture, []);
  const group = useRef<THREE.Group>(null!);
  const rays = useMemo(
    () =>
      new Array(6).fill(0).map((_, i) => ({
        x: -6.5 + i * 2.6,
        rot: i % 2 ? 0.16 : -0.12,
        s: 1 + (i % 3) * 0.4,
      })),
    []
  );
  useFrame((s) => {
    group.current.rotation.y = Math.sin(s.clock.elapsedTime * 0.05) * 0.15;
    const day = clamp(sunElevation(reef.sun), 0, 1);
    group.current.children.forEach((c, i) => {
      const m = (c as THREE.Mesh).material as THREE.MeshBasicMaterial;
      m.opacity = 0.1 * day * (0.65 + 0.35 * Math.sin(s.clock.elapsedTime * 0.5 + i * 1.7));
    });
  });
  return (
    <group ref={group} position={[0, 0, -5]}>
      {rays.map((r, i) => (
        <mesh key={i} position={[r.x, -7, 0]} rotation-z={r.rot} scale={[2.2 * r.s, 17, 1]}>
          <planeGeometry />
          <meshBasicMaterial
            map={tex}
            transparent
            opacity={0.08}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
    </group>
  );
}

function Snow() {
  const count = reef.lowPower ? 220 : 520;
  const ref = useRef<THREE.Points>(null!);
  const seeds = useMemo(() => {
    const rng = mulberry32(7);
    const pos = new Float32Array(count * 3);
    const speed = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (rng() - 0.5) * 24;
      pos[i * 3 + 1] = -rng() * 46;
      pos[i * 3 + 2] = -9 + rng() * 11;
      speed[i] = 0.1 + rng() * 0.18;
    }
    return { pos, speed };
  }, [count]);
  useFrame((s, dt) => {
    const attr = ref.current.geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    const t = s.clock.elapsedTime;
    for (let i = 0; i < count; i++) {
      arr[i * 3 + 1] -= seeds.speed[i] * dt;
      arr[i * 3] += Math.sin(t * 0.4 + i) * 0.0015;
      if (arr[i * 3 + 1] < -46) arr[i * 3 + 1] = -0.5;
    }
    attr.needsUpdate = true;
  });
  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[seeds.pos, 3]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.05}
        color="#cfe8ff"
        transparent
        opacity={0.45}
        depthWrite={false}
        sizeAttenuation
      />
    </points>
  );
}

/* ----------------------------------- fish ------------------------------------ */

interface FishSpec {
  cx: number;
  cy: number;
  cz: number;
  r: number;
  phase: number;
  speed: number;
  vert: number;
  school: number;
}

const SCHOOL_COLORS = ["#ffb347", "#7fd8ff", "#c792ff"];

function Fish() {
  const total = reef.lowPower ? 45 : 90;
  const ref = useRef<THREE.InstancedMesh>(null!);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const ahead = useMemo(() => new THREE.Vector3(), []);
  const specs = useMemo<FishSpec[]>(() => {
    const rng = mulberry32(11);
    const centers = [
      { x: -2, y: -7.5, z: -3.5 },
      { x: 2.5, y: -18, z: -4.5 },
      { x: -1.5, y: -30, z: -3 },
    ];
    return new Array(total).fill(0).map((_, i) => {
      const s = i % 3;
      return {
        cx: centers[s].x + (rng() - 0.5) * 2,
        cy: centers[s].y + (rng() - 0.5) * 3,
        cz: centers[s].z + (rng() - 0.5) * 2,
        r: 1.6 + rng() * 2.4,
        phase: rng() * Math.PI * 2,
        speed: 0.25 + rng() * 0.3,
        vert: 0.3 + rng() * 0.6,
        school: s,
      };
    });
  }, [total]);
  const geo = useMemo(() => {
    const g = new THREE.ConeGeometry(0.075, 0.3, 5);
    g.rotateX(Math.PI / 2);
    return g;
  }, []);
  useLayoutEffect(() => {
    const c = new THREE.Color();
    for (let i = 0; i < total; i++) {
      c.set(SCHOOL_COLORS[specs[i].school]);
      ref.current.setColorAt(i, c);
    }
    if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
  }, [specs, total]);
  useFrame((s) => {
    const t = s.clock.elapsedTime;
    for (let i = 0; i < total; i++) {
      const f = specs[i];
      const a = t * f.speed + f.phase;
      const px = f.cx + Math.cos(a) * f.r;
      const py = f.cy + Math.sin(a * 0.63 + f.phase) * f.vert;
      const pz = f.cz + Math.sin(a) * f.r * 0.7;
      const a2 = a + 0.12;
      ahead.set(
        f.cx + Math.cos(a2) * f.r,
        f.cy + Math.sin(a2 * 0.63 + f.phase) * f.vert,
        f.cz + Math.sin(a2) * f.r * 0.7
      );
      dummy.position.set(px, py, pz);
      dummy.lookAt(ahead);
      dummy.updateMatrix();
      ref.current.setMatrixAt(i, dummy.matrix);
    }
    ref.current.instanceMatrix.needsUpdate = true;
  });
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, total]} geometry={geo}>
      <meshStandardMaterial flatShading roughness={0.6} />
    </instancedMesh>
  );
}

/* --------------------------------- reefscape --------------------------------- */

interface Inst {
  pos: THREE.Vector3;
  quat: THREE.Quaternion;
  scale: THREE.Vector3;
  color: THREE.Color;
}

const CORAL_PALETTE = ["#ff7a59", "#c792ff", "#35e0c2", "#ffc14d", "#ff5aa5", "#7fd8ff"];
const ROCK_COLORS = ["#3a4456", "#2f3947", "#46506a"];

function buildBranches(
  origin: THREE.Vector3,
  dir: THREE.Vector3,
  len: number,
  depth: number,
  color: THREE.Color,
  rng: () => number,
  out: Inst[]
) {
  const end = origin.clone().addScaledVector(dir, len);
  const mid = origin.clone().addScaledVector(dir, len / 2);
  const quat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  out.push({
    pos: mid,
    quat,
    scale: new THREE.Vector3(0.55 + depth * 0.28, len, 0.55 + depth * 0.28),
    color,
  });
  if (depth <= 0) return;
  const kids = 2 + Math.floor(rng() * 2);
  for (let i = 0; i < kids; i++) {
    const axis = new THREE.Vector3(rng() - 0.5, 0.25, rng() - 0.5).normalize();
    const child = dir
      .clone()
      .applyAxisAngle(axis, 0.5 + rng() * 0.6)
      .normalize();
    if (child.y < 0.15) child.y = 0.15 + rng() * 0.3;
    child.normalize();
    buildBranches(end, child, len * (0.62 + rng() * 0.16), depth - 1, color, rng, out);
  }
}

function useReefInstances() {
  return useMemo(() => {
    const rng = mulberry32(1337);
    const rocks: Inst[] = [];
    const branches: Inst[] = [];
    const plates: Inst[] = [];

    // Colony sites the camera passes on the way down: [x, y, z, rockScale]
    const sites: Array<[number, number, number, number]> = [
      [-4.5, -10.5, -4, 1.5],
      [4.8, -12.5, -5.5, 1.8],
      [2.3, -20.8, -1.6, 1.3], // spawning colony (particles rise from here)
      [-4.2, -22.5, -5, 1.6],
      [4.6, -27.5, -4.5, 1.9],
      [-3.6, -33.5, -3.6, 1.4],
      [-2.2, -41.6, -1.2, 1.2], // reef floor, near throne
      [1.8, -41.7, -3.2, 1.7],
      [7.2, -41.5, -2.6, 1.4],
      [-5.4, -41.8, -4.4, 2.1],
    ];

    for (const [x, y, z, s] of sites) {
      const rockCount = 2 + Math.floor(rng() * 2);
      for (let i = 0; i < rockCount; i++) {
        rocks.push({
          pos: new THREE.Vector3(x + (rng() - 0.5) * 1.6, y - 0.2 + (rng() - 0.5) * 0.4, z + (rng() - 0.5) * 1.6),
          quat: new THREE.Quaternion().setFromEuler(
            new THREE.Euler(rng() * Math.PI, rng() * Math.PI, rng() * Math.PI)
          ),
          scale: new THREE.Vector3(
            s * (0.5 + rng() * 0.6),
            s * (0.35 + rng() * 0.5),
            s * (0.5 + rng() * 0.6)
          ),
          color: new THREE.Color(ROCK_COLORS[Math.floor(rng() * ROCK_COLORS.length)]),
        });
      }
      const colonies = 1 + Math.floor(rng() * 2);
      for (let i = 0; i < colonies; i++) {
        const color = new THREE.Color(CORAL_PALETTE[Math.floor(rng() * CORAL_PALETTE.length)]);
        const origin = new THREE.Vector3(x + (rng() - 0.5) * 1.2, y + 0.3, z + (rng() - 0.5) * 1.2);
        const dir = new THREE.Vector3((rng() - 0.5) * 0.5, 1, (rng() - 0.5) * 0.5).normalize();
        buildBranches(origin, dir, 0.5 + rng() * 0.35, 2, color, rng, branches);
      }
      if (rng() > 0.45) {
        plates.push({
          pos: new THREE.Vector3(x + (rng() - 0.5) * 1.4, y + 0.45, z + (rng() - 0.5) * 1.4),
          quat: new THREE.Quaternion().setFromEuler(
            new THREE.Euler((rng() - 0.5) * 0.5, rng() * Math.PI, (rng() - 0.5) * 0.5)
          ),
          scale: new THREE.Vector3(0.8 + rng() * 0.7, 1, 0.8 + rng() * 0.7),
          color: new THREE.Color(CORAL_PALETTE[Math.floor(rng() * CORAL_PALETTE.length)]),
        });
      }
    }
    return { rocks, branches, plates };
  }, []);
}

function InstancedSet({
  items,
  geo,
  roughness = 0.85,
}: {
  items: Inst[];
  geo: THREE.BufferGeometry;
  roughness?: number;
}) {
  const ref = useRef<THREE.InstancedMesh>(null!);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  useLayoutEffect(() => {
    items.forEach((it, i) => {
      dummy.position.copy(it.pos);
      dummy.quaternion.copy(it.quat);
      dummy.scale.copy(it.scale);
      dummy.updateMatrix();
      ref.current.setMatrixAt(i, dummy.matrix);
      ref.current.setColorAt(i, it.color);
    });
    ref.current.instanceMatrix.needsUpdate = true;
    if (ref.current.instanceColor) ref.current.instanceColor.needsUpdate = true;
  }, [items, dummy]);
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, items.length]} geometry={geo}>
      <meshStandardMaterial flatShading roughness={roughness} />
    </instancedMesh>
  );
}

function Reefscape() {
  const { rocks, branches, plates } = useReefInstances();
  const rockGeo = useMemo(() => new THREE.IcosahedronGeometry(1, 1), []);
  const branchGeo = useMemo(() => new THREE.CylinderGeometry(0.035, 0.075, 1, 5), []);
  const plateGeo = useMemo(() => new THREE.CylinderGeometry(0.75, 0.68, 0.09, 9), []);
  return (
    <group>
      <InstancedSet items={rocks} geo={rockGeo} />
      <InstancedSet items={branches} geo={branchGeo} roughness={0.55} />
      <InstancedSet items={plates} geo={plateGeo} roughness={0.6} />
      {/* reef floor */}
      <mesh rotation-x={-Math.PI / 2} position={[0, -42.2, -2]}>
        <planeGeometry args={[120, 60]} />
        <meshStandardMaterial color="#101a2c" flatShading roughness={1} />
      </mesh>
    </group>
  );
}

/* ------------------------------- health ring --------------------------------- */

const RING_GREEN = new THREE.Color("#35e0c2");
const RING_AMBER = new THREE.Color("#ffc14d");
const RING_RED = new THREE.Color("#ff5a4d");

function scoreColor(out: THREE.Color, s: number) {
  if (s >= 70) out.copy(RING_AMBER).lerp(RING_GREEN, (s - 70) / 30);
  else out.copy(RING_RED).lerp(RING_AMBER, s / 70);
}

function HealthRing() {
  const grp = useRef<THREE.Group>(null!);
  const mat = useRef<THREE.MeshStandardMaterial>(null!);
  const spriteMat = useRef<THREE.SpriteMaterial>(null!);
  const light = useRef<THREE.PointLight>(null!);
  const col = useMemo(() => new THREE.Color(), []);
  const glow = useMemo(makeGlowTexture, []);
  useFrame((s, dt) => {
    grp.current.rotation.z += dt * 0.18;
    grp.current.rotation.x = Math.sin(s.clock.elapsedTime * 0.35) * 0.18;
    grp.current.rotation.y = Math.cos(s.clock.elapsedTime * 0.28) * 0.22;
    scoreColor(col, reef.score);
    mat.current.emissive.copy(col);
    mat.current.emissiveIntensity = 1.6;
    spriteMat.current.color.copy(col);
    light.current.color.copy(col);
  });
  return (
    <group position={[2.6, -9.7, -0.5]}>
      <group ref={grp}>
        <mesh>
          <torusGeometry args={[0.95, 0.09, 20, 90]} />
          <meshStandardMaterial ref={mat} color="#0b0f14" roughness={0.3} />
        </mesh>
      </group>
      <sprite scale={[4.6, 4.6, 1]}>
        <spriteMaterial
          ref={spriteMat}
          map={glow}
          transparent
          opacity={0.35}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </sprite>
      <pointLight ref={light} intensity={2.4} distance={7} />
    </group>
  );
}

/* -------------------------------- light rail --------------------------------- */

function LightRail() {
  const mats = useRef<Array<THREE.MeshStandardMaterial | null>>([]);
  useFrame(() => {
    CHANNELS.forEach((c, i) => {
      const m = mats.current[i];
      if (m) m.emissiveIntensity = 0.12 + c.curve(reef.sun) * 2.6;
    });
  });
  return (
    <group position={[-2.9, -15.5, -1.2]}>
      <mesh position={[0, 0.32, 0]}>
        <boxGeometry args={[2.7, 0.14, 0.5]} />
        <meshStandardMaterial color="#151c28" roughness={0.4} metalness={0.5} />
      </mesh>
      {CHANNELS.map((c, i) => (
        <mesh key={c.id} position={[-1.19 + i * 0.34, 0.18, 0]}>
          <boxGeometry args={[0.24, 0.1, 0.34]} />
          <meshStandardMaterial
            ref={(m) => {
              mats.current[i] = m;
            }}
            color="#0b0f14"
            emissive={c.color}
            emissiveIntensity={0.5}
          />
        </mesh>
      ))}
    </group>
  );
}

/* ------------------------------- spawn burst --------------------------------- */

const SPAWN_ORIGINS = [
  new THREE.Vector3(2.3, -20.6, -1.6),
  new THREE.Vector3(2.9, -21.0, -2.4),
];

function Spawn() {
  const N = 520;
  const ref = useRef<THREE.Points>(null!);
  const matRef = useRef<THREE.PointsMaterial>(null!);
  const state = useMemo(
    () => ({
      pos: new Float32Array(N * 3),
      vel: new Float32Array(N * 3),
      life: 0,
      seen: 0,
      rng: mulberry32(99),
    }),
    []
  );
  useFrame((s, dt) => {
    if (reef.spawnPulse !== state.seen) {
      state.seen = reef.spawnPulse;
      state.life = 8;
      for (let i = 0; i < N; i++) {
        const o = SPAWN_ORIGINS[i % SPAWN_ORIGINS.length];
        state.pos[i * 3] = o.x + (state.rng() - 0.5) * 0.7;
        state.pos[i * 3 + 1] = o.y + (state.rng() - 0.5) * 0.5;
        state.pos[i * 3 + 2] = o.z + (state.rng() - 0.5) * 0.7;
        state.vel[i * 3] = (state.rng() - 0.5) * 0.12;
        state.vel[i * 3 + 1] = 0.22 + state.rng() * 0.45;
        state.vel[i * 3 + 2] = (state.rng() - 0.5) * 0.12;
      }
    }
    const attr = ref.current.geometry.getAttribute("position") as THREE.BufferAttribute;
    if (state.life > 0) {
      state.life -= dt;
      const t = s.clock.elapsedTime;
      const arr = attr.array as Float32Array;
      for (let i = 0; i < N; i++) {
        arr[i * 3] = state.pos[i * 3] += (state.vel[i * 3] + Math.sin(t + i) * 0.02) * dt;
        arr[i * 3 + 1] = state.pos[i * 3 + 1] += state.vel[i * 3 + 1] * dt;
        arr[i * 3 + 2] = state.pos[i * 3 + 2] += state.vel[i * 3 + 2] * dt;
      }
      attr.needsUpdate = true;
      matRef.current.opacity = clamp(state.life / 2.5, 0, 1) * 0.95;
    } else {
      matRef.current.opacity = 0;
    }
  });
  return (
    <points ref={ref} frustumCulled={false}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[state.pos, 3]} />
      </bufferGeometry>
      <pointsMaterial
        ref={matRef}
        size={0.085}
        color="#ffc2cf"
        transparent
        opacity={0}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        sizeAttenuation
      />
    </points>
  );
}

/* ------------------------------- dosing pumps -------------------------------- */

function DosingPumps() {
  const heads = useRef<Array<THREE.Mesh | null>>([]);
  useFrame((_, dt) => {
    heads.current.forEach((h, i) => {
      if (h) h.rotation.z += dt * (1.2 + i * 0.5);
    });
  });
  const labels = ["ALK", "CA", "MG"];
  return (
    <group position={[5.8, -32.9, -1.6]}>
      <mesh position={[0.65, -0.55, 0]}>
        <boxGeometry args={[3.4, 0.16, 1.4]} />
        <meshStandardMaterial color="#151c28" roughness={0.5} />
      </mesh>
      {labels.map((_, i) => (
        <group key={i} position={[i * 1.15 - 0.4, 0, 0]}>
          <mesh>
            <boxGeometry args={[0.62, 0.42, 0.4]} />
            <meshStandardMaterial color="#1d2635" roughness={0.35} metalness={0.3} />
          </mesh>
          <mesh
            ref={(m) => {
              heads.current[i] = m;
            }}
            position={[0, 0.06, 0.24]}
          >
            <cylinderGeometry args={[0.16, 0.16, 0.1, 12]} />
            <meshStandardMaterial color="#35e0c2" roughness={0.3} />
          </mesh>
          <mesh position={[-0.2, -0.1, 0.21]}>
            <sphereGeometry args={[0.03, 8, 8]} />
            <meshStandardMaterial color="#0b0f14" emissive="#35e0c2" emissiveIntensity={2} />
          </mesh>
          <mesh position={[0, 0.5, 0.24]}>
            <cylinderGeometry args={[0.025, 0.025, 0.75, 6]} />
            <meshStandardMaterial color="#7fd8ff" transparent opacity={0.6} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

/* ------------------------------- exploded kit -------------------------------- */

function KitExploded() {
  const grp = useRef<THREE.Group>(null!);
  useFrame((s) => {
    grp.current.rotation.y = s.clock.elapsedTime * 0.28;
    grp.current.position.y = Math.sin(s.clock.elapsedTime * 0.6) * 0.12;
  });
  const chip = (x: number, z: number, i: number) => (
    <mesh key={i} position={[x, 0.05, z]}>
      <boxGeometry args={[0.12, 0.05, 0.09]} />
      <meshStandardMaterial color="#10151d" roughness={0.4} />
    </mesh>
  );
  return (
    <group position={[-5.5, -32.7, -1.8]} scale={1.15}>
      <group ref={grp}>
        {/* enclosure base */}
        <mesh position={[0, 0, 0]}>
          <boxGeometry args={[1.1, 0.12, 0.8]} />
          <meshStandardMaterial color="#1d2635" roughness={0.5} />
        </mesh>
        {/* main board */}
        <group position={[0, 0.55, 0]}>
          <mesh>
            <boxGeometry args={[0.95, 0.05, 0.65]} />
            <meshStandardMaterial color="#0f7a4d" roughness={0.45} />
          </mesh>
          {[chip(-0.25, 0.1, 0), chip(0.1, -0.12, 1), chip(0.3, 0.14, 2)]}
        </group>
        {/* relay module */}
        <group position={[0, 1.1, 0]}>
          <mesh>
            <boxGeometry args={[0.9, 0.08, 0.6]} />
            <meshStandardMaterial color="#1a3f8f" roughness={0.45} />
          </mesh>
          {[-0.3, -0.1, 0.1, 0.3].map((x, i) => (
            <mesh key={i} position={[x, 0.09, 0]}>
              <boxGeometry args={[0.15, 0.12, 0.22]} />
              <meshStandardMaterial color="#10151d" roughness={0.4} />
            </mesh>
          ))}
        </group>
        {/* PSU */}
        <mesh position={[0, 1.65, 0]}>
          <boxGeometry args={[0.6, 0.26, 0.5]} />
          <meshStandardMaterial color="#6a7486" roughness={0.35} metalness={0.5} />
        </mesh>
        {/* enclosure lid */}
        <mesh position={[0, 2.2, 0]}>
          <boxGeometry args={[1.1, 0.12, 0.8]} />
          <meshStandardMaterial color="#1d2635" roughness={0.5} />
        </mesh>
        {/* assembly guide line */}
        <mesh position={[0, 1.1, 0]}>
          <cylinderGeometry args={[0.008, 0.008, 2.5, 6]} />
          <meshBasicMaterial color="#35e0c2" transparent opacity={0.35} />
        </mesh>
      </group>
      <pointLight color="#35e0c2" intensity={2.5} distance={6} position={[0.6, 1.4, 1.2]} />
    </group>
  );
}

/* ---------------------------------- throne ----------------------------------- */

function Throne() {
  const spot = useRef<THREE.SpotLight>(null!);
  const plaque = useMemo(() => makePlaqueTexture("A VERY GOOD BOX"), []);
  useLayoutEffect(() => {
    spot.current.target.position.set(-5.5, -41.2, -1.8);
    spot.current.target.updateMatrixWorld();
  }, []);
  return (
    <group position={[-5.5, -41.7, -1.8]} scale={1.4}>
      {/* stone throne */}
      <mesh position={[0, 0.32, -0.28]}>
        <boxGeometry args={[1.05, 1.5, 0.22]} />
        <meshStandardMaterial color="#2a3242" roughness={0.9} flatShading />
      </mesh>
      <mesh position={[0, 0.12, 0]}>
        <boxGeometry args={[1.05, 0.26, 0.8]} />
        <meshStandardMaterial color="#323b4e" roughness={0.9} flatShading />
      </mesh>
      <mesh position={[-0.55, 0.42, 0]}>
        <boxGeometry args={[0.16, 0.7, 0.8]} />
        <meshStandardMaterial color="#2a3242" roughness={0.9} flatShading />
      </mesh>
      <mesh position={[0.55, 0.42, 0]}>
        <boxGeometry args={[0.16, 0.7, 0.8]} />
        <meshStandardMaterial color="#2a3242" roughness={0.9} flatShading />
      </mesh>
      {/* the very good box */}
      <group position={[0, 0.44, 0.05]}>
        <mesh>
          <boxGeometry args={[0.52, 0.3, 0.36]} />
          <meshStandardMaterial color="#0c0f14" roughness={0.35} metalness={0.2} />
        </mesh>
        <mesh position={[0.17, 0.05, 0.185]}>
          <sphereGeometry args={[0.022, 8, 8]} />
          <meshStandardMaterial color="#0b0f14" emissive="#38ff70" emissiveIntensity={3} />
        </mesh>
        {/* tiny crown */}
        <group position={[0, 0.24, 0]} rotation-z={0.12}>
          <mesh>
            <torusGeometry args={[0.12, 0.025, 8, 20]} />
            <meshStandardMaterial color="#d4af37" metalness={0.8} roughness={0.3} />
          </mesh>
          {[-0.08, 0, 0.08].map((x, i) => (
            <mesh key={i} position={[x, 0.07, 0]}>
              <coneGeometry args={[0.028, 0.09, 6]} />
              <meshStandardMaterial color="#d4af37" metalness={0.8} roughness={0.3} />
            </mesh>
          ))}
        </group>
      </group>
      {/* plaque */}
      <mesh position={[0, -0.02, 0.62]} rotation-x={-0.5}>
        <planeGeometry args={[0.9, 0.22]} />
        <meshBasicMaterial map={plaque} />
      </mesh>
      <spotLight
        ref={spot}
        position={[0.4, 3.4, 1.6]}
        angle={0.5}
        penumbra={0.6}
        intensity={42}
        distance={12}
        color="#ffe8b0"
      />
    </group>
  );
}

/* --------------------------------- CTA glow ---------------------------------- */

function CtaGlow() {
  const glow = useMemo(makeGlowTexture, []);
  return (
    <group position={[0, -44.6, -2.5]}>
      <pointLight color="#35e0c2" intensity={6} distance={16} />
      <sprite scale={[10, 10, 1]}>
        <spriteMaterial
          map={glow}
          color="#1fae96"
          transparent
          opacity={0.45}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </sprite>
    </group>
  );
}

/* ---------------------------------- export ----------------------------------- */

export default function Scene() {
  return (
    <div className="canvas-wrap" aria-hidden="true">
      <Canvas
        dpr={[1, 1.75]}
        camera={{ fov: 55, position: [0, 4, 7], near: 0.1, far: 140 }}
        gl={{ antialias: true, powerPreference: "high-performance" }}
      >
        <Rig />
        <SunLight />
        <Water />
        <GodRays />
        <Snow />
        <Fish />
        <Reefscape />
        <HealthRing />
        <LightRail />
        <Spawn />
        <DosingPumps />
        <KitExploded />
        <Throne />
        <CtaGlow />
      </Canvas>
    </div>
  );
}
