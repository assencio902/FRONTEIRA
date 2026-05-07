/**
 * app.js – Main application logic
 * FRONTEIRA INTELIGENTE – Sistema de Controle de Fronteira com LPR
 */

(function () {
  'use strict';

  /* ================================================================
     Utility helpers
  ================================================================ */
  function el(id) { return document.getElementById(id); }

  function statusBadge(status) {
    var cls = {
      'Liberado':  'badge-status-liberado',
      'Alerta':    'badge-status-alerta',
      'Bloqueado': 'badge-status-bloqueado',
    }[status] || 'bg-secondary';
    return '<span class="badge ' + cls + '">' + esc(status) + '</span>';
  }

  function directionBadge(dir) {
    if (dir === 'Entrada') return '<span class="badge bg-success">&#x2192; Entrada</span>';
    return '<span class="badge bg-danger">&#x2190; Sa&iacute;da</span>';
  }

  function esc(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatDateTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function showToast(message, type) {
    var toast = el('liveToast');
    var body  = el('toastMessage');
    toast.className = 'toast align-items-center border-0 text-white bg-' + (type || 'primary');
    body.textContent = message;
    var bsToast = bootstrap.Toast.getOrCreateInstance(toast, { delay: 3500 });
    bsToast.show();
  }

  /* ================================================================
     Clock
  ================================================================ */
  function updateClock() {
    var now = new Date();
    el('clockDisplay').textContent = now.toLocaleTimeString('pt-BR');
  }
  setInterval(updateClock, 1000);
  updateClock();

  /* ================================================================
     Navigation
  ================================================================ */
  var pages = ['dashboard', 'lpr', 'vehicles', 'crossings', 'alerts'];

  function showPage(name) {
    pages.forEach(function (p) {
      var sec = el('page-' + p);
      if (sec) sec.classList.toggle('d-none', p !== name);
    });
    document.querySelectorAll('.nav-link[data-page]').forEach(function (link) {
      link.classList.toggle('active', link.dataset.page === name);
    });
    if (name === 'dashboard')  renderDashboard();
    if (name === 'vehicles')   renderVehicles();
    if (name === 'crossings')  renderCrossings();
    if (name === 'alerts')     renderAlerts();
  }

  document.querySelectorAll('.nav-link[data-page]').forEach(function (link) {
    link.addEventListener('click', function (e) {
      e.preventDefault();
      showPage(link.dataset.page);
    });
  });

  /* ================================================================
     Dashboard
  ================================================================ */
  var chartHourly = null;
  var chartStatus = null;

  function renderDashboard() {
    var crossings = DB.getCrossings();
    var today     = new Date().toLocaleDateString('pt-BR');
    var todayCrossings = crossings.filter(function (c) {
      return new Date(c.timestamp).toLocaleDateString('pt-BR') === today;
    });

    var total    = todayCrossings.length;
    var ok       = todayCrossings.filter(function (c) { return c.status === 'Liberado'; }).length;
    var alert    = todayCrossings.filter(function (c) { return c.status === 'Alerta'; }).length;
    var blocked  = todayCrossings.filter(function (c) { return c.status === 'Bloqueado'; }).length;

    el('statTotal').textContent   = total;
    el('statOk').textContent      = ok;
    el('statAlert').textContent   = alert;
    el('statBlocked').textContent = blocked;

    /* Hourly bar chart */
    var hours = Array.from({ length: 24 }, function (_, i) { return i; });
    var hourlyCounts = hours.map(function (h) {
      return todayCrossings.filter(function (c) {
        return new Date(c.timestamp).getHours() === h;
      }).length;
    });

    var ctx1 = el('chartHourly').getContext('2d');
    if (chartHourly) chartHourly.destroy();
    chartHourly = new Chart(ctx1, {
      type: 'bar',
      data: {
        labels: hours.map(function (h) { return h + 'h'; }),
        datasets: [{
          label: 'Passagens',
          data: hourlyCounts,
          backgroundColor: 'rgba(13,110,253,0.7)',
          borderColor: '#0d6efd',
          borderWidth: 1,
          borderRadius: 4,
        }],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
      },
    });

    /* Status pie chart */
    var ctx2 = el('chartStatus').getContext('2d');
    if (chartStatus) chartStatus.destroy();
    chartStatus = new Chart(ctx2, {
      type: 'doughnut',
      data: {
        labels: ['Liberado', 'Alerta', 'Bloqueado'],
        datasets: [{
          data: [ok, alert, blocked],
          backgroundColor: ['#198754', '#ffc107', '#dc3545'],
        }],
      },
      options: {
        plugins: {
          legend: { position: 'bottom' },
        },
        cutout: '65%',
      },
    });

    /* Recent crossings */
    var tbody = el('recentCrossingsBody');
    var recent = crossings.slice(0, 10);
    tbody.innerHTML = recent.map(function (c) {
      return '<tr>'
        + '<td class="text-muted small">' + esc(formatDateTime(c.timestamp)) + '</td>'
        + '<td><code class="fw-bold">' + esc(c.plate) + '</code></td>'
        + '<td>' + esc(c.model) + '</td>'
        + '<td>' + esc(c.owner) + '</td>'
        + '<td>' + esc(c.checkpoint) + '</td>'
        + '<td>' + statusBadge(c.status) + '</td>'
        + '</tr>';
    }).join('');
  }

  /* ================================================================
     LPR Scanner
  ================================================================ */
  var lprSamplePlates = ['ABC1234', 'XYZ5678', 'DEF9012', 'GHI3456', 'JKL7890', 'MNO1122', 'PQR3344', 'STU5566', 'VWX9900', 'ZZZ0001'];

  function doScan(plate) {
    plate = plate.trim().replace(/[^A-Z0-9]/gi, '').toUpperCase();
    if (!plate || plate.length < 5) {
      showToast('Informe uma placa válida.', 'warning');
      return;
    }

    /* Show plate in camera overlay */
    var pd = el('plateDetected');
    pd.textContent = plate;
    pd.classList.remove('d-none');

    var checkpoint = el('lprCheckpoint').value;
    var direction  = document.querySelector('input[name="direction"]:checked').value;
    var vehicle    = DB.findVehicleByPlate(plate);

    var status = vehicle ? vehicle.status : 'Alerta';
    var model  = vehicle ? vehicle.model  : 'Não cadastrado';
    var owner  = vehicle ? vehicle.owner  : 'Desconhecido';
    var obs    = vehicle ? vehicle.obs    : 'Veículo não encontrado na base de dados';

    /* Record crossing */
    var crossing = DB.addCrossing({
      timestamp:  new Date().toISOString(),
      plate:      plate,
      model:      model,
      owner:      owner,
      checkpoint: checkpoint,
      direction:  direction,
      status:     status,
      agent:      'Agente Admin',
    });

    /* Create alert if needed */
    if (status !== 'Liberado') {
      DB.addAlert({
        plate:      plate,
        model:      model,
        owner:      owner,
        status:     status,
        checkpoint: checkpoint,
        direction:  direction,
        obs:        obs,
        crossingId: crossing.id,
      });
      updateAlertBadge();
    }

    /* Render result */
    renderLprResult(plate, vehicle, status, model, owner, obs, crossing);
  }

  function renderLprResult(plate, vehicle, status, model, owner, obs, crossing) {
    var colorMap = { 'Liberado': 'success', 'Alerta': 'warning', 'Bloqueado': 'danger' };
    var iconMap  = { 'Liberado': 'check-circle-fill', 'Alerta': 'exclamation-triangle-fill', 'Bloqueado': 'x-octagon-fill' };
    var color    = colorMap[status] || 'secondary';
    var icon     = iconMap[status]  || 'question-circle';

    var html = '<div class="text-center mb-3">'
      + '<i class="bi bi-' + icon + ' text-' + color + '" style="font-size:3rem"></i>'
      + '</div>'
      + '<div class="text-center result-plate mb-3 text-' + color + '">' + esc(plate) + '</div>'
      + '<div class="alert alert-' + (status === 'Liberado' ? 'success' : (status === 'Alerta' ? 'warning' : 'danger')) + ' fw-semibold text-center fs-5 mb-3">'
      + statusBadge(status) + ' &nbsp; ' + esc(status === 'Liberado' ? 'ACESSO PERMITIDO' : (status === 'Alerta' ? 'VEÍCULO EM ALERTA' : 'ACESSO BLOQUEADO'))
      + '</div>';

    html += '<table class="table table-sm table-bordered">'
      + '<tr><th width="40%">Modelo</th><td>' + esc(model) + '</td></tr>'
      + '<tr><th>Proprietário</th><td>' + esc(owner) + '</td></tr>';
    if (vehicle) {
      html += '<tr><th>Cor / Ano</th><td>' + esc(vehicle.color) + ' / ' + esc(String(vehicle.year)) + '</td></tr>'
        + '<tr><th>Documento</th><td>' + esc(vehicle.doc) + '</td></tr>'
        + '<tr><th>Nacionalidade</th><td>' + esc(vehicle.nationality) + '</td></tr>';
    }
    html += '<tr><th>Ponto</th><td>' + esc(crossing.checkpoint) + ' – ' + esc(crossing.direction) + '</td></tr>'
      + '<tr><th>Hora</th><td>' + esc(formatDateTime(crossing.timestamp)) + '</td></tr>';
    if (obs) {
      html += '<tr><th>Observação</th><td class="text-danger fw-semibold">' + esc(obs) + '</td></tr>';
    }
    html += '</table>';

    el('lprResult').innerHTML = html;

    var toastType = { 'Liberado': 'success', 'Alerta': 'warning', 'Bloqueado': 'danger' }[status] || 'primary';
    showToast((status === 'Liberado' ? '✅ Liberado: ' : (status === 'Alerta' ? '⚠️ Alerta: ' : '🚫 Bloqueado: ')) + plate, toastType);
  }

  el('btnScan').addEventListener('click', function () {
    doScan(el('lprInput').value);
  });

  el('lprInput').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') doScan(el('lprInput').value);
  });

  el('btnSimulate').addEventListener('click', function () {
    var plate = lprSamplePlates[Math.floor(Math.random() * lprSamplePlates.length)];
    el('lprInput').value = plate;

    /* Camera "scanning" animation */
    el('cameraOverlay').innerHTML = '<div class="spinner-border text-primary" role="status"></div><br/><span class="small text-white mt-2">Detectando…</span>';
    el('plateDetected').classList.add('d-none');

    setTimeout(function () {
      el('cameraOverlay').innerHTML = '<i class="bi bi-camera-video fs-1"></i><br /><span class="small">Câmera Ativa</span>';
      doScan(plate);
    }, 1200);
  });

  /* ================================================================
     Vehicles
  ================================================================ */
  function renderVehicles(filter) {
    var list = DB.getVehicles();
    if (filter) {
      var q  = (filter.q || '').toLowerCase();
      var st = filter.status || '';
      list = list.filter(function (v) {
        var matchQ  = !q  || v.plate.toLowerCase().includes(q) || v.model.toLowerCase().includes(q) || v.owner.toLowerCase().includes(q);
        var matchSt = !st || v.status === st;
        return matchQ && matchSt;
      });
    }

    var tbody = el('vehiclesBody');
    if (!list.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Nenhum veículo encontrado.</td></tr>';
      return;
    }
    tbody.innerHTML = list.map(function (v) {
      return '<tr>'
        + '<td><code class="fw-bold">' + esc(v.plate) + '</code></td>'
        + '<td>' + esc(v.model) + '</td>'
        + '<td>' + esc(v.color) + '</td>'
        + '<td>' + esc(String(v.year)) + '</td>'
        + '<td>' + esc(v.owner) + '</td>'
        + '<td class="text-muted small">' + esc(v.doc) + '</td>'
        + '<td>' + esc(v.nationality) + '</td>'
        + '<td>' + statusBadge(v.status) + '</td>'
        + '<td>'
        +   '<button class="btn btn-sm btn-outline-primary me-1 btn-edit-vehicle" data-id="' + v.id + '" title="Editar"><i class="bi bi-pencil"></i></button>'
        +   '<button class="btn btn-sm btn-outline-danger btn-delete-vehicle" data-id="' + v.id + '" title="Excluir"><i class="bi bi-trash"></i></button>'
        + '</td>'
        + '</tr>';
    }).join('');

    /* Edit buttons */
    document.querySelectorAll('.btn-edit-vehicle').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = Number(btn.dataset.id);
        var v  = DB.getVehicles().find(function (x) { return x.id === id; });
        if (!v) return;
        fillVehicleModal(v);
        bootstrap.Modal.getOrCreateInstance(el('vehicleModal')).show();
      });
    });

    /* Delete buttons */
    document.querySelectorAll('.btn-delete-vehicle').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (!confirm('Confirmar exclusão do veículo?')) return;
        DB.deleteVehicle(Number(btn.dataset.id));
        renderVehicles();
        showToast('Veículo excluído.', 'secondary');
      });
    });
  }

  function fillVehicleModal(v) {
    el('vehicleId').value  = v ? String(v.id) : '';
    el('vPlate').value      = v ? v.plate        : '';
    el('vModel').value      = v ? v.model        : '';
    el('vColor').value      = v ? v.color        : '';
    el('vYear').value       = v ? String(v.year) : '';
    el('vOwner').value      = v ? v.owner        : '';
    el('vDoc').value        = v ? v.doc          : '';
    el('vNationality').value= v ? v.nationality  : '';
    el('vStatus').value     = v ? v.status       : 'Liberado';
    el('vObs').value        = v ? v.obs          : '';
  }

  el('btnAddVehicle').addEventListener('click', function () {
    fillVehicleModal(null);
  });

  el('btnSaveVehicle').addEventListener('click', function () {
    var plate = el('vPlate').value.trim().replace(/\s/g, '').toUpperCase();
    var model = el('vModel').value.trim();
    var owner = el('vOwner').value.trim();
    if (!plate || !model || !owner) {
      showToast('Preencha os campos obrigatórios.', 'warning');
      return;
    }

    var id = el('vehicleId').value ? Number(el('vehicleId').value) : null;
    DB.upsertVehicle({
      id:          id || 0,
      plate:       plate,
      model:       model,
      color:       el('vColor').value.trim(),
      year:        parseInt(el('vYear').value, 10) || 0,
      owner:       owner,
      doc:         el('vDoc').value.trim(),
      nationality: el('vNationality').value.trim(),
      status:      el('vStatus').value,
      obs:         el('vObs').value.trim(),
    });

    bootstrap.Modal.getOrCreateInstance(el('vehicleModal')).hide();
    renderVehicles();
    showToast('Veículo salvo com sucesso.', 'success');
  });

  el('btnVehicleFilter').addEventListener('click', function () {
    renderVehicles({ q: el('vehicleSearch').value, status: el('vehicleStatusFilter').value });
  });

  el('vehicleSearch').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') el('btnVehicleFilter').click();
  });

  /* ================================================================
     Crossings Log
  ================================================================ */
  function renderCrossings(filter) {
    var list = DB.getCrossings();
    if (filter) {
      var q  = (filter.q || '').toLowerCase();
      var st = filter.status || '';
      var cp = filter.checkpoint || '';
      list = list.filter(function (c) {
        var mQ  = !q  || c.plate.toLowerCase().includes(q) || c.owner.toLowerCase().includes(q);
        var mSt = !st || c.status === st;
        var mCp = !cp || c.checkpoint === cp;
        return mQ && mSt && mCp;
      });
    }

    el('crossingsCount').textContent = list.length;
    var tbody = el('crossingsBody');
    if (!list.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Nenhuma passagem encontrada.</td></tr>';
      return;
    }
    tbody.innerHTML = list.map(function (c) {
      return '<tr>'
        + '<td class="text-muted small">' + esc(formatDateTime(c.timestamp)) + '</td>'
        + '<td><code class="fw-bold">' + esc(c.plate) + '</code></td>'
        + '<td>' + esc(c.model) + '</td>'
        + '<td>' + esc(c.owner) + '</td>'
        + '<td>' + esc(c.checkpoint) + '</td>'
        + '<td>' + directionBadge(c.direction) + '</td>'
        + '<td>' + statusBadge(c.status) + '</td>'
        + '<td class="text-muted small">' + esc(c.agent) + '</td>'
        + '</tr>';
    }).join('');
  }

  el('btnCrossingFilter').addEventListener('click', function () {
    renderCrossings({
      q:          el('crossingSearch').value,
      status:     el('crossingStatusFilter').value,
      checkpoint: el('crossingCheckpointFilter').value,
    });
  });

  el('btnExportCrossings').addEventListener('click', function () {
    var list = DB.getCrossings();
    var header = ['Data/Hora', 'Placa', 'Modelo', 'Proprietario', 'Ponto', 'Direcao', 'Status', 'Agente'];
    var rows   = list.map(function (c) {
      return [
        formatDateTime(c.timestamp),
        c.plate, c.model, c.owner, c.checkpoint, c.direction, c.status, c.agent
      ].map(function (v) { return '"' + String(v).replace(/"/g, '""') + '"'; }).join(',');
    });
    var csv  = [header.join(',')].concat(rows).join('\n');
    var blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    var url  = URL.createObjectURL(blob);
    var a    = document.createElement('a');
    a.href = url;
    a.download = 'passagens_fronteira.csv';
    a.click();
    URL.revokeObjectURL(url);
    showToast('CSV exportado.', 'success');
  });

  /* ================================================================
     Alerts
  ================================================================ */
  function updateAlertBadge() {
    var unread = DB.getAlerts().filter(function (a) { return !a.read; }).length;
    el('alertBadge').textContent = unread;
    el('alertBadge').classList.toggle('d-none', unread === 0);
  }

  function renderAlerts() {
    var list = DB.getAlerts();
    var container = el('alertsContainer');
    if (!list.length) {
      container.innerHTML = '<div class="alert alert-secondary"><i class="bi bi-check-all me-2"></i>Nenhum alerta ativo.</div>';
      return;
    }
    container.innerHTML = list.map(function (a) {
      var cls = a.status === 'Bloqueado' ? 'alert-card-bloqueado' : 'alert-card-alerta';
      var bg  = a.status === 'Bloqueado' ? 'danger' : 'warning';
      var read = a.read ? 'opacity-50' : '';
      return '<div class="card shadow-sm border-0 mb-3 ' + cls + ' ' + read + '">'
        + '<div class="card-body">'
        + '<div class="d-flex justify-content-between align-items-start">'
        + '<div>'
        + '<span class="badge bg-' + bg + ' mb-1">' + esc(a.status) + '</span>'
        + (a.read ? ' <span class="badge bg-secondary">Lido</span>' : '')
        + '<h5 class="mb-1"><code>' + esc(a.plate) + '</code> &mdash; ' + esc(a.model) + '</h5>'
        + '<p class="mb-1 text-muted small">'
        + '<i class="bi bi-person-fill me-1"></i>' + esc(a.owner)
        + ' &nbsp;|&nbsp; <i class="bi bi-geo-alt-fill me-1"></i>' + esc(a.checkpoint) + ' – ' + esc(a.direction)
        + ' &nbsp;|&nbsp; <i class="bi bi-clock me-1"></i>' + esc(formatDateTime(a.timestamp))
        + '</p>'
        + (a.obs ? '<p class="mb-0 text-danger small"><i class="bi bi-exclamation-triangle-fill me-1"></i>' + esc(a.obs) + '</p>' : '')
        + '</div>'
        + (!a.read
          ? '<button class="btn btn-sm btn-outline-secondary btn-mark-read" data-id="' + a.id + '">Marcar como lido</button>'
          : '')
        + '</div>'
        + '</div>'
        + '</div>';
    }).join('');

    document.querySelectorAll('.btn-mark-read').forEach(function (btn) {
      btn.addEventListener('click', function () {
        DB.markAlertRead(Number(btn.dataset.id));
        renderAlerts();
        updateAlertBadge();
      });
    });
  }

  el('btnClearAlerts').addEventListener('click', function () {
    if (!confirm('Limpar todos os alertas?')) return;
    DB.clearAlerts();
    renderAlerts();
    updateAlertBadge();
    showToast('Alertas limpos.', 'secondary');
  });

  /* ================================================================
     Boot
  ================================================================ */
  updateAlertBadge();
  showPage('dashboard');
})();
