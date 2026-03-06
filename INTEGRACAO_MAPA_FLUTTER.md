# 🗺️ Integração do Mapa Flutter com Backend

## ✅ Resumo da Implementação

O app Flutter agora **consome a mesma API** que o sistema web para exibir câmeras no mapa. Não há coordenadas fixas no código - tudo vem do backend existente.

---

## 📡 Endpoints Utilizados

### 1. **GET `/api/v1/cameras?include_inactive=true`**

**Arquivo web que usa:** [ingest/static/dashboard.html](ingest/static/dashboard.html) (linha 5421)

**Função JavaScript:**
```javascript
async function loadMapa() {
  var rCams = await fetch('/api/cameras?include_inactive=true');
  var dCams = await rCams.json();
  var cameras = dCams.items || [];
  // ... renderiza marcadores no mapa Leaflet
}
```

**Backend:** [ingest/api/camera_router.py](ingest/api/camera_router.py) (linha 9-64)

**Exemplo de JSON retornado:**
```json
{
  "items": [
    {
      "id": 1,
      "camera_id": "CAM_BR101_KM350",
      "nome": "Câmera BR-101 Norte",
      "ativa": true,
      "criticidade": "CRITICA",
      "peso_score": 1.5,
      "created_at": "2024-01-15T10:30:00",
      "ip": "192.168.1.100",
      "last_seen": "2026-03-06T14:25:30",
      "total_events": 15420,
      "events_today": 234,
      "direcao": "CRESCENTE",
      "latitude": -15.123456,
      "longitude": -52.654321,
      "modo_integracao": "push",
      "usuario": null
    },
    {
      "id": 2,
      "camera_id": "CAM_BR262_KM120",
      "nome": "Câmera BR-262 Sul",
      "ativa": true,
      "criticidade": "NORMAL",
      "peso_score": 1.0,
      "created_at": "2024-02-10T08:15:00",
      "ip": "192.168.1.101",
      "last_seen": "2026-03-06T14:20:15",
      "total_events": 8932,
      "events_today": 145,
      "direcao": "DECRESCENTE",
      "latitude": -16.789012,
      "longitude": -51.234567,
      "modo_integracao": "listen",
      "usuario": "admin"
    }
  ],
  "total": 2
}
```

**Campos principais:**
- `latitude`, `longitude` → Coordenadas GPS da câmera
- `nome` → Nome da câmera exibido no marcador
- `camera_id` → Identificador único
- `criticidade` → "CRITICA" ou "NORMAL"
- `direcao` → "CRESCENTE" ou "DECRESCENTE"
- `last_seen` → Timestamp da última comunicação (para status online/offline)
- `events_today` / `total_events` → Estatísticas de eventos
- `ip` → Endereço IP da câmera
- `ativa` → Se a câmera está ativa

---

### 2. **GET `/api/v1/cameras/status`**

**Arquivo web que usa:** [ingest/static/dashboard.html](ingest/static/dashboard.html) (linha 5422)

**Backend:** [ingest/api/camera_router.py](ingest/api/camera_router.py) (linha 66-79)

**Exemplo de JSON retornado:**
```json
{
  "status": {
    "CAM_BR101_KM350": "2026-03-06T14:25:30",
    "CAM_BR262_KM120": "2026-03-06T14:20:15",
    "CAM_BR364_KM085": null
  }
}
```

**Uso:** Fornece o timestamp da última comunicação (`last_seen`) para cada câmera, permitindo calcular se está online/offline.

---

## 📦 Arquivos Criados/Modificados

### 1. ✨ **Novo: `flutter_app/lib/models/camera.dart`**

Model Flutter que representa uma câmera retornada pela API.

**Principais recursos:**
- Factory `Camera.fromJson()` para parsing do JSON
- Getter `hasGps` → verifica se tem coordenadas válidas
- Getter `status` → calcula status baseado em `last_seen`:
  - **Online** → última comunicação < 5 minutos
  - **Recente** → última comunicação < 1 hora
  - **Offline** → última comunicação < 24 horas
  - **Inativa** ou **Sem comunicação**
