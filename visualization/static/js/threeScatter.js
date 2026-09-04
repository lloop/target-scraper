import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// Helper: Simple camera-facing text label
function createAxisTitle(text, color) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  canvas.width = 512;
  canvas.height = 128;

  ctx.fillStyle = color;
  ctx.font = 'Bold 44px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 256, 64);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  
  const spriteMaterial = new THREE.SpriteMaterial({ 
    map: texture,
    transparent: true,
    depthTest: false 
  });
  
  const sprite = new THREE.Sprite(spriteMaterial);
  sprite.scale.set(12, 3, 1);
  return sprite;
}

export function render3DScatterPlot(containerId, dataPoints) {
  // Container safety fallback
  const container = document.getElementById(containerId) || document.body;
  const width = container.clientWidth || window.innerWidth;
  const height = container.clientHeight || window.innerHeight;
  const COUNT = dataPoints.length;

  // 1. Scene, Camera, Renderer
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0f172a); // Dark Navy background

  const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000);
  camera.position.set(30, 25, 45);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);

  // 2. Lights & Orbit Controls
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(ambientLight);

  const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
  dirLight.position.set(20, 40, 20);
  scene.add(dirLight);

  const overheadLight = new THREE.DirectionalLight(0x38bdf8, 0.5);
  overheadLight.position.set(0, 50, 0);
  scene.add(overheadLight);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  // 3. Grid Helper & Axes
  const gridHelper = new THREE.GridHelper(40, 20, 0x475569, 0x1e293b);
  gridHelper.position.y = -15;
  scene.add(gridHelper);

  // X-Axis (Price) -> RED
  const xGeo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-20, -15, -20),
    new THREE.Vector3(20, -15, -20)
  ]);
  // X-Axis (Price) -> MUTED RED/CORAL
  scene.add(new THREE.Line(xGeo, new THREE.LineBasicMaterial({ color: 0x9f5a5a, linewidth: 2, transparent: true, opacity: 0.6 })));

  // Y-Axis (Rating) -> MUTED SLATE GREEN
  const yGeo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-20, -15, -20),
    new THREE.Vector3(-20, 15, -20)
  ]);
  scene.add(new THREE.Line(yGeo, new THREE.LineBasicMaterial({ color: 0x5a8f6e, linewidth: 2, transparent: true, opacity: 0.6 })));

  // Z-Axis (Reviews) -> MUTED SLATE BLUE
  const zGeo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-20, -15, -20),
    new THREE.Vector3(-20, -15, 20)
  ]);
  scene.add(new THREE.Line(zGeo, new THREE.LineBasicMaterial({ color: 0x5a789f, linewidth: 2, transparent: true, opacity: 0.6 })));
  // 3D Axis Labels
  const labelX = createAxisTitle("PRICE →", "#ef4444");
  labelX.position.set(24, -15, -20);
  scene.add(labelX);

  const labelY = createAxisTitle("RATING ↑", "#22c55e");
  labelY.position.set(-20, 18, -20);
  scene.add(labelY);

  const labelZ = createAxisTitle("REVIEWS ↗", "#3b82f6");
  labelZ.position.set(-20, -15, 24);
  scene.add(labelZ);

  // 4. Pre-calculate Morph Target Coordinates
  const currentPositions = new Float32Array(COUNT * 3);
  const targetPositions = new Float32Array(COUNT * 3);

  const layouts = {
    scatter: new Float32Array(COUNT * 3),
    towers: new Float32Array(COUNT * 3),
    galaxy: new Float32Array(COUNT * 3)
  };

  const categories = [...new Set(dataPoints.map(p => p.category || 'Default'))];
  const categoryHeights = {};
  categories.forEach(c => (categoryHeights[c] = 0));

  dataPoints.forEach((pt, i) => {
    const idx = i * 3;

    // Layout 1: 3D Scatter Plot
    layouts.scatter[idx] = pt.position.x;
    layouts.scatter[idx + 1] = pt.position.y;
    layouts.scatter[idx + 2] = pt.position.z;

    // Layout 2: Category Towers
    const catIdx = categories.indexOf(pt.category || 'Default');
    const colAngle = (catIdx / categories.length) * Math.PI * 2;
    const radius = 22;
    const towerX = Math.cos(colAngle) * radius;
    const towerZ = Math.sin(colAngle) * radius;
    const towerY = -15 + (categoryHeights[pt.category || 'Default'] || 0) * 0.8;
    categoryHeights[pt.category || 'Default'] = (categoryHeights[pt.category || 'Default'] || 0) + 1;

    layouts.towers[idx] = towerX;
    layouts.towers[idx + 1] = towerY;
    layouts.towers[idx + 2] = towerZ;

    // Layout 3: Price Galaxy Spiral
    const normPrice = Math.max(0.1, pt.price || 1);
    const spiralRadius = Math.sqrt(normPrice) * 3.5;
    const angle = i * 0.15;
    layouts.galaxy[idx] = Math.cos(angle) * spiralRadius;
    layouts.galaxy[idx + 1] = ((pt.rating || 3) - 2.5) * 4;
    layouts.galaxy[idx + 2] = Math.sin(angle) * spiralRadius;

    // Default to scatter plot
    currentPositions[idx] = layouts.scatter[idx];
    currentPositions[idx + 1] = layouts.scatter[idx + 1];
    currentPositions[idx + 2] = layouts.scatter[idx + 2];

    targetPositions[idx] = layouts.scatter[idx];
    targetPositions[idx + 1] = layouts.scatter[idx + 1];
    targetPositions[idx + 2] = layouts.scatter[idx + 2];
  });

  // 5. InstancedMesh Generation (1 Draw Call for 2,000 items)
  const geometry = new THREE.SphereGeometry(0.5, 16, 16);
  const material = new THREE.MeshStandardMaterial({
    roughness: 0.3,
    metalness: 0.2,
    transparent: true,
    opacity: 0.85
  });

  const instancedMesh = new THREE.InstancedMesh(geometry, material, COUNT);
  const dummy = new THREE.Object3D();
  const color = new THREE.Color();

  dataPoints.forEach((pt, i) => {
    dummy.position.set(pt.position.x, pt.position.y, pt.position.z);
    dummy.updateMatrix();
    instancedMesh.setMatrixAt(i, dummy.matrix);

    color.set(pt.color || 0x3b82f6);
    instancedMesh.setColorAt(i, color);
  });

  instancedMesh.instanceMatrix.needsUpdate = true;
  instancedMesh.instanceColor.needsUpdate = true;
  scene.add(instancedMesh);

  // --- CATEGORY TOGGLE SYSTEM ---
  let activeCategories = new Set(categories);
  const currentScales = new Float32Array(COUNT).fill(1);
  const targetScales = new Float32Array(COUNT).fill(1);

  function setupCategoryToggles() {
    const filterContainer = document.getElementById('category-filter-bar');
    if (!filterContainer) return;

    filterContainer.innerHTML = '';

    // Master Toggle Button
    const masterBtn = document.createElement('button');
    masterBtn.className = 'cat-btn active';
    masterBtn.textContent = 'Toggle All';
    masterBtn.style.cssText = 'padding: 6px 12px; cursor: pointer; font-weight: bold;';
    
    masterBtn.onclick = () => {
      if (activeCategories.size === categories.length) {
        activeCategories.clear();
        filterContainer.querySelectorAll('.cat-btn-single').forEach(b => b.classList.remove('active'));
      } else {
        activeCategories = new Set(categories);
        filterContainer.querySelectorAll('.cat-btn-single').forEach(b => b.classList.add('active'));
      }
      updateCategoryScales();
    };
    filterContainer.appendChild(masterBtn);

    // Individual Category Buttons
    categories.forEach(cat => {
      const btn = document.createElement('button');
      btn.className = 'cat-btn cat-btn-single active';
      btn.textContent = cat;
      btn.style.cssText = 'padding: 6px 12px; cursor: pointer;';

      btn.onclick = () => {
        if (activeCategories.has(cat)) {
          activeCategories.delete(cat);
          btn.classList.remove('active');
        } else {
          activeCategories.add(cat);
          btn.classList.add('active');
        }
        updateCategoryScales();
      };

      filterContainer.appendChild(btn);
    });
  }

  function updateCategoryScales() {
    dataPoints.forEach((pt, i) => {
      const cat = pt.category || 'Default';
      targetScales[i] = activeCategories.has(cat) ? 1 : 0;
    });
  }

  setupCategoryToggles();

  // Expose layout switcher globally for UI buttons
  window.switchLayout = function (layoutName) {
    if (!layouts[layoutName]) return;
    const target = layouts[layoutName];
    for (let i = 0; i < COUNT * 3; i++) {
      targetPositions[i] = target[i];
    }
  };

  // 6. Tooltip & Raycasting
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  const tooltip = document.getElementById('tooltip');

  window.addEventListener('mousemove', (event) => {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / height) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObject(instancedMesh);

    if (intersects.length > 0 && tooltip) {
      const instanceId = intersects[0].instanceId;
      const data = dataPoints[instanceId];

      // Hide tooltip if hovered item's category is currently turned off
      if (targetScales[instanceId] === 0) {
        tooltip.style.display = 'none';
        return;
      }

      tooltip.style.display = 'block';
      tooltip.style.left = `${event.clientX + 15}px`;
      tooltip.style.top = `${event.clientY + 15}px`;
      tooltip.innerHTML = `
        <strong>${data.title}</strong><br/>
        Category: ${data.category}<br/>
        Price: $${data.price}<br/>
        Rating: ${data.rating} ★ (${data.reviews} reviews)
      `;
    } else if (tooltip) {
      tooltip.style.display = 'none';
    }
  });

  // 7. Animation & Morphing Loop
  const LERP_FACTOR = 0.05;

  function animate() {
    requestAnimationFrame(animate);

    let needsMatrixUpdate = false;

    for (let i = 0; i < COUNT; i++) {
      const idx = i * 3;

      const cx = currentPositions[idx];
      const cy = currentPositions[idx + 1];
      const cz = currentPositions[idx + 2];

      const tx = targetPositions[idx];
      const ty = targetPositions[idx + 1];
      const tz = targetPositions[idx + 2];

      const cs = currentScales[i];
      const ts = targetScales[i];

      const posChanged = Math.abs(tx - cx) > 0.001 || Math.abs(ty - cy) > 0.001 || Math.abs(tz - cz) > 0.001;
      const scaleChanged = Math.abs(ts - cs) > 0.001;

      if (posChanged || scaleChanged) {
        currentPositions[idx] += (tx - cx) * LERP_FACTOR;
        currentPositions[idx + 1] += (ty - cy) * LERP_FACTOR;
        currentPositions[idx + 2] += (tz - cz) * LERP_FACTOR;

        currentScales[i] += (ts - cs) * LERP_FACTOR;

        dummy.position.set(
          currentPositions[idx],
          currentPositions[idx + 1],
          currentPositions[idx + 2]
        );

        const s = currentScales[i];
        dummy.scale.set(s, s, s);

        dummy.updateMatrix();
        instancedMesh.setMatrixAt(i, dummy.matrix);

        needsMatrixUpdate = true;
      }
    }

    if (needsMatrixUpdate) {
      instancedMesh.instanceMatrix.needsUpdate = true;
    }

    controls.update();
    renderer.render(scene, camera);
  }

  animate();
}