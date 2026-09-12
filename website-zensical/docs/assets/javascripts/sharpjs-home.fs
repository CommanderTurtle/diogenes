module DiogenesDocs.Assets.HomeJs

let file = """import * as THREE from "./three.module.min.js";

let sceneMounted = false;
let sceneController = null;

function flameMaterial(front) {
  return new THREE.ShaderMaterial({
    uniforms: { time: { value: 0 } },
    vertexShader: `
      uniform float time;
      varying vec2 vUv;
      varying float hValue;

      float random(in vec2 st) {
        return fract(sin(dot(st.xy, vec2(12.9898, 78.233))) * 43758.5453123);
      }

      float noise(in vec2 st) {
        vec2 i = floor(st);
        vec2 f = fract(st);
        float a = random(i);
        float b = random(i + vec2(1.0, 0.0));
        float c = random(i + vec2(0.0, 1.0));
        float d = random(i + vec2(1.0, 1.0));
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(a, b, u.x) +
          (c - a) * u.y * (1.0 - u.x) +
          (d - b) * u.x * u.y;
      }

      void main() {
        vUv = uv;
        vec3 pos = position;
        pos *= vec3(0.8, 2.0, 0.725);
        hValue = position.y;
        float posXZlen = length(position.xz);
        pos.y *= 1.0 +
          (cos((posXZlen + 0.25) * 3.1415926) * 0.25 +
          noise(vec2(0.0, time)) * 0.125 +
          noise(vec2(position.x + time, position.z + time)) * 0.5) * position.y;
        pos.x += noise(vec2(time * 2.0, (position.y - time) * 4.0)) * hValue * 0.0312;
        pos.z += noise(vec2((position.y - time) * 4.0, time * 2.0)) * hValue * 0.0312;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
      }
    `,
    fragmentShader: `
      varying float hValue;
      varying vec2 vUv;

      vec3 heatmapGradient(float t) {
        return clamp(
          (pow(t, 1.5) * 0.8 + 0.2) *
          vec3(smoothstep(0.0, 0.35, t) + t * 0.5,
               smoothstep(0.5, 1.0, t),
               max(1.0 - t * 1.7, t * 7.0 - 6.0)),
          0.0,
          1.0
        );
      }

      void main() {
        float v = abs(smoothstep(0.0, 0.4, hValue) - 1.0);
        float alpha = (1.0 - v) * 0.99;
        alpha -= 1.0 - smoothstep(1.0, 0.97, hValue);
        gl_FragColor = vec4(
          heatmapGradient(smoothstep(0.0, 0.3, hValue)) * vec3(0.95, 0.95, 0.4),
          alpha
        );
        gl_FragColor.rgb = mix(vec3(0.0, 0.0, 1.0), gl_FragColor.rgb, smoothstep(0.0, 0.3, hValue));
        gl_FragColor.rgb += vec3(1.0, 0.9, 0.5) * (1.25 - vUv.y);
        gl_FragColor.rgb = mix(gl_FragColor.rgb, vec3(0.66, 0.32, 0.03), smoothstep(0.95, 1.0, hValue));
      }
    `,
    transparent: true,
    side: front ? THREE.FrontSide : THREE.BackSide
  });
}

function mountFlame() {
  if (sceneMounted) return;
  sceneMounted = true;
  document.body.classList.add("dio-flame-active");

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch (_) {
    document.body.classList.add("dio-no-webgl");
    return;
  }

  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x101005);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.className = "dio-flame-canvas";
  renderer.domElement.setAttribute("aria-label", "Interactive candle");
  document.body.prepend(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 1, 1000);
  const target = new THREE.Vector3(0, 2, 0);
  const baseline = {
    radius: 15,
    azimuth: Math.atan2(3, 8),
    polar: Math.acos((5 - target.y) / 15)
  };
  let radius = baseline.radius;
  let azimuth = baseline.azimuth;
  let polar = baseline.polar;

  function placeCamera() {
    const sinPolar = Math.sin(polar);
    camera.position.set(
      target.x + radius * sinPolar * Math.sin(azimuth),
      target.y + radius * Math.cos(polar),
      target.z + radius * sinPolar * Math.cos(azimuth)
    );
    camera.lookAt(target);
  }
  placeCamera();

  function resetCamera() {
    radius = baseline.radius;
    azimuth = baseline.azimuth;
    polar = baseline.polar;
    placeCamera();
  }

  const directional = new THREE.DirectionalLight(0xffffff, 0.025);
  directional.position.setScalar(10);
  scene.add(directional);
  scene.add(new THREE.AmbientLight(0xffffff, 0.0625));

  const casePath = new THREE.Path();
  casePath.moveTo(0, 0);
  casePath.lineTo(0, 0);
  casePath.absarc(1.5, 0.5, 0.5, Math.PI * 1.5, Math.PI * 2);
  casePath.lineTo(2, 1.5);
  casePath.lineTo(1.99, 1.5);
  casePath.lineTo(1.9, 0.5);
  const caseMesh = new THREE.Mesh(
    new THREE.LatheGeometry(casePath.getPoints(), 64),
    new THREE.MeshStandardMaterial({ color: "silver" })
  );
  caseMesh.castShadow = true;

  const paraffinPath = new THREE.Path();
  paraffinPath.moveTo(0, -0.25);
  paraffinPath.lineTo(0, -0.25);
  paraffinPath.absarc(1, 0, 0.25, Math.PI * 1.5, Math.PI * 2);
  paraffinPath.lineTo(1.25, 0);
  paraffinPath.absarc(1.89, 0.1, 0.1, Math.PI * 1.5, Math.PI * 2);
  const paraffinGeometry = new THREE.LatheGeometry(paraffinPath.getPoints(), 64);
  paraffinGeometry.translate(0, 1.25, 0);
  caseMesh.add(new THREE.Mesh(
    paraffinGeometry,
    new THREE.MeshStandardMaterial({ color: 0xffff99, side: THREE.BackSide, metalness: 0, roughness: 0.75 })
  ));

  const wickProfile = new THREE.Shape();
  wickProfile.absarc(0, 0, 0.0625, 0, Math.PI * 2);
  const wickCurve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0, 0.5, -0.0625),
    new THREE.Vector3(0.25, 0.5, 0.125)
  ]);
  const wickGeometry = new THREE.ExtrudeGeometry(wickProfile, {
    steps: 8,
    bevelEnabled: false,
    extrudePath: wickCurve
  });
  const wickColors = [];
  const wickDark = new THREE.Color("black");
  const wickHot = new THREE.Color(0x994411);
  const wickBase = new THREE.Color(0xffff44);
  for (let index = 0; index < wickGeometry.attributes.position.count; index += 1) {
    const y = wickGeometry.attributes.position.getY(index);
    (y < 0.15 ? wickBase : y < 0.4 ? wickDark : wickHot).toArray(wickColors, index * 3);
  }
  wickGeometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(wickColors), 3));
  wickGeometry.translate(0, 0.95, 0);
  caseMesh.add(new THREE.Mesh(wickGeometry, new THREE.MeshBasicMaterial({ vertexColors: true })));

  const candleLight = new THREE.PointLight(0xffaa33, 1, 5, 2);
  candleLight.position.set(0, 3, 0);
  candleLight.castShadow = true;
  caseMesh.add(candleLight);
  const movingLight = new THREE.PointLight(0xffaa33, 1, 10, 2);
  movingLight.position.set(0, 4, 0);
  movingLight.castShadow = true;
  caseMesh.add(movingLight);

  const flameMaterials = [];
  function addFlame() {
    const geometry = new THREE.SphereGeometry(0.5, 32, 32);
    geometry.translate(0, 0.5, 0);
    const material = flameMaterial(true);
    flameMaterials.push(material);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(0.06, 1.2, 0.06);
    mesh.rotation.y = THREE.MathUtils.degToRad(-45);
    caseMesh.add(mesh);
  }
  addFlame();
  addFlame();

  const texture = new THREE.TextureLoader().load("https://threejs.org/examples/textures/hardwood2_diffuse.jpg");
  const tableGeometry = new THREE.CylinderGeometry(14, 14, 0.5, 64);
  tableGeometry.translate(0, -0.25, 0);
  const tableMesh = new THREE.Mesh(
    tableGeometry,
    new THREE.MeshStandardMaterial({ map: texture, metalness: 0, roughness: 0.75 })
  );
  tableMesh.receiveShadow = true;
  tableMesh.add(caseMesh);
  scene.add(tableMesh);

  let dragging = false;
  let pointerId = null;
  let pointerX = 0;
  let pointerY = 0;
  let homeInteraction = false;

  function isControlTarget(targetNode) {
    if (!(targetNode instanceof Element)) return true;
    return Boolean(targetNode.closest(
      "a, button, input, textarea, select, summary, pre, code, table, " +
      "[contenteditable='true'], .md-search, .md-nav__link, .md-typeset p, " +
      ".md-typeset li, .md-typeset h1, .md-typeset h2, .md-typeset h3, " +
      ".md-typeset h4, .md-typeset blockquote"
    ));
  }

  document.addEventListener("pointerdown", (event) => {
    if (!homeInteraction || event.button !== 0 || isControlTarget(event.target)) return;
    dragging = true;
    pointerId = event.pointerId;
    pointerX = event.clientX;
    pointerY = event.clientY;
    document.body.classList.add("dio-camera-dragging");
  });
  document.addEventListener("pointermove", (event) => {
    if (!dragging || event.pointerId !== pointerId) return;
    azimuth -= (event.clientX - pointerX) * 0.006;
    polar = THREE.MathUtils.clamp(polar + (event.clientY - pointerY) * 0.006, THREE.MathUtils.degToRad(60), THREE.MathUtils.degToRad(95));
    pointerX = event.clientX;
    pointerY = event.clientY;
    placeCamera();
  });
  document.addEventListener("pointerup", (event) => {
    if (event.pointerId !== pointerId) return;
    dragging = false;
    pointerId = null;
    document.body.classList.remove("dio-camera-dragging");
  });
  document.addEventListener("pointercancel", () => {
    dragging = false;
    pointerId = null;
    document.body.classList.remove("dio-camera-dragging");
  });
  document.addEventListener("wheel", (event) => {
    if (!homeInteraction || isControlTarget(event.target)) return;
    event.preventDefault();
    radius = THREE.MathUtils.clamp(radius + Math.sign(event.deltaY) * 0.8, 4, 20);
    placeCamera();
  }, { passive: false });

  sceneController = {
    setHomeInteraction(enabled) {
      homeInteraction = enabled;
      renderer.domElement.setAttribute("aria-label", enabled ? "Interactive candle" : "Candle background");
      if (!enabled) {
        dragging = false;
        pointerId = null;
        document.body.classList.remove("dio-camera-dragging");
        resetCamera();
      }
    }
  };

  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  const clock = new THREE.Clock();
  let time = 0;
  function draw() {
    requestAnimationFrame(draw);
    time += clock.getDelta();
    flameMaterials[0].uniforms.time.value = time;
    flameMaterials[1].uniforms.time.value = time;
    movingLight.position.x = Math.sin(time * Math.PI) * 0.25;
    movingLight.position.z = Math.cos(time * Math.PI * 0.75) * 0.25;
    movingLight.intensity = 2 + Math.sin(time * Math.PI * 2) * Math.cos(time * Math.PI * 1.5) * 0.25;
    renderer.render(scene, camera);
  }
  draw();
}

function syncPage() {
  mountFlame();
  const isHome = Boolean(document.querySelector(".dio-home"));
  document.body.classList.toggle("dio-page-home", isHome);
  sceneController?.setHomeInteraction(isHome);
}

if (typeof document$ !== "undefined") document$.subscribe(syncPage);
else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", syncPage, { once: true });
else syncPage();
"""

let render() = file