- Getter `statusColor` → retorna cor hex para o status
- Classe `CameraListResponse` para o envelope `{items, total}`

**Exemplo de uso:**
```dart
final camera = Camera.fromJson(jsonMap);
print('${camera.nome} está ${camera.status}'); // "Câmera BR-101 Norte está Online"
if (camera.hasGps) {
  print('GPS: ${camera.latitude}, ${camera.longitude}');
}
```

---

### 2. ✨ **Novo: `flutter_app/lib/services/camera_service.dart`**

Serviço para consumir os endpoints de câmeras.

**Métodos:**
- `getCameras({includeInactive: true})` → Busca lista completa de câmeras
- `getCameraStatus()` → Busca mapa de status
- `getCamerasWithGps()` → Retorna apenas câmeras com GPS válido

**Exemplo de uso:**
```dart
final response = await CameraService.instance.getCameras(includeInactive: true);
print('Total: ${response.total} câmeras');
print('Com GPS: ${response.withGps.length}');
print('Sem GPS: ${response.withoutGps.length}');

for (final camera in response.withGps) {
  print('${camera.nome}: [${camera.latitude}, ${camera.longitude}]');
}
```

**Tratamento de erros:**
- Lança `ApiException` para erros HTTP (401, 404, 500, etc.)
- Loga errors com `debugPrint` para troubleshooting

---

### 3. 🔧 **Modificado: `flutter_app/lib/screens/trajectory_screen.dart`**

Tela de mapa do app Flutter agora **carrega e exibe câmeras** do backend.

**Alterações principais:**

#### Imports adicionados:
```dart
import '../models/camera.dart';
import '../services/camera_service.dart';
```

#### Estado adicionado:
```dart
List<Camera> _cameras = [];          // Câmeras carregadas da API
bool _loadingCameras = false;        // Flag de loading
bool _showCamerasOnMap = true;       // Toggle para mostrar/ocultar câmeras
```

#### Carregamento automático:
```dart
@override
void initState() {
  super.initState();
  _loadCameras();  // Carrega câmeras assim que a tela abre
}

Future<void> _loadCameras() async {
  setState(() => _loadingCameras = true);
  try {
    final response = await CameraService.instance.getCameras(includeInactive: true);
    if (!mounted) return;
    setState(() {
      _cameras = response.withGps;
      _loadingCameras = false;
    });
  } catch (e) {
    setState(() => _loadingCameras = false);
    debugPrint('[TrajectoryScreen] Erro ao carregar câmeras: $e');
  }
}
```

#### Marcadores no mapa:
```dart
final markers = <Marker>{
  // Marcadores de trajetória (verde/amarelo/vermelho)
  for (var i = 0; i < validEntries.length; i++)
    Marker(
      markerId: MarkerId('pt_${validEntries[i].key}'),
      position: LatLng(...),
      icon: BitmapDescriptor.defaultMarkerWithHue(...),
      onTap: () => _showPointDetails(...),
    ),
  
  // ✨ NOVO: Marcadores de câmeras (azul/roxo)
  if (_showCamerasOnMap)
    ...(_cameras.map((camera) {
      return Marker(
        markerId: MarkerId('cam_${camera.cameraId}'),
        position: LatLng(camera.latitude!, camera.longitude!),
        icon: BitmapDescriptor.defaultMarkerWithHue(
          camera.status == 'Online' 
            ? BitmapDescriptor.hueAzure   // Azul = online
            : BitmapDescriptor.hueViolet  // Roxo = offline/inativa
        ),
        onTap: () => _showCameraDetails(camera),
        infoWindow: InfoWindow(
          title: '📹 ${camera.nome}',
          snippet: camera.status,
        ),
      );
    })),
};
```

