// import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';
// import { OrbitControls } from 'https://unpkg.com/three@0.160.0/examples/jsm/controls/OrbitControls.js';

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export function render3DScatterPlot(containerId, dataPoints) {
  const container = document.getElementById(containerId);
  const width = container.clientWidth;
  const height = container.clientHeight;

  // 1. Scene, Camera, Renderer
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0f172a); // Dark Navy background

  const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000);
  camera.position.set(30, 25, 45);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(width, height);
  container.appendChild(renderer.domElement);

  // 2. Lights & Orbit Controls
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
  scene.add(ambientLight);
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
  dirLight.position.set(20, 40, 20);
  scene.add(dirLight);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  // 3. Grid Helper
  const gridHelper = new THREE.GridHelper(40, 20, 0x475569, 0x1e293b);
  gridHelper.position.y = -15;
  scene.add(gridHelper);

  // 4. Generate 3D Data Cubes
  const geometry = new THREE.BoxGeometry(1.2, 1.2, 1.2);
  const meshes = [];

  dataPoints.forEach(pt => {
    const material = new THREE.MeshStandardMaterial({
      color: pt.color,
      roughness: 0.3,
      metalness: 0.2,
      transparent: true,
      opacity: 0.85
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(pt.position.x, pt.position.y, pt.position.z);
    mesh.userData = pt; // Store metadata for raycasting tooltips
    
    scene.add(mesh);
    meshes.push(mesh);
  });

  // 5. Tooltip & Raycasting (Hover Detection)
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  const tooltip = document.getElementById('tooltip');

  window.addEventListener('mousemove', (event) => {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / height) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(meshes);

    if (intersects.length > 0) {
      const data = intersects[0].object.userData;
      tooltip.style.display = 'block';
      tooltip.style.left = `${event.clientX + 15}px`;
      tooltip.style.top = `${event.clientY + 15}px`;
      tooltip.innerHTML = `
        <strong>${data.title}</strong><br/>
        Category: ${data.category}<br/>
        Price: $${data.price}<br/>
        Rating: ${data.rating} ★ (${data.reviews} reviews)
      `;
    } else {
      tooltip.style.display = 'none';
    }
  });

  // 6. Animation Loop
  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }
  animate();
}