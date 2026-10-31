import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import './TableScene.css';

export interface TableSceneProps {
  dealSignal?: number;
}

interface CanvasTextureWithEl extends THREE.CanvasTexture {
  __canvas?: HTMLCanvasElement;
}


function makeCardTexture(rank: string, suit: 'spades' | 'hearts' | 'diamonds' | 'clubs'): CanvasTextureWithEl {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 358;
  const ctx = c.getContext('2d')!;
  ctx.fillStyle = '#faf7ef';
  ctx.fillRect(0, 0, 256, 358);
  ctx.strokeStyle = '#d8d2c2';
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 250, 352);
  const color = suit === 'hearts' || suit === 'diamonds' ? '#b3202c' : '#1c1c1e';
  ctx.fillStyle = color;
  ctx.font = 'bold 64px Georgia, serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText(rank, 20, 16);
  ctx.font = '56px serif';
  const glyph = suit === 'spades' ? '\u2660' : suit === 'hearts' ? '\u2665' : suit === 'diamonds' ? '\u2666' : '\u2663';
  ctx.fillText(glyph, 20, 92);
  ctx.save();
  ctx.translate(236, 342);
  ctx.rotate(Math.PI);
  ctx.font = 'bold 64px Georgia, serif';
  ctx.fillText(rank, 0, 0);
  ctx.font = '56px serif';
  ctx.fillText(glyph, 0, 76);
  ctx.restore();
  ctx.font = '140px serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(glyph, 128, 210);
  const tex = new THREE.CanvasTexture(c) as CanvasTextureWithEl;
  tex.__canvas = c;
  tex.anisotropy = 4;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeFeltTexture(): CanvasTextureWithEl {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 512;
  const ctx = c.getContext('2d')!;
  ctx.fillStyle = '#b52b2c';
  ctx.fillRect(0, 0, 512, 512);
  for (let i = 0; i < 9000; i++) {
    const a = Math.random() * 0.09;
    ctx.fillStyle = Math.random() > 0.5 ? `rgba(255,220,220,${a})` : `rgba(20,0,0,${a})`;
    ctx.fillRect(Math.random() * 512, Math.random() * 512, 2, 2);
  }
  const tex = new THREE.CanvasTexture(c) as CanvasTextureWithEl;
  tex.__canvas = c;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeBackTexture(): CanvasTextureWithEl {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 358;
  const ctx = c.getContext('2d')!;
  ctx.fillStyle = '#8e1f28';
  ctx.fillRect(0, 0, 256, 358);
  ctx.strokeStyle = '#f0e8d8';
  ctx.lineWidth = 4;
  ctx.strokeRect(14, 14, 228, 330);
  ctx.lineWidth = 1.5;
  for (let i = -358; i < 256; i += 18) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i + 358, 358);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(i + 358, 0);
    ctx.lineTo(i, 358);
    ctx.stroke();
  }
  const tex = new THREE.CanvasTexture(c) as CanvasTextureWithEl;
  tex.__canvas = c;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

const RANKS = ['Q', 'J', '10', '8', '7', '9'];
const SUITS: Array<'spades' | 'hearts' | 'diamonds' | 'clubs'> = ['spades', 'hearts', 'diamonds', 'clubs', 'spades', 'hearts'];