#### Popup de detalhes da câmera:
```dart
void _showCameraDetails(Camera camera) {
  showModalBottomSheet(
    context: context,
    backgroundColor: _kCard,
    builder: (context) => Container(
      padding: const EdgeInsets.all(20),
      child: Column(
        children: [
          Text('📹 ${camera.nome}', style: TextStyle(fontSize: 18)),
          Text(camera.cameraId, style: TextStyle(color: Colors.grey)),
          Divider(),
          _DetailRow(icon: Icons.router, label: 'IP', value: camera.ip ?? '—'),
          _DetailRow(icon: Icons.circle, label: 'Status', value: camera.status),
          _DetailRow(icon: Icons.navigation, label: 'Direção', value: camera.direcao ?? '—'),
          _DetailRow(icon: Icons.warning_amber, label: 'Criticidade', value: camera.criticidade),
          _DetailRow(icon: Icons.event, label: 'Eventos Hoje', value: camera.eventsToday.toString()),
          _DetailRow(icon: Icons.analytics, label: 'Total de Eventos', value: camera.totalEvents.toString()),
          _DetailRow(icon: Icons.access_time, label: 'Última Comunicação', value: camera.lastSeen ?? '—'),
          Text('📍 ${camera.latitude}, ${camera.longitude}', style: TextStyle(fontSize: 11)),
        ],
      ),
    ),
  );
}
```

#### UI para togglear câmeras:
```dart
// Switch adicionado no painel de busca
Container(
  child: Row(
    children: [
      Icon(Icons.videocam, color: Colors.grey),
      Text('Exibir câmeras no mapa (${_cameras.length} câmeras)'),
      Switch(
        value: _showCamerasOnMap,
        onChanged: (value) => setState(() => _showCamerasOnMap = value),
        activeColor: Colors.yellow,
      ),
    ],
  ),
)
```

---

## 🎨 Diferenciação Visual no Mapa

Para que o usuário diferencie facilmente câmeras de pontos de trajetória:

| Tipo | Cor do Marcador | Significado |
|------|----------------|-------------|
| 🟢 **Início da Trajetória** | Verde | Primeiro ponto detectado |
| 🟠 **Fim da Trajetória** | Laranja | Último ponto detectado |
| 🔴 **Pontos Intermediários** | Vermelho | Passagens intermediárias |
| 🔵 **Câmera Online** | Azul (Azure) | Câmera com comunicação < 5 min |
| 🟣 **Câmera Offline/Inativa** | Roxo (Violet) | Câmera sem comunicação recente |

---

## 🚀 Como Usar no App

1. **Abrir o app Flutter** e navegar para a tela **"Mapas & Rotas"** (trajectory_screen)

2. **Câmeras carregam automaticamente** ao abrir a tela:
   - Loading aparece no switch: "Exibir câmeras no mapa ..."
   - Quando carregar, mostra o total: "(15 câmeras)"

3. **Toggle câmeras no mapa:**
   - Use o switch para mostrar/ocultar marcadores de câmeras
   - Padrão: câmeras **visíveis**

4. **Visualizar detalhes:**
   - **Toque em um marcador azul/roxo** → Abre popup com:
     - Nome, ID, IP, Status, Direção, Criticidade
     - Eventos hoje e total de eventos
     - Última comunicação
     - Coordenadas GPS

5. **Buscar trajetória de placa:**
   - Informe placa + período
   - Clique em "Buscar"
   - Mapa mostra:
     - **Pontos de passagem** (verde/laranja/vermelho)
     - **Câmeras** (azul/roxo) - se o switch estiver ativo
     - **Linha de trajetória** conectando os pontos

---

## 🔍 Fluxo de Dados

```
┌─────────────────────────────────────────────────┐
│  PostgreSQL Database                            │
│  ├── cameras table                              │
│  └── lpr_events table                           │
└────────────────┬────────────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────────────┐
│  FastAPI Backend (ingest/api/camera_router.py)  │
│  ├── GET /api/v1/cameras?include_inactive=true  │
│  └── GET /api/v1/cameras/status                 │
└────────────┬────────────────────────────────────┘
             │
             ├──────────────────────┬───────────────────────┐
             ↓                      ↓                       ↓
┌────────────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Sistema Web           │  │  Flutter App     │  │  Outros clientes │
│  (dashboard.html)      │  │  (Mobile/Desktop)│  │                  │
│  ├── Leaflet + OSM     │  │  ├── Google Maps │  │                  │
│  └── Marcadores        │  │  └── Marcadores  │  │                  │
└────────────────────────┘  └──────────────────┘  └──────────────────┘
```

