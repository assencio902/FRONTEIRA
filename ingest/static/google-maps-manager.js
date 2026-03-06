/**
 * GOOGLE MAPS - GERENCIADOR PRINCIPAL
 * Sistema de Monitoramento BPFRON
 * Arquivo: google-maps-manager.js
 * 
 * Este arquivo gerencia toda a integração do Google Maps no sistema.
 * Inclui inicialização, marcadores, trajetórias e controles.
 */

// ====================================================================
// VARIÁVEIS GLOBAIS
// ====================================================================

var googleMapInstance = null;              // Instância do Google Maps
var googleMapMarkers = [];                 // Array de marcadores
var googleMapCurrentMapType = 'hybrid';    // Tipo de mapa atual (roadmap, satellite, hybrid, terrain)
var googleMapTrajectoryPolyline = null;    // Polyline da trajetória
var googleMapTrajectoryMarkers = [];       // Marcadores da trajetória
var googleMapCamerasCache = [];            // Cache das câmeras carregadas

// ====================================================================
// INICIALIZAÇÃO DO MAPA
// ====================================================================

/**
 * Inicializa o Google Maps no container especificado
 * Coordenadas padrão: Centro do Brasil (-15.0, -52.0)
 */
function initGoogleMap() {
  const container = document.getElementById('google-map-container');
  if (!container) {
    console.error('[Google Maps] Container não encontrado: google-map-container');
    return;
  }

  // Configurações iniciais do mapa
  const mapOptions = {
    center: { lat: -15.0, lng: -52.0 },  // Centro do Brasil
    zoom: 5,
    mapTypeId: googleMapCurrentMapType,
    mapTypeControl: false,               // Removemos o controle padrão (usaremos customizado)
    streetViewControl: true,
    fullscreenControl: true,
    zoomControl: true,
    gestureHandling: 'greedy'            // Permite zoom com scroll sem Ctrl
  };

  // Cria a instância do mapa
  googleMapInstance = new google.maps.Map(container, mapOptions);

  // Cria os controles customizados
  createMapTypeSelector();

  console.log('[Google Maps] Inicializado com sucesso');
}

// ====================================================================
// CONTROLE DE TIPO DE MAPA
// ====================================================================

/**
 * Cria o seletor customizado de tipo de mapa
 */
function createMapTypeSelector() {
  if (!googleMapInstance) return;

  const controlDiv = document.createElement('div');
  controlDiv.className = 'map-controls-overlay';
  controlDiv.style.cssText = 'position:absolute;top:10px;right:10px;z-index:1000;';

  const selectorDiv = document.createElement('div');
  selectorDiv.className = 'map-type-selector';
  selectorDiv.innerHTML = `
    <div class="map-type-selector-title">🗺️ Tipo de Mapa</div>
    <button class="map-type-button" data-type="roadmap">
      <span class="map-type-icon">🛣️</span>
      <span>Ruas</span>
    </button>
    <button class="map-type-button" data-type="satellite">
      <span class="map-type-icon">🛰️</span>
      <span>Satélite</span>
    </button>
    <button class="map-type-button active" data-type="hybrid">
      <span class="map-type-icon">🌍</span>
      <span>Híbrido</span>
    </button>
    <button class="map-type-button" data-type="terrain">
      <span class="map-type-icon">⛰️</span>
      <span>Terreno</span>
    </button>
  `;

  // Adiciona event listeners aos botões
  const buttons = selectorDiv.querySelectorAll('.map-type-button');
  buttons.forEach(btn => {
    btn.addEventListener('click', function() {
      const mapType = this.getAttribute('data-type');
      changeMapType(mapType);
    });
  });

  controlDiv.appendChild(selectorDiv);

  // Adiciona ao DOM (fora do mapa para não interferir com controles do Google)
  const mapContainer = document.getElementById('google-map-container');
  if (mapContainer) {
    mapContainer.style.position = 'relative';
    mapContainer.appendChild(controlDiv);
  }
}

/**
 * Altera o tipo de mapa e atualiza a UI
 */
function changeMapType(mapType) {
  if (!googleMapInstance) return;

  googleMapCurrentMapType = mapType;
  googleMapInstance.setMapTypeId(mapType);

  // Atualiza botões ativos
  document.querySelectorAll('.map-type-button').forEach(btn => {
    btn.classList.remove('active');
  });
  document.querySelector(`.map-type-button[data-type="${mapType}"]`)?.classList.add('active');

  console.log(`[Google Maps] Tipo alterado para: ${mapType}`);
}

