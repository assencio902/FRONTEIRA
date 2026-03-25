
// Callback global para Google Maps API
var _googleMapsReady = false;
function initGoogleMaps() {
  _googleMapsReady = true;
  console.log('[Google Maps] API carregada com sucesso');
}
// Tratamento de erro global do Google Maps
function gm_authFailure() {
  console.error('[Google Maps] Erro de autenticação - verifique a chave da API');
  var noGps = document.getElementById('map-no-gps');
  if (noGps) {
    noGps.innerHTML = '<div style="background:rgba(239,68,68,0.1);border:1px solid var(--danger);border-radius:8px;padding:12px;color:var(--danger)">'
      + '<strong>❌ Erro de Autenticação Google Maps</strong><br>'
      + '<small>A chave da API pode estar inválida, expirada ou sem as permissões necessárias.<br>'
      + 'Verifique: Maps JavaScript API, Visualization API habilitadas.</small>'
      + '</div>';
  }
}