**Resultado:** Web e mobile **consomem a mesma fonte de dados**. Se você cadastrar uma câmera no sistema web, ela aparece automaticamente no app Flutter após recarregar a tela.

---

## 📋 Checklist de Validação

- ✅ Endpoint `/api/v1/cameras` identificado no sistema web
- ✅ JSON parsing validado (Camera.fromJson)
- ✅ CameraService implementado e testado
- ✅ Marcadores renderizados no GoogleMap
- ✅ Diferenciação visual por cor (azul=online, roxo=offline)
- ✅ Popup de detalhes ao clicar no marcador
- ✅ Toggle show/hide câmeras no mapa
- ✅ Carregamento automático no initState
- ✅ Sem coordenadas fixas no código - tudo vem do backend
- ✅ Estrutura atual do app preservada

---

## 🐛 Troubleshooting

### Problema: "Câmeras não aparecem no mapa"

**Possíveis causas:**
1. **Switch desligado** → Ativar "Exibir câmeras no mapa"
2. **API retorna erro 401** → Token expirado, fazer login novamente
3. **Backend down** → Verificar se o servidor FastAPI está rodando
4. **Câmeras sem GPS** → Endpoint só retorna câmeras com `latitude` e `longitude` válidos

**Debug:**
```dart
// Os logs aparecem no console quando há problemas:
[CameraService] GET http://localhost:8000/api/v1/cameras?include_inactive=true
[CameraService] Response: 200
[CameraService] Loaded 15 cameras (12 with GPS)
```

### Problema: "Marcadores de câmeras sobrepõem marcadores de trajetória"

**Solução:** Os marcadores têm cores diferentes (câmeras=azul/roxo, trajetória=verde/laranja/vermelho). O Flutter renderiza na ordem do Set, então trajetórias podem sobrepor câmeras. Isso é proposital para que os pontos de passagem fiquem em destaque.

### Problema: "Status sempre mostra 'Sem comunicação'"

**Causa:** Campo `last_seen` vem `null` do backend.

**Solução:** Verificar se a tabela `lpr_events` tem registros recentes para essa câmera. O campo `last_seen` é calculado como `MAX(occurred_at)` no SQL.

---

## 🎯 Próximos Passos (Sugestões)

- [ ] Adicionar filtro por criticidade (mostrar apenas câmeras CRITICAS)
- [ ] Adicionar filtro por status (mostrar apenas Online/Offline)
- [ ] Implementar refresh automático (polling a cada 30s)
- [ ] Adicionar heatmap de eventos (como no sistema web)
- [ ] Visualizar eventos recentes ao clicar na câmera
- [ ] Traçar rotas otimizadas entre câmeras
- [ ] Notificações push quando câmera fica offline

---

## 📝 Resumo Final

**O que foi entregue:**
1. ✅ Análise do endpoint usado no sistema web (`/api/v1/cameras`)
2. ✅ Identificação dos campos de latitude/longitude retornados
3. ✅ Model Flutter (`Camera`) para representar os dados
4. ✅ Service Flutter (`CameraService`) para consumir a API
5. ✅ Integração no mapa (`trajectory_screen.dart`) com marcadores
6. ✅ Exibição de informações detalhadas (nome, IP, status, eventos, etc.)
7. ✅ Sem coordenadas fixas - 100% dinâmico do backend
8. ✅ Estrutura atual do app preservada

**Arquivos modificados/criados:**
- `flutter_app/lib/models/camera.dart` (novo)
- `flutter_app/lib/services/camera_service.dart` (novo)
- `flutter_app/lib/screens/trajectory_screen.dart` (modificado)

**Resultado:** O app Flutter agora exibe **exatamente as mesmas câmeras** que o sistema web, consumindo a mesma API. Adicione/edite/remova câmeras no web e elas aparecerão automaticamente no mobile.