// ====================================================================
// MARCADORES DE CÂMERAS
// ====================================================================

/**
 * Adiciona um marcador de câmera no mapa
 */
function addCameraMarker(camera, statusColor, statusLabel) {
  if (!googleMapInstance || !camera.latitude || !camera.longitude) return;

  // Define a cor do ícone baseado no status
  const iconUrl = getCameraMarkerIcon(statusColor);

  const marker = new google.maps.Marker({
    position: { lat: camera.latitude, lng: camera.longitude },
    map: googleMapInstance,
    title: camera.nome,
    icon: {
      url: iconUrl,
      scaledSize: new google.maps.Size(32, 32),
      anchor: new google.maps.Point(16, 32)
    }
  });

  // Cria o conteúdo do InfoWindow
  const infoContent = createCameraInfoWindowContent(camera, statusColor, statusLabel);

  const infoWindow = new google.maps.InfoWindow({
    content: infoContent
  });

  // Evento de clique no marcador
  marker.addListener('click', function() {
    // Fecha outras InfoWindows abertas
    googleMapMarkers.forEach(m => {
      if (m.infoWindow) m.infoWindow.close();
    });
    infoWindow.open(googleMapInstance, marker);
  });

  // Armazena referência da InfoWindow
  marker.infoWindow = infoWindow;

  googleMapMarkers.push(marker);
  return marker;
}

/**
 * Retorna URL do ícone do marcador baseado na cor
 */
function getCameraMarkerIcon(color) {
  // Usa marcadores coloridos do Google Maps
  const colorMap = {
    '#22c55e': 'green',   // Online
    '#f59e0b': 'yellow',  // Aguardando
    '#ef4444': 'red',     // Offline
    '#6b7280': 'gray',    // Nunca detectado
    '#a855f7': 'purple'   // Inativa
  };

  const colorName = colorMap[color] || 'red';
  return `http://maps.google.com/mapfiles/ms/icons/${colorName}-dot.png`;
}

/**
 * Cria o conteúdo HTML do InfoWindow
 */