const TableScene: React.FC<TableSceneProps> = ({ dealSignal }) => {
  const mountRef = useRef<HTMLDivElement>(null);
  const dealRef = useRef<(() => void) | null>(null);
  const [webglFailed, setWebglFailed] = useState(false);
  const [dealing, setDealing] = useState(false);
  const [motionPaused, setMotionPaused] = useState(false);
  const motionRef = useRef(false);

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sync = () => { motionRef.current = media.matches; setMotionPaused(media.matches); };
    sync();
    media.addEventListener('change', sync);
    return () => media.removeEventListener('change', sync);
  }, []);

  const triggerDeal = useCallback(() => {
    if (dealRef.current) dealRef.current();
  }, []);

  useEffect(() => {
    if (dealSignal !== undefined && dealSignal > 0) triggerDeal();
  }, [dealSignal, triggerDeal]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    if (new URLSearchParams(window.location.search).get('view') === 'static') { setWebglFailed(true); return; }

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setWebglFailed(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.7));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    const CAM_BASE = new THREE.Vector3(0, 7.2, 11.5);
    camera.position.copy(CAM_BASE);
    camera.lookAt(0, 0.4, 0);

    const disposables: Array<{ dispose(): void }> = [];
    const track = <T extends { dispose(): void }>(x: T): T => { disposables.push(x); return x; };

    // Lights
    const hemi = new THREE.HemisphereLight(0xfff6e8, 0x3a2a20, 0.55);
    scene.add(hemi);
    const key = new THREE.DirectionalLight(0xfff2dd, 2.2);
    key.position.set(5, 10, 6);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = -10;
    key.shadow.camera.right = 10;
    key.shadow.camera.top = 10;
    key.shadow.camera.bottom = -10;
    key.shadow.bias = -0.0004;
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xdfe8ff, 0.5);
    fill.position.set(-6, 5, -4);
    scene.add(fill);
    const spot = new THREE.SpotLight(0xffe9c4, 60, 20, 0.7, 0.6, 1.6);
    spot.position.set(0, 8.5, 1);
    spot.target.position.set(0, 0, 0);
    scene.add(spot, spot.target);

    const root = new THREE.Group();
    scene.add(root);
    root.rotation.y = -0.16;
    const shadowCanvas = document.createElement('canvas');
    shadowCanvas.width = shadowCanvas.height = 256;
    const shadowContext = shadowCanvas.getContext('2d')!;
    const gradient = shadowContext.createRadialGradient(128, 128, 12, 128, 128, 128);
    gradient.addColorStop(0, 'rgba(35,25,20,0.24)'); gradient.addColorStop(1, 'rgba(35,25,20,0)');
    shadowContext.fillStyle = gradient; shadowContext.fillRect(0, 0, 256, 256);
    const shadowTexture = track(new THREE.CanvasTexture(shadowCanvas));
    const shadowPlane = new THREE.Mesh(new THREE.PlaneGeometry(19, 12), new THREE.MeshBasicMaterial({ map: shadowTexture, transparent: true, depthWrite: false }));
    shadowPlane.rotation.x = -Math.PI / 2; shadowPlane.position.y = -0.02; scene.add(shadowPlane);

    // ---- Table: layered oval rails + felt ----
    const tableGroup = new THREE.Group();
    root.add(tableGroup);

    const feltTex = track(makeFeltTexture());
    feltTex.repeat.set(3, 2);
    const feltMat = track(new THREE.MeshStandardMaterial({ map: feltTex, color: 0xffffff, roughness: 0.95, metalness: 0 }));

    const railMat = track(new THREE.MeshPhysicalMaterial({ color: 0x0c0c0e, roughness: 0.32, metalness: 0.05, clearcoat: 0.55, clearcoatRoughness: 0.3 }));
    const silverMat = track(new THREE.MeshStandardMaterial({ color: 0xc9ccd2, roughness: 0.22, metalness: 1 }));

    // Felt top (flattened cylinder)
    const feltGeo = track(new THREE.CylinderGeometry(4.4, 4.4, 0.18, 64));
    feltGeo.scale(1.45, 1, 1);
    const felt = new THREE.Mesh(feltGeo, feltMat);
    felt.position.y = 1.05;
    felt.receiveShadow = true;
    tableGroup.add(felt);

    // Layered bevelled rails: torus rings scaled to oval
    const railSpecs = [
      { r: 4.46, tube: 0.23, y: 1.1, scale: 1.45 },
      { r: 4.62, tube: 0.16, y: 1.02, scale: 1.45 },
      { r: 4.75, tube: 0.14, y: 0.95, scale: 1.45 },
    ];
    railSpecs.forEach((s, i) => {
      const g = track(new THREE.TorusGeometry(s.r, s.tube, 32, 96));
      const m = new THREE.Mesh(g, i === 1 ? silverMat : railMat);
      m.rotation.x = Math.PI / 2;
      m.scale.set(s.scale, 1, 1);
      m.position.y = s.y;
      m.castShadow = true;
      m.receiveShadow = true;
      tableGroup.add(m);
    });

    // Silver inlay ring on felt edge
    const inlayGeo = track(new THREE.TorusGeometry(4.15, 0.035, 12, 96));
    const inlay = new THREE.Mesh(inlayGeo, silverMat);
    inlay.rotation.x = Math.PI / 2;
    inlay.scale.set(1.45, 1, 1);
    inlay.position.y = 1.15;
    tableGroup.add(inlay);

    // Shallow solid apron gives the tabletop a physical edge under the rim.
    const apronGeo = track(new THREE.CylinderGeometry(4.72, 4.7, 0.28, 96));
    apronGeo.scale(1.45, 1, 1);
    const apron = new THREE.Mesh(apronGeo, railMat);
    apron.position.y = 0.74;
    apron.castShadow = true;
    apron.receiveShadow = true;
    tableGroup.add(apron);

    // Pedestal base
    const pedestalMat = track(new THREE.MeshPhysicalMaterial({ color: 0x141416, roughness: 0.25, metalness: 0.3, clearcoat: 0.8 }));
    const pedGeo = track(new THREE.CylinderGeometry(0.9, 1.5, 1.0, 48));
    const ped = new THREE.Mesh(pedGeo, pedestalMat);
    ped.position.y = 0.5;
    ped.castShadow = true;
    tableGroup.add(ped);
    const footGeo = track(new THREE.CylinderGeometry(2.1, 2.4, 0.16, 48));
    const foot = new THREE.Mesh(footGeo, pedestalMat);
    foot.position.y = 0.08;
    foot.receiveShadow = true;
    tableGroup.add(foot);
    const collarGeo = track(new THREE.TorusGeometry(0.95, 0.06, 12, 48));
    const collar = new THREE.Mesh(collarGeo, silverMat);
    collar.rotation.x = Math.PI / 2;
    collar.position.y = 1.0;
    tableGroup.add(collar);

    // ---- Chip stacks (silver) ----
    // GLM-generated striped edge texture keeps the chip stacks readable in direct light.
    const chipCanvas = document.createElement('canvas');
    chipCanvas.width = 512; chipCanvas.height = 64;
    const chipContext = chipCanvas.getContext('2d')!;
    chipContext.fillStyle = '#f5efe2'; chipContext.fillRect(0, 0, 512, 64);
    chipContext.fillStyle = '#b3202c';
    for (let i = 0; i < 6; i++) chipContext.fillRect(i * 512 / 6 + 29, 0, 26, 64);
    const chipTex = track(new THREE.CanvasTexture(chipCanvas));
    chipTex.colorSpace = THREE.SRGBColorSpace;
    const chipGeo = track(new THREE.CylinderGeometry(0.31, 0.31, 0.075, 32));
    const chipTop = track(new THREE.MeshStandardMaterial({ color: 0xf5efe2, roughness: 0.42, metalness: 0 }));
    const chipSide = track(new THREE.MeshStandardMaterial({ map: chipTex, roughness: 0.42, metalness: 0 }));
    const stackSpots: Array<[number, number]> = [[-3.3, -0.2], [-2.5, -1.5], [3.2, 0.1], [2.5, -1.6], [0.3, -2.2]];
    stackSpots.forEach(([x, z], stackIndex) => {
      const n = 5 + stackIndex % 4;
      for (let i = 0; i < n; i++) {
        const chip = new THREE.Mesh(chipGeo, [chipSide, chipTop, chipTop]);
        chip.position.set(x + (i % 2) * 0.012, 1.16 + i * 0.078, z);
        chip.rotation.y = i * 0.2;
        chip.castShadow = true;
        tableGroup.add(chip);
      }
    });

    // ---- Cards ----
    const backTex = track(makeBackTexture());
    const cardGeo = track(new THREE.BoxGeometry(1.05, 0.025, 1.45));
    interface CardRig { group: THREE.Group; face: THREE.Mesh; delay: number; target: THREE.Vector3; targetRot: number; }
    const cards: CardRig[] = [];
    const faceMats: THREE.MeshStandardMaterial[] = [];
    for (let i = 0; i < 3; i++) {
      const faceTex = track(makeCardTexture(RANKS[i], SUITS[i]));
      const faceMat = track(new THREE.MeshStandardMaterial({ map: faceTex, roughness: 0.55, metalness: 0 }));
      const backMat = track(new THREE.MeshStandardMaterial({ map: backTex, roughness: 0.6, metalness: 0 }));
      const edgeMat = track(new THREE.MeshStandardMaterial({ color: 0xe9e4d6, roughness: 0.7 }));
      const mats = [edgeMat, edgeMat, backMat, faceMat, edgeMat, edgeMat];
      const mesh = new THREE.Mesh(cardGeo, mats);
      mesh.castShadow = true;
      const g = new THREE.Group();
      g.add(mesh);
      // start stacked near center-right (deck)
      g.position.set(1.6, 1.18 + i * 0.024, 0.1);
      g.rotation.y = 0.15;
      tableGroup.add(g);
      const t = (i - 1);
      const target = new THREE.Vector3(t * 1.05, 1.2 + i * 0.025, 1.15 - Math.abs(t) * 0.28);
      cards.push({ group: g, face: mesh, delay: i * 0.09, target, targetRot: -t * 0.26 });
      faceMats.push(faceMat);
    }
    // Two oversized, gently tilted cards give the scene a foreground silhouette.
    const heroCardGeo = track(new THREE.BoxGeometry(1.85, 0.035, 2.75));
    const heroEdge = track(new THREE.MeshStandardMaterial({ color: 0xeee8d9, roughness: 0.62 }));
    [0, 1].forEach((i) => {
      const face = track(makeCardTexture(i === 0 ? 'A' : 'K', i === 0 ? 'spades' : 'hearts'));
      const front = track(new THREE.MeshStandardMaterial({ map: face, roughness: 0.6 }));
      const back = track(new THREE.MeshStandardMaterial({ map: backTex, roughness: 0.6 }));
      const card = new THREE.Mesh(heroCardGeo, [heroEdge, heroEdge, front, back, heroEdge, heroEdge]);
      card.position.set(i === 0 ? -1.05 : 1.05, 2.65 + i * 0.14, 0.45);
      card.rotation.set(0.95, i === 0 ? -0.12 : 0.12, i === 0 ? -0.06 : 0.06);
      card.castShadow = true;
      tableGroup.add(card);
    });

    // Begin with community cards face up.
    cards.forEach((c) => { c.group.position.copy(c.target); c.group.rotation.y = c.targetRot; c.face.rotation.x = Math.PI; c.group.visible = true; });

    // ---- Deal animation ----
    let dealT = -1;
    const DUR = 1.6;
    dealRef.current = () => {
      if (motionRef.current) {
        cards.forEach((c) => { c.group.position.copy(c.target); c.group.rotation.y = c.targetRot; c.face.rotation.x = Math.PI; c.group.visible = true; });
        dealT = -1; setDealing(false); return;
      }
      dealT = 0;
      setDealing(true);
      cards.forEach((c, i) => { c.group.position.set(1.6, 1.18 + i * 0.024, 0.1); c.group.rotation.y = 0.15; c.face.rotation.x = 0; c.group.visible = true; });
    };

    // ---- Pointer parallax ----
    let px = 0, py = 0, tx = 0, ty = 0;
    const onPointer = (e: PointerEvent) => {
      const r = mount.getBoundingClientRect();
      tx = ((e.clientX - r.left) / r.width - 0.5) * 2;
      ty = ((e.clientY - r.top) / r.height - 0.5) * 2;
    };
    window.addEventListener('pointermove', onPointer, { passive: true });

    // ---- Resize ----
    const resize = () => {
      const w = mount.clientWidth || 1;
      const h = mount.clientHeight || 1;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.fov = 38;
      const halfVertical = THREE.MathUtils.degToRad(camera.fov / 2);
      const halfHorizontal = Math.atan(Math.tan(halfVertical) * camera.aspect);
      const distance = (camera.aspect < 0.9 ? 7.5 : 5.6) / Math.sin(Math.min(halfVertical, halfHorizontal));
      CAM_BASE.set(3.0, 7.2, 11.5).normalize().multiplyScalar(Math.max(distance, 18));
      camera.position.copy(CAM_BASE);
      camera.lookAt(0, 0.4, 0);
      camera.updateProjectionMatrix();
    };
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(mount);

    // ---- IntersectionObserver pause ----
    let visible = true;
    let raf = 0;
    const io = new IntersectionObserver((entries) => {
      visible = entries[0].isIntersecting;
      if (visible && !raf) { clock.getDelta(); raf = requestAnimationFrame(tick); }
      else if (!visible && raf) { cancelAnimationFrame(raf); raf = 0; }
    }, { threshold: 0.05 });
    io.observe(mount);

    // ---- Loop ----
    const clock = new THREE.Clock();
    const tick = () => {
      raf = 0;
      if (!visible) return;
      raf = requestAnimationFrame(tick);
      const dt = Math.min(clock.getDelta(), 0.05);
      const t = clock.elapsedTime;

      px += (tx - px) * 0.06;
      py += (ty - py) * 0.06;
      if (!motionRef.current) {
        camera.position.x = CAM_BASE.x + px * 1.1;
        camera.position.y = CAM_BASE.y + py * 0.5;
        camera.position.z = CAM_BASE.z;
        camera.lookAt(0, 0.4, 0);
        root.rotation.y = -0.16 + Math.sin(t * 0.15) * 0.03;
        spot.intensity = 58 + Math.sin(t * 1.3) * 4;
      } else {
        camera.position.copy(CAM_BASE);
        camera.lookAt(0, 0.4, 0);
      }

      if (dealT >= 0) {
        dealT += dt;
        const p = Math.min(dealT / DUR, 1);
        cards.forEach((c, i) => {
          const local = THREE.MathUtils.clamp((p - c.delay / DUR) / (1 - c.delay / DUR), 0, 1);
          const e = 1 - Math.pow(1 - local, 3);
          c.group.position.lerpVectors(new THREE.Vector3(1.6, 1.18 + i * 0.024, 0.1), c.target, e);
          c.group.rotation.y = THREE.MathUtils.lerp(0.15, c.targetRot, e);
          // flip reveal in last 40%
          const flip = THREE.MathUtils.clamp((local - 0.6) / 0.4, 0, 1);
          c.face.rotation.x = flip * Math.PI;
        });
        if (p >= 1) { dealT = -1; setDealing(false); }
      }

      renderer.render(scene, camera);
    };
    tick();

    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
      resizeObserver.disconnect();
      window.removeEventListener('pointermove', onPointer);
      scene.traverse((obj) => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry.dispose();
          const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
          mats.forEach((m) => m.dispose());
        }
      });
      shadowPlane.geometry.dispose();
      shadowPlane.material.dispose();
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
      dealRef.current = null;
    };
  }, []);

  return (
    <section className="ts-hero" aria-label="Decorative poker table illustration">
      <div ref={mountRef} className="ts-canvas-mount" aria-hidden="true" />
      {webglFailed && (
        <div className="ts-fallback" role="img" aria-label="Illustration of an oval poker table with cards and chips">
          <div className="ts-fallback-table">
            <span className="ts-fallback-card">A&spades;</span>
            <span className="ts-fallback-card">K&hearts;</span>
            <span className="ts-fallback-card">Q&clubs;</span>
          </div>
        </div>
      )}
      {!webglFailed && <div className="ts-controls">
        <button type="button" className="ts-motion-btn" aria-pressed={motionPaused} onClick={() => { const next = !motionRef.current; motionRef.current = next; setMotionPaused(next); }}>{motionPaused ? 'Resume motion' : 'Pause motion'}</button>
        <button type="button" className="ts-deal-btn" onClick={triggerDeal} disabled={dealing}>{dealing ? 'Dealing…' : 'Deal cards ↗'}</button>
      </div>}
    </section>
  );
};

export default TableScene;
export { TableScene };