function createCameraInfoWindowContent(camera, statusColor, statusLabel) {
  const critTag = camera.criticidade === 'CRITICA'
    ? '<span style="color:#ef4444;font-weight:700">CRÍTICA</span>'
    : '<span style="color:#86efac">NORMAL</span>';

  const dirTag = camera.direcao
    ? `<br><b>Direção:</b> <span style="color:#facc15">${camera.direcao}</span>`
    : '';

  const camIdEsc = (camera.camera_id || '').replace(/'/g, "\\'");

  return `
    <div class="camera-popup">
      <div class="camera-popup-title">
        📹 ${camera.nome}
      </div>
      <div class="camera-popup-content">
        <b>ID:</b> ${camera.camera_id || '—'}<br>
        <b>IP:</b> <span style="font-family:monospace">${camera.ip || '—'}</span><br>
        <b>Criticidade:</b> ${critTag}${dirTag}<br>
        <b>Status:</b> <span style="color:${statusColor};font-weight:600">${statusLabel}</span><br>
        <b>Eventos hoje:</b> ${camera.events_today || 0} &nbsp;&nbsp;
        <b>Total:</b> ${camera.total_events || 0}
      </div>
      <div class="camera-popup-coords">
        ${camera.latitude.toFixed(6)}, ${camera.longitude.toFixed(6)}
      </div>
      <button class="camera-popup-button" onclick="_filtrarEventosPorCamera('${camIdEsc}')">
        🎯 Ver eventos desta câmera
      </button>
    </div>
  `;
}

/**
 * Remove todos os marcadores do mapa
 */
function clearAllMarkers() {
  googleMapMarkers.forEach(marker => {
    if (marker.infoWindow) marker.infoWindow.close();
    marker.setMap(null);
  });
  googleMapMarkers = [];
}

// ====================================================================
// TRAJETÓRIA DE VEÍCULOS
// ====================================================================

/**
 * Desenha a trajetória de um veículo no mapa
 */
function drawVehicleTrajectory(trajectoryPoints) {
  if (!googleMapInstance || !trajectoryPoints || trajectoryPoints.length === 0) return;

  // Remove trajetória anterior
  clearTrajectory();

  // Cria o polyline da trajetória
  const path = trajectoryPoints.map(p => ({ lat: p.lat, lng: p.lng }));

  googleMapTrajectoryPolyline = new google.maps.Polyline({
    path: path,
    geodesic: true,
    strokeColor: '#ef4444',
    strokeOpacity: 0.8,
    strokeWeight: 4,
    map: googleMapInstance
  });

  // Adiciona marcadores numerados
  trajectoryPoints.forEach((point, index) => {
    const marker = new google.maps.Marker({
      position: { lat: point.lat, lng: point.lng },
      map: googleMapInstance,
      label: {
        text: String(index + 1),
        color: 'white',
        fontSize: '12px',
        fontWeight: 'bold'
      },
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        fillColor: '#ef4444',
        fillOpacity: 1,
        strokeColor: 'white',
        strokeWeight: 2,
        scale: 12
      }
    });

    // InfoWindow com detalhes do ponto
    const infoContent = `
      <div style="font-family:system-ui;min-width:180px">
        <div style="font-weight:700;margin-bottom:6px">📍 Ponto ${index + 1}</div>
        <div style="font-size:0.8rem;line-height:1.6">
          <b>Câmera:</b> ${point.cam_nome || 'N/A'}<br>
          <b>Placa:</b> ${point.plate}<br>
          <b>Data/Hora:</b> ${point.ts ? new Date(point.ts).toLocaleString('pt-BR') : 'N/A'}
        </div>
      </div>
    `;

    const infoWindow = new google.maps.InfoWindow({ content: infoContent });
    marker.addListener('click', () => infoWindow.open(googleMapInstance, marker));

    googleMapTrajectoryMarkers.push(marker);
  });

  // Marcador de início
  if (trajectoryPoints.length > 0) {
    const startPoint = trajectoryPoints[0];
    new google.maps.Marker({
      position: { lat: startPoint.lat, lng: startPoint.lng },
      map: googleMapInstance,
      label: {
        text: '▶ INÍCIO',
        color: 'white',
        fontSize: '9px',
        fontWeight: 'bold'
      },
      icon: {
        path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
        fillColor: '#22c55e',
        fillOpacity: 1,
        strokeColor: 'white',
        strokeWeight: 2,
        scale: 5,
        rotation: 0
      }
    });

    // Marcador de fim
    const endPoint = trajectoryPoints[trajectoryPoints.length - 1];
    new google.maps.Marker({
      position: { lat: endPoint.lat, lng: endPoint.lng },
      map: googleMapInstance,
      label: {
        text: '◼ FIM',
        color: 'white',
        fontSize: '9px',
        fontWeight: 'bold'
      },
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        fillColor: '#f59e0b',
        fillOpacity: 1,
        strokeColor: 'white',
        strokeWeight: 2,
        scale: 8
      }
    });
  }

  // Ajusta o zoom e centro para mostrar toda a trajetória
  const bounds = new google.maps.LatLngBounds();
  path.forEach(point => bounds.extend(point));
  googleMapInstance.fitBounds(bounds);
}

/**
 * Remove a trajetória do mapa
 */
function clearTrajectory() {
  if (googleMapTrajectoryPolyline) {
    googleMapTrajectoryPolyline.setMap(null);
    googleMapTrajectoryPolyline = null;
  }

  googleMapTrajectoryMarkers.forEach(marker => marker.setMap(null));
  googleMapTrajectoryMarkers = [];
}

// ====================================================================
// CARREGAMENTO DE DADOS
// ====================================================================

/**
 * Carrega e exibe as câmeras no mapa (integração com o sistema existente)
 */
async function loadGoogleMapCameras() {
  if (!googleMapInstance) {
    console.error('[Google Maps] Mapa não inicializado');
    return;
  }

  try {
    // Requisições para câmeras e status
    const [rCams, rStatus] = await Promise.all([
      fetch('/api/cameras?include_inactive=true'),
      fetch('/api/cameras/status')
    ]);

    const dCams = await rCams.json();
    const dStatus = rStatus.ok ? await rStatus.json() : {};

    const cameras = dCams.items || [];
    const statusMap = dStatus.status || {};

    googleMapCamerasCache = cameras;

    // Remove marcadores anteriores
    clearAllMarkers();

    // Filtra câmeras com GPS
    const withGps = cameras.filter(c => c.latitude != null && c.longitude != null);
    const withoutGps = cameras.filter(c => c.latitude == null || c.longitude == null);

    // Adiciona marcadores
    const bounds = new google.maps.LatLngBounds();
    withGps.forEach(camera => {
      const lastSeen = statusMap[camera.camera_id] || camera.last_seen || null;
      const color = _mapaStatusColor(lastSeen, camera.ativa);
      const label = camera.ativa === false ? 'Inativa' : _mapaStatusLabel(lastSeen);

      addCameraMarker(camera, color, label);
      bounds.extend({ lat: camera.latitude, lng: camera.longitude });
    });

    // Ajusta zoom para mostrar todas as câmeras
    if (withGps.length > 0) {
      googleMapInstance.fitBounds(bounds);
      
      // Limita o zoom máximo
      google.maps.event.addListenerOnce(googleMapInstance, 'idle', function() {
        if (googleMapInstance.getZoom() > 15) {
          googleMapInstance.setZoom(15);
        }
      });
    }

    // Atualiza lista de câmeras sem GPS
    updateNoGpsCamerasList(withoutGps, statusMap);

    console.log(`[Google Maps] ${withGps.length} câmeras carregadas`);

  } catch (error) {
    console.error('[Google Maps] Erro ao carregar câmeras:', error);
    const noGps = document.getElementById('map-no-gps');
    if (noGps) {
      noGps.innerHTML = `<div style="color:var(--danger);font-size:.82rem">❌ Erro ao carregar câmeras: ${error.message}</div>`;
    }
  }
}

/**
 * Atualiza a lista de câmeras sem GPS
 */
function updateNoGpsCamerasList(withoutGps, statusMap) {
  const noGps = document.getElementById('map-no-gps');
  if (!noGps) return;

  if (!withoutGps.length) {
    noGps.innerHTML = '<div style="font-size:.79rem;color:var(--muted)">✓ Todas as câmeras possuem coordenadas GPS.</div>';
  } else {
    noGps.innerHTML = `
      <div style="font-size:.82rem;color:var(--muted);margin-bottom:10px">
        ⚠️ ${withoutGps.length} câmera(s) sem GPS cadastrado:
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:8px">
        ${withoutGps.map(c => {
          const clr = _mapaStatusColor(statusMap[c.camera_id] || c.last_seen || null, c.ativa);
          return `
            <span style="background:rgba(255,255,255,.06);border:1px solid var(--border);border-radius:8px;padding:6px 12px;font-size:.79rem;display:inline-flex;align-items:center;gap:6px">
              <span style="color:${clr}">●</span>
              ${c.nome}
              <button class="btn btn-outline btn-xs" style="padding:1px 6px;font-size:.7rem" onclick="editCamera(decodeURIComponent('${encodeURIComponent(JSON.stringify(c))}'))">+ GPS</button>
            </span>
          `;
        }).join('')}
      </div>
    `;
  }
}

// ====================================================================
// UTILITÁRIOS
// ====================================================================

/**
 * Adiciona marcador de teste (para demonstração)
 */
function addTestMarker() {
  if (!googleMapInstance) {
    console.error('[Google Maps] Mapa não inicializado');
    return;
  }

  const testMarker = new google.maps.Marker({
    position: { lat: -15.0, lng: -52.0 },
    map: googleMapInstance,
    title: '📍 Marcador de Teste',
    icon: {
      url: 'http://maps.google.com/mapfiles/ms/icons/blue-dot.png',
      scaledSize: new google.maps.Size(32, 32)
    }
  });

  const infoWindow = new google.maps.InfoWindow({
    content: `
      <div style="font-family:system-ui;padding:8px">
        <h3 style="margin:0 0 8px 0;color:#22c55e">✅ Google Maps Integrado!</h3>
        <p style="margin:0;font-size:0.85rem">
          Este é um marcador de teste.<br>
          O sistema está funcionando corretamente.
        </p>
      </div>
    `
  });

  testMarker.addListener('click', () => {
    infoWindow.open(googleMapInstance, testMarker);
  });

  console.log('[Google Maps] Marcador de teste adicionado');
}

// ====================================================================
// EXPORTAÇÃO PARA COMPATIBILIDADE
// ====================================================================

// Compatibilidade com código legado (mantém nome antigo loadMapa)
window.initGoogleMap = initGoogleMap;
window.loadGoogleMapCameras = loadGoogleMapCameras;
window.changeMapType = changeMapType;
window.addTestMarker = addTestMarker;
window.clearTrajectory = clearTrajectory;
window.drawVehicleTrajectory = drawVehicleTrajectory;

console.log('[Google Maps Manager] Módulo carregado com sucesso');
