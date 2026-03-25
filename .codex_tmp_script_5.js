
// ===== ALARME — WEB AUDIO API =====
var _audioCtx = null;
var _alarmSoundMuted = false;

function toggleMuteAlarm() {
  _alarmSoundMuted = !_alarmSoundMuted;
  var btn   = document.getElementById('btn-mute-alarm');
  var label = document.getElementById('mute-alarm-label');
  if (!btn || !label) return;
  if (_alarmSoundMuted) {
    btn.classList.remove('btn-outline'); btn.classList.add('btn-warning');
    label.textContent = 'MUDO';
    btn.title = 'Som silenciado — clique para reativar';
  } else {
    btn.classList.remove('btn-warning'); btn.classList.add('btn-outline');
    label.textContent = 'ON';
    btn.title = 'Silenciar/ativar som das notificações';
  }
}

function _getAudioCtx() {
  if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return _audioCtx;
}

function _playTone(freq, duration, startTime, ctx, type) {
  var osc = ctx.createOscillator();
  var gain = ctx.createGain();
  osc.connect(gain); gain.connect(ctx.destination);
  osc.type = type || 'sine';
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0.5, startTime);
  gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration);
  osc.start(startTime); osc.stop(startTime + duration);
}

function playAlarmSound(sound) {
  if (_alarmSoundMuted) return;  // silenciado — pula o som, mantém flash/toast
  try {
    var ctx = _getAudioCtx();
    var t = ctx.currentTime;
    if (sound === 'beep') {
      _playTone(880, 0.35, t, ctx);
      _playTone(880, 0.35, t + 0.45, ctx);
    } else if (sound === 'siren') {
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(440, t);
      osc.frequency.linearRampToValueAtTime(880, t + 0.5);
      osc.frequency.linearRampToValueAtTime(440, t + 1.0);
      osc.frequency.linearRampToValueAtTime(880, t + 1.5);
      gain.gain.setValueAtTime(0.4, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 1.6);
      osc.start(t); osc.stop(t + 1.6);
    } else if (sound === 'bell') {
      _playTone(1047, 1.2, t, ctx);
      _playTone(1319, 0.6, t + 0.05, ctx);
    } else if (sound === 'urgent') {
      for (var i = 0; i < 5; i++) {
        _playTone(i % 2 === 0 ? 1200 : 800, 0.1, t + i * 0.15, ctx, 'square');
      }
    }
  } catch(e) { console.warn('Audio:', e); }
}

// ===== LISTA DE ALERTAS =====

var _alertsList    = [];  // {type, icon, plate, detail, ts, tsISO, seen, data}
var _alertsUnseen  = 0;

function addAlert(type, icon, plate, detail, routeInfo, extraData) {
  var now = new Date();
  var ts  = now.toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  var tsISO = now.toISOString();
  _alertsList.unshift({type:type, icon:icon, plate:plate, detail:detail, ts:ts, tsISO:tsISO, seen:false, route: routeInfo||null, data: extraData||null});
  if (_alertsList.length > 200) _alertsList.pop();
  _alertsUnseen++;
  var badge = document.getElementById('alerts-badge');
  if (badge) { badge.textContent = _alertsUnseen > 99 ? '99+' : _alertsUnseen; badge.style.display = ''; }
}

function _renderAlertsList() {
  var body = document.getElementById('alerts-panel-body');
  if (!body) return;
  if (!_alertsList.length) {
    body.innerHTML = '<div style="color:var(--muted);text-align:center;padding:40px;font-size:.85rem">Nenhum alerta ainda.</div>';
    return;
  }
  body.innerHTML = _alertsList.map(function(a, i) {
    // Cor base: usa a cor da lista (câmera) ou cor fixa por tipo
    var accentColor;
    if (a.type === 'camera' && a.data && a.data.lists && a.data.lists[0] && a.data.lists[0].color) {
      accentColor = a.data.lists[0].color;
    } else if (a.type === 'avistado') {
      accentColor = '#c4b5fd';
    } else if (a.type === 'abordagem') {
      accentColor = '#fbbf24';
    } else {
      accentColor = '#f87171';
    }

    var clickCls   = a.route ? ' clickable' : '';
    var clickAttr  = a.route ? ' onclick="_alertClick(' + i + ')"' : '';
    // Estilo inline: borda lateral + fundo tint baseados na cor da lista
    var itemStyle  = a.seen
      ? 'border-left:3px solid ' + accentColor + '44'
      : 'border-left:3px solid ' + accentColor + ';background:' + accentColor + '18';

    // Relatório detalhado para alertas de câmera
    var reportHtml = '';
    if (a.type === 'camera' && a.data) {
      var d = a.data;
      var dtFmt = a.tsISO
        ? new Date(a.tsISO).toLocaleString('pt-BR', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'})
        : a.ts;
      var listTags = (d.lists || []).map(function(l) {
        return '<span style="background:#3b82f633;color:#3b82f6;border:1px solid #3b82f644;border-radius:99px;padding:1px 8px;font-weight:700;font-size:.72rem;margin-right:3px">' + (l.list_name || l.name) + '</span>';
      }).join('');
      reportHtml =
        '<div class="alert-report" style="background:' + accentColor + '12;border-color:' + accentColor + '44">' +
          '<div class="alert-report-plate" style="color:' + accentColor + '">&#9888; ' + a.plate + '</div>' +
          '<div class="alert-report-row"><span>&#128197; Data/Hora:</span><strong>' + dtFmt + '</strong></div>' +
          (d.camera ? '<div class="alert-report-row"><span>&#128247; C\u00e2mera:</span><strong>' + d.camera + '</strong></div>' : '') +
          (listTags ? '<div class="alert-report-row" style="flex-wrap:wrap;gap:3px"><span>&#128203; Listas:</span>' + listTags + '</div>' : '') +
          (d.sound ? '<div class="alert-report-row"><span>&#128266; Som:</span><strong>' + d.sound + '</strong></div>' : '') +
          (d.direcao ? '<div class="alert-report-row"><span>&#8597; Dire\u00e7\u00e3o:</span><strong style="color:var(--accent)">' + (d.direcao === 'CRESCENTE' ? '&#8593; CRESCENTE' : '&#8595; DECRESCENTE') + '</strong></div>' : '') +
          (a.seen ? '' : '<div style="font-size:.68rem;color:' + accentColor + ';margin-top:4px">&#9679; N\u00e3o visualizado</div>') +
        '</div>';
    }

    return '<div class="alert-item' + (a.seen ? '' : ' unseen') + clickCls + '" style="' + itemStyle + '"' + clickAttr + '>'
      + '<div class="alert-item-icon">' + a.icon + '</div>'
      + '<div style="flex:1;min-width:0">'
        + '<div class="alert-item-plate" style="color:' + accentColor + '">' + a.plate + '</div>'
        + '<div class="alert-item-detail">' + a.detail + '</div>'
        + reportHtml
        + (a.route ? '<div class="alert-item-link">\uD83D\uDD0D Ver relat\u00f3rio</div>' : '')
      + '</div>'
      + '<div class="alert-item-ts">' + a.ts + '</div>'
      + '</div>';
  }).join('');
}

function _alertClick(i) {
  var a = _alertsList[i];
  if (!a || !a.route) return;
  closeAlertsPanel();
  var tipo  = a.route.type;
  var plate = a.route.plate;
  _openToastDetail(tipo, plate);
}

function openAlertsPanel() {
  // marca todos como vistos
  _alertsList.forEach(function(a){ a.seen = true; });
  _alertsUnseen = 0;
  var badge = document.getElementById('alerts-badge');
  if (badge) badge.style.display = 'none';
  // atualiza contador no cabeçalho
  var cnt = document.getElementById('alerts-panel-count');
  if (cnt) cnt.textContent = _alertsList.length ? '(' + _alertsList.length + ' registro' + (_alertsList.length > 1 ? 's' : '') + ')' : '';
  _renderAlertsList();
  document.getElementById('alerts-panel').classList.add('open');
  document.getElementById('alerts-panel-overlay').style.display = 'block';
}

function closeAlertsPanel() {
  document.getElementById('alerts-panel').classList.remove('open');
  document.getElementById('alerts-panel-overlay').style.display = 'none';
}

function clearAlerts() {
  _alertsList = []; _alertsUnseen = 0;
  var badge = document.getElementById('alerts-badge');
  if (badge) badge.style.display = 'none';
  _renderAlertsList();
}

var _alarmToastTimer = null;
var _abordagemTimer = null;
var _alvoAvistadoTimer = null;
var _alvoAvistadoSeen = {};
var _toastPlates = {}; // guarda plate ativo de cada toast

function _openToastDetail(tipo, plate) {
  var toastId = tipo === 'avistado' ? 'alvo-avistado-toast' : 'abordagem-toast';
  document.getElementById(toastId).style.display = 'none';
  plate = plate || _toastPlates[tipo];
  if (!plate) return;
  var batTab = document.querySelector('.nav-item[onclick*="batedor"]');
  if (batTab) batTab.click();
  setTimeout(function() {
    if (tipo === 'abordagem') {
      // abre companheiros do veículo — mostra a relação com o líder/batedor
      var grpTab = document.querySelector('#bat-sub-tabs .sub-tab[onclick*="grupos"]');
      if (grpTab) grpTab.click();
      setTimeout(function(){ openAlvoDetail(plate, ''); }, 80);
    } else {
      var alvosTab = document.querySelector('#bat-sub-tabs .sub-tab[onclick*="alvos"]');
      if (alvosTab) alvosTab.click();
      setTimeout(function(){ openAlvoDetail(plate, ''); }, 80);
    }
  }, 120);
}

// triggerComboio: alarma comboio de 2 ou 3 veículos com papéis identificados
function triggerComboio(batedor, alvo, escolta, cameras, avgDelta) {
  _toastPlates['abordagem'] = alvo;
  _toastPlates['abordagem_leader'] = batedor;
  var membros = [
    {role: '\uD83D\uDEA8 POSS\u00cdVEL BATEDOR',       plate: batedor, cor: '#f87171'},
    {role: '\uD83C\uDFAF POSS\u00cdVEL ALVO A ABORDAR', plate: alvo,    cor: '#fbbf24'}
  ];
  if (escolta) membros.push({role: '\uD83D\uDD12 ESCOLTA / RETAGUARDA', plate: escolta, cor: '#a78bfa'});
  var todasPlacas = membros.map(function(m){ return m.plate; }).join(' + ');
  var detalheAlerta = '\uD83D\uDEA8 Batedor: <strong>' + batedor + '</strong>'
    + ' &nbsp;\uD83C\uDFAF Alvo: <strong>' + alvo + '</strong>'
    + (escolta ? ' &nbsp;\uD83D\uDD12 Escolta: <strong>' + escolta + '</strong>' : '')
    + ' \u2014 ' + cameras + ' c\u00e2mera(s), \u0394' + avgDelta + 's';
  addAlert('abordagem', '&#9888;&#65039;', todasPlacas, detalheAlerta, {type:'abordagem', plate:alvo});
  var toast = document.getElementById('abordagem-toast');
  document.getElementById('abordagem-toast-plate').innerHTML =
    '<div style="display:flex;flex-direction:column;gap:5px;margin:8px 0">'
    + membros.map(function(m) {
        return '<div>'
          + '<span style="font-size:.65rem;font-weight:700;letter-spacing:.08em;opacity:.75;display:block;margin-bottom:2px">' + m.role + '</span>'
          + '<span style="font-size:1.4rem;font-weight:900;letter-spacing:.12em;color:' + m.cor + '">' + m.plate + '</span>'
          + '</div>';
      }).join('')
    + '</div>';
  document.getElementById('abordagem-toast-desc').innerHTML =
    'Vistos juntos em <strong>' + cameras + ' c\u00e2mera(s)</strong>'
    + ' \u2014 intervalo m\u00e9dio de <strong>' + avgDelta + 's</strong>.<br>'
    + '<span style="color:#f87171">' + batedor + '</span> chega <strong>antes</strong> \u2014 poss\u00edvel abertura de caminho.';
  if (_batNotifEnabled) {
    toast.style.display = 'block';
    if (_abordagemTimer) clearTimeout(_abordagemTimer);
    _abordagemTimer = setTimeout(function(){ toast.style.display = 'none'; }, 20000);
    try {
      var ctx = _getAudioCtx(); var t = ctx.currentTime;
      for (var i = 0; i < 3; i++) {
        var osc = ctx.createOscillator(); var g = ctx.createGain();
        osc.connect(g); g.connect(ctx.destination);
        osc.type = 'triangle'; osc.frequency.value = i === 1 ? 660 : 880;
        g.gain.setValueAtTime(0.4, t + i*0.22);
        g.gain.exponentialRampToValueAtTime(0.001, t + i*0.22 + 0.2);
        osc.start(t + i*0.22); osc.stop(t + i*0.22 + 0.22);
      }
    } catch(e) {}
  }
}

function triggerAlvoAvistado(plate, camera, descricao, direcao) {
  _toastPlates['avistado'] = plate;
  var dirTxt = direcao === 'CRESCENTE' ? ' \u00b7 \u2191 CRESCENTE' : direcao === 'DECRESCENTE' ? ' \u00b7 \u2193 DECRESCENTE' : '';
  addAlert('avistado', '&#127919;', plate,
    'C&acirc;mera: <strong>' + camera + '</strong>' + (descricao ? ' &mdash; ' + descricao : '') + dirTxt,
    {type:'avistado', plate:plate});
  var toast = document.getElementById('alvo-avistado-toast');
  document.getElementById('alvo-avistado-plate').textContent = plate;
  document.getElementById('alvo-avistado-desc').innerHTML =
    'Detectado na c&acirc;mera <strong>' + camera + '</strong>'
    + (direcao ? ' &nbsp;<span style="color:var(--accent);font-weight:700">' + (direcao === 'CRESCENTE' ? '&#8593;' : '&#8595;') + ' ' + direcao + '</span>' : '')
    + (descricao ? '<br><span style="opacity:.85">' + descricao + '</span>' : '');
  if (_batNotifEnabled) {
    toast.style.display = 'block';
    if (_alvoAvistadoTimer) clearTimeout(_alvoAvistadoTimer);
    _alvoAvistadoTimer = setTimeout(function(){ toast.style.display = 'none'; }, 15000);
    try {
      var ctx = _getAudioCtx();
      var t = ctx.currentTime;
      [440, 660].forEach(function(freq, i) {
        var osc = ctx.createOscillator(); var g = ctx.createGain();
        osc.connect(g); g.connect(ctx.destination);
        osc.type = 'sine'; osc.frequency.value = freq;
        g.gain.setValueAtTime(0.35, t + i*0.22);
        g.gain.exponentialRampToValueAtTime(0.001, t + i*0.22 + 0.25);
        osc.start(t + i*0.22); osc.stop(t + i*0.22 + 0.28);
      });
    } catch(e) {}
  }
}
function triggerAbordagem(follower, leader, cameras, avgDelta) {
  _toastPlates['abordagem'] = follower;
  _toastPlates['abordagem_leader'] = leader;
  addAlert('abordagem', '&#9888;&#65039;',
    leader + ' + ' + follower,
    '&#128680; Batedor: <strong>' + leader + '</strong> &nbsp;&#128663; Alvo: <strong>' + follower + '</strong>'
    + ' &mdash; ' + cameras + ' c\u00e2mera(s), \u0394' + avgDelta + 's');
  var toast = document.getElementById('abordagem-toast');
  document.getElementById('abordagem-toast-plate').innerHTML =
    '<div style="display:flex;flex-direction:column;gap:5px;margin:8px 0">'
    + '<div>'
    +   '<span style="font-size:.65rem;font-weight:700;letter-spacing:.08em;opacity:.75;display:block;margin-bottom:2px">&#128680; POSS\u00cdVEL BATEDOR</span>'
    +   '<span style="font-size:1.4rem;font-weight:900;letter-spacing:.12em;color:#f87171">' + leader + '</span>'
    + '</div>'
    + '<div>'
    +   '<span style="font-size:.65rem;font-weight:700;letter-spacing:.08em;opacity:.75;display:block;margin-bottom:2px">&#127919; POSS\u00cdVEL ALVO A ABORDAR</span>'
    +   '<span style="font-size:1.4rem;font-weight:900;letter-spacing:.12em;color:#fbbf24">' + follower + '</span>'
    + '</div>'
    + '</div>';
  document.getElementById('abordagem-toast-desc').innerHTML =
    'Vistos juntos em <strong>' + cameras + ' c\u00e2mera(s)</strong>'
    + ' &mdash; intervalo m\u00e9dio de <strong>' + avgDelta + 's</strong>.<br>'
    + '<span style="color:#f87171">' + leader + '</span> chega <strong>antes</strong> &mdash; poss\u00edvel abertura de caminho.';
  toast.style.display = 'block';
  if (_abordagemTimer) clearTimeout(_abordagemTimer);
  _abordagemTimer = setTimeout(function(){ toast.style.display = 'none'; }, 20000);
  try {
    var ctx = _getAudioCtx();
    var t = ctx.currentTime;
    for (var i = 0; i < 3; i++) {
      var osc = ctx.createOscillator(); var g = ctx.createGain();
      osc.connect(g); g.connect(ctx.destination);
      osc.type = 'triangle'; osc.frequency.value = i === 1 ? 660 : 880;
      g.gain.setValueAtTime(0.4, t + i*0.22);
      g.gain.exponentialRampToValueAtTime(0.001, t + i*0.22 + 0.2);
      osc.start(t + i*0.22); osc.stop(t + i*0.22 + 0.22);
    }
  } catch(e) {}
}
function triggerAlarm(plate, lists, direcao) {
  var alarmLists = lists.filter(function(l){ return l.alarm_enabled; });
  if (!alarmLists.length) return;
  var listNames = alarmLists.map(function(l){ return l.list_name || l.name || '?'; }).join(', ');
  var soundName = alarmLists[0].alarm_sound || 'beep';
  var dirTxt = direcao === 'CRESCENTE' ? ' \u00b7 \u2191 CRESCENTE' : direcao === 'DECRESCENTE' ? ' \u00b7 \u2193 DECRESCENTE' : '';

  // Sempre salva no histórico (mesmo mudo)
  addAlert('camera', '&#128247;', plate,
    'Lista(s): <strong>' + listNames + '</strong>' + dirTxt,
    null,
    { lists: alarmLists, camera: null, sound: soundName, direcao: direcao || null }
  );

  // Se mudo: apenas histórico — sem som, sem flash, sem toast
  if (_alarmSoundMuted) return;

  // Som
  playAlarmSound(soundName);
  // Flash na tela
  var ov = document.getElementById('alarm-overlay');
  ov.style.display = 'block';
  setTimeout(function(){ ov.style.display = 'none'; }, 1200);
  // Toast
  var toast = document.getElementById('alarm-toast');
  document.getElementById('alarm-toast-plate').textContent = plate;
  document.getElementById('alarm-toast-lists').innerHTML =
    '&#128247; Lista(s): <strong>' +
    alarmLists.map(function(l){ return l.list_name || l.name || '?'; }).join(', ') +
    '</strong>';
  var dirEl = document.getElementById('alarm-toast-dir');
  if (direcao) {
    dirEl.innerHTML = '<span class="alarm-dir">' +
      (direcao === 'CRESCENTE' ? '&#8593; CRESCENTE' : '&#8595; DECRESCENTE') +
      '</span>';
  } else { dirEl.innerHTML = ''; }
  toast.style.display = 'block';
  if (_alarmToastTimer) clearTimeout(_alarmToastTimer);
  _alarmToastTimer = setTimeout(function(){ toast.style.display = 'none'; }, 7000);
}

// ===== PAINEL =====
var _CHART_COLORS = ['#3b82f6','#22c55e','#f59e0b','#a855f7','#ef4444','#06b6d4','#ec4899','#84cc16','#f97316','#64748b','#10b981','#8b5cf6'];

function _chartUiColors() {
  var style = getComputedStyle(document.documentElement);
  var isBranco = document.documentElement.getAttribute('data-theme') === 'branco';
  return {
    tick: (style.getPropertyValue('--muted') || (isBranco ? '#64748b' : '#d4f5df')).trim(),
    text: (style.getPropertyValue('--text') || (isBranco ? '#0f172a' : '#ffffff')).trim(),
    grid: isBranco ? 'rgba(15,23,42,.08)' : 'rgba(212,245,223,.08)',
    gridStrong: isBranco ? 'rgba(15,23,42,.12)' : 'rgba(212,245,223,.12)',
    doughnutBorder: isBranco ? '#ffffff' : 'rgba(5,46,22,.88)'
  };
}

function _destroyPanelChart(id) {
  if (_pnCharts[id]) {
    _pnCharts[id].destroy();
    delete _pnCharts[id];
  }
}

function _panelHasData(values) {
  return Array.isArray(values) && values.some(function(v){ return Number(v || 0) > 0; });
}

function _panelSetChartState(wrapId, badgeId, hasData, emptyTitle, emptyCopy, badgeText) {
  var wrap = document.getElementById(wrapId);
  if (wrap) {
    wrap.classList.toggle('is-empty', !hasData);
    var title = wrap.querySelector('.chart-empty-title');
    var copy = wrap.querySelector('.chart-empty-copy');
    if (title && emptyTitle) title.textContent = emptyTitle;
    if (copy && emptyCopy) copy.textContent = emptyCopy;
  }
  var badge = document.getElementById(badgeId);
  if (badge && badgeText) badge.textContent = badgeText;
}

function _mkChart(id, type, labels, datasets, opts) {
  if (_pnCharts[id]) { _pnCharts[id].destroy(); }
  var ctx = document.getElementById(id);
  if (!ctx) return;
  var ui = _chartUiColors();
  _pnCharts[id] = new Chart(ctx, {
    type: type,
    data: { labels: labels, datasets: datasets },
    options: Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: ui.tick, font: { size: 10 } }, grid: { color: ui.grid } },
        y: { ticks: { color: ui.tick, font: { size: 10 } }, grid: { color: ui.gridStrong }, beginAtZero: true }
      }
    }, opts || {})
  });
}

function _mkDoughnut(id, labels, data) {
  if (_pnCharts[id]) { _pnCharts[id].destroy(); }
  var ctx = document.getElementById(id);
  if (!ctx) return;
  var ui = _chartUiColors();
  _pnCharts[id] = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{ data: data, backgroundColor: _CHART_COLORS, borderColor: ui.doughnutBorder, borderWidth: 2 }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '60%',
      plugins: {
        legend: { display: true, position: 'bottom',
          labels: { color: ui.tick, font: { size: 10 }, boxWidth: 10, padding: 10 } }
      }
    }
  });
}

function _prodNumber(value) {
  var n = Number(value);
  return isFinite(n) ? n : 0;
}

function _fmtProdNumber(value, maxDigits) {
  return _prodNumber(value).toLocaleString('pt-BR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: maxDigits || 0
  });
}

function _fmtProdDrogas(value) {
  var drogasKg = _prodNumber(value);
  if (drogasKg >= 1000) {
    return _fmtProdNumber(drogasKg / 1000, 2) + ' T';
  }
  return _fmtProdNumber(drogasKg, 2) + ' KG';
}

function _parseProdInput(id) {
  var el = document.getElementById(id);
  var raw = String((el && el.value) || '').trim();
  if (!raw) return 0;
  raw = raw.replace(',', '.');
  var parsed = Number(raw);
  return isFinite(parsed) ? parsed : NaN;
}

function _produtividadeMetaText(data, adminFallback, userFallback) {
  data = data || {};
  if (data.updated_at) {
    return 'Ultimo lancamento em ' + _fmtAdminTs(data.updated_at, true) + (data.updated_by ? ' por ' + data.updated_by : '');
  }
  if ((window._authRole || '') === 'admin') {
    return adminFallback || 'Use a aba "Produtividade" para registrar novas ocorrencias.';
  }
  return userFallback || 'Indicadores aguardando atualizacao do administrador.';
}

function _setPainelProdutividade(data) {
  data = data || {};
  var armasEl = document.getElementById('pn-prod-armas');
  var drogasKgEl = document.getElementById('pn-prod-drogas-kg');
  var veicEl = document.getElementById('pn-prod-veiculos');
  var pessoasEl = document.getElementById('pn-prod-pessoas');
  var veicAbEl = document.getElementById('pn-prod-veiculos-abordados');
  var metaEl = document.getElementById('pn-prod-meta');
  var drogasKg = _prodNumber(data.drogas_apreendidas_kg != null ? data.drogas_apreendidas_kg : data.peso_kg);
  if (armasEl) armasEl.textContent = _fmtProdNumber(data.armas_apreendidas, 0);
  if (drogasKgEl) drogasKgEl.textContent = _fmtProdDrogas(drogasKg);
  if (veicEl) veicEl.textContent = _fmtProdNumber(data.veiculos_recuperados, 0);
  if (pessoasEl) pessoasEl.textContent = _fmtProdNumber(data.pessoas_abordadas, 0);
  if (veicAbEl) veicAbEl.textContent = _fmtProdNumber(data.veiculos_abordados, 0);
  if (metaEl) {
    metaEl.textContent = data.updated_at
      ? 'Atualizado em ' + _fmtAdminTs(data.updated_at, false) + (data.updated_by ? ' por ' + data.updated_by : '')
      : _produtividadeMetaText(data, 'Use a aba "Produtividade" para registrar novas ocorrencias.');
  }
}

function _setProdutividadeTab(data) {
  data = data || {};
  var drogasKg = _prodNumber(data.drogas_apreendidas_kg != null ? data.drogas_apreendidas_kg : data.peso_kg);
  var summaryMetaEl = document.getElementById('prod-summary-meta');
  var launchMetaEl = document.getElementById('prod-launch-meta');
  var currentText = 'Acumulado atual: '
    + _fmtProdNumber(data.armas_apreendidas, 0) + ' armas, '
    + _fmtProdDrogas(drogasKg) + ' e '
    + _fmtProdNumber(data.veiculos_recuperados, 0) + ' veiculos recuperados.';
  var metaText = _produtividadeMetaText(
    data,
    'Cada novo lancamento sera somado ao acumulado do painel.',
    'Indicadores aguardando o primeiro lancamento.'
  );

  var totalArmasEl = document.getElementById('prod-total-armas');
  var totalDrogasEl = document.getElementById('prod-total-drogas-kg');
  var totalVeiculosEl = document.getElementById('prod-total-veiculos');
  var totalPessoasEl = document.getElementById('prod-total-pessoas');
  var totalVeiculosAbEl = document.getElementById('prod-total-veiculos-abordados');

  if (totalArmasEl) totalArmasEl.textContent = _fmtProdNumber(data.armas_apreendidas, 0);
  if (totalDrogasEl) totalDrogasEl.textContent = _fmtProdDrogas(drogasKg);
  if (totalVeiculosEl) totalVeiculosEl.textContent = _fmtProdNumber(data.veiculos_recuperados, 0);
  if (totalPessoasEl) totalPessoasEl.textContent = _fmtProdNumber(data.pessoas_abordadas, 0);
  if (totalVeiculosAbEl) totalVeiculosAbEl.textContent = _fmtProdNumber(data.veiculos_abordados, 0);
  if (summaryMetaEl) summaryMetaEl.textContent = metaText;
  if (launchMetaEl) launchMetaEl.textContent = currentText + ' ' + metaText;
}

async function loadPainelProdutividade() {
  try {
    var resp = await fetch('/api/produtividade');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    _painelProdutividadeCache = await resp.json();
    _setPainelProdutividade(_painelProdutividadeCache);
    _setProdutividadeTab(_painelProdutividadeCache);
  } catch(e) {
    console.error('produtividade', e);
    _painelProdutividadeCache = null;
    _setPainelProdutividade({});
    _setProdutividadeTab({});
  }
}

function resetProdutividadeForm() {
  ['prod-entry-armas', 'prod-entry-drogas-kg', 'prod-entry-veiculos'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.value = '';
  });
  var errorEl = document.getElementById('prod-entry-error');
  var okEl = document.getElementById('prod-entry-ok');
  if (errorEl) errorEl.textContent = '';
  if (okEl) {
    okEl.textContent = '';
    okEl.style.display = 'none';
  }
}

function resetProdutividadeSummaryFeedback() {
  var errorEl = document.getElementById('prod-summary-error');
  var okEl = document.getElementById('prod-summary-ok');
  if (errorEl) errorEl.textContent = '';
  if (okEl) {
    okEl.textContent = '';
    okEl.style.display = 'none';
  }
}

function openProdutividadeResetModal() {
  if ((window._authRole || '') !== 'admin') return;
  var pwdEl = document.getElementById('prod-reset-password');
  var errorEl = document.getElementById('prod-reset-error');
  var btn = document.getElementById('prod-reset-ok-btn');
  if (pwdEl) pwdEl.value = '';
  if (errorEl) errorEl.textContent = '';
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '&#128465; Confirmar Reset';
  }
  openModal('prod-reset-modal');
  setTimeout(function() {
    var el = document.getElementById('prod-reset-password');
    if (el) el.focus();
  }, 80);
}

function closeProdutividadeResetModal() {
  var pwdEl = document.getElementById('prod-reset-password');
  var errorEl = document.getElementById('prod-reset-error');
  if (pwdEl) pwdEl.value = '';
  if (errorEl) errorEl.textContent = '';
  closeModal('prod-reset-modal');
}

function switchProdutividadeSub(name, el) {
  var target = el || document.querySelector('#prod-sub-tabs .sub-tab[data-prod="' + name + '"]');
  document.querySelectorAll('#prod-sub-tabs .sub-tab').forEach(function(tab) {
    tab.classList.remove('active');
  });
  if (target) target.classList.add('active');
  var launchPane = document.getElementById('prod-sub-lancamentos');
  var summaryPane = document.getElementById('prod-sub-resumo');
  if (launchPane) launchPane.classList.toggle('active', name === 'lancamentos');
  if (summaryPane) summaryPane.classList.toggle('active', name === 'resumo');
  var labels = {
    lancamentos: 'Produtividade / Nova ocorrencia',
    resumo: 'Produtividade / Resumo acumulado'
  };
  trackPageView('produtividade:' + name, labels[name] || ('Produtividade / ' + name), '/dashboard#produtividade/' + name);
}

async function loadProdutividadeTab(resetForm, preferredSub) {
  if ((window._authRole || '') !== 'admin') return;
  if (!_painelProdutividadeCache) await loadPainelProdutividade();
  else _setProdutividadeTab(_painelProdutividadeCache);
  if (resetForm !== false) resetProdutividadeForm();
  if (resetForm !== false) resetProdutividadeSummaryFeedback();
  var activeTabEl = document.querySelector('#prod-sub-tabs .sub-tab.active');
  var activeSub = preferredSub || ((resetForm === false && activeTabEl) ? activeTabEl.getAttribute('data-prod') : '') || 'lancamentos';
  switchProdutividadeSub(activeSub);
}

function openProdutividadeModal() {
  if ((window._authRole || '') !== 'admin') return;
  var navEl = document.querySelector('#sidebar .nav-item[data-menu="produtividade"]');
  if (navEl) {
    switchTab('produtividade', navEl);
    return;
  }
}

async function saveProdutividadeLancamento() {
  if ((window._authRole || '') !== 'admin') return;
  var errorEl = document.getElementById('prod-entry-error');
  var okEl = document.getElementById('prod-entry-ok');
  var btn = document.getElementById('prod-entry-save-btn');
  if (errorEl) errorEl.textContent = '';
  if (okEl) {
    okEl.textContent = '';
    okEl.style.display = 'none';
  }

  var payload = {
    modo: 'incrementar',
    armas_apreendidas: _parseProdInput('prod-entry-armas'),
    drogas_apreendidas_kg: _parseProdInput('prod-entry-drogas-kg'),
    veiculos_recuperados: _parseProdInput('prod-entry-veiculos')
  };

  if (!isFinite(payload.armas_apreendidas) || !isFinite(payload.drogas_apreendidas_kg) || !isFinite(payload.veiculos_recuperados)) {
    if (errorEl) errorEl.textContent = 'Preencha apenas numeros validos.';
    return;
  }
  if (payload.armas_apreendidas < 0 || payload.drogas_apreendidas_kg < 0 || payload.veiculos_recuperados < 0) {
    if (errorEl) errorEl.textContent = 'Os indicadores nao podem ser negativos.';
    return;
  }
  if (payload.armas_apreendidas === 0 && payload.drogas_apreendidas_kg === 0 && payload.veiculos_recuperados === 0) {
    if (errorEl) errorEl.textContent = 'Informe ao menos um valor maior que zero para registrar a ocorrencia.';
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Salvando...';
  try {
    var resp = await fetch('/api/produtividade', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) {
      var errData = await resp.json().catch(function(){ return {}; });
      throw new Error(errData.detail || ('HTTP ' + resp.status));
    }
    _painelProdutividadeCache = await resp.json();
    _setPainelProdutividade(_painelProdutividadeCache);
    _setProdutividadeTab(_painelProdutividadeCache);
    ['prod-entry-armas', 'prod-entry-drogas-kg', 'prod-entry-veiculos'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.value = '';
    });
    if (okEl) {
      okEl.textContent = 'Ocorrencia somada ao acumulado com sucesso.';
      okEl.style.display = 'block';
    }
  } catch(e) {
    console.error('save produtividade incremento', e);
    if (errorEl) errorEl.textContent = 'Erro: ' + e.message;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '&#128190; Somar ao acumulado';
  }
}

async function confirmProdutividadeReset() {
  if ((window._authRole || '') !== 'admin') return;

  var pwdEl = document.getElementById('prod-reset-password');
  var senha = (pwdEl ? pwdEl.value : '').trim();
  var modalErrorEl = document.getElementById('prod-reset-error');
  var modalBtn = document.getElementById('prod-reset-ok-btn');
  var errorEl = document.getElementById('prod-summary-error');
  var okEl = document.getElementById('prod-summary-ok');
  var btn = document.getElementById('prod-summary-reset-btn');
  if (!senha) {
    if (modalErrorEl) modalErrorEl.textContent = 'Digite sua senha para confirmar.';
    if (pwdEl) pwdEl.focus();
    return;
  }
  if (modalErrorEl) modalErrorEl.textContent = '';
  if (errorEl) errorEl.textContent = '';
  if (okEl) {
    okEl.textContent = '';
    okEl.style.display = 'none';
  }

  if (modalBtn) {
    modalBtn.disabled = true;
    modalBtn.textContent = 'Confirmando...';
  }
  btn.disabled = true;
  btn.textContent = 'Zerando...';
  try {
    var resp = await fetch('/api/produtividade', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        modo: 'zerar',
        senha_confirmacao: senha
      })
    });
    if (pwdEl) pwdEl.value = '';
    if (!resp.ok) {
      var errData = await resp.json().catch(function(){ return {}; });
      throw new Error(errData.detail || ('HTTP ' + resp.status));
    }
    _painelProdutividadeCache = await resp.json();
    _setPainelProdutividade(_painelProdutividadeCache);
    _setProdutividadeTab(_painelProdutividadeCache);
    closeProdutividadeResetModal();
    if (okEl) {
      okEl.textContent = 'Totais zerados com sucesso. Pessoas e veiculos abordados permaneceram automaticos.';
      okEl.style.display = 'block';
    }
  } catch(e) {
    console.error('reset produtividade acumulado', e);
    if (pwdEl) pwdEl.value = '';
    if (modalErrorEl) modalErrorEl.textContent = e.message;
    if (pwdEl) pwdEl.focus();
    if (errorEl) errorEl.textContent = 'Erro: ' + e.message;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '&#128465; Zerar';
    if (modalBtn) {
      modalBtn.disabled = false;
      modalBtn.innerHTML = '&#128465; Confirmar Reset';
    }
  }
}

async function saveProdutividade() {
  if ((window._authRole || '') !== 'admin') return;
  var errorEl = document.getElementById('prod-form-error');
  var btn = document.getElementById('prod-save-btn');
  if (errorEl) errorEl.textContent = '';

  var payload = {
    modo: 'substituir',
    armas_apreendidas: _parseProdInput('prod-armas'),
    drogas_apreendidas_kg: _parseProdInput('prod-drogas-kg'),
    veiculos_recuperados: _parseProdInput('prod-veiculos')
  };

  if (!isFinite(payload.armas_apreendidas) || !isFinite(payload.drogas_apreendidas_kg) || !isFinite(payload.veiculos_recuperados)) {
    if (errorEl) errorEl.textContent = 'Preencha apenas numeros validos.';
    return;
  }
  if (payload.armas_apreendidas < 0 || payload.drogas_apreendidas_kg < 0 || payload.veiculos_recuperados < 0) {
    if (errorEl) errorEl.textContent = 'Os indicadores nao podem ser negativos.';
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Salvando...';
  try {
    var resp = await fetch('/api/produtividade', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) {
      var errData = await resp.json().catch(function(){ return {}; });
      throw new Error(errData.detail || ('HTTP ' + resp.status));
    }
    _painelProdutividadeCache = await resp.json();
    _setPainelProdutividade(_painelProdutividadeCache);
    _setProdutividadeTab(_painelProdutividadeCache);
    closeModal('painel-produtividade-modal');
  } catch(e) {
    console.error('save produtividade legado', e);
    if (errorEl) errorEl.textContent = 'Erro: ' + e.message;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '&#128190; Salvar';
  }
}

async function loadPainel() {
  try {
    var ov = await fetch('/api/stats/overview').then(function(r){ return r.json(); });
    document.getElementById('pn-total').textContent     = (ov.total_events    || ov.total || 0).toLocaleString('pt-BR');
    document.getElementById('pn-today').textContent     = (ov.today_events    || 0).toLocaleString('pt-BR');
    document.getElementById('pn-lasthour').textContent  = (ov.last_hour_events || ov.last_hour || 0).toLocaleString('pt-BR');
    document.getElementById('pn-cameras').textContent   = (ov.active_cameras  || 0).toLocaleString('pt-BR');
    document.getElementById('pn-monitored').textContent = (ov.monitored_plates || 0).toLocaleString('pt-BR');
    document.getElementById('pn-alerts').textContent    = (ov.alerts_today    || ov.alerts || 0).toLocaleString('pt-BR');
  } catch(e) { console.error('overview', e); }

  try {
    var pq = await fetch('/api/pessoas?limit=1').then(function(r){ return r.json(); });
    document.getElementById('pn-pessoas').textContent = (pq.total || 0).toLocaleString('pt-BR');
    var pessoasSub = document.getElementById('pn-pessoas-sub');
    if (pessoasSub) pessoasSub.textContent = (pq.total || 0) > 0 ? 'abrir cadastros' : 'nenhum cadastro';
  } catch(e) { console.error('pessoas count', e); }

  await loadPainelProdutividade();

  try {
    var ph = await fetch('/api/stats/events-per-hour').then(function(r){ return r.json(); });
    var phItems    = ph.items || [];
    var hourLabels = phItems.map(function(d){ return d.hour || d.label || ''; });
    var hourData   = phItems.map(function(d){ return d.count || d.total || 0; });
    var hasHourData = _panelHasData(hourData);
    _mkChart('pn-chart-hour', 'bar', hourLabels, [{
      label: 'Eventos', data: hourData,
      backgroundColor: 'rgba(59,130,246,.55)', borderColor: '#3b82f6', borderWidth: 1,
      borderRadius: 3
    }], { plugins: { legend: { display: false } } });
    _panelSetChartState(
      'pn-chart-hour-wrap',
      'pn-hour-badge',
      hasHourData,
      'Sem eventos recentes',
      'Assim que houver movimentacao, este grafico vai mostrar a distribuicao por hora.',
      hasHourData ? phItems.length.toLocaleString('pt-BR') + ' faixas' : 'Sem fluxo'
    );
  } catch(e) {
    console.error('hour', e);
    _destroyPanelChart('pn-chart-hour');
    _panelSetChartState(
      'pn-chart-hour-wrap',
      'pn-hour-badge',
      false,
      'Grafico indisponivel',
      'Nao foi possivel carregar os eventos por hora neste momento.',
      'Indisponivel'
    );
  }

  try {
    var pd = await fetch('/api/stats/events-per-day').then(function(r){ return r.json(); });
    var pdItems   = pd.items || [];
    var dayLabels = pdItems.map(function(d){ return (d.day || '').substring(5); });
    var dayData   = pdItems.map(function(d){ return d.count || d.total || 0; });
    var hasDayData = _panelHasData(dayData);
    _mkChart('pn-chart-day', 'line', dayLabels, [{
      label: 'Eventos', data: dayData,
      borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,.12)',
      borderWidth: 2, pointRadius: 2, fill: true, tension: 0.35
    }], {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: _chartUiColors().tick, font: { size: 9 }, maxRotation: 45 }, grid: { color: _chartUiColors().grid } },
        y: { ticks: { color: _chartUiColors().tick, font: { size: 10 } }, grid: { color: _chartUiColors().gridStrong }, beginAtZero: true }
      }
    });
    _panelSetChartState(
      'pn-chart-day-wrap',
      'pn-day-badge',
      hasDayData,
      'Sem historico para exibir',
      'Quando houver registros diarios, a curva vai aparecer aqui com a evolucao do periodo.',
      hasDayData ? pdItems.length.toLocaleString('pt-BR') + ' dias' : 'Sem historico'
    );
  } catch(e) {
    console.error('day', e);
    _destroyPanelChart('pn-chart-day');
    _panelSetChartState(
      'pn-chart-day-wrap',
      'pn-day-badge',
      false,
      'Grafico indisponivel',
      'Nao foi possivel carregar a serie diaria neste momento.',
      'Indisponivel'
    );
  }

  try {
    var tp = await fetch('/api/stats/top-plates?limit=10').then(function(r){ return r.json(); });
    var tpItems = tp.items || [];
    var pLabels = tpItems.map(function(d){ return d.plate || ''; });
    var pData   = tpItems.map(function(d){ return d.count || d.total || 0; });
    var hasPlateData = _panelHasData(pData);
    _mkChart('pn-chart-plates', 'bar', pLabels, [{
      label: 'Passagens', data: pData,
      backgroundColor: _CHART_COLORS.map(function(c){ return c + '99'; }),
      borderColor: _CHART_COLORS, borderWidth: 1, borderRadius: 4
    }], {
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: _chartUiColors().tick, font: { size: 10 } }, grid: { color: _chartUiColors().grid }, beginAtZero: true },
        y: { ticks: { color: _chartUiColors().text, font: { size: 10, weight: '600' } }, grid: { display: false } }
      }
    });
    _panelSetChartState(
      'pn-chart-plates-wrap',
      'pn-plates-badge',
      hasPlateData,
      'Nenhuma placa no ranking',
      'O ranking aparece automaticamente quando houver passagens suficientes para comparacao.',
      hasPlateData ? tpItems.length.toLocaleString('pt-BR') + ' placas' : 'Sem ranking'
    );
  } catch(e) {
    console.error('plates', e);
    _destroyPanelChart('pn-chart-plates');
    _panelSetChartState(
      'pn-chart-plates-wrap',
      'pn-plates-badge',
      false,
      'Ranking indisponivel',
      'Nao foi possivel carregar o ranking de placas agora.',
      'Indisponivel'
    );
  }

  try {
    var ec = await fetch('/api/stats/events-per-camera').then(function(r){ return r.json(); });
    var ecItems = ec.items || [];
    var camData = ecItems.map(function(d){ return d.count || d.total || 0; });
    var hasCamData = _panelHasData(camData);
    if (hasCamData) {
      _mkDoughnut('pn-chart-cam',
        ecItems.map(function(d){ return d.camera || ''; }),
        camData
      );
    } else {
      _destroyPanelChart('pn-chart-cam');
    }
    _panelSetChartState(
      'pn-chart-cam-wrap',
      'pn-cam-badge',
      hasCamData,
      'Nenhuma camera com atividade',
      'Quando as cameras enviarem eventos, a distribuicao por equipamento sera exibida aqui.',
      hasCamData ? ecItems.length.toLocaleString('pt-BR') + ' cameras' : 'Sem distribuicao'
    );
  } catch(e) {
    console.error('cam', e);
    _destroyPanelChart('pn-chart-cam');
    _panelSetChartState(
      'pn-chart-cam-wrap',
      'pn-cam-badge',
      false,
      'Distribuicao indisponivel',
      'Nao foi possivel carregar a atividade por camera neste momento.',
      'Indisponivel'
    );
  }
  _markTabLoaded('painel');
}

// ===== ESTADO =====
var currentTab  = 'painel';
var curFilter   = '';
var curCamera   = '';
var curDateFrom = '';
var curDateTo   = '';
var evOffset    = 0;
var EV_LIMIT    = 5;
var evTotal     = 0;
var lastMaxId   = 0;
var _evTableReady = false;  // true após primeiro render completo em offset=0; habilita modo incremental
var monPlates   = {};
var cameraSet   = new Set();
var chartHour   = null;
var chartCam    = null;
var editListId  = null;
var _editVehicleId = null;
var listsCache  = [];
var _imgMeta    = {}; // cache evId -> {camName, ts} para o modal de imagem

// ===== UTILS =====
function fmtTs(ts) {
  if (!ts) return '-';
  try {
    return new Date(ts).toLocaleString('pt-BR', {
      day:'2-digit', month:'2-digit', year:'numeric',
      hour:'2-digit', minute:'2-digit', second:'2-digit'
    });
  } catch(e) { return ts; }
}

function formatConfidencePercent(value) {
  var n = Number(value) || 0;
  // normaliza: valores <= 1 são fração (0.91 → 91)
  if (n > 0 && n <= 1) n = n * 100;
  return Math.round(Math.max(0, Math.min(100, n)));
}

function percentInputToRatio(value, fallback) {
  var n = parseFloat(value);
  if (isNaN(n)) return fallback;
  if (n > 1) n = n / 100;
  return Math.max(0, Math.min(1, n));
}

function ratioToPercentInput(value, fallback) {
  var n = parseFloat(value);
  if (isNaN(n)) return fallback;
  if (n > 0 && n <= 1) n = n * 100;
  return String(Math.round(Math.max(0, Math.min(100, n))));
}

function fmtConf(c) {
  if (c == null || c === '') return '-';
  var n = parseFloat(c);
  if (isNaN(n)) return c;
  var pct = formatConfidencePercent(n);
  var cls = pct >= 85 ? 'badge-green' : pct >= 60 ? 'badge-yellow' : 'badge-red';
  return '<span class="badge ' + cls + '">' + pct + '%</span>';
}

function scoreClass(s) {
  return s >= 50 ? 'badge-red' : s >= 20 ? 'badge-yellow' : 'badge-green';
}

// ===== TABS =====
var TAB_TITLES = { painel: 'Painel', produtividade: 'Produtividade', eventos: 'Eventos', batedor: 'Batedor de Suspeitos', veiculos: 'Veiculos Monitorados', cameras: 'C\u00e2meras', mapa: 'Mapa de C\u00e2meras', alarmes: 'Alarmes', usuarios: 'Usu\u00e1rios', storage: 'Storage', config: 'Configura\u00e7\u00f5es' };
var _pnCharts = {};
var _painelProdutividadeCache = null;
var _vehicleTargetFlow = null;
var _tabLoadMeta = {};

function _queueTabLoad(name, loader, maxAgeMs, force) {
  var meta = _tabLoadMeta[name] || (_tabLoadMeta[name] = { promise: null, loadedAt: 0 });
  var now = Date.now();
  if (!force && meta.promise) return meta.promise;
  if (!force && meta.loadedAt && maxAgeMs > 0 && (now - meta.loadedAt) < maxAgeMs) {
    return Promise.resolve();
  }
  meta.promise = Promise.resolve()
    .then(loader)
    .catch(function(err) {
      console.error('[tab-load:' + name + ']', err);
    })
    .finally(function() {
      meta.loadedAt = Date.now();
      meta.promise = null;
    });
  return meta.promise;
}

function _invalidateTabLoad(name) {
  if (_tabLoadMeta[name]) _tabLoadMeta[name].loadedAt = 0;
}

function _markTabLoaded(name) {
  var meta = _tabLoadMeta[name] || (_tabLoadMeta[name] = { promise: null, loadedAt: 0 });
  meta.loadedAt = Date.now();
}

function switchTab(name, el) {
  console.log('[switchTab] chamado com:', name);
  var role = window._authRole || 'visualizador';
  if (role !== 'admin' && (name === 'produtividade' || name === 'cameras' || name === 'storage' || name === 'usuarios')) {
    var painelNav = document.querySelector('#sidebar .nav-item[onclick="switchTab(\'painel\',this)"]');
    if (name !== 'painel' && painelNav) {
      switchTab('painel', painelNav);
    }
    return;
  }
  document.querySelectorAll('.tab-pane').forEach(function(p){ p.classList.remove('active'); });
  document.querySelectorAll('.nav-item').forEach(function(n){ n.classList.remove('active'); });
  var tabEl = document.getElementById('tab-' + name);
  console.log('[switchTab] tab-element encontrado:', !!tabEl);
  if (tabEl) tabEl.classList.add('active');
  el.classList.add('active');
  document.getElementById('topbar-title').textContent = TAB_TITLES[name] || name;
  currentTab = name;
  if (name === 'painel')  _queueTabLoad('painel', function(){ return loadPainel(); }, 15000);
  if (name === 'produtividade') loadProdutividadeTab(true, 'lancamentos');
  if (name === 'eventos') loadEvents(evOffset);
  if (name === 'batedor') {
    var activeBat = document.querySelector('#bat-sub-tabs .sub-tab.active');
    var batName = activeBat ? activeBat.getAttribute('data-bat') : 'placas';
    var _batTabMap = {
      placas: document.getElementById('bat-subtab-placas'),
      suspeitos: document.getElementById('bat-subtab-suspeitos'),
      alvos: document.getElementById('bat-subtab-alvos')
    };
    var nextBat = _batTabMap[batName] ? batName : 'placas';
    var nextBatEl = _batTabMap[nextBat];
    if (nextBatEl) {
      switchBatTab(nextBat, nextBatEl);
    } else {
      _cenSwitchView('placas');
      _cenSingleInit();
      _cenSingleFocusPlateInput();
    }
  }
  if (name === 'veiculos') { loadLists(); }
  if (name === 'cameras')  _queueTabLoad('cameras', function(){ return loadCameras(); }, 10000);
  if (name === 'mapa')     _queueTabLoad('mapa', function(){ return loadMapa(); }, 10000);
  else                     _stopMapaAutoRefresh();
  if (name === 'usuarios') _queueTabLoad('usuarios', function(){ return loadUsers(); }, 10000);
  if (name === 'storage')  _queueTabLoad('storage', function(){ return loadStorageSettings(); }, 30000);
  if (name === 'alarmes')  _queueTabLoad('alarmes', function(){ return loadAlarmes(); }, 10000);
  if (name === 'config')   initConfigTab();
  trackPageView(name, TAB_TITLES[name] || name, '/dashboard#' + name);
}
// garante acesso global mesmo em contextos de onclick attribute
window.switchTab = switchTab;

function switchBatTab(name, el) {
  // para o monitoramento ao vivo se sair de placas individuais
  if (name !== 'suspeitos' && name !== 'placas' && _cenLiveEnabled) {
    _cenLiveEnabled = false; _cenStopTimer();
    var livBtn = document.getElementById('btn-cen-live');
    if (livBtn) { livBtn.classList.remove('btn-success'); livBtn.classList.add('btn-outline');
                  livBtn.innerHTML = '&#9654; <span id="cen-live-label">Monitorar</span>'; }
  }
  document.querySelectorAll('#bat-sub-tabs .sub-tab').forEach(function(t){ t.classList.remove('active'); });
  // desativa todos os panes reais existentes no DOM
  ['central', 'alvos', 'grupos'].forEach(function(n){
    var el2 = document.getElementById('bat-sub-'+n);
    if (el2) el2.classList.remove('active');
  });
  // garante que o detalhe do alvo seja ocultado ao trocar de sub-aba
  var dvEl = document.getElementById('alvo-detalhe-view');
  if (dvEl) dvEl.classList.remove('active');
  el.classList.add('active');
  el.setAttribute('data-bat', name);
  // 'suspeitos' e 'placas' compartilham bat-sub-central; alternam a view interna
  if (name === 'suspeitos') {
    document.getElementById('bat-sub-central').classList.add('active');
    _cenSwitchView('grupos');
    _cgsLoad(true);
  } else if (name === 'placas') {
    document.getElementById('bat-sub-central').classList.add('active');
    _cenSwitchView('placas');
    _cenSingleInit();
    _cenSingleFocusPlateInput();
  } else if (name === 'alvos') {
    document.getElementById('bat-sub-alvos').classList.add('active');
    loadAlvos(); _loadAlvoCameras();
  }
  var labels = { suspeitos: 'Batedor / Suspeitos', placas: 'Batedor / Placas', alvos: 'Batedor / Alvos' };
  trackPageView('batedor:' + name, labels[name] || ('Batedor / ' + name), '/dashboard#batedor/' + name);
}

function refreshCurrent() {
  if (currentTab === 'painel')  loadPainel();
  else if (currentTab === 'eventos') loadEvents();
  else if (currentTab === 'batedor') {
    var activeBat = document.querySelector('#bat-sub-tabs .sub-tab.active');
    var batName = activeBat ? activeBat.getAttribute('data-bat') : 'suspeitos';
    if      (batName === 'suspeitos') _cgsLoad(true);
    else if (batName === 'placas')    _cenSingleRefreshCurrent();
    else if (batName === 'alvos')     loadAlvos();
    else _cgsLoad(true);
  }
  else if (currentTab === 'cameras') loadCameras();
  else if (currentTab === 'alarmes') loadAlarmes();
  else { loadLists(); }
}

// ===== MODAIS =====
function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }
async function _cancelVehicleTargetFlow() {
  var targetFlow = _vehicleTargetFlow;
  _vehicleTargetFlow = null;
  closeModal('vehicle-target-modal');
  closeModal('vehicle-modal');
  if (targetFlow && typeof targetFlow.restore === 'function') {
    try {
      await targetFlow.restore();
    } catch (restoreErr) {
      console.warn('[vehicle:target] restore cancelado falhou:', restoreErr);
    }
  }
}

function _vehicleTargetFocusChooser() {
  var sel = document.getElementById('vehicle-target-list');
  if (sel) setTimeout(function(){ sel.focus(); }, 80);
}

function _vehicleTargetBackStep() {
  var targetFlow = _vehicleTargetFlow;
  if (!targetFlow || typeof targetFlow.restore !== 'function') return false;
  if (targetFlow.stage === 'vehicle-form') {
    targetFlow.stage = 'target-choice';
    closeModal('vehicle-modal');
    var vehErr = document.getElementById('veh-form-error');
    if (vehErr) vehErr.textContent = '';
    var targetErr = document.getElementById('vehicle-target-error');
    if (targetErr) targetErr.textContent = '';
    var sel = document.getElementById('vehicle-target-list');
    if (sel && targetFlow.listId) sel.value = String(targetFlow.listId);
    openModal('vehicle-target-modal');
    _vehicleTargetFocusChooser();
    return true;
  }
  _cancelVehicleTargetFlow();
  return true;
}
function closeVehicleModal() {
  if (_vehicleTargetBackStep()) return;
  closeModal('vehicle-modal');
  _vehicleTargetFlow = null;
}
function closeVehicleTargetModal() {
  if (_vehicleTargetBackStep()) return;
  closeModal('vehicle-target-modal');
  _vehicleTargetFlow = null;
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    if (_usersActivityVisible) { toggleUsersActivitySection(false); return; }
    if (document.getElementById('traj-map-modal').classList.contains('open')) { _fecharMapaOverlay(false); return; }
    if (document.getElementById('rel-modal').classList.contains('open')) { closeRelModal(true); return; }
    if (document.getElementById('vehicle-modal').classList.contains('open')) { closeVehicleModal(); return; }
    if (document.getElementById('vehicle-target-modal').classList.contains('open')) { closeVehicleTargetModal(); return; }
    ['img-modal','detail-modal','list-modal','vehicle-modal','vehicle-target-modal','camera-modal','painel-produtividade-modal','user-modal','alarme-modal','rel-modal','cgs-detalhe-modal','cad-view-modal'].forEach(closeModal);
  }
});

function openImage(evId, plate) {
  var img = document.getElementById('img-modal-img');
  var err = document.getElementById('img-modal-error');
  document.getElementById('img-modal-evnum').textContent = 'Evento #' + evId;
  document.getElementById('img-modal-plate-title').textContent = plate || '—';
  img.style.display = 'block';
  err.style.display = 'none';
  img.src = '/api/events/' + evId + '/image?_=' + Date.now();
  var meta = _imgMeta[evId] || {};
  document.getElementById('img-modal-cam').textContent  = meta.camName || '-';
  var dtObj = meta.ts ? new Date(meta.ts) : null;
  document.getElementById('img-modal-date').textContent = dtObj ? dtObj.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric'}) : '-';
  document.getElementById('img-modal-time').textContent = dtObj ? dtObj.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '-';

  // --- Badge: Confiança ---
  var confBadge = document.getElementById('img-modal-conf-badge');
  if (meta.confidence != null) {
    var confVal = formatConfidencePercent(meta.confidence);
    confBadge.textContent = '✓ ' + confVal + '% confiança';
    confBadge.style.display = 'inline-block';
    confBadge.style.background  = confVal >= 90 ? 'rgba(34,197,94,.15)' : confVal >= 70 ? 'rgba(234,179,8,.15)' : 'rgba(239,68,68,.15)';
    confBadge.style.color       = confVal >= 90 ? '#86efac'              : confVal >= 70 ? '#fde047'              : '#fca5a5';
    confBadge.style.borderColor = confVal >= 90 ? 'rgba(34,197,94,.3)'  : confVal >= 70 ? 'rgba(234,179,8,.3)'  : 'rgba(239,68,68,.3)';
  } else { confBadge.style.display = 'none'; }

  // --- Badge: Direção ---
  var dirBadge = document.getElementById('img-modal-dir-badge');
  if (meta.direcao) {
    dirBadge.textContent = (meta.direcao === 'CRESCENTE' ? '↑ ' : '↓ ') + meta.direcao;
    dirBadge.style.display = 'inline-block';
  } else { dirBadge.style.display = 'none'; }

  // --- Painel Dados da Câmera (XML) ---
  var camPanel = document.getElementById('img-modal-camdata');
  var camBody  = document.getElementById('img-modal-camdata-body');
  var cm = meta.cam_meta;
  if (cm) {
    var _xmlTypeMap  = {car:'Carro',truck:'Caminhão',bus:'Ônibus',motorcycle:'Moto',van:'Van',pickup:'Pickup',minibus:'Micro-ônibus',bicycle:'Bicicleta',person:'Pessoa'};
    var _xmlColorMap = {black:'Preto',white:'Branco',silver:'Prata',gray:'Cinza',red:'Vermelho',blue:'Azul',yellow:'Amarelo',green:'Verde',orange:'Laranja',purple:'Roxo',brown:'Marrom',beige:'Bege',gold:'Dourado'};
    var _plateCMap   = {white:'Branca',yellow:'Amarela',blue:'Azul',green:'Verde',red:'Vermelha',black:'Preta'};
    var camParts = [];
    var _chip = function(label, val, color) {
      return '<div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:6px 12px;min-width:110px">'
        + '<div style="font-size:.67rem;color:#93c5fd;text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px">' + label + '</div>'
        + '<div style="font-weight:700;font-size:.86rem;color:' + (color||'#e2e8f0') + '">' + val + '</div></div>';
    };
    if (cm.vehicle_type)  camParts.push(_chip('Tipo (câmera)',  _xmlTypeMap[cm.vehicle_type]   || cm.vehicle_type,  '#e2e8f0'));
    if (cm.vehicle_color) camParts.push(_chip('Cor (câmera)',   _xmlColorMap[cm.vehicle_color] || cm.vehicle_color, '#e2e8f0'));
    if (cm.plate_color)   camParts.push(_chip('Cor da Placa',   _plateCMap[cm.plate_color]     || cm.plate_color,   '#fde047'));
    if (cm.speed != null) {
      var spColor = (cm.speed_limit && cm.speed > cm.speed_limit) ? '#fca5a5' : '#86efac';
      var spLabel = cm.speed_limit ? cm.speed + ' km/h (lim. ' + cm.speed_limit + ')' : cm.speed + ' km/h';
      camParts.push(_chip('Velocidade', spLabel, spColor));
    } else if (cm.speed_limit != null) {
      camParts.push(_chip('Limite', cm.speed_limit + ' km/h', '#e2e8f0'));
    }
    if (cm.illegal_name && cm.illegal_name.toLowerCase() !== 'normal') {
      camParts.push(_chip('Infração', cm.illegal_name, '#fca5a5'));
    }
    if (cm.plate_char_confidence) {
      var chars    = cm.plate_char_confidence.split(',');
      var plateStr = plate || '';
      var charHtml = chars.map(function(c, i) {
        var pct = parseInt(c, 10);
        var ch  = plateStr[i] || '?';
        var col = pct >= 95 ? '#86efac' : pct >= 80 ? '#fde047' : '#fca5a5';
        return '<span style="display:inline-flex;flex-direction:column;align-items:center;margin:0 3px">'
          + '<span style="font-size:.82rem;font-weight:800;color:#e2e8f0">' + ch + '</span>'
          + '<span style="font-size:.62rem;color:' + col + '">' + pct + '%</span></span>';
      }).join('');
      camParts.push('<div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:6px 12px">'
        + '<div style="font-size:.67rem;color:#93c5fd;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px">Confiança por Caractere</div>'
        + '<div style="display:flex;gap:2px">' + charHtml + '</div></div>');
    }
    if (camParts.length) {
      camBody.innerHTML = camParts.join('');
      camPanel.style.display = 'block';
    } else { camPanel.style.display = 'none'; }
  } else { camPanel.style.display = 'none'; }

  // --- Painel YOLO / IA ---
  var yoloPanel = document.getElementById('img-modal-yolo');
  var yoloBody  = document.getElementById('img-modal-yolo-body');
  var yoloParts = [];
  var colorDot  = { 'Branco':'#f8fafc','Preto':'#1e293b','Prata/Cinza':'#94a3b8','Vermelho':'#ef4444','Azul':'#3b82f6','Amarelo':'#eab308','Verde':'#22c55e','Laranja':'#f97316','Roxo':'#a855f7','Outro':'#64748b','Indeterminada':'#64748b' };
  if (meta.sem_placa_motivo) {
    yoloParts.push('<div style="background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.35);border-radius:7px;padding:6px 10px;min-width:200px"><div style="font-size:.68rem;color:#fca5a5;text-transform:uppercase;margin-bottom:3px">&#9888; Motivo sem placa</div><div style="color:#fecaca;font-weight:600;font-size:.84rem">' + meta.sem_placa_motivo + '</div></div>');
  }
  if (meta.target_vehicle) {
    var tv  = meta.target_vehicle;
    var cor = tv.cor || 'Indeterminada';
    var dot = '<span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:' + (colorDot[cor]||'#64748b') + ';border:1px solid rgba(255,255,255,.35);vertical-align:middle"></span>';
    var pq  = tv.plate_analysis || {};
    var pqStr = pq.qualidade ? ' &nbsp;<span style="font-size:.74rem;color:var(--muted)">Placa: ' + pq.qualidade + '</span>' : '';
    yoloParts.push('<div style="background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.35);border-radius:7px;padding:7px 12px;min-width:220px"><div style="font-size:.67rem;color:#86efac;text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px">&#127919; Ve&iacute;culo da placa</div><div style="font-weight:700;font-size:.9rem">' + (tv.class_pt || tv.class || '-') + ' &nbsp;' + dot + ' ' + cor + pqStr + '</div></div>');
  }
  if (meta.vehicle_details && meta.vehicle_details.length) {
    var outros = meta.target_vehicle
      ? meta.vehicle_details.filter(function(vd) { return vd !== meta.target_vehicle; })
      : meta.vehicle_details;
    if (outros.length) {
      var tiposCount = {};
      outros.forEach(function(vd) { var t = vd.class_pt || vd.class || '?'; tiposCount[t] = (tiposCount[t]||0)+1; });
      var tiposStr = Object.keys(tiposCount).map(function(t){ return tiposCount[t]+'&times;'+t; }).join(', ');
      yoloParts.push('<div style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:7px;padding:6px 10px"><div style="font-size:.67rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px">Outros na cena</div><div style="font-size:.82rem;color:var(--muted)">' + tiposStr + '</div></div>');
    }
  }
  if (meta.image_quality) {
    var iq = meta.image_quality;
    var iqColor = iq.qualidade && iq.qualidade !== 'Boa' ? '#fca5a5' : '#86efac';
    yoloParts.push('<div style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:7px;padding:6px 10px"><div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px">Qualidade da imagem</div><div style="font-size:.82rem"><span style="color:' + iqColor + ';font-weight:600">' + (iq.qualidade||'-') + '</span> &nbsp;<span style="color:var(--muted)">blur=' + (iq.blur_score||0) + ' brilho=' + (iq.brightness||0) + '</span></div></div>');
  }
  if (yoloParts.length) {
    yoloBody.innerHTML = yoloParts.join('');
    yoloPanel.style.display = 'block';
  } else {
    yoloPanel.style.display = 'none';
  }
  openModal('img-modal');
}

function openImageUrl(url, title) {
  var imageUrl = normalizeImageUrl(url);
  if (!imageUrl) return;
  var img = document.getElementById('img-modal-img');
  var err = document.getElementById('img-modal-error');
  document.getElementById('img-modal-evnum').textContent = 'Imagem';
  document.getElementById('img-modal-plate-title').textContent = title || 'Visualizacao';
  img.style.display = 'block';
  err.style.display = 'none';
  img.src = imageUrl + (imageUrl.indexOf('?') >= 0 ? '&' : '?') + '_=' + Date.now();
  document.getElementById('img-modal-cam').textContent = '-';
  document.getElementById('img-modal-date').textContent = '-';
  document.getElementById('img-modal-time').textContent = '-';
  document.getElementById('img-modal-list').textContent = '-';
  document.getElementById('img-modal-priority').textContent = '-';
  document.getElementById('img-modal-alert-status').textContent = '-';
  document.getElementById('img-modal-conf-badge').style.display = 'none';
  document.getElementById('img-modal-dir-badge').style.display = 'none';
  document.getElementById('img-modal-camdata').style.display = 'none';
  document.getElementById('img-modal-camdata-body').innerHTML = '';
  document.getElementById('img-modal-yolo').style.display = 'none';
  document.getElementById('img-modal-yolo-body').innerHTML = '';
  openModal('img-modal');
}

function normalizeImageUrl(path) {
  if (!path) return '';
  path = String(path).trim();
  if (!path) return '';
  if (path.indexOf('http://') === 0 || path.indexOf('https://') === 0 || path.indexOf('/') === 0) {
    return path;
  }
  return '/uploads/' + path.replace(/^\.?\//, '');
}

// ===== PLACAS MONITORADAS =====
async function loadMonPlates() {
  try {
    var r = await fetch('/api/vehicles/allplates');
    var d = await r.json();
    monPlates = d.plates || {};
  } catch(e) {
    monPlates = {};
  }
}

function plateHtml(plate) {
  if (!plate || plate === 'unknown' || plate.trim() === '') return '<span style="color:var(--muted)">-</span>';
  var pm = monPlates[plate.toUpperCase()];
  if (pm && pm.length) {
    var c = '#ef4444';
    var title = pm.map(function(l){ return l.list_name; }).join(', ');
    return '<span class="plate-tag plate-alert" title="' + title + '" style="background:' + c + '22;color:' + c + ';border-color:' + c + '55">&#9888; ' + plate + '</span>';
  }
  return '<span class="plate-tag">' + plate + '</span>';
}

function _activeAlarmListsForPlate(plate) {
  if (!plate) return [];
  var pm = monPlates[plate.toUpperCase()];
  if (!pm || !pm.length) return [];
  return pm.filter(function(l) { return !!l.alarm_enabled; });
}

function _hasActiveAlarmForPlate(plate) {
  return _activeAlarmListsForPlate(plate).length > 0;
}

function listBadgesHtml(plate) {
  if (!plate) return '';
  var pm = monPlates[plate.toUpperCase()];
  if (!pm || !pm.length) return '';
  return pm.map(function(l){
    return '<span class="list-badge" style="background:#3b82f622;color:#3b82f6;border:1px solid #3b82f644">' + l.list_name + '</span>';
  }).join(' ');
}

// ===== EVENTOS =====
var _eventCache = {};

async function loadEvents(newOffset) {
  if (newOffset !== undefined) { evOffset = newOffset; _evTableReady = false; }
  document.getElementById('events-status').innerHTML = '<span class="spinner"></span>';
  var p = new URLSearchParams({ limit: EV_LIMIT, offset: evOffset });
  if (curFilter)   p.set('plate', curFilter);
  if (curCamera)   p.set('camera_id', curCamera);
  if (curDateFrom) p.set('dt_from', curDateFrom);
  if (curDateTo)   p.set('dt_to',   curDateTo);
  try {
    var r = await fetch('/api/events?' + p);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    var data = await r.json();
    evTotal = data.total || 0;
    var items = data.items || [];
    _eventCache = {};
    items.forEach(function(ev) { _eventCache[ev.id] = ev; });
    var newIds = new Set();
    if (evOffset === 0 && lastMaxId > 0) {
      items.forEach(function(ev){ if (ev.id > lastMaxId) newIds.add(ev.id); });
    }
    if (items.length) lastMaxId = Math.max(lastMaxId, ...items.map(function(e){ return e.id; }));
    // Disparar alarme para novas placas monitoradas
    if (newIds.size > 0) {
      var alarmed = new Set();
      items.forEach(function(ev) {
        if (!newIds.has(ev.id)) return;
        var pm = ev.plate && monPlates[ev.plate.toUpperCase()];
        if (pm && !alarmed.has(ev.plate)) {
          alarmed.add(ev.plate);
          triggerAlarm(ev.plate, pm);
        }
      });
    }
    renderEvents(items, newIds);
    updateEvCards(evTotal, items);
    updatePagination();
    updateCamFilter(items);
    buildCharts(items);
    document.getElementById('events-status').textContent = items.length + ' de ' + evTotal + ' registro(s)';
  } catch(e) {
    document.getElementById('events-status').textContent = 'Erro: ' + e.message;
    document.getElementById('events-tbody').innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--danger);padding:24px">Erro: ' + e.message + '</td></tr>';
  }
}

function _yoloBadge(ev) {
  var yr = ev.yolo_result;
  if (!yr || yr.error) return '<span style="font-size:.68rem;color:var(--muted)">&#8212;</span>';
  var icons = { car:'&#128663;', truck:'&#128666;', motorcycle:'&#127949;', bus:'&#128652;', bicycle:'&#128690;', person:'&#128694;' };
  var colorDot = { 'Branco':'#f8fafc','Preto':'#1e293b','Prata/Cinza':'#94a3b8','Vermelho':'#ef4444','Azul':'#3b82f6','Amarelo':'#eab308','Verde':'#22c55e','Laranja':'#f97316','Roxo':'#a855f7','Outro':'#64748b','Indeterminada':'#64748b' };
  var parts = [];
  // Veículo da placa (target_vehicle) em destaque
  var tv = yr.target_vehicle;
  if (tv) {
    var cor = tv.cor || '';
    var dot = cor ? '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + (colorDot[cor]||'#64748b') + ';border:1px solid rgba(255,255,255,.3);vertical-align:middle;margin-left:2px"></span>' : '';
    parts.push((icons[tv.class]||'&#128663;') + '&nbsp;<strong>' + (tv.class_pt||tv.class) + '</strong>' + dot + (cor?' '+cor:''));
  } else if (yr.vehicle_details && yr.vehicle_details.length) {
    yr.vehicle_details.forEach(function(vd) {
      var cor = vd.cor || '';
      var dot = cor ? '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + (colorDot[cor]||'#64748b') + ';border:1px solid rgba(255,255,255,.3);vertical-align:middle;margin-left:2px"></span>' : '';
      parts.push((icons[vd.class]||'&#128663;') + '&nbsp;' + (vd.class_pt||vd.class) + dot + (cor?' '+cor:''));
    });
  } else if (yr.vehicle_types) {
    Object.keys(yr.vehicle_types).forEach(function(t) {
      parts.push((icons[t] || '&#128663;') + '&nbsp;' + yr.vehicle_types[t] + ' ' + t);
    });
  }
  if (yr.person_count > 0) parts.push('&#128694;&nbsp;' + yr.person_count + ' pessoa');
  // Motivo sem placa
  var motivo = ev.sem_placa_motivo || (yr && yr.sem_placa_motivo);
  if (motivo) {
    parts.push('<span style="color:#fca5a5">&#9888;&nbsp;' + motivo + '</span>');
  }
  if (!parts.length) return '<span style="font-size:.68rem;color:var(--muted)">sem detec.</span>';
  return '<span style="font-size:.69rem;color:var(--success);line-height:1.7">' + parts.join('<br>') + '</span>';
}

function _buildEvRowHtml(ev, isNew) {
  _imgMeta[ev.id] = {
    camName:          ev.cam_nome || ev.channel_name || ev.camera_id || '',
    ts:               ev.ts || ev.occurred_at || '',
    confidence:       ev.confidence != null ? ev.confidence : null,
    direcao:          ev.direcao || null,
    sem_placa_motivo: ev.sem_placa_motivo || null,
    target_vehicle:   ev.target_vehicle   || (ev.yolo_result && ev.yolo_result.target_vehicle) || null,
    vehicle_details:  ev.vehicle_details  || null,
    image_quality:    ev.image_quality    || null,
    cam_meta:         ev.cam_meta         || null,
  };
  var imgUrl = ev.image || ev.image_path || ev.thumb || null;
  var thumb = imgUrl
    ? '<img class="thumb" src="' + imgUrl + '" loading="lazy" onerror="this.parentNode.innerHTML=\'<div class=\\\'thumb-none\\\'>sem foto</div>\'" onclick="openImage(' + ev.id + ',\'' + (ev.plate||'').replace(/'/g,"\\'") + '\')">'
    : '<div class="thumb-none">sem foto</div>';
  var badges = listBadgesHtml(ev.plate);
  var ts = fmtTs(ev.ts || ev.occurred_at);
  var cam = ev.cam_nome || ev.channel_name || ev.camera_id || 'desconhecida';
  if (cam.length > 28) cam = cam.substring(0,28) + '...';
  var dir = ev.direcao;
  var dirCell = dir === 'CRESCENTE'
    ? '<span style="color:var(--accent);font-size:.75rem;font-weight:700">&#8593; CRESCENTE</span>'
    : dir === 'DECRESCENTE'
      ? '<span style="color:var(--accent);font-size:.75rem;font-weight:700">&#8595; DECRESCENTE</span>'
      : '<span style="color:var(--muted);font-size:.72rem">&#8212;</span>';
  var acaoEvento = ev.plate
    ? 'openEventReport(' + ev.id + ')'
    : 'openImage(' + ev.id + ',\'' + (ev.plate||'').replace(/'/g,"\\'") + '\')';
  var tituloAcaoEvento = ev.plate ? 'Abrir relatório da placa' : 'Abrir imagem do evento';
  return '<tr class="' + (isNew ? 'row-new' : '') + '" data-ev-id="' + ev.id + '">'
    + '<td style="color:var(--muted);font-size:.74rem">' + ev.id + '</td>'
    + '<td>' + thumb + '</td>'
    + '<td>' + plateHtml(ev.plate) + (badges ? '<div style="display:flex;gap:3px;flex-wrap:wrap;margin-top:3px">' + badges + '</div>' : '') + '</td>'
    + '<td style="font-size:.79rem;white-space:nowrap">' + ts + '</td>'
    + '<td style="color:var(--muted);font-size:.77rem">' + cam + '</td>'
    + '<td style="white-space:nowrap">' + dirCell + '</td>'
    + '<td>' + fmtConf(ev.confidence) + '</td>'
    + '<td style="min-width:90px">' + _yoloBadge(ev) + '</td>'
    + '<td><button class="btn btn-outline btn-xs" onclick="' + acaoEvento + '" title="' + tituloAcaoEvento + '">&#128269; Relatório</button></td>'
    + '</tr>';
}

function renderEvents(items, newIds) {
  newIds = newIds || new Set();
  var tb = document.getElementById('events-tbody');

  if (!items.length) {
    _evTableReady = false;
    tb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:32px">Nenhum evento encontrado.</td></tr>';
    return;
  }

  // ── Modo incremental: offset=0, tabela populada, chegaram eventos novos ──
  if (_evTableReady && evOffset === 0 && newIds.size > 0) {
    var newItems = items.filter(function(ev){ return newIds.has(ev.id); });
    newItems.sort(function(a, b){ return b.id - a.id; }); // mais recente primeiro
    newItems.forEach(function(ev) {
      if (tb.querySelector('[data-ev-id="' + ev.id + '"]')) return; // já exibido
      var tmp = document.createElement('tbody');
      tmp.innerHTML = _buildEvRowHtml(ev, true);
      tb.insertBefore(tmp.firstElementChild, tb.firstChild);
    });
    // Mantém exatamente EV_LIMIT linhas
    while (tb.rows.length > EV_LIMIT) tb.deleteRow(tb.rows.length - 1);
    return;
  }

  // ── Sem novidades e tabela já populada: não re-renderiza ──
  if (_evTableReady && evOffset === 0 && newIds.size === 0) return;

  // ── Render completo ──
  tb.innerHTML = items.map(function(ev) {
    return _buildEvRowHtml(ev, newIds.has(ev.id));
  }).join('');
  _evTableReady = (evOffset === 0);
}

function updateEvCards(total, items) {
  document.getElementById('ev-total').textContent = total != null ? total : '-';
  if (!items.length) return;
  document.getElementById('ev-last-plate').textContent = items[0].plate || '-';
  document.getElementById('ev-last-ts').textContent = fmtTs(items[0].ts || items[0].occurred_at);
  var now = Date.now();
  var lastHour = items.filter(function(ev){
    try { return new Date(ev.ts || ev.occurred_at).getTime() > now - 3600000; } catch(e){ return false; }
  }).length;
  document.getElementById('ev-last-hour').textContent = lastHour;
  var confs = items.map(function(e){ return parseFloat(e.confidence); }).filter(function(n){ return !isNaN(n) && n > 0; });
  if (confs.length) {
    var avg = confs.reduce(function(a,b){ return a+b; }) / confs.length;
    document.getElementById('ev-avg-conf').textContent = formatConfidencePercent(avg) + '%';
  } else {
    document.getElementById('ev-avg-conf').textContent = '-';
  }
  var alerts = items.filter(function(ev){ return _hasActiveAlarmForPlate(ev.plate); }).length;
  document.getElementById('ev-alerts').textContent = alerts > 0 ? String(alerts) : '0';
}

function populateEvCameraFilter() {
  var sel = document.getElementById('ev-camera');
  if (!sel) return;
  var cur = sel.value;
  var cams = (window._camsData || []).filter(function(c){ return c.ativa !== false; });
  if (cams.length === 0) {
    // fallback: usa cameraSet (IPs dos eventos carregados)
    sel.innerHTML = '<option value="">Todas as cameras</option>' +
      Array.from(cameraSet).sort().map(function(c){
        return '<option value="' + c + '"' + (c === cur ? ' selected' : '') + '>' + c + '</option>';
      }).join('');
    return;
  }
  // Ordena pelo nome da câmera
  cams = cams.slice().sort(function(a,b){ return (a.nome||'').localeCompare(b.nome||''); });
  sel.innerHTML = '<option value="">Todas as cameras</option>' +
    cams.map(function(c){
      // valor para filtro = ip (é o que fica em lpr_events.camera_id)
      var val = c.ip || c.camera_id;
      var label = c.nome || c.camera_id;
      return '<option value="' + val + '"' + (val === cur ? ' selected' : '') + '>' + label + '</option>';
    }).join('');
}

function updateCamFilter(items) {
  // Mantém cameraSet atualizado (fallback), mas usa _camsData se disponível
  items.forEach(function(ev){ if (ev.camera_id) cameraSet.add(ev.camera_id); });
  populateEvCameraFilter();
}

function updatePagination() {
  var pages = Math.ceil(evTotal / EV_LIMIT) || 1;
  var page  = Math.floor(evOffset / EV_LIMIT) + 1;
  document.getElementById('ev-page-info').textContent = 'Pag. ' + page + ' / ' + pages;
  document.getElementById('ev-prev').disabled = evOffset <= 0;
  document.getElementById('ev-next').disabled = evOffset + EV_LIMIT >= evTotal;
}

function evPage(dir) { loadEvents(Math.max(0, evOffset + dir * EV_LIMIT)); }

function setEvLimit(val) {
  EV_LIMIT = parseInt(val, 10);
  evOffset = 0;
  loadEvents(0);
}

function _toLocalInput(d) {
  // Formata Date para string "YYYY-MM-DDTHH:MM" usada em datetime-local
  var pad = function(n){ return String(n).padStart(2,'0'); };
  return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()) +
    'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

function _clearEventPresetActive() {
  document.querySelectorAll('#tab-eventos .ev-period-btn').forEach(function(btn) {
    btn.classList.remove('active');
  });
}

function _setEventPresetActive(preset) {
  document.querySelectorAll('#tab-eventos .ev-period-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn.getAttribute('data-preset') === preset);
  });
}

function setDatePreset(preset) {
  var now  = new Date();
  var from;
  if (preset === 'today') {
    from = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
  } else if (preset === '24h') {
    from = new Date(now.getTime() - 24 * 3600 * 1000);
  } else if (preset === 'week') {
    from = new Date(now.getTime() - 7 * 24 * 3600 * 1000);
  } else if (preset === '30d') {
    from = new Date(now.getTime() - 30 * 24 * 3600 * 1000);
  } else if (preset === '90d') {
    from = new Date(now.getTime() - 90 * 24 * 3600 * 1000);
  }
  _setEventPresetActive(preset);
  document.getElementById('ev-date-from').value = _toLocalInput(from);
  document.getElementById('ev-date-to').value   = _toLocalInput(now);
  filterEvents();
}

function batWindowChange() {
  var v = document.getElementById('bat-window').value;
  document.getElementById('bat-date-row').classList.toggle('visible', v === 'custom');
}
function cenWindowChange() {
  var windowEl = document.getElementById('cen-window');
  var rowEl = document.getElementById('cen-date-row');
  if (!windowEl) return;
  var v = windowEl.value;
  if (rowEl) rowEl.classList.toggle('visible', v === 'custom');
  if (v !== 'custom') loadCentral(true);
}
function convWindowChange() {
  var v = document.getElementById('conv-window').value;
  document.getElementById('conv-date-row').classList.toggle('visible', v === 'custom');
}
function grpWindowChange() {
  var v = document.getElementById('grp-window').value;
  document.getElementById('grp-date-row').classList.toggle('visible', v === 'custom');
}

function _toIso(localVal) {
  // datetime-local value 'YYYY-MM-DDTHH:MM' -> ISO string
  if (!localVal) return null;
  return new Date(localVal).toISOString();
}

function filterEvents() {
  curFilter = document.getElementById('ev-search').value.trim();
  curCamera = document.getElementById('ev-camera').value;
  var df = document.getElementById('ev-date-from').value;
  var dt = document.getElementById('ev-date-to').value;
  curDateFrom = df ? df + ':00' : '';
  curDateTo   = dt ? dt + ':59' : '';
  loadEvents(0);
}

function clearFilter() {
  document.getElementById('ev-search').value = '';
  document.getElementById('ev-camera').value = '';
  document.getElementById('ev-date-from').value = '';
  document.getElementById('ev-date-to').value = '';
  _clearEventPresetActive();
  curFilter   = '';
  curCamera   = '';
  curDateFrom = '';
  curDateTo   = '';
  loadEvents(0);
}

// ===== GRAFICOS =====
var CG = { color:'#64748b', grid:'rgba(0,0,0,.07)', bar:'rgba(59,130,246,.7)', bar2:'rgba(123,169,233,.75)' };

function chartOpts() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: CG.color, font: { size: 10 } }, grid: { color: CG.grid } },
      y: { ticks: { color: CG.color, font: { size: 10 }, stepSize: 1 }, grid: { color: CG.grid }, beginAtZero: true }
    }
  };
}

function buildCharts(items) {
  var now = new Date();
  var hourMap = {};
  for (var i = 11; i >= 0; i--) {
    var h = new Date(now);
    h.setMinutes(0,0,0);
    h.setHours(h.getHours() - i);
    hourMap[h.getHours() + 'h'] = 0;
  }
  items.forEach(function(ev){
    try {
      var d = new Date(ev.ts || ev.occurred_at);
      if ((now - d) / 3600000 <= 12) {
        var k = d.getHours() + 'h';
        if (k in hourMap) hourMap[k]++;
      }
    } catch(e){}
  });
  if (chartHour) chartHour.destroy();
  chartHour = new Chart(document.getElementById('chart-hour').getContext('2d'), {
    type: 'bar',
    data: { labels: Object.keys(hourMap), datasets: [{ data: Object.values(hourMap), backgroundColor: CG.bar, borderRadius: 4 }] },
    options: chartOpts()
  });
  var camMap = {};
  items.forEach(function(ev){ if (ev.camera_id) camMap[ev.camera_id] = (camMap[ev.camera_id] || 0) + 1; });
  var sorted = Object.entries(camMap).sort(function(a,b){ return b[1]-a[1]; }).slice(0, 8);
  if (chartCam) chartCam.destroy();
  var opts2 = Object.assign({}, chartOpts(), { indexAxis: 'y' });
  chartCam = new Chart(document.getElementById('chart-cam').getContext('2d'), {
    type: 'bar',
    data: {
      labels: sorted.map(function(x){ return x[0].length > 24 ? x[0].slice(0,24)+'...' : x[0]; }),
      datasets: [{ data: sorted.map(function(x){ return x[1]; }), backgroundColor: CG.bar2, borderRadius: 4 }]
    },
    options: opts2
  });
}

// ===== BATEDOR =====
function openConvoyDetail(btn, evidenceJson) {
  var evidences;
  try { evidences = JSON.parse(evidenceJson); } catch(e) { evidences = []; }
  document.getElementById('detail-modal-plate').textContent = 'Evidencias do Comboio';
  var rows = evidences.map(function(ev) {
    var yoloA = ev.yolo_vc_a >= 0
      ? '<span class="badge badge-' + (ev.yolo_vc_a>=2?'red':'green') + '">' + ev.yolo_vc_a + '</span>'
      : '<span style="color:var(--muted)">-</span>';
    var yoloB = ev.yolo_vc_b >= 0
      ? '<span class="badge badge-' + (ev.yolo_vc_b>=2?'red':'green') + '">' + ev.yolo_vc_b + '</span>'
      : '<span style="color:var(--muted)">-</span>';
    return '<tr>'
      + '<td style="font-size:.77rem">' + (ev.cam_a||'?') + '</td>'
      + '<td style="font-size:.77rem">' + (ev.cam_b||'?') + '</td>'
      + '<td>' + (ev.delta_t||'?') + 's</td>'
      + '<td style="font-size:.75rem;color:var(--muted)">' + fmtTs(ev.ts_a) + '</td>'
      + '<td>' + yoloA + '</td>'
      + '<td>' + yoloB + '</td>'
      + '</tr>';
  }).join('');
  document.getElementById('detail-modal-body').innerHTML =
    '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">'
    + '<button class="btn btn-sm" style="background:#ef4444;color:#fff;font-weight:700" onclick="verTrajetoriaNoMapa()">&#128663; Trajetória no Mapa</button>'
    + '</div>'
    + '<div class="table-wrap"><table><thead><tr>'
    + '<th>Camera A</th><th>Camera B</th><th>Delta-t</th><th>Horario</th><th>YOLO A</th><th>YOLO B</th>'
    + '</tr></thead><tbody>' + rows + '</tbody></table></div>';
  // Trajetória no mapa
  var _tcPlates = [], _tcPoints = [];
  evidences.forEach(function(ev) {
    if (ev.plate_a && _tcPlates.indexOf(ev.plate_a) < 0) _tcPlates.push(ev.plate_a);
    if (ev.plate_b && _tcPlates.indexOf(ev.plate_b) < 0) _tcPlates.push(ev.plate_b);
    if (ev.cam_a && ev.ts_a) _tcPoints.push({ camera_id: ev.cam_a, ts: ev.ts_a, plate: ev.plate_a || '', cam_nome: ev.cam_a });
    if (ev.cam_b && ev.ts_b) _tcPoints.push({ camera_id: ev.cam_b, ts: ev.ts_b, plate: ev.plate_b || '', cam_nome: ev.cam_b });
  });
  _mapaTrajetoria = _tcPlates.length ? { plates: _tcPlates, points: _tcPoints } : null;
  var _mb1 = document.getElementById('detail-modal-map-btn');
  if (_mb1) _mb1.style.display = _tcPlates.length ? '' : 'none';
  openModal('detail-modal');
}
// ===================================================================
// CENTRAL — GRUPOS SUSPEITOS (descoberta automática)
// ===================================================================

var _cgsAllGroups  = [];
var _cgsPage       = 0;
var _cgsPageSize   = 15;

function _cenSwitchView(view) {
  var vGrupos = document.getElementById('cen-view-grupos');
  var vPlacas = document.getElementById('cen-view-placas');
  var tGrupos = document.getElementById('cen-tab-grupos');
  var tPlacas = document.getElementById('cen-tab-placas');
  if (view === 'grupos') {
    if (vGrupos) vGrupos.style.display = '';
    if (vPlacas) vPlacas.style.display = 'none';
    if (tGrupos) { tGrupos.style.background = 'var(--primary)'; tGrupos.style.color = '#fff'; tGrupos.style.borderBottomColor = 'var(--primary)'; }
    if (tPlacas) { tPlacas.style.background = 'var(--card)'; tPlacas.style.color = 'var(--muted)'; }
  } else {
    if (vGrupos) vGrupos.style.display = 'none';
    if (vPlacas) vPlacas.style.display = '';
    if (tPlacas) { tPlacas.style.background = 'var(--primary)'; tPlacas.style.color = '#fff'; }
    if (tGrupos) { tGrupos.style.background = 'var(--card)'; tGrupos.style.color = 'var(--muted)'; }
  }
}

function _cenSingleDefaultOpts() {
  return {
    window: '24h',
    ts_from: null,
    ts_to: null,
    direction: null,
    min_confidence: 0,
    min_cameras: 2,
  };
}

function _cenSingleFocusPlateInput() {
  var input = document.getElementById('cen-single-plate');
  if (!input) return;
  setTimeout(function() {
    try { input.focus(); input.select(); } catch(e) {}
  }, 80);
}

function _cenSingleLoadRecentSearches() {
  try {
    var raw = localStorage.getItem('cenSingleRecentSearches');
    var parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) {
      _cenSingleRecentSearches = parsed
        .map(function(value) { return String(value || '').trim().toUpperCase(); })
        .filter(Boolean)
        .slice(0, 8);
    }
  } catch(e) {
    _cenSingleRecentSearches = [];
  }
}

function _cenSingleSaveRecentSearches() {
  try {
    localStorage.setItem('cenSingleRecentSearches', JSON.stringify(_cenSingleRecentSearches.slice(0, 8)));
  } catch(e) {}
}

function _cenSinglePushRecent(plate) {
  plate = String(plate || '').trim().toUpperCase();
  if (!plate) return;
  _cenSingleRecentSearches = [plate].concat(_cenSingleRecentSearches.filter(function(item) { return item !== plate; })).slice(0, 8);
  _cenSingleSaveRecentSearches();
  _cenSingleRenderRecentSearches();
}

function _cenSingleRenderRecentSearches() {
  var wrap = document.getElementById('cen-single-recents-wrap');
  var body = document.getElementById('cen-single-recents');
  if (!wrap || !body) return;
  if (!_cenSingleRecentSearches.length) {
    wrap.style.display = 'none';
    body.innerHTML = '';
    return;
  }
  wrap.style.display = '';
  body.innerHTML = _cenSingleRecentSearches.map(function(plate) {
    return '<button class="btn btn-outline btn-xs" style="font-family:monospace;font-weight:700" onclick="_cenSingleUseRecent(\'' + plate.replace(/'/g, "\\'") + '\')">' + plate + '</button>';
  }).join('');
}

function _cenSingleUseRecent(plate) {
  var input = document.getElementById('cen-single-plate');
  if (input) input.value = String(plate || '').trim().toUpperCase();
  _cenSingleSearchFromForm();
}

function _cenSingleSetStatus(message, tone) {
  var el = document.getElementById('cen-single-statusline');
  if (!el) return;
  el.innerHTML = message || '';
  var colors = {
    info: 'var(--muted)',
    ok: '#86efac',
    warn: '#fcd34d',
    error: '#fca5a5',
  };
  el.style.color = colors[tone || 'info'] || 'var(--muted)';
}

function _cenSinglePlateInput(el) {
  if (!el) return;
  var clean = (el.value || '').replace(/[^A-Z0-9]/gi, '').toUpperCase().slice(0, 7);
  if (el.value !== clean) el.value = clean;
}

function _cenSingleGetWindowValue() {
  var win = document.getElementById('cen-single-window');
  return (win && win.value) || '24h';
}

function _cenSingleSetWindowControls(value) {
  value = value || '24h';
  var el = document.getElementById('cen-single-window');
  if (el) el.value = value;
}

function _cenSingleWindowChange(sourceEl) {
  var selected = (sourceEl && sourceEl.value) || _cenSingleGetWindowValue();
  var row = document.getElementById('cen-single-date-row');
  var fromEl = document.getElementById('cen-single-ts-from');
  var toEl = document.getElementById('cen-single-ts-to');
  if (!row) return;
  _cenSingleSetWindowControls(selected);
  var isCustom = selected === 'custom';
  row.style.display = isCustom ? 'flex' : 'none';
  if (isCustom && fromEl && toEl && (!fromEl.value || !toEl.value)) {
    var now = new Date();
    fromEl.value = _toLocalDTInput(new Date(now.getTime() - 7 * 86400000));
    toEl.value = _toLocalDTInput(now);
  }
}

function _cenSingleApplyOptsToForm(opts, force) {
  opts = opts || _cenSingleDefaultOpts();
  var plateEl = document.getElementById('cen-single-plate');
  var winEl = document.getElementById('cen-single-window');
  var dirEl = document.getElementById('cen-single-direction');
  var confEl = document.getElementById('cen-single-confidence');
  var minCamEl = document.getElementById('cen-single-min-cameras');
  var fromEl = document.getElementById('cen-single-ts-from');
  var toEl = document.getElementById('cen-single-ts-to');
  if (plateEl && (force || !plateEl.value) && _cenSingleState.plate) plateEl.value = _cenSingleState.plate;
  if (winEl && (force || !winEl.value)) {
    _cenSingleSetWindowControls(opts.window || '24h');
  } else {
    _cenSingleSetWindowControls(_cenSingleGetWindowValue());
  }
  if (dirEl && (force || !dirEl.value)) dirEl.value = opts.direction || '';
  if (confEl && (force || !confEl.value)) confEl.value = String(opts.min_confidence || 0);
  if (minCamEl && (force || !minCamEl.value)) minCamEl.value = String(opts.min_cameras != null ? opts.min_cameras : 2);
  if (fromEl && (force || !fromEl.value)) {
    fromEl.value = opts.ts_from ? _toLocalDTInput(new Date(opts.ts_from)) : _toLocalDTInput(new Date(Date.now() - 7 * 86400000));
  }
  if (toEl && (force || !toEl.value)) {
    toEl.value = opts.ts_to ? _toLocalDTInput(new Date(opts.ts_to)) : _toLocalDTInput(new Date());
  }
  _cenSingleWindowChange();
}

function _cenSingleResetSummaryCards() {
  var values = {
    'cen-single-card-plate': '&#8212;',
    'cen-single-card-plate-sub': 'Aguardando pesquisa',
    'cen-single-card-score': '&#8212;',
    'cen-single-card-score-sub': 'Sem an&aacute;lise carregada',
    'cen-single-card-last': '&#8212;',
    'cen-single-card-last-sub': 'Sem passagens no per&iacute;odo',
    'cen-single-card-partners': '&#8212;',
    'cen-single-card-partners-sub': 'Nenhuma consulta em andamento',
  };
  Object.keys(values).forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = values[id];
  });
}

function _cenSingleRiskMeta(report) {
  var raw = String((report && report.level) || '').toLowerCase();
  if (raw === 'alerta') {
    return { label: 'ALTO', color: '#fca5a5', bg: 'rgba(220,38,38,.18)', border: 'rgba(239,68,68,.35)' };
  }
  if (raw === 'suspeito') {
    return { label: 'M&Eacute;DIO', color: '#fcd34d', bg: 'rgba(217,119,6,.18)', border: 'rgba(245,158,11,.35)' };
  }
  return { label: 'NORMAL', color: '#86efac', bg: 'rgba(34,197,94,.12)', border: 'rgba(34,197,94,.25)' };
}

function _cenSingleSyncSummaryCards(report, centralItem) {
  if (!report) { _cenSingleResetSummaryCards(); return; }
  var summary = report.summary || {};
  var partners = report.convoy_partners || [];
  var lastSeen = summary.last_seen ? fmtTs(summary.last_seen) : '&#8212;';
  var risk = _cenSingleRiskMeta(report);
  var statusSub = report.is_alvo
    ? '&#127919; J&aacute; cadastrada como alvo'
    : partners.length
      ? 'Com ' + partners.length + ' parceiro(s) confirmado(s)'
      : 'Sem parceiro confirmado no recorte';
  var scoreText = String(report.score || 0) + ' pts';
  var scoreSub = risk.label + ' &middot; ' + (summary.total_passes || 0) + ' passagem(ns)';
  if (centralItem && centralItem.threat_center && centralItem.threat_center.matched_target) {
    scoreSub += ' &middot; v&iacute;nculo com alvo';
  }
  var plateEl = document.getElementById('cen-single-card-plate');
  var plateSubEl = document.getElementById('cen-single-card-plate-sub');
  var scoreEl = document.getElementById('cen-single-card-score');
  var scoreSubEl = document.getElementById('cen-single-card-score-sub');
  var lastEl = document.getElementById('cen-single-card-last');
  var lastSubEl = document.getElementById('cen-single-card-last-sub');
  var partEl = document.getElementById('cen-single-card-partners');
  var partSubEl = document.getElementById('cen-single-card-partners-sub');
  if (plateEl) plateEl.textContent = report.plate || _cenSingleState.plate || '\u2014';
  if (plateSubEl) plateSubEl.innerHTML = statusSub;
  if (scoreEl) scoreEl.innerHTML = '<span style="color:' + risk.color + '">' + scoreText + '</span>';
  if (scoreSubEl) scoreSubEl.innerHTML = scoreSub;
  if (lastEl) lastEl.innerHTML = lastSeen;
  if (lastSubEl) lastSubEl.innerHTML = summary.cameras_count ? summary.cameras_count + ' c&acirc;m. distintas' : 'Sem passagens no per&iacute;odo';
  if (partEl) partEl.textContent = String(partners.length);
  if (partSubEl) {
    var partnerThreshold = (_cenSingleState.opts && _cenSingleState.opts.min_cameras) || 0;
    partSubEl.innerHTML = partners.length
      ? 'Filtro atual: ' + (partnerThreshold > 0 ? '&gt;= ' + String(partnerThreshold) + ' c&acirc;m.' : 'qualquer v&iacute;nculo')
      : 'Nenhum parceiro confirmado';
  }
}

function _cenSingleSyncActionButtons() {
  var hasReport = !!(_cenSingleState && _cenSingleState.report);
  var hasEvents = hasReport && (_cenSingleState.report.events || []).length > 0;
  var isAlvo = hasReport && !!_cenSingleState.report.is_alvo;
  var buttons = {
    full: document.getElementById('cen-single-btn-full'),
    report: document.getElementById('cen-single-btn-report'),
    map: document.getElementById('cen-single-btn-map'),
    target: document.getElementById('cen-single-btn-target'),
  };
  if (buttons.full) buttons.full.disabled = !hasReport;
  if (buttons.report) buttons.report.disabled = !hasReport;
  if (buttons.map) buttons.map.disabled = !hasEvents;
  if (buttons.target) {
    buttons.target.disabled = !hasReport || isAlvo;
    buttons.target.innerHTML = isAlvo ? '&#127919; J&aacute; &eacute; alvo' : '&#127919; Criar alvo';
  }
}

function _cenSingleRenderEmpty() {
  var body = document.getElementById('cen-single-body');
  if (!body) return;
  body.innerHTML = '<div style="text-align:center;color:var(--muted);padding:24px 10px">'
    + 'Digite uma placa e clique em <strong>Pesquisar</strong> para abrir o relat&oacute;rio detalhado.'
    + '</div>';
}

function _cenSingleRenderLoading(plate) {
  var body = document.getElementById('cen-single-body');
  if (!body) return;
  body.innerHTML = '<div style="text-align:center;color:var(--muted);padding:28px 10px">'
    + '<span class="spinner"></span><br><br>Analisando <strong style="font-family:monospace">' + plate + '</strong>&hellip;'
    + '</div>';
}

function _cenSingleBuildReportUrl(plate, opts) {
  var url = '/api/vehicle/report?plate=' + encodeURIComponent(plate);
  if (opts.window && opts.window !== 'custom') url += '&window=' + encodeURIComponent(opts.window);
  if (opts.ts_from) url += '&ts_from=' + encodeURIComponent(opts.ts_from);
  if (opts.ts_to) url += '&ts_to=' + encodeURIComponent(opts.ts_to);
  if (opts.direction) url += '&filter_direction=' + encodeURIComponent(opts.direction);
  if (opts.min_confidence > 0) url += '&min_confidence=' + String(opts.min_confidence);
  if (opts.min_cameras > 0) url += '&min_cameras=' + String(opts.min_cameras);
  return url;
}

function _cenSingleBuildCentralUrl(plate, opts) {
  var url = '/api/batedor/central?limit=25&plate_prefix=' + encodeURIComponent(plate);
  if (opts.ts_from && opts.ts_to) {
    url += '&window=1h';
    url += '&ts_from=' + encodeURIComponent(opts.ts_from);
    url += '&ts_to=' + encodeURIComponent(opts.ts_to);
  } else {
    url += '&window=' + encodeURIComponent(opts.window || '24h');
  }
  if (opts.direction) url += '&direcao=' + encodeURIComponent(opts.direction);
  return url;
}

function _cenSingleReadOpts() {
  var dirEl = document.getElementById('cen-single-direction');
  var confEl = document.getElementById('cen-single-confidence');
  var minCamEl = document.getElementById('cen-single-min-cameras');
  var fromEl = document.getElementById('cen-single-ts-from');
  var toEl = document.getElementById('cen-single-ts-to');
  var opts = _cenSingleDefaultOpts();
  opts.window = _cenSingleGetWindowValue();
  opts.direction = dirEl ? (dirEl.value || null) : null;
  opts.min_confidence = confEl ? (parseFloat(confEl.value || '0') || 0) : 0;
  opts.min_cameras = minCamEl ? (parseInt(minCamEl.value || '0', 10) || 0) : 0;
  if (opts.window === 'custom') {
    opts.ts_from = _toIso(fromEl ? fromEl.value : '');
    opts.ts_to = _toIso(toEl ? toEl.value : '');
    if (!opts.ts_from || !opts.ts_to) {
      _cenSingleSetStatus('Informe o per&iacute;odo personalizado antes de pesquisar.', 'error');
      return null;
    }
  } else {
    opts.ts_from = null;
    opts.ts_to = null;
  }
  return opts;
}

function _cenSingleHumanWindow(opts) {
  if (!opts) return 'per&iacute;odo atual';
  if (opts.window === 'custom' && opts.ts_from && opts.ts_to) return 'per&iacute;odo personalizado';
  var labels = { '6h': '6 horas', '24h': '24 horas', '7d': '7 dias', '30d': '30 dias' };
  return labels[opts.window] || opts.window || 'per&iacute;odo atual';
}

function _cenSingleSection(title, body, accentColor, borderColor) {
  return '<div style="margin-bottom:14px;border:1px solid ' + (borderColor || 'rgba(255,255,255,.08)') + ';background:rgba(255,255,255,.03);border-radius:14px;padding:14px 16px">'
    + '<div style="font-size:.88rem;font-weight:800;margin-bottom:12px;color:' + (accentColor || 'var(--accent2)') + ';text-transform:uppercase;letter-spacing:.05em">' + title + '</div>'
    + body
    + '</div>';
}

function _cenSingleMetric(label, value, sub, color) {
  return '<div style="border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:12px 14px;background:rgba(0,0,0,.12)">'
    + '<div style="font-size:.68rem;color:var(--muted);font-weight:800;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">' + label + '</div>'
    + '<div style="font-size:1.2rem;font-weight:800;color:' + (color || '#fff') + '">' + value + '</div>'
    + (sub ? '<div style="font-size:.76rem;color:var(--muted);margin-top:5px">' + sub + '</div>' : '')
    + '</div>';
}

function _cenSingleBuildMapState(plate, events) {
  _mapaTrajetoria = {
    plates: [plate],
    points: (events || []).map(function(ev) {
      return {
        camera_id: ev.camera_id,
        ts: ev.ts || '',
        plate: plate,
        cam_nome: ev.camera_name || ev.camera_id || '',
      };
    }),
  };
}

function _cenSingleRenderAnalysis(report, centralItem) {
  var body = document.getElementById('cen-single-body');
  if (!body || !report) return;
  var summary = report.summary || {};
  var eventsAsc = (report.events || []).slice().sort(function(a, b) {
    return new Date(a && a.ts ? a.ts : 0) - new Date(b && b.ts ? b.ts : 0);
  });
  var eventsDesc = eventsAsc.slice().reverse();
  var partners = (report.convoy_partners || []).slice().sort(function(a, b) {
    return Number((b && b.cameras_together) || 0) - Number((a && a.cameras_together) || 0);
  });
  var risk = _cenSingleRiskMeta(report);
  var firstEvent = eventsAsc.length ? eventsAsc[0] : null;
  var lastEvent = eventsAsc.length ? eventsAsc[eventsAsc.length - 1] : null;
  var vehicleType = (centralItem && centralItem.vehicle_type) || (lastEvent && lastEvent.vehicle_type) || '\u2014';
  var vehicleColor = (centralItem && centralItem.vehicle_color) || '\u2014';
  var cameraOrder = [];
  var seenCamera = {};
  eventsAsc.forEach(function(ev) {
    var name = ev.camera_name || ev.camera_id || 'Sem c&acirc;mera';
    if (!seenCamera[name]) {
      seenCamera[name] = true;
      cameraOrder.push(name);
    }
  });
  var routeHtml = cameraOrder.length
    ? cameraOrder.slice(0, 8).map(function(name, index) {
        var arrow = index < Math.min(cameraOrder.length, 8) - 1 ? '<span style="color:var(--muted)">&nbsp;&#8594;&nbsp;</span>' : '';
        return '<span style="display:inline-flex;align-items:center;padding:5px 10px;border-radius:999px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);font-size:.77rem;color:#f8fafc">' + name + '</span>' + arrow;
      }).join('')
      + (cameraOrder.length > 8 ? '<span style="color:var(--muted);font-size:.76rem">&nbsp;+ ' + (cameraOrder.length - 8) + ' c&acirc;m.</span>' : '')
    : '<span style="color:var(--muted)">Nenhuma c&acirc;mera no per&iacute;odo.</span>';
  var actionNote = report.is_alvo
    ? '<div style="margin-top:12px;padding:12px 14px;background:rgba(124,58,237,.12);border:1px solid rgba(168,85,247,.34);border-radius:12px;font-size:.82rem;color:#ede9fe;line-height:1.5">&#127919; Esta placa j&aacute; est&aacute; cadastrada como alvo. Use a investiga&ccedil;&atilde;o para refor&ccedil;ar monitoramento, conferir parceiros e consolidar rota.</div>'
    : partners.length
      ? '<div style="margin-top:12px;padding:12px 14px;background:rgba(217,119,6,.12);border:1px solid rgba(245,158,11,.30);border-radius:12px;font-size:.82rem;color:#fde68a;line-height:1.5">&#128101; H&aacute; acompanhamento confirmado no recorte. Vale validar recorr&ecirc;ncia, lideran&ccedil;a e reaproxima&ccedil;&otilde;es entre os parceiros abaixo.</div>'
      : '<div style="margin-top:12px;padding:12px 14px;background:rgba(34,197,94,.10);border:1px solid rgba(34,197,94,.24);border-radius:12px;font-size:.82rem;color:#bbf7d0;line-height:1.5">&#9989; N&atilde;o houve parceiro confirmado no filtro atual. A an&aacute;lise segue focada na rota e nas passagens da pr&oacute;pria placa.</div>';

  var summaryHtml = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:12px">'
    + _cenSingleMetric('Risco', risk.label, report.is_alvo ? 'placa j&aacute; cadastrada como alvo' : 'avalia&ccedil;&atilde;o operacional', risk.color)
    + _cenSingleMetric('Score', String(report.score || 0) + ' pts', 'pontua&ccedil;&atilde;o individual')
    + _cenSingleMetric('Passagens', String(summary.total_passes || 0), firstEvent ? 'desde ' + fmtTs(firstEvent.ts) : 'nenhuma no per&iacute;odo')
    + _cenSingleMetric('C&acirc;meras', String(summary.cameras_count || 0), 'locais distintos')
    + _cenSingleMetric('Parceiros', String(partners.length), partners.length ? 'com filtro confirmado' : 'sem confirma&ccedil;&atilde;o')
    + _cenSingleMetric('Conf. m&eacute;dia', summary.avg_confidence > 0 ? formatConfidencePercent(summary.avg_confidence) + '%' : '\u2014', 'leituras v&aacute;lidas')
    + '</div>'
    + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px">'
      + _cenSingleMetric('Dire&ccedil;&atilde;o dominante', summary.dom_direction === 'CRESCENTE' ? '&#8593; CRESCENTE' : summary.dom_direction === 'DECRESCENTE' ? '&#8595; DECRESCENTE' : '\u2014', 'fluxo predominante')
      + _cenSingleMetric('Tipo do ve&iacute;culo', vehicleType || '\u2014', 'detec&ccedil;&atilde;o mais recente')
      + _cenSingleMetric('Cor', vehicleColor || '\u2014', 'enriquecimento da central')
      + _cenSingleMetric('&Uacute;ltimo visto', lastEvent ? fmtTs(lastEvent.ts) : '\u2014', lastEvent ? (lastEvent.camera_name || lastEvent.camera_id || '') : 'sem passagens')
    + '</div>'
    + actionNote;

  if (report.is_alvo && (report.alvo_descricao || report.alvo_list)) {
    summaryHtml += '<div style="margin-top:12px;padding:12px 14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px">'
      + '<div style="font-size:.74rem;font-weight:800;color:var(--accent2);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">&#127919; Cadastro operacional</div>'
      + '<div style="font-size:.82rem;color:var(--text)">' + (report.alvo_descricao || 'Sem descri&ccedil;&atilde;o cadastrada.') + '</div>'
      + (report.alvo_list ? '<div style="font-size:.76rem;color:var(--muted);margin-top:6px">Lista: ' + report.alvo_list + '</div>' : '')
      + '</div>';
  }

  var trajectoryHtml = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-bottom:12px">'
    + _cenSingleMetric('Primeira passagem', firstEvent ? fmtTs(firstEvent.ts) : '\u2014', firstEvent ? (firstEvent.camera_name || firstEvent.camera_id || '') : '')
    + _cenSingleMetric('&Uacute;ltima passagem', lastEvent ? fmtTs(lastEvent.ts) : '\u2014', lastEvent ? (lastEvent.camera_name || lastEvent.camera_id || '') : '')
    + _cenSingleMetric('Percurso resumido', cameraOrder.length ? String(cameraOrder.length) + ' c&acirc;m.' : '\u2014', cameraOrder.length ? 'ordem de apari&ccedil;&atilde;o' : 'sem rota')
    + '</div>'
    + '<div style="padding:12px 14px;background:rgba(0,0,0,.12);border:1px solid rgba(255,255,255,.08);border-radius:12px;margin-bottom:12px">'
      + '<div style="font-size:.74rem;font-weight:800;color:var(--accent2);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">&#128506; Ordem de c&acirc;meras no per&iacute;odo</div>'
      + '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0;line-height:1.8">' + routeHtml + '</div>'
    + '</div>';

  var eventRows = eventsDesc.slice(0, 12).map(function(ev, index) {
    var conf = ev.confidence > 0 ? formatConfidencePercent(ev.confidence) + '%' : '\u2014';
    return '<tr>'
      + '<td style="font-size:.74rem;color:var(--muted);text-align:center">' + (index + 1) + '</td>'
      + '<td style="font-size:.78rem;white-space:nowrap">' + (ev.ts ? fmtTs(ev.ts) : '\u2014') + '</td>'
      + '<td style="font-size:.78rem">' + (ev.camera_name || ev.camera_id || '\u2014') + '</td>'
      + '<td style="font-size:.78rem;font-weight:700">' + (ev.direcao || '\u2014') + '</td>'
      + '<td style="font-size:.78rem;color:var(--muted)">' + (ev.vehicle_type || '\u2014') + '</td>'
      + '<td style="font-size:.78rem;color:var(--muted);text-align:center">' + conf + '</td>'
      + '</tr>';
  }).join('');
  trajectoryHtml += eventsDesc.length
    ? '<div class="table-wrap"><table><thead><tr><th>#</th><th>Data / Hora</th><th>C&acirc;mera</th><th>Dire&ccedil;&atilde;o</th><th>Tipo</th><th>Conf.</th></tr></thead><tbody>' + eventRows + '</tbody></table></div>'
    : '<div style="padding:14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;color:var(--muted);font-size:.82rem">Nenhuma passagem encontrada para a placa no per&iacute;odo selecionado.</div>';

  var partnersHtml = '';
  if (partners.length) {
    var partnerRows = partners.map(function(partner) {
      var camNames = (partner.cameras_detail || []).map(function(item) { return item.cam_nome || item.camera_id; }).join(', ');
      var spanLabel = partner.trip_span_sec >= 60 ? Math.round(partner.trip_span_sec / 60) + ' min' : (partner.trip_span_sec || 0) + ' s';
      var alvoBadge = partner.is_alvo ? ' <span class="badge badge-danger" style="font-size:.64rem">ALVO</span>' : '';
      return '<tr>'
        + '<td>' + plateHtml(partner.plate) + alvoBadge + '</td>'
        + '<td style="text-align:center;font-weight:700;color:var(--accent2)">' + String(partner.cameras_together || 0) + '</td>'
        + '<td style="text-align:center;font-size:.78rem">' + spanLabel + '</td>'
        + '<td style="font-size:.76rem;white-space:nowrap">' + (partner.last_seen ? fmtTs(partner.last_seen) : '\u2014') + '</td>'
        + '<td style="font-size:.74rem;color:var(--muted);max-width:220px;overflow:hidden;text-overflow:ellipsis" title="' + camNames + '">' + (camNames || '\u2014') + '</td>'
        + '<td><button class="btn btn-outline btn-xs" onclick="_cenSingleSearch(\'' + String(partner.plate || '').replace(/'/g, "\\'") + '\')">&#128269; Analisar</button></td>'
        + '</tr>';
    }).join('');
    partnersHtml = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:12px">'
      + _cenSingleMetric('Parceiros confirmados', String(partners.length), 'mesma rota / per&iacute;odo')
      + _cenSingleMetric('Maior coocorr&ecirc;ncia', String(Math.max.apply(null, partners.map(function(partner) { return Number(partner.cameras_together || 0); }))) + ' c&acirc;m.', 'melhor parceiro')
      + _cenSingleMetric('Parceiros alvo', String(partners.filter(function(partner) { return !!partner.is_alvo; }).length), 'j&aacute; cadastrados')
      + '</div>'
      + '<div style="background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.14);border-radius:10px;padding:10px 12px;margin-bottom:10px;font-size:.78rem;color:#fca5a5">&#9888; A lista abaixo mostra parceiros confirmados na mesma janela operacional, filtrados pela for&ccedil;a m&iacute;nima definida no topo.</div>'
      + '<div class="table-wrap"><table><thead><tr><th>Parceiro</th><th>C&acirc;meras juntos</th><th>Span</th><th>&Uacute;ltimo visto</th><th>C&acirc;meras</th><th>A&ccedil;&atilde;o</th></tr></thead><tbody>' + partnerRows + '</tbody></table></div>';
  } else {
    partnersHtml = '<div style="padding:14px;background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.18);border-radius:10px;color:#bbf7d0;font-size:.82rem">&#9989; Nenhum parceiro confirmado com o filtro atual. Se quiser ampliar a busca, reduza a for&ccedil;a do parceiro ou aumente o per&iacute;odo.</div>';
  }

  var lastDecision = report.last_decision;
  var decisionLabels = {
    confirmado: '&#9989; Suspeito confirmado',
    falso_positivo: '&#10060; Falso positivo',
    ignorar: '&#9197; Ignorado',
  };
  var decisionHtml = lastDecision
    ? '<div style="margin-bottom:12px;padding:12px 14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px">'
        + '<div style="font-size:.74rem;font-weight:800;color:var(--accent2);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Ultima decisao operacional</div>'
        + '<div style="font-size:.88rem;font-weight:800;color:#fff;margin-bottom:4px">' + (decisionLabels[lastDecision.decision] || lastDecision.decision || '\u2014') + '</div>'
        + '<div style="font-size:.8rem;color:var(--muted);line-height:1.5">'
          + (lastDecision.note ? lastDecision.note + '<br>' : '')
          + 'Registrado por ' + (lastDecision.operator || 'sistema') + ' em ' + (lastDecision.created_at ? fmtTs(lastDecision.created_at) : '\u2014') + '.'
        + '</div>'
      + '</div>'
    : '<div style="margin-bottom:12px;padding:12px 14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px;color:var(--muted);font-size:.82rem">Nenhuma decisao operacional registrada para esta placa at&eacute; o momento.</div>';

  var tc = centralItem && centralItem.threat_center ? centralItem.threat_center : null;
  var threatHtml = '';
  if (tc) {
    var rs = tc.route_similarity || {};
    var badges = (tc.threat_badges || []).map(function(badge) {
      return '<span class="badge" style="background:rgba(139,92,246,.35);color:#ede9fe;font-size:.68rem">' + badge + '</span>';
    }).join(' ');
    threatHtml = '<div style="padding:12px 14px;background:rgba(139,92,246,.08);border:1px solid rgba(139,92,246,.22);border-radius:12px">'
      + '<div style="font-size:.74rem;font-weight:800;color:#ddd6fe;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Central de amea&ccedil;a</div>'
      + (badges ? '<div style="margin-bottom:8px">' + badges + '</div>' : '')
      + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px">'
        + _cenSingleMetric('Alvo cadastrado', tc.matched_target ? '&#9989; Sim' : '&#8212; N&atilde;o', tc.match_type || '', '#ede9fe')
        + _cenSingleMetric('Rota semelhante', rs.matched ? '&#9989; Sim' : '&#8212; N&atilde;o', rs.best_alvo ? 'mais parecida com ' + rs.best_alvo : '', '#ede9fe')
        + _cenSingleMetric('Similaridade', rs.similarity_ratio ? Math.round(rs.similarity_ratio * 100) + '%' : '\u2014', rs.common_cameras && rs.common_cameras.length ? rs.common_cameras.length + ' c&acirc;m. em comum' : '')
      + '</div>'
      + ((rs.common_cameras && rs.common_cameras.length) ? '<div style="font-size:.78rem;color:var(--muted);margin-top:10px">C&acirc;meras em comum: ' + rs.common_cameras.join(', ') + '</div>' : '')
      + ((rs.common_cities && rs.common_cities.length) ? '<div style="font-size:.78rem;color:var(--muted);margin-top:4px">Cidades em comum: ' + rs.common_cities.join(', ') + '</div>' : '')
      + '</div>';
  } else {
    threatHtml = '<div style="padding:12px 14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px;color:var(--muted);font-size:.82rem">Nenhum v&iacute;nculo adicional com alvo ou rota semelhante foi identificado na central para este recorte.</div>';
  }

  if (centralItem) {
    threatHtml += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:12px">'
      + _cenSingleMetric('Score atividade', String(centralItem.score_activity || 0) + ' pts', 'movimenta&ccedil;&atilde;o da placa')
      + _cenSingleMetric('Score acompanhamento', String(centralItem.score_acompanhamento || 0) + ' pts', 'grupo / parceiros')
      + _cenSingleMetric('Score rota', String(centralItem.score_rota || 0) + ' pts', 'semelhan&ccedil;a operacional')
      + _cenSingleMetric('Score alvo', String(centralItem.score_alvo || 0) + ' pts', 'cadastro direto')
      + '</div>';
  }

  body.innerHTML = _cenSingleSection('1. Resumo t&aacute;tico da placa', summaryHtml, risk.color, risk.border)
    + _cenSingleSection('2. Trajet&oacute;ria no per&iacute;odo', trajectoryHtml, 'var(--accent2)')
    + _cenSingleSection('3. Companheiros / comboio (' + partners.length + ')', partnersHtml, '#fca5a5', 'rgba(239,68,68,.18)')
    + _cenSingleSection('4. Decis&atilde;o e v&iacute;nculo operacional', decisionHtml + threatHtml, 'var(--accent2)');
}

function _cenSingleInit() {
  var plateEl = document.getElementById('cen-single-plate');
  if (!plateEl) return;
  var opts = _cenSingleState.opts || _cenSingleDefaultOpts();
  _cenSingleApplyOptsToForm(opts, !_cenSingleInitDone);
  _cenSingleLoadRecentSearches();
  _cenSingleRenderRecentSearches();
  if (_cenSingleState.plate && !plateEl.value) plateEl.value = _cenSingleState.plate;
  if (_cenSingleState.report) {
    _cenSingleSyncSummaryCards(_cenSingleState.report, _cenSingleState.centralItem);
    _cenSingleSyncActionButtons();
    _cenSingleRenderAnalysis(_cenSingleState.report, _cenSingleState.centralItem);
  } else {
    _cenSingleResetSummaryCards();
    _cenSingleSyncActionButtons();
    _cenSingleRenderEmpty();
    _cenSingleSetStatus('Informe a placa e o per&iacute;odo desejado para abrir o relat&oacute;rio detalhado.', 'info');
  }
  _cenSingleInitDone = true;
}

async function _cenSingleSearchFromForm() {
  var plateEl = document.getElementById('cen-single-plate');
  if (!plateEl) return;
  var plate = (plateEl.value || '').trim().toUpperCase();
  if (!plate) {
    _cenSingleSetStatus('Informe uma placa para pesquisar.', 'error');
    _cenSingleFocusPlateInput();
    return;
  }
  var opts = _cenSingleReadOpts();
  if (!opts) return;
  await _cenSingleSearch(plate, opts);
}

async function _cenSingleSearch(plate, opts) {
  plate = String(plate || '').replace(/[^A-Z0-9]/gi, '').toUpperCase().slice(0, 7);
  if (!plate) {
    _cenSingleSetStatus('Placa inv&aacute;lida para pesquisa.', 'error');
    return;
  }
  var plateEl = document.getElementById('cen-single-plate');
  if (plateEl) plateEl.value = plate;
  opts = opts || _cenSingleReadOpts() || _cenSingleDefaultOpts();
  _cenSingleState.plate = plate;
  _cenSingleState.opts = Object.assign({}, opts);
  _cenSinglePushRecent(plate);
  _cenSingleSetStatus('Gerando relat&oacute;rio de ' + plate + ' em ' + _cenSingleHumanWindow(opts) + '&hellip;', 'info');
  try {
    var responses = await Promise.all([
      fetch(_cenSingleBuildReportUrl(plate, opts)),
      fetch(_cenSingleBuildCentralUrl(plate, opts)).catch(function() { return null; }),
    ]);
    var reportResp = responses[0];
    var centralResp = responses[1];
    if (!reportResp || !reportResp.ok) {
      var errPayload = await reportResp.json().catch(function() { return { detail: 'HTTP ' + (reportResp ? reportResp.status : '?') }; });
      throw new Error(errPayload.detail || ('HTTP ' + reportResp.status));
    }
    var report = await reportResp.json();
    var centralItem = null;
    if (centralResp && centralResp.ok) {
      var centralPayload = await centralResp.json().catch(function() { return { items: [] }; });
      centralItem = (centralPayload.items || []).find(function(item) { return item.plate === plate; }) || null;
    }
    _cenSingleState.report = report;
    _cenSingleState.centralItem = centralItem;
    _batedorReportData = { plate: plate, d: report };
    _reportCurrentPlate = plate;
    _reportCurrentOpts = _normalizeReportOpts(opts);
    if (centralItem) _cenAllItems = [centralItem];
    _cenSingleBuildMapState(plate, report.events || []);
    _cenSingleSyncSummaryCards(report, centralItem);
    _abrirRelatorioPlacaIndividual();
    _cenSingleSetStatus('Relat&oacute;rio aberto para ' + plate + '.', 'ok');
  } catch(e) {
    _cenSingleState.report = null;
    _cenSingleState.centralItem = null;
    _cenSingleResetSummaryCards();
    _cenSingleSetStatus('Erro ao gerar o relat&oacute;rio da placa ' + plate + ': ' + e.message, 'error');
  }
}

function _cenSingleOpenFullAnalysis() {
  if (!_cenSingleState.report) return;
  openBatedorReport(_cenSingleState.plate, false, _cenSingleState.opts || _cenSingleDefaultOpts());
}

function _cenSingleOpenPrintableReport() {
  if (!_cenSingleState.report) return;
  _abrirRelatorioPlacaIndividual();
}

function _cenSingleOpenMap() {
  if (!_cenSingleState.report) return;
  var events = (_cenSingleState.report.events || []).slice();
  if (!events.length) return;
  var timestamps = events.map(function(ev) { return ev.ts; }).filter(Boolean).sort();
  var nowMs = Date.now();
  var tsFrom = timestamps.length
    ? _toLocalDTInput(new Date(new Date(timestamps[0]).getTime() - 3600000))
    : _toLocalDTInput(new Date(nowMs - 7 * 86400000));
  var tsTo = timestamps.length
    ? _toLocalDTInput(new Date(new Date(timestamps[timestamps.length - 1]).getTime() + 3600000))
    : _toLocalDTInput(new Date(nowMs));
  _verRotaNaMapa(_cenSingleState.plate, tsFrom, tsTo, events.length + ' passagem(ns)');
}

async function _cenSingleRestoreReportModal(plate) {
  plate = String(plate || (_cenSingleState && _cenSingleState.plate) || '').trim().toUpperCase();
  var nav = document.querySelector('#sidebar .nav-item[onclick*="batedor"]');
  if (nav && typeof switchTab === 'function') switchTab('batedor', nav);
  var subTab = document.getElementById('bat-subtab-placas');
  if (subTab && typeof switchBatTab === 'function') switchBatTab('placas', subTab);
  if ((!_batedorReportData || !_batedorReportData.d) && _cenSingleState && _cenSingleState.report) {
    _batedorReportData = { plate: plate || _cenSingleState.plate || '', d: _cenSingleState.report };
  }
  if (_batedorReportData && _batedorReportData.d) {
    _abrirRelatorioPlacaIndividual();
    return;
  }
  if (plate) {
    await _cenSingleSearch(plate, (_cenSingleState && _cenSingleState.opts) || _cenSingleDefaultOpts());
  }
}

function _cenSingleStartTargetFlow(plate) {
  plate = String(plate || (_cenSingleState && _cenSingleState.plate) || '').trim().toUpperCase();
  if (!plate) return;
  _vehicleTargetFlow = {
    stage: 'target-choice',
    message: '🎯 Alvo salvo com sucesso!',
    restore: async function() {
      await _cenSingleRestoreReportModal(plate);
    }
  };
  _addPlateAsAlvo(plate);
}

function _cenSingleCreateTarget() {
  if (!_cenSingleState.report || _cenSingleState.report.is_alvo) return;
  _cenSingleStartTargetFlow(_cenSingleState.plate);
}

function _cenSingleClear() {
  var plateEl = document.getElementById('cen-single-plate');
  if (plateEl) plateEl.value = '';
  _cenSingleState = {
    plate: '',
    report: null,
    opts: _cenSingleDefaultOpts(),
    centralItem: null,
  };
  _cenSingleApplyOptsToForm(_cenSingleDefaultOpts(), true);
  _cenSingleResetSummaryCards();
  _cenSingleSyncActionButtons();
  _cenSingleRenderEmpty();
  _cenSingleSetStatus('Consulta limpa. Informe uma nova placa para abrir a an&aacute;lise detalhada.', 'info');
  _cenSingleFocusPlateInput();
}

function _cenSingleRefreshCurrent() {
  var plateEl = document.getElementById('cen-single-plate');
  var currentPlate = (plateEl && plateEl.value ? plateEl.value : _cenSingleState.plate || '').trim().toUpperCase();
  _cenSingleInit();
  if (currentPlate) {
    var opts = _cenSingleReadOpts();
    if (opts) _cenSingleSearch(currentPlate, opts);
  }
}

function _cgsGroupSizeChange() {
  var gs   = (document.getElementById('cgs-gsizes')    || {}).value || '2';
  var mode = (document.getElementById('cgs-ordermode') || {}).value;
  var plLabel = document.getElementById('cgs-payload-label');
  if (plLabel) plLabel.style.display = (mode === 'leader_front' && gs === '3+') ? 'inline' : 'none';
  _cgsLoad(true);
}

function _cgsOrderModeChange() {
  var mode = (document.getElementById('cgs-ordermode') || {}).value;
  var opts = document.getElementById('cgs-leader-opts');
  if (opts) opts.style.display = (mode === 'leader_front') ? 'inline' : 'none';
  var gs = (document.getElementById('cgs-gsizes') || {}).value || '2';
  var plLabel = document.getElementById('cgs-payload-label');
  if (plLabel) plLabel.style.display = (mode === 'leader_front' && gs === '3+') ? 'inline' : 'none';
  _cgsLoad(true);
}

function _cgsWindowChange() {
  var v = document.getElementById('cgs-window').value;
  document.getElementById('cgs-date-row').classList.toggle('visible', v === 'custom');
  if (v !== 'custom') _cgsLoad(true);
}

function _cgsReset() {
  var el;
  el = document.getElementById('cgs-window');      if (el) { el.value = '24h'; _cgsWindowChange(); }
  el = document.getElementById('cgs-gsizes');      if (el) el.value = '2';
  el = document.getElementById('cgs-min-cameras'); if (el) el.value = '2';
  el = document.getElementById('cgs-cowin');       if (el) el.value = '300';
  el = document.getElementById('cgs-risco');       if (el) el.value = '';
  var om = document.getElementById('cgs-ordermode'); if (om) { om.value = 'any'; _cgsOrderModeChange(); }
  var lr = document.getElementById('cgs-leader-ratio'); if (lr) lr.value = '70';
  var pm = document.getElementById('cgs-payload-max');  if (pm) pm.value = '0';
}

function _cgsApplyFilter() {
  _cgsPage = 0;
  _cgsRenderPage();
}

function _resolveTrajectoryCameraPoint(item, plate) {
  var cams = window._camsData || [];
  var eventKeys = [
    String(item.camera_id || '').trim().toLowerCase(),
    String(item.camera_ip || '').trim().toLowerCase(),
    String(item.camera_name || '').trim().toLowerCase(),
    String(item.cam_nome || '').trim().toLowerCase(),
    String(item.camera || '').trim().toLowerCase(),
    String(item.channel_name || '').trim().toLowerCase()
  ].filter(Boolean);
  var cam = cams.find(function(c) {
    var keys = [
      String(c.camera_id || '').trim().toLowerCase(),
      String(c.ip || '').trim().toLowerCase(),
      String(c.nome || '').trim().toLowerCase()
    ].filter(Boolean);
    return eventKeys.some(function(k) { return keys.indexOf(k) >= 0; });
  });
  if (!cam || cam.latitude == null || cam.longitude == null) return null;
  return {
    camera_id: item.camera_id || cam.camera_id || cam.ip || '',
    ts: item.occurred_at || item.ts || '',
    plate: plate,
    cam_nome: item.camera_name || item.cam_nome || item.camera || item.channel_name || cam.nome || cam.camera_id || '',
    lat: Number(cam.latitude),
    lng: Number(cam.longitude)
  };
}

function _buildTrajectoryFallbackFromReport(plate, apiData) {
  var rd = _batedorReportData;
  var wantedPlate = String(plate || '').trim().toUpperCase();
  var reportPlate = rd && rd.plate ? String(rd.plate).trim().toUpperCase() : '';
  var statePlate = (_cenSingleState && _cenSingleState.plate) ? String(_cenSingleState.plate).trim().toUpperCase() : '';
  var report = rd && rd.d ? rd.d : ((_cenSingleState && _cenSingleState.report) || null);
  if (!report) return null;
  if (reportPlate && reportPlate !== wantedPlate) return null;
  if (!reportPlate && statePlate && statePlate !== wantedPlate) return null;
  var events = (report.events || []).slice();
  if (!events.length) return null;

  var seen = {};
  var points = [];
  var missing = {};

  events.forEach(function(ev) {
    var point = _resolveTrajectoryCameraPoint(ev, plate);
    if (point && point.lat != null && point.lng != null) {
      var key = [point.camera_id || point.cam_nome || '', point.ts || ''].join('|');
      if (!seen[key]) {
        seen[key] = true;
        points.push(point);
      }
      return;
    }
    var missName = ev.camera_name || ev.cam_nome || ev.camera || ev.channel_name || ev.camera_id || ev.camera_ip || '';
    if (missName) missing[missName] = true;
  });

  if (!points.length) return null;
  points.sort(function(a, b) { return new Date(a.ts || 0) - new Date(b.ts || 0); });
  (apiData && apiData.cameras_without_gps || []).forEach(function(name) {
    if (name) missing[name] = true;
  });

  return {
    plate: wantedPlate,
    start: apiData && apiData.start,
    end: apiData && apiData.end,
    total_events: Math.max(Number((apiData && apiData.total_events) || 0), events.length),
    total_points: points.length,
    cameras_without_gps: Object.keys(missing),
    points: points
  };
}

async function openEventReport(eventId) {
  var ev = _eventCache[eventId];
  if (!ev || !ev.plate) {
    if (ev && ev.id) openImage(ev.id, ev.plate || '');
    return;
  }

  var plate = String(ev.plate || '').trim().toUpperCase();
  var tsBase = ev.ts || ev.occurred_at;
  var eventDate = tsBase ? new Date(tsBase) : new Date();
  if (isNaN(eventDate.getTime())) eventDate = new Date();
  var dayStart = new Date(eventDate);
  dayStart.setHours(0, 0, 0, 0);
  var dayEnd = new Date(eventDate);
  dayEnd.setHours(23, 59, 59, 999);

  _reportHistory = [];
  _reportCurrentPlate = null;
  _reportCurrentOpts = null;
  _detailModalReturnFn = function() { openEventReport(eventId); };
  document.getElementById('detail-modal-plate').innerHTML = '&#128203; Relat&oacute;rio do Evento &mdash; ' + plate;
  document.getElementById('detail-modal-body').innerHTML = '<p style="color:var(--muted)"><span class="spinner"></span> Carregando passagens do dia...</p>';
  var _mb = document.getElementById('detail-modal-map-btn');
  if (_mb) _mb.style.display = 'none';
  openModal('detail-modal');

  try {
    var rangeStart = _toLocalDTInput(dayStart);
    var rangeEnd = _toLocalDTInput(dayEnd);
    var responses = await Promise.all([
      fetch('/api/events?limit=200&plate=' + encodeURIComponent(plate)
        + '&dt_from=' + encodeURIComponent(dayStart.toISOString())
        + '&dt_to=' + encodeURIComponent(dayEnd.toISOString())),
      fetch('/api/vehicles/' + encodeURIComponent(plate) + '/trajectory'
        + '?start=' + encodeURIComponent(rangeStart)
        + '&end=' + encodeURIComponent(rangeEnd)
        + '&dedupe_seconds=5')
    ]);
    var resp = responses[0];
    var trajResp = responses[1];
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var d = await resp.json();
    var events = (d.items || []).slice().sort(function(a, b) {
      return new Date(b.occurred_at || b.ts || 0).getTime() - new Date(a.occurred_at || a.ts || 0).getTime();
    });
    var camerasSeen = {};
    var confSum = 0;
    var confCount = 0;
    events.forEach(function(item) {
      var camKey = item.camera_id || item.cam_nome || item.channel_name || '';
      if (camKey) camerasSeen[camKey] = true;
      var confNum = Number(item.confidence);
      if (confNum > 0) {
        confSum += confNum;
        confCount += 1;
      }
    });
    var currentCam = ev.cam_nome || ev.channel_name || ev.camera_id || '-';
    var currentDir = ev.direcao === 'CRESCENTE'
      ? '<span class="badge badge-info" style="font-size:.7rem">&#8593; CRESCENTE</span>'
      : ev.direcao === 'DECRESCENTE'
        ? '<span class="badge badge-warning" style="font-size:.7rem">&#8595; DECRESCENTE</span>'
        : '<span style="color:var(--muted)">—</span>';
    var avgConf = confCount > 0
      ? formatConfidencePercent(confSum / confCount) + '%'
      : '—';
    var currentThumb = (ev.image || ev.image_path || ev.thumb)
      ? '<img class="thumb" src="/api/events/' + ev.id + '/thumbnail?w=112&h=78" loading="lazy" onclick="openImage(' + ev.id + ',\'' + plate.replace(/'/g,"\\'") + '\')" style="width:112px;height:78px;border-radius:8px;object-fit:cover;cursor:pointer;border:1px solid rgba(255,255,255,.08)">'
      : '<div class="thumb-none" style="width:112px;height:78px">sem foto</div>';

    var topHtml = '<div style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;margin-bottom:14px;padding:14px 16px;background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(255,255,255,.02));border:1px solid rgba(255,255,255,.08);border-radius:14px">'
      + '<div>'
      + '<div style="font-size:.72rem;color:var(--muted);font-weight:800;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">Ocorrência atual</div>'
      + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px">'
      + '<div><div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Placa</div><div style="font-size:1.05rem;font-weight:800;color:#fff;font-family:monospace">' + plate + '</div></div>'
      + '<div><div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Data/Hora</div><div style="font-size:.84rem;color:#fff">' + fmtTs(tsBase) + '</div></div>'
      + '<div><div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Câmera</div><div style="font-size:.84rem;color:#fff">' + currentCam + '</div></div>'
      + '<div><div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Direção</div><div style="font-size:.84rem">' + currentDir + '</div></div>'
      + '</div>'
      + '</div>'
      + '<div style="display:flex;align-items:flex-start;justify-content:flex-end">' + currentThumb + '</div>'
      + '</div>';

    var actionHtml = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px;padding:12px 14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px">'
      + '<button class="btn btn-sm" style="background:#ef4444;color:#fff;font-weight:700" onclick="verTrajetoriaNoMapa()">&#128663; Ver Trajet&oacute;ria no Mapa</button>'
      + '<button class="btn btn-sm" style="background:rgba(139,92,246,.78);color:#fff;font-weight:700" onclick="_addPlateAsAlvo(\'' + plate.replace(/'/g,"\\'") + '\')">&#127919; Cadastrar como Alvo</button>'
      + '<button class="btn btn-outline btn-sm" onclick="openAlvoDetail(\'' + plate.replace(/'/g,"\\'") + '\',\'\')">&#128269; Procurar Companheiro</button>'
      + '</div>';

    var summaryHtml = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:14px">'
      + '<div style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:12px 14px"><div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Passagens no dia</div><div style="font-size:1.25rem;font-weight:800;color:#fff">' + events.length + '</div></div>'
      + '<div style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:12px 14px"><div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Câmeras distintas</div><div style="font-size:1.25rem;font-weight:800;color:#fff">' + Object.keys(camerasSeen).length + '</div></div>'
      + '<div style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:12px 14px"><div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Conf. média</div><div style="font-size:1.25rem;font-weight:800;color:#fff">' + avgConf + '</div></div>'
      + '</div>';

    var passRows = events.map(function(item) {
      _imgMeta[item.id] = {
        camName: item.camera_name || item.camera_id || '',
        ts: item.occurred_at || item.ts || '',
        confidence: item.confidence != null ? item.confidence : null
      };
      var conf = item.confidence > 0 ? formatConfidencePercent(item.confidence) + '%' : '-';
      var thumb = item.image_path
        ? '<img class="thumb" src="/api/events/' + item.id + '/thumbnail?w=96&h=64" loading="lazy" onclick="openImage(' + item.id + ',\'' + plate.replace(/'/g,"\\'") + '\')" style="border-radius:6px;cursor:pointer">'
        : '<div class="thumb-none">-</div>';
      return '<tr>'
        + '<td>' + thumb + '</td>'
        + '<td style="white-space:nowrap;font-size:.79rem">' + fmtTs(item.occurred_at || item.ts) + '</td>'
        + '<td style="font-size:.79rem">' + (item.cam_nome || item.camera || item.channel_name || item.camera_id || '-') + '</td>'
        + '<td>' + _dirCell(item.direcao) + '</td>'
        + '<td style="text-align:center;font-weight:700">' + conf + '</td>'
        + '</tr>';
    }).join('');

    var eventsHtml = '<h3 style="font-size:.95rem;font-weight:800;margin:14px 0 8px;color:#fff">&#128247; Últimas passagens do veículo no dia</h3>'
      + (events.length
        ? '<div class="table-wrap"><table><thead><tr><th>Foto</th><th>Data/Hora</th><th>Câmera</th><th>Direção</th><th>Conf.</th></tr></thead><tbody>' + passRows + '</tbody></table></div>'
        : '<p style="color:var(--muted);font-size:.82rem">Nenhuma passagem encontrada para este veículo no dia do evento.</p>');

    document.getElementById('detail-modal-body').innerHTML = topHtml + actionHtml + summaryHtml + eventsHtml;
    _mapaTrajetoria = null;
    if (trajResp.ok) {
      var trajData = await trajResp.json();
      _mapaTrajetoria = {
        plates: [plate],
        points: (trajData.points || []).map(function(p) {
          return {
            lat: p.lat,
            lng: p.lon,
            ts: p.ts,
            plate: plate,
            camera_id: p.camera_id,
            cam_nome: p.camera_name,
            direcao: p.direction,
            seq: 0
          };
        }),
        stats: {
          total_points: trajData.total_points || 0,
          total_events: trajData.total_events || events.length,
          cameras_without_gps: trajData.cameras_without_gps || []
        }
      };
    }
  } catch (e) {
    document.getElementById('detail-modal-body').innerHTML = '<p style="color:var(--danger)">Erro ao carregar relatório do evento: ' + e.message + '</p>';
  }
}

function _cgsPageNav(delta) {
  _cgsPage = Math.max(0, _cgsPage + delta);
  _cgsRenderPage();
}

async function _cgsLoad(showSpinner) {
  var tbody = document.getElementById('cgs-tbody');
  if (!tbody) return;
  if (showSpinner) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:32px"><span class="spinner"></span> Analisando grupos suspeitos&hellip;</td></tr>';
  }
  var w = (document.getElementById('cgs-window') || {}).value || '24h';
  var tsFrom = null, tsTo = null;
  if (w === 'custom') {
    tsFrom = _toIso((document.getElementById('cgs-ts-from') || {}).value);
    tsTo   = _toIso((document.getElementById('cgs-ts-to')   || {}).value);
    if (!tsFrom || !tsTo) { alert('Informe o per\u00edodo personalizado.'); return; }
    w = '1h';
  }
  var gs        = (document.getElementById('cgs-gsizes')      || {}).value || '2';
  var minCam    = (document.getElementById('cgs-min-cameras') || {}).value || '2';
  var cowin     = (document.getElementById('cgs-cowin')       || {}).value || '300';
  var orderMode = (document.getElementById('cgs-ordermode')   || {}).value || 'any';
  var leaderR   = percentInputToRatio((document.getElementById('cgs-leader-ratio')|| {}).value || '70', 0.70);
  var payloadM  = (document.getElementById('cgs-payload-max') || {}).value || '0';
  var url = '/api/central/grupos_suspeitos'
    + '?window=' + encodeURIComponent(w)
    + '&group_sizes=' + encodeURIComponent(gs)
    + '&min_cameras=' + encodeURIComponent(minCam)
    + '&co_window=' + encodeURIComponent(cowin)
    + '&order_mode=' + encodeURIComponent(orderMode)
    + '&leader_ratio=' + encodeURIComponent(leaderR)
    + '&payload_max_front=' + encodeURIComponent(payloadM)
    + '&limit=200';
  if (tsFrom) url += '&ts_from=' + encodeURIComponent(tsFrom);
  if (tsTo)   url += '&ts_to='   + encodeURIComponent(tsTo);
  try {
    var resp = await fetch(url);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var data = await resp.json();
    _cgsAllGroups = data.groups || [];
    _cgsPage = 0;
    // atualizar cards
    var total  = _cgsAllGroups.length;
    var nalto  = _cgsAllGroups.filter(function(g){ return g.risco === 'ALTO'; }).length;
    var nmedio = _cgsAllGroups.filter(function(g){ return g.risco === 'MÉDIO'; }).length;
    var nalvo  = _cgsAllGroups.filter(function(g){ return g.alvos && g.alvos.length > 0; }).length;
    var el;
    el = document.getElementById('cgs-total'); if (el) el.textContent = total;
    el = document.getElementById('cgs-alto');  if (el) el.textContent = nalto  || '-';
    el = document.getElementById('cgs-medio'); if (el) el.textContent = nmedio || '-';
    el = document.getElementById('cgs-alvos'); if (el) el.textContent = nalvo  || '-';
    _cgsRenderPage();
  } catch(e) {
    if (tbody) tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--danger);padding:24px">Erro ao carregar: ' + e.message + '</td></tr>';
  }
}

function _cgsRenderPage() {
  var riscoFl = (document.getElementById('cgs-risco') || {}).value || '';
  var items = _cgsAllGroups.filter(function(g) {
    if (riscoFl && g.risco !== riscoFl) return false;
    return true;
  });
  var total = items.length;
  var pages = Math.max(1, Math.ceil(total / _cgsPageSize));
  if (_cgsPage >= pages) _cgsPage = pages - 1;
  var start = _cgsPage * _cgsPageSize;
  var page  = items.slice(start, start + _cgsPageSize);

  var pg = document.getElementById('cgs-pagination');
  if (total > _cgsPageSize) {
    pg.style.display = 'flex';
    document.getElementById('cgs-page-info').textContent =
      'P\u00e1gina ' + (_cgsPage + 1) + ' de ' + pages + ' \u00b7 ' + total + ' grupo(s)';
    document.getElementById('cgs-btn-prev').disabled = _cgsPage === 0;
    document.getElementById('cgs-btn-next').disabled = _cgsPage >= pages - 1;
  } else if (total > 0) {
    pg.style.display = 'flex';
    document.getElementById('cgs-page-info').textContent = total + ' grupo(s)';
    document.getElementById('cgs-btn-prev').disabled = true;
    document.getElementById('cgs-btn-next').disabled = true;
  } else {
    pg.style.display = 'none';
  }
  _cgsRenderTable(page, total);
}

function _cgsRiscoBadge(risco) {
  if (risco === 'ALTO')  return '<span class="badge badge-red"    style="font-size:.78rem">&#128293; ALTO</span>';
  if (risco === 'MÉDIO') return '<span class="badge badge-yellow" style="font-size:.78rem">&#9888; M&Eacute;DIO</span>';
  return '<span class="badge badge-green" style="font-size:.78rem">&#128994; BAIXO</span>';
}

function _cgsPadraoBadge(padrao) {
  var bg = '#6366f1', color = '#fff';
  if (padrao === 'BATEDOR')   { bg = '#dc2626'; }
  else if (padrao === 'DUPLA') { bg = '#d97706'; }
  else if (padrao.indexOf('3') >= 0) { bg = '#7c3aed'; }
  return '<span style="font-size:.72rem;font-weight:700;background:' + bg + ';color:' + color + ';padding:2px 9px;border-radius:99px;white-space:nowrap">' + padrao + '</span>';
}

function _cgsRenderTable(items, total) {
  var tbody = document.getElementById('cgs-tbody');
  if (!tbody) return;
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:32px">'
      + (total === 0 ? 'Nenhum grupo suspeito detectado com os filtros atuais.' : 'Sem resultados nesta p\u00e1gina.')
      + '</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(function(g) {
    // Placas
    var placasHtml = g.plates.map(function(p) {
      var isAlvo = g.alvos && g.alvos.some(function(a){ return a.plate === p; });
      var isLeader = p === g.leader;
      var style = 'font-family:monospace;font-weight:800;font-size:.9rem;letter-spacing:.06em;white-space:nowrap';
      var color = isAlvo ? 'color:#dbc483' : isLeader ? 'color:#f87171' : 'color:var(--text)';
      var badge = isAlvo
        ? ' <span style="font-size:.62rem;background:#a07a24;color:#fff7db;padding:1px 5px;border-radius:99px;vertical-align:middle">ALVO</span>'
        : isLeader && g.leader_ratio >= 0.70
        ? ' <span style="font-size:.62rem;background:#dc2626;color:#fff;padding:1px 5px;border-radius:99px;vertical-align:middle">&#128308;</span>'
        : '';
      return '<div style="' + style + ';' + color + '">' + p + badge + '</div>';
    }).join('');

    // Câmeras
    var camCount = g.cameras_count;
    var diasJuntos = Number(g.distinct_days || 0);
    var diasHtml = diasJuntos
      ? '<span style="font-weight:700;font-size:.88rem;color:var(--accent2)">' + diasJuntos + '</span> <span style="font-size:.72rem;color:var(--muted)">dia(s)</span>'
      : '<span style="color:var(--muted)">—</span>';

    // Localidades (nomes das câmeras, únicos, max 2)
    var locs = g.cameras_names || [];
    var locText = locs.slice(0, 2).join(', ') + (locs.length > 2 ? ' +' + (locs.length - 2) : '');

    // Última vez juntos
    var lastHtml = g.last_seen
      ? '<span style="font-size:.78rem;white-space:nowrap">' + new Date(g.last_seen).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'}) + '</span>'
      : '<span style="color:var(--muted)">&mdash;</span>';

    // Score chip
    var scoreBg = g.score >= 80 ? '#ef4444' : g.score >= 40 ? '#d97706' : '#6b7280';
    var scoreHtml = '<span style="font-size:.78rem;font-weight:800;background:' + scoreBg + ';color:#fff;padding:2px 9px;border-radius:99px">' + g.score + '</span>';

    var tcBadgesHtml = '';
    if (g.threat_center && g.threat_center.threat_badges && g.threat_center.threat_badges.length) {
      tcBadgesHtml = g.threat_center.threat_badges.map(function(badge) {
        var isLider = badge === 'LÍDER_É_ALVO';
        return '<br><span style="font-size:.6rem;font-weight:800;background:' + (isLider ? '#dc2626' : '#a07a24') + ';color:' + (isLider ? '#fff' : '#fff7db') + ';padding:1px 5px;border-radius:99px">' + (isLider ? '\u2605 L\u00cdDER ALVO' : '\u26a1 ALVO NO GRUPO') + '</span>';
      }).join('');
    }

    var rowStyle = g.risco === 'ALTO' ? 'background:rgba(239,68,68,.05)' : (g.threat_center && g.threat_center.matched_target) || (g.alvos && g.alvos.length) ? 'background:rgba(196,166,74,.08)' : '';

    // Ações
    var safeId  = (g.id || '').replace(/'/g,"\\'");
    var ações = '<div class="action-buttons">'
      + '<button class="btn btn-outline btn-xs" title="Visualizar grupo" onclick="_cgsOpenDetalhe(\'' + safeId + '\')">&#128269; Visualizar</button>'
      + '</div>';

    return '<tr style="' + rowStyle + '">'
      + '<td style="max-width:220px">' + placasHtml + '</td>'
      + '<td>'
        + _cgsPadraoBadge(g.padrao)
        + '<div style="font-size:.72rem;color:var(--muted);margin-top:4px">'
        + (g.leader && g.leader_ratio >= 0.70
            ? 'Líder: <span style="font-family:monospace;color:var(--text)">' + g.leader + '</span>'
            : 'Sem líder fixo')
        + '</div>'
      + '</td>'
      + '<td style="text-align:center">' + diasHtml + '</td>'
      + '<td style="text-align:center">'
        + '<span style="font-weight:700;font-size:.9rem;color:var(--accent2)">' + camCount + '</span> '
        + '<span style="font-size:.72rem;color:var(--muted)">c\u00e2m.</span></td>'
      + '<td>' + lastHtml + '</td>'
      + '<td style="font-size:.76rem;color:var(--muted);max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + locs.join(', ') + '">' + locText + '</td>'
      + '<td style="text-align:center">' + _cgsRiscoBadge(g.risco) + '<br>' + scoreHtml + tcBadgesHtml + '</td>'
      + '<td class="action-cell">' + ações + '</td>'
      + '</tr>';
  }).join('');
}

// ── Grupo Suspeito: detalhe completo ────────────────────────────────────────
var _cgsCurrentGroup = null;

function _cgsOpenDetalhe(groupId) {
  var group = _cgsAllGroups.find(function(g){ return g.id === groupId; });
  if (!group) return;
  _cgsCurrentGroup = group;
  _cgsBuildDetalhe(group);
  openModal('cgs-detalhe-modal');
}

function _cgsCriarAlvo() {
  var role = window._authRole || 'visualizador';
  if (role !== 'admin' && role !== 'operador') {
    alert('Seu perfil nao possui permissao para criar alvo.');
    return;
  }
  var g = _cgsCurrentGroup;
  if (!g || !g.plates || !g.plates.length) return;
  var alvoMap = {};
  (g.alvos || []).forEach(function(a) {
    var plate = String((a && a.plate) || '').trim().toUpperCase();
    if (plate) alvoMap[plate] = true;
  });
  var preferred = '';
  var leader = String(g.leader || '').trim().toUpperCase();
  if (leader && !alvoMap[leader]) preferred = leader;
  if (!preferred) {
    var nextPlate = g.plates.find(function(p) {
      return !alvoMap[String(p || '').trim().toUpperCase()];
    });
    if (nextPlate) preferred = String(nextPlate).trim().toUpperCase();
  }
  if (!preferred && leader) preferred = leader;
  if (!preferred) preferred = String(g.plates[0] || '').trim().toUpperCase();
  if (!preferred) return;
  if ((g.alvos || []).length >= g.plates.length) {
    alert('Todas as placas deste grupo ja estao cadastradas como alvo.');
    return;
  }
  var groupId = g.id;
  _vehicleTargetFlow = {
    stage: 'target-choice',
    message: '🎯 Alvo salvo com sucesso!',
    restore: async function() {
      var nav = document.querySelector('#sidebar .nav-item[onclick*="batedor"]');
      if (nav) switchTab('batedor', nav);
      var btn = document.getElementById('bat-subtab-suspeitos');
      if (btn) switchBatTab('suspeitos', btn);
      await _cgsLoad(true);
      if (groupId) _cgsOpenDetalhe(groupId);
    }
  };
  closeModal('cgs-detalhe-modal');
  _addPlateAsAlvo(preferred);
}

function _cgsBuildDetalhe(g) {
  // Título
  var titulo = document.getElementById('cgs-det-titulo');
  if (titulo) titulo.textContent = '&#128101; Grupo Suspeito \u2014 ' + g.plates.join(' + ');

  // Score badge
  var scoreBg    = g.score >= 80 ? '#ef4444' : g.score >= 40 ? '#d97706' : '#6b7280';
  var riscoBg    = g.risco === 'ALTO' ? 'rgba(239,68,68,.18)' : g.risco === '\u00c9DIO' ? 'rgba(245,158,11,.15)' : 'rgba(107,114,128,.15)';
  var riscoBorder= g.risco === 'ALTO' ? 'rgba(239,68,68,.5)'  : g.risco === 'M\u00c9DIO' ? 'rgba(245,158,11,.4)'  : 'rgba(107,114,128,.3)';
  var riscoIcon  = g.risco === 'ALTO' ? '&#128293;' : g.risco === 'M\u00c9DIO' ? '&#9888;' : '&#128994;';
  var riscoColor = g.risco === 'ALTO' ? '#fca5a5' : g.risco === 'M\u00c9DIO' ? '#fcd34d' : '#86efac';

  // Helpers
  var dash = '<span style="color:var(--muted)">&mdash;</span>';
  var fmtTs = function(iso) {
    if (!iso) return dash;
    return new Date(iso).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
  };
  var fmtSec = function(s) {
    if (!s) return dash;
    s = Math.round(s);
    if (s < 60)   return s + 's';
    if (s < 3600) { var m = Math.floor(s/60); return m + ' min' + (s%60 ? ' ' + s%60 + 's' : ''); }
    var h = Math.floor(s/3600); var rm = Math.floor((s%3600)/60);
    return h + 'h' + (rm ? ' ' + rm + 'min' : '');
  };

  // ── 1. Header: placas + score + padrão + risco ───────────────────────────
  var placasHtml = g.plates.map(function(p) {
    var isAlvo   = g.alvos && g.alvos.some(function(a){ return a.plate === p; });
    var isLeader = p === g.leader && g.leader_ratio >= 0.70;
    var roleLabel = isAlvo ? '<span style="font-size:.65rem;font-weight:700;background:#a07a24;color:#fff7db;padding:1px 6px;border-radius:99px">ALVO</span>'
      : isLeader ? '<span style="font-size:.65rem;font-weight:700;background:#dc2626;color:#fff;padding:1px 6px;border-radius:99px">BATEDOR</span>'
      : '<span style="font-size:.65rem;font-weight:700;background:#374151;color:#d1d5db;padding:1px 6px;border-radius:99px">MEMBRO</span>';
    var plateColor = isAlvo ? '#dbc483' : isLeader ? '#f87171' : 'var(--text)';
    return '<div style="display:flex;flex-direction:column;align-items:center;gap:4px;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 16px;min-width:100px">'
      + '<span style="font-family:monospace;font-size:1.1rem;font-weight:800;letter-spacing:.1em;color:' + plateColor + ';white-space:nowrap">' + p + '</span>'
      + roleLabel
      + (isAlvo && g.alvos ? (function(){
          var a = g.alvos.find(function(x){ return x.plate === p; });
          return a && a.descricao ? '<span style="font-size:.68rem;color:var(--muted);text-align:center;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + a.descricao + '">' + a.descricao + '</span>' : '';
        })() : '')
      + '</div>';
  }).join('');

  var headerHtml = '<div style="display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start;margin-bottom:18px">'

    // Placas
    + '<div style="flex:1;min-width:0">'
      + '<div style="font-size:.7rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);font-weight:600;margin-bottom:8px">&#128663; Placas Envolvidas</div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:8px">' + placasHtml + '</div>'
    + '</div>'

    // Cards de métricas
    + '<div style="display:flex;flex-wrap:wrap;gap:8px;flex-shrink:0">'

      // Risco
      + '<div style="background:' + riscoBg + ';border:1px solid ' + riscoBorder + ';border-radius:10px;padding:10px 16px;text-align:center;min-width:90px">'
        + '<div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Risco</div>'
        + '<div style="font-size:.88rem;font-weight:800;color:' + riscoColor + ';white-space:nowrap">' + riscoIcon + ' ' + g.risco + '</div>'
        + '<div style="margin-top:4px"><span style="font-size:.82rem;font-weight:700;background:' + scoreBg + ';color:#fff;padding:2px 10px;border-radius:99px">' + g.score + '</span></div>'
      + '</div>'

      // Padrão
      + '<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 16px;text-align:center;min-width:90px">'
        + '<div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Padr\u00e3o</div>'
        + '<div style="font-size:.82rem;font-weight:800;color:var(--text)">' + g.padrao + '</div>'
        + '<div style="font-size:.68rem;color:var(--muted);margin-top:3px">' + g.group_size + ' ve\u00edculos</div>'
      + '</div>'

      // Coocorrências
      + '<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 16px;text-align:center;min-width:80px">'
        + '<div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Cooc.</div>'
        + '<div style="font-size:1.2rem;font-weight:800;color:var(--accent2)">' + g.cameras_count + 'x</div>'
        + '<div style="font-size:.68rem;color:var(--muted);margin-top:2px">c\u00e2meras</div>'
      + '</div>'

      // Dias distintos
      + '<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 16px;text-align:center;min-width:80px">'
        + '<div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;margin-bottom:4px">Dias</div>'
        + '<div style="font-size:1.2rem;font-weight:800;color:' + (g.distinct_days >= 5 ? '#ef4444' : g.distinct_days >= 2 ? '#f59e0b' : 'var(--text)') + '">' + (g.distinct_days || 0) + '</div>'
        + '<div style="font-size:.68rem;color:var(--muted);margin-top:2px">distintos</div>'
      + '</div>'

    + '</div>'
  + '</div>';

  // ── 2. Grade de campos ────────────────────────────────────────────────────
  var mkField = function(label, value) {
    return '<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 14px">'
      + '<div style="font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);font-weight:600;margin-bottom:4px">' + label + '</div>'
      + '<div style="font-size:.85rem;font-weight:600;color:var(--text)">' + value + '</div>'
    + '</div>';
  };

  var locsHtml = (g.cameras_names && g.cameras_names.length)
    ? g.cameras_names.map(function(n){ return '<span style="font-size:.76rem;background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:2px 8px;white-space:nowrap">' + n + '</span>'; }).join(' ')
    : dash;

  var alvosHtml = (g.alvos && g.alvos.length)
    ? g.alvos.map(function(a){
        return '<span style="font-size:.76rem;background:rgba(196,166,74,.16);border:1px solid rgba(196,166,74,.38);border-radius:6px;padding:2px 8px;color:#dbc483;white-space:nowrap">&#127919; ' + a.plate + (a.descricao ? ' &mdash; ' + a.descricao : '') + '</span>';
      }).join('<br style="margin:2px">')
    : dash;

  var scoreReasonsHtml = (g.score_reason && g.score_reason.length)
    ? g.score_reason.map(function(r){ return '<li style="font-size:.76rem;color:var(--muted)">' + r + '</li>'; }).join('')
    : '<li style="font-size:.76rem;color:var(--muted)">Sem breakdown dispon\u00edvel</li>';

  var fieldsHtml = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;margin-bottom:18px">'
    + mkField('&#128197; Primeiro visto', fmtTs(g.first_seen))
    + mkField('&#128336; \u00daltima vez juntos', fmtTs(g.last_seen))
    + mkField('&#128663; Span da viagem', fmtSec(g.trip_span_sec))
    + mkField('&#127942; L\u00edder / Batedor', g.leader || dash)
    + mkField('&#128198; Dias distintos (90d)', g.distinct_days ? String(g.distinct_days) + ' dias' : dash)
    + mkField('&#128247; C\u00e2meras em comum', String(g.cameras_count))
  + '</div>';

  var locFieldHtml = '<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin-bottom:8px">'
    + '<div style="font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);font-weight:600;margin-bottom:6px">&#128205; Localidades</div>'
    + '<div style="display:flex;flex-wrap:wrap;gap:5px">' + locsHtml + '</div>'
  + '</div>';

  var alvosFieldHtml = g.alvos && g.alvos.length
    ? '<div style="background:rgba(139,92,246,.08);border:1px solid rgba(139,92,246,.3);border-radius:8px;padding:10px 14px;margin-bottom:8px">'
        + '<div style="font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;color:#c4b5fd;font-weight:700;margin-bottom:6px">&#127919; Alvos Cadastrados no Grupo</div>'
        + '<div style="display:flex;flex-direction:column;gap:4px">' + alvosHtml + '</div>'
      + '</div>'
    : '';

  var scoreHtml = '<details style="margin-bottom:18px">'
    + '<summary style="font-size:.8rem;font-weight:700;color:var(--accent2);cursor:pointer;padding:4px 0">&#128202; Breakdown do Score (' + g.score + ' pts)</summary>'
    + '<ul style="margin:8px 0 0 16px;padding:0;list-style:disc">' + scoreReasonsHtml + '</ul>'
  + '</details>';

  // ── Vínculo com alvo (Phase 1 — threat_center) ────────────────────────────
  var tcAlertHtml = '';
  if (g.threat_center && g.threat_center.matched_target) {
    var tc = g.threat_center;
    var tcBadges = tc.threat_badges.map(function(badge) {
      var isLider = badge === 'LÍDER_É_ALVO';
      return '<span style="font-size:.72rem;font-weight:800;background:' + (isLider ? '#dc2626' : '#a07a24') + ';color:' + (isLider ? '#fff' : '#fff7db') + ';padding:2px 10px;border-radius:99px">'
        + (isLider ? '\u2605 L\u00cdDER \u00c9 ALVO' : '\u26a1 ALVO NO GRUPO') + '</span>';
    }).join(' ');
    var tcPlates = tc.matched_plates && tc.matched_plates.length
      ? '<span style="font-size:.76rem;color:#dbc483;margin-left:6px">Placas: <strong>' + tc.matched_plates.join(', ') + '</strong></span>'
      : '';
    tcAlertHtml = '<div style="background:rgba(196,166,74,.12);border:1px solid rgba(196,166,74,.45);border-radius:10px;padding:10px 16px;margin-bottom:14px">'
      + '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:6px">'
        + '<span style="font-size:.95rem">&#127919;</span>'
        + '<span style="font-size:.82rem;font-weight:800;color:#dbc483;letter-spacing:.03em">V\u00cdNCULO COM ALVO CADASTRADO</span>'
        + tcPlates
      + '</div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:6px">' + tcBadges + '</div>'
    + '</div>';
  }

  // ── 3. Linha do tempo de passagens conjuntas ──────────────────────────────
var camsCnf = (g.cameras_confirmed || []).slice().sort(function(a,b){
  var ai = Number(a && a.timeline_index);
  var bi = Number(b && b.timeline_index);
  if (Number.isFinite(ai) && Number.isFinite(bi) && ai !== bi) return ai - bi;
  return new Date(a.ts_min) - new Date(b.ts_min);
});

  var timelineHtml;
  if (!camsCnf.length) {
    timelineHtml = '<div style="color:var(--muted);font-size:.85rem;padding:8px 0">&mdash; Sem passagens registradas.</div>';
  } else {
    var prevTs = null;
    var rows = camsCnf.map(function(c, i) {
      var tsMin = c.ts_min ? new Date(c.ts_min) : null;
      var tsMax = c.ts_max ? new Date(c.ts_max) : null;
      var tsStr = tsMin ? tsMin.toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '\u2014';
      var spanStr = c.span_sec ? fmtSec(c.span_sec) : '0s';
      var ordem = c.plate_order && c.plate_order.length
        ? c.plate_order.map(function(p,idx){
            var isAlvo   = g.alvos && g.alvos.some(function(a){ return a.plate === p; });
            var isLeader = p === g.leader;
            var color = isAlvo ? '#c4b5fd' : isLeader ? '#f87171' : 'var(--text)';
            return '<span style="font-family:monospace;font-size:.8rem;font-weight:700;color:' + color + '">' + (idx+1) + '\u00ba ' + p + '</span>';
          }).join(' \u2192 ')
        : '<span style="color:var(--muted)">&mdash;</span>';

      // intervalo desde câmera anterior
      var intervalHtml = '';
      if (prevTs && tsMin) {
        var delta = (tsMin - prevTs) / 1000;
        intervalHtml = '<div style="display:flex;align-items:center;gap:4px;padding:3px 0 3px 18px">'
          + '<div style="width:1px;height:16px;background:var(--border);margin-left:5px"></div>'
          + '<span style="font-size:.7rem;color:var(--muted);font-style:italic">&#8595; ' + fmtSec(delta) + ' depois</span>'
          + '</div>';
      }
      prevTs = tsMax || tsMin;

      var dotColor = i === 0 ? '#22c55e' : i === camsCnf.length-1 ? '#ef4444' : 'var(--primary)';
      return intervalHtml
        + '<div style="display:flex;gap:10px;align-items:flex-start">'
          + '<div style="display:flex;flex-direction:column;align-items:center;flex-shrink:0;padding-top:4px">'
            + '<div style="width:12px;height:12px;border-radius:50%;background:' + dotColor + ';border:2px solid rgba(255,255,255,.15);flex-shrink:0"></div>'
          + '</div>'
          + '<div style="flex:1;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:9px 13px;margin-bottom:0">'
            + '<div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:5px">'
              + '<span style="font-size:.84rem;font-weight:700;color:var(--text)">' + (c.cam_nome || c.camera_id || '\u2014') + '</span>'
              + '<span style="font-size:.72rem;color:var(--muted)">&#128336; ' + tsStr + '</span>'
              + '<span style="font-size:.72rem;background:rgba(250,204,21,.12);border:1px solid rgba(250,204,21,.25);border-radius:99px;padding:1px 7px;color:#fde68a">span: ' + spanStr + '</span>'
            + '</div>'
            + '<div style="font-size:.76rem;color:var(--muted)">Ordem: ' + ordem + '</div>'
          + '</div>'
        + '</div>';
    }).join('');

    timelineHtml = '<div style="padding:4px 0">' + rows + '</div>';
  }

  // ── 4. Monta tudo ─────────────────────────────────────────────────────────
  document.getElementById('cgs-det-body').innerHTML =
    headerHtml
    + tcAlertHtml
    + fieldsHtml
    + locFieldHtml
    + alvosFieldHtml
    + scoreHtml
    + '<div style="font-size:.82rem;font-weight:700;color:var(--accent2);text-transform:uppercase;letter-spacing:.07em;margin-bottom:10px">&#128203; Linha do Tempo &mdash; Passagens Conjuntas</div>'
    + timelineHtml;
}

// ═══════════════════════════════════════════════════════════════════════════
// MOTOR UNIFICADO DE RELATÓRIOS — _relEngine
// Usado por: _cgsGerarRelatorio, _alvoDvGerarRelatorio
// ═══════════════════════════════════════════════════════════════════════════
var _relPdfTitleSlug = 'relatorio';
var _relCurrentMapaFn = null;
var _relCurrentCreateTargetFn = null;
var _batedorReportData = null;  // cache dos dados carregados por openBatedorReport
var _relEngine = (function() {
  var D = '\u2014'; // em dash
  function fmtTs(iso) {
    if (!iso) return D;
    return new Date(iso).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }
  function fmtSec(s) {
    if (!s) return D;
    s = Math.round(s);
    if (s < 60) return s + 's';
    if (s < 3600) { var m = Math.floor(s/60); return m + ' min' + (s%60 ? ' ' + (s%60) + 's' : ''); }
    var h = Math.floor(s/3600), rm = Math.floor((s%3600)/60);
    return h + 'h' + (rm ? ' ' + rm + 'min' : '');
  }
  function fmtInterval(ms) {
    if (ms == null || ms < 0) return null;
    return fmtSec(Math.round(Math.abs(ms) / 1000));
  }
  function riskColor(risco) {
    if (!risco) return '#6b7280';
    var r = risco.toUpperCase();
    return r === 'CR\u00cdTICO' ? '#f87171' : r === 'ALTO' ? '#fb923c' : r === 'M\u00c9DIO' ? '#fbbf24' : r === 'BAIXO' ? '#4ade80' : '#6b7280';
  }
  function section(title, body) {
    return '<div style="margin-bottom:16px">'
      + '<div style="font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;font-weight:800;color:#1d4ed8;border-bottom:2px solid #e5e7eb;padding-bottom:5px;margin-bottom:10px">' + title + '</div>'
      + body
      + '</div>';
  }
  function buildHeader(o) {
    var rc = riskColor(o.risco);
    return '<div style="display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #1d4ed8;padding-bottom:12px;margin-bottom:18px;flex-wrap:wrap;gap:10px">'
      + '<div>'
        + '<div style="font-size:.62rem;text-transform:uppercase;letter-spacing:.1em;color:#6b7280;font-weight:700;margin-bottom:2px">Sistema de Monitoramento BPFRON</div>'
        + '<div style="font-size:1.2rem;font-weight:800;color:#111">' + o.titulo + '</div>'
        + (o.subtitulo ? '<div style="font-size:.8rem;color:#374151;margin-top:4px">' + o.subtitulo + '</div>' : '')
      + '</div>'
      + '<div style="text-align:right;flex-shrink:0">'
        + '<div style="font-size:.65rem;color:#6b7280">Gerado em</div>'
        + '<div style="font-size:.75rem;font-weight:700;color:#374151">' + o.now + '</div>'
        + (o.risco ? '<div style="margin-top:6px;display:inline-block;padding:3px 10px;border-radius:99px;font-size:.74rem;font-weight:800;background:' + rc + ';color:#fff">' + o.risco.toUpperCase() + (o.score != null ? ' \u00b7 ' + o.score + ' pts' : '') + '</div>' : '')
      + '</div>'
    + '</div>';
  }
  function buildKPIs(kpis) {
    var cards = kpis.filter(function(k){ return k != null; }).map(function(k) {
      return '<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px;text-align:center">'
        + '<div style="font-size:1.3rem;margin-bottom:4px">' + (k.icon || '') + '</div>'
        + '<div style="font-size:.62rem;color:#6b7280;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px">' + k.label + '</div>'
        + '<div style="font-size:1rem;font-weight:800;color:' + (k.color || '#111') + '">' + (k.value != null ? k.value : D) + '</div>'
      + '</div>';
    }).join('');
    return '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;margin-bottom:16px">' + cards + '</div>';
  }
  function buildFooter(now) {
    return '<div style="font-size:.65rem;color:#9ca3af;border-top:1px solid #e5e7eb;padding-top:10px;margin-top:8px;text-align:right">'
      + 'Gerado em ' + now + ' \u00b7 Sistema de Monitoramento BPFRON \u00b7 Confidencial'
    + '</div>';
  }
  function render(blocks, printWrapperId) {
    return '<div id="' + printWrapperId + '" class="report-light-surface" style="font-family:ui-sans-serif,system-ui,sans-serif;line-height:1.5">'
      + blocks.join('')
      + '</div>';
  }
  return { fmtTs:fmtTs, fmtSec:fmtSec, fmtInterval:fmtInterval, riskColor:riskColor,
           section:section, buildHeader:buildHeader, buildKPIs:buildKPIs,
           buildFooter:buildFooter, render:render };
})();

function _relBuildExportHtmlDoc() {
  var body = document.getElementById('rel-modal-body');
  if (!body) return '';
  return '<!DOCTYPE html><html lang="pt-br"><head>'
    + '<meta charset="utf-8"><title>Relatorio_' + _relPdfTitleSlug + '</title>'
    + '<style>*{box-sizing:border-box;margin:0;padding:0}'
    + 'body{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;font-size:13px;color:#111827;background:#fff;padding:24px 28px;line-height:1.5}'
    + 'table{width:100%;border-collapse:collapse}th,td{padding:7px 10px;font-size:12px}'
    + 'th{background:#f3f4f6;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:#374151;text-align:left}'
    + 'tr{border-bottom:1px solid #e5e7eb}'
    + '@page{size:A4 portrait;margin:14mm 12mm}@media print{body{padding:0}}'
    + '</style></head><body>'
    + body.innerHTML + '</body></html>';
}

function _relAbrirDocumentoExportado() {
  var html = _relBuildExportHtmlDoc();
  if (!html) return null;
  var win = window.open('', '_blank', 'width=950,height=720');
  if (!win) return null;
  win.document.write(html);
  win.document.close();
  win.focus();
  return win;
}

var _relHtml2PdfPromise = null;

function _relEnsureHtml2PdfLib() {
  if (window.html2pdf) return Promise.resolve(window.html2pdf);
  if (_relHtml2PdfPromise) return _relHtml2PdfPromise;
  _relHtml2PdfPromise = new Promise(function(resolve, reject) {
    var existing = document.getElementById('rel-html2pdf-lib');
    if (existing) {
      existing.addEventListener('load', function() {
        if (window.html2pdf) resolve(window.html2pdf);
        else reject(new Error('html2pdf não carregado.'));
      }, { once:true });
      existing.addEventListener('error', function() {
        reject(new Error('Falha ao carregar html2pdf.'));
      }, { once:true });
      return;
    }
    var s = document.createElement('script');
    s.id = 'rel-html2pdf-lib';
    s.src = 'https://cdn.jsdelivr.net/npm/html2pdf.js@0.10.1/dist/html2pdf.bundle.min.js';
    s.onload = function() {
      if (window.html2pdf) resolve(window.html2pdf);
      else reject(new Error('html2pdf indisponível após carregamento.'));
    };
    s.onerror = function() {
      reject(new Error('Não foi possível carregar a biblioteca de PDF.'));
    };
    document.head.appendChild(s);
  });
  return _relHtml2PdfPromise;
}

function _relBuildPdfExportNode() {
  var body = document.getElementById('rel-modal-body');
  if (!body) return null;
  var report = body.querySelector('#rel-print') || body.firstElementChild || body;
  var host = document.createElement('div');
  host.style.cssText = 'position:fixed;left:-20000px;top:0;width:794px;background:#ffffff;padding:18px 18px 24px;box-sizing:border-box;z-index:-1';
  var clone = report.cloneNode(true);
  clone.style.margin = '0';
  clone.style.width = '100%';
  host.appendChild(clone);
  document.body.appendChild(host);
  return host;
}

function _relDestroyPdfExportNode(node) {
  if (node && node.parentNode) node.parentNode.removeChild(node);
}

async function _relGenerateStyledPdf() {
  var html2pdf = await _relEnsureHtml2PdfLib();
  var host = _relBuildPdfExportNode();
  if (!host) throw new Error('Relatório indisponível para exportação.');
  var fileName = (_relPdfTitleSlug || 'relatorio').replace(/[^A-Z0-9_\-]/gi, '_') + '.pdf';
  try {
    await html2pdf().set({
      margin: [8, 8, 8, 8],
      filename: fileName,
      image: { type: 'jpeg', quality: 0.98 },
      html2canvas: {
        scale: 2,
        useCORS: true,
        backgroundColor: '#ffffff',
        logging: false,
        letterRendering: true
      },
      jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
      pagebreak: { mode: ['css', 'legacy'] }
    }).from(host).save();
  } finally {
    _relDestroyPdfExportNode(host);
  }
}

async function _relSalvarNoPC() {
  try {
    await _relGenerateStyledPdf();
    if (typeof _flashMsg === 'function') _flashMsg('💾 PDF salvo no PC.', '#2563eb');
  } catch (err) {
    alert('Erro ao salvar PDF: ' + err.message);
  }
}

async function _relExportarPDF() {
  try {
    await _relGenerateStyledPdf();
    if (typeof _flashMsg === 'function') _flashMsg('💾 PDF exportado.', '#2563eb');
  } catch (err) {
    alert('Erro ao exportar PDF: ' + err.message);
  }
}

function _relInjectPrintStyle() {
  if (document.getElementById('rel-print-style')) return;
  var s = document.createElement('style');
  s.id = 'rel-print-style';
  s.textContent = '@media print{body > *:not(#rel-modal){display:none!important}'
    + '#rel-modal{display:block!important;position:static!important;background:none!important;padding:0!important}'
    + '#rel-modal .modal{max-width:100%!important;max-height:none!important;box-shadow:none!important;border:none!important;padding:0!important}'
    + '#rel-modal .modal-header{display:none!important}#rel-print{color:#000!important}}';
  document.head.appendChild(s);
}

async function closeRelModal(restoreContext) {
  var restoreFn = _relModalCloseRestoreFn;
  _relModalCloseRestoreFn = null;
  _relModalReturnFn = null;
  _relCurrentMapaFn = null;
  _relCurrentCreateTargetFn = null;
  closeModal('rel-modal');
  if (restoreContext && typeof restoreFn === 'function') {
    try {
      await restoreFn();
    } catch (restoreErr) {
      console.warn('[relatorio] retorno apos fechar falhou:', restoreErr);
    }
  }
}

function _relAbrirModal(titulo, html, mapaFn, restoreFn, backLabel, createTargetFn, showPrintBtn) {
  document.getElementById('rel-modal-titulo').textContent = titulo;
  document.getElementById('rel-modal-body').innerHTML = html;
  var btnMapa = document.getElementById('rel-btn-mapa');
  var btnTarget = document.getElementById('rel-btn-target');
  var btnPrint = document.getElementById('rel-btn-print');
  if (btnMapa) { _relCurrentMapaFn = mapaFn || null; btnMapa.style.display = mapaFn ? 'flex' : 'none'; }
  if (btnTarget) { _relCurrentCreateTargetFn = createTargetFn || null; btnTarget.style.display = createTargetFn ? 'flex' : 'none'; }
  if (btnPrint) btnPrint.style.display = showPrintBtn === false ? 'none' : 'flex';
  _relModalCloseRestoreFn = typeof restoreFn === 'function' ? restoreFn : null;
  _relModalReturnFn = function() { _relAbrirModal(titulo, html, mapaFn, restoreFn, backLabel, createTargetFn, showPrintBtn); };
  _relPdfTitleSlug = titulo.replace(/[^A-Z0-9_]/gi, '_');
  _relInjectPrintStyle();
  openModal('rel-modal');
}

function _relVerRotaMapa() {
  if (typeof _relCurrentMapaFn === 'function') { _relCurrentMapaFn(); }
}

function _relCriarAlvo() {
  if (typeof _relCurrentCreateTargetFn === 'function') { _relCurrentCreateTargetFn(); }
}

// ── Relatório de Placa Individual ────────────────────────────────────────────
function _abrirRelatorioPlacaIndividual() {
  var rd = _batedorReportData;
  if (!rd) return;

  var plate = rd.plate;
  var d = rd.d || {};
  var events = (d.events || []).slice().sort(function(a, b) {
    return new Date(a && a.ts ? a.ts : 0) - new Date(b && b.ts ? b.ts : 0);
  });
  var partners = (d.convoy_partners || []).slice().sort(function(a, b) {
    return Number((b && b.cameras_together) || 0) - Number((a && a.cameras_together) || 0);
  });
  var summary = d.summary || {};
  var now = new Date().toLocaleString('pt-BR', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  var score = Number(d.score || 0);
  var rawLevel = String(d.level || '').toUpperCase();
  var level = rawLevel === 'ALTO' || rawLevel === 'CRITICO' || rawLevel === 'CRÍTICO'
    ? 'ALTO'
    : (rawLevel === 'MEDIO' || rawLevel === 'MÉDIO')
      ? 'MÉDIO'
      : (rawLevel === 'BAIXO' || rawLevel === 'NORMAL')
        ? 'BAIXO'
        : (score >= 75 ? 'ALTO' : score >= 35 ? 'MÉDIO' : 'BAIXO');
  var riskColor = level === 'ALTO' ? '#dc2626' : (level === 'MÉDIO' ? '#d97706' : '#16a34a');
  var lastEvent = events.length ? events[events.length - 1] : null;
  var lastSeen = lastEvent && lastEvent.ts
    ? new Date(lastEvent.ts).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'})
    : '\u2014';
  var cenItem = (_cenAllItems || []).find(function(it) { return it.plate === plate; });
  var tc = cenItem && cenItem.threat_center ? cenItem.threat_center : null;

  function _df(label, value) {
    return '<div><div style="font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:2px">' + label + '</div>'
      + '<div style="font-size:.88rem;font-weight:600;color:#111">' + (value != null ? value : '\u2014') + '</div></div>';
  }
  function _miniCard(label, value, color) {
    return '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:10px 12px">'
      + '<div style="font-size:.66rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:4px">' + label + '</div>'
      + '<div style="font-size:1rem;font-weight:800;color:' + (color || '#111827') + '">' + value + '</div>'
      + '</div>';
  }
  function _fmtTs(iso) {
    return iso ? new Date(iso).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '\u2014';
  }
  function _decisionLabel(decision) {
    var map = { confirmado: 'Suspeito confirmado', falso_positivo: 'Falso positivo', ignorar: 'Ignorado' };
    return map[decision] || decision || '\u2014';
  }
  function _pill(text, bg, fg) {
    return '<span style="display:inline-block;background:' + bg + ';color:' + fg + ';font-size:.72rem;font-weight:800;padding:5px 10px;border-radius:999px">' + text + '</span>';
  }

  var acao = (function() {
    if (d.is_alvo) {
      return {
        titulo: 'Ação sugerida: monitoramento prioritário',
        detalhe: 'A placa já está cadastrada como alvo. O relatório deve apoiar abordagem, monitoramento e validação dos parceiros recentes.',
        bg: '#fef2f2',
        border: '#fca5a5',
        color: '#b91c1c'
      };
    }
    if (partners.length >= 2 && score >= 75) {
      return {
        titulo: 'Ação sugerida: aprofundar vínculo com outros veículos',
        detalhe: 'A placa tem score alto e circula acompanhada. Vale validar se o caso deve evoluir para análise relacional de grupo suspeito.',
        bg: '#fff7ed',
        border: '#fdba74',
        color: '#c2410c'
      };
    }
    if (partners.length > 0) {
      return {
        titulo: 'Ação sugerida: acompanhar parceiros confirmados',
        detalhe: 'A placa apresenta acompanhamento em comboio. O foco operacional é verificar recorrência, liderança e contexto da rota.',
        bg: '#fefce8',
        border: '#fde68a',
        color: '#a16207'
      };
    }
    if (score >= 75) {
      return {
        titulo: 'Ação sugerida: abordagem prioritária',
        detalhe: 'Os sinais da própria placa sustentam prioridade alta, mesmo sem grupo confirmado no período.',
        bg: '#fef2f2',
        border: '#fca5a5',
        color: '#b91c1c'
      };
    }
    if (score >= 35) {
      return {
        titulo: 'Ação sugerida: monitorar e consolidar histórico',
        detalhe: 'Há sinais suficientes para manter atenção, mas a indicação principal ainda é complementar o contexto da placa.',
        bg: '#fefce8',
        border: '#fde68a',
        color: '#a16207'
      };
    }
    return {
      titulo: 'Ação sugerida: monitoramento de rotina',
      detalhe: 'Sem elementos fortes de confirmação no momento. O relatório serve como registro tático da movimentação da placa.',
      bg: '#f0fdf4',
      border: '#86efac',
      color: '#166534'
    };
  })();

  var kpisHtml = _relEngine.buildKPIs([
    { icon: '\uD83D\uDCCA', label: 'Score individual', value: score + ' pts', color: riskColor },
    { icon: '\u26A0\uFE0F', label: 'Risco', value: level, color: riskColor },
    { icon: '\uD83D\uDCCB', label: 'Passagens', value: String(summary.total_passes || events.length) },
    { icon: '\uD83D\uDCF7', label: 'Câmeras', value: summary.cameras_count != null ? String(summary.cameras_count) : '\u2014' },
    { icon: '\uD83D\uDC65', label: 'Acompanhamento', value: partners.length ? String(partners.length) + ' parceiro(s)' : 'Nenhum' },
    d.is_alvo ? { icon: '\uD83C\uDFAF', label: 'Status', value: 'ALVO', color: '#dc2626' } : null
  ]);

  var dadosHtml = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px 20px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:14px 18px">'
    + _df('Placa', '<span style="font-family:monospace;color:#b91c1c;font-weight:800">' + plate + '</span>')
    + _df('Score individual', score + ' pts')
    + _df('Risco', '<span style="font-weight:800;color:' + riskColor + '">' + level + '</span>')
    + _df('Último visto', lastSeen)
    + _df('Total de passagens', String(summary.total_passes || events.length || '\u2014'))
    + _df('Câmeras distintas', summary.cameras_count != null ? String(summary.cameras_count) : '\u2014')
    + _df('Parceiros confirmados', String(summary.partners_count || partners.length || 0))
    + _df('Direção dominante', summary.dom_direction || '\u2014')
    + _df('Confiança média', summary.avg_confidence > 0 ? formatConfidencePercent(summary.avg_confidence) + '%' : '\u2014')
    + _df('Tipo / Cor', [d.vehicle_type, d.vehicle_color].filter(Boolean).join(' / ') || '\u2014');
  if (d.is_alvo) {
    dadosHtml += _df('Status operacional', '<span style="color:#b91c1c;font-weight:800">\uD83C\uDFAF Alvo rastreado</span>');
    if (d.alvo_descricao) dadosHtml += _df('Descrição do alvo', d.alvo_descricao);
    if (d.alvo_list) dadosHtml += _df('Lista vinculada', d.alvo_list);
  }
  dadosHtml += '</div>';
  dadosHtml += '<div style="margin-top:12px;padding:14px 16px;background:' + acao.bg + ';border:1px solid ' + acao.border + ';border-radius:10px">'
    + '<div style="font-size:.82rem;font-weight:800;color:' + acao.color + ';margin-bottom:4px">' + acao.titulo + '</div>'
    + '<div style="font-size:.82rem;color:#374151;line-height:1.45">' + acao.detalhe + '</div>'
    + '</div>';

  if (cenItem && (cenItem.score_activity != null || cenItem.score_acompanhamento != null || cenItem.score_rota != null || cenItem.score_alvo != null)) {
    dadosHtml += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:12px">'
      + _miniCard('Atividade da placa', String(cenItem.score_activity || 0) + ' pts', '#111827')
      + _miniCard('Acompanhamento', String(cenItem.score_acompanhamento || 0) + ' pts', '#a16207')
      + _miniCard('Rota', String(cenItem.score_rota || 0) + ' pts', '#1d4ed8')
      + _miniCard('Alvo', String(cenItem.score_alvo || 0) + ' pts', '#b91c1c')
      + '</div>';
  }

  var badges = (d.badges || []).map(function(b) {
    var cl = b === 'ALVO' ? '#dc2626' : (b.indexOf('MULTI') >= 0 || b === 'COMBOIO') ? '#d97706' : '#2563eb';
    return '<span style="display:inline-block;background:' + cl + ';color:#fff;font-size:.65rem;font-weight:700;padding:2px 8px;border-radius:99px;margin-right:4px;margin-top:4px">' + b + '</span>';
  }).join('');
  if (badges) {
    dadosHtml += '<div style="margin-top:10px"><div style="font-size:.68rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:4px">Indicadores ativos</div>' + badges + '</div>';
  }

  var partnerAlvos = partners.filter(function(p) { return !!p.is_alvo; }).length;
  var partnerMaxCam = partners.length ? Math.max.apply(null, partners.map(function(p){ return Number(p.cameras_together || 0); })) : 0;
  var spanVals = partners.map(function(p){ return Number(p.trip_span_sec || 0); }).filter(function(v){ return v > 0; });
  var partnerMinSpan = spanVals.length ? Math.min.apply(null, spanVals) : 0;
  var acompanhamentoStats = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:12px">'
    + _miniCard('Parceiros confirmados', String(partners.length), '#111827')
    + _miniCard('Maior coocorrência', partnerMaxCam ? String(partnerMaxCam) + ' câm.' : '\u2014', '#1d4ed8')
    + _miniCard('Melhor span', partnerMinSpan ? _relEngine.fmtSec(partnerMinSpan) : '\u2014', '#a16207')
    + _miniCard('Alvos entre parceiros', String(partnerAlvos), partnerAlvos ? '#b91c1c' : '#111827')
    + '</div>';

  var partRows = partners.map(function(p) {
    var tripMin = Math.round((p.trip_span_sec || 0) / 60);
    var alvoMark = p.is_alvo ? ' ' + _pill('ALVO', '#dc2626', '#fff') : '';
    var camNames = (p.cameras_detail || []).map(function(c){ return c.cam_nome || c.camera_id; }).join(', ');
    return '<tr style="border-bottom:1px solid #e5e7eb">'
      + '<td style="padding:6px 10px;font-size:.82rem;font-weight:700;font-family:monospace">' + p.plate + alvoMark + '</td>'
      + '<td style="padding:6px 10px;text-align:center;font-weight:700;color:#1d4ed8">' + p.cameras_together + ' câm.</td>'
      + '<td style="padding:6px 10px;font-size:.78rem">' + (tripMin > 0 ? tripMin + ' min' : (p.trip_span_sec || 0) + 's') + '</td>'
      + '<td style="padding:6px 10px;font-size:.78rem;white-space:nowrap">' + _fmtTs(p.last_seen) + '</td>'
      + '<td style="padding:6px 10px;font-size:.78rem;color:#6b7280;max-width:260px;overflow:hidden;text-overflow:ellipsis">' + (camNames || '\u2014') + '</td>'
      + '</tr>';
  }).join('');
  var comboioHtml = partners.length
    ? acompanhamentoStats
      + '<div style="margin-bottom:10px;padding:12px 14px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:10px;font-size:.82rem;color:#374151;line-height:1.45">A placa está acompanhada por parceiros confirmados no recorte analisado. Esta seção mostra com quem ela circulou e em quais câmeras o vínculo ficou mais forte.</div>'
      + '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">'
        + '<thead><tr style="background:#e5e7eb">'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Parceiro</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Câmeras juntos</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Span</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Último visto</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Câmeras</th>'
        + '</tr></thead><tbody>' + partRows + '</tbody></table></div>'
    : '<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px;font-size:.82rem;color:#6b7280">Nenhum parceiro em comboio confirmado no período. O foco deste relatório permanece na atividade da própria placa.</div>';

  var evRows = events.map(function(ev, i) {
    var dtFmt = ev.ts ? new Date(ev.ts).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '\u2014';
    var conf = ev.confidence > 0 ? formatConfidencePercent(ev.confidence) + '%' : '\u2014';
    var intervalo = '\u2014';
    if (i > 0 && events[i-1].ts && ev.ts) {
      var ms = Math.abs(new Date(ev.ts) - new Date(events[i-1].ts));
      intervalo = _relEngine.fmtSec(Math.round(ms / 1000));
    }
    return '<tr style="border-bottom:1px solid #e5e7eb">'
      + '<td style="padding:6px 10px;text-align:center;font-size:.75rem;color:#9ca3af">' + (i + 1) + '</td>'
      + '<td style="padding:6px 10px;font-size:.78rem;white-space:nowrap">' + dtFmt + '</td>'
      + '<td style="padding:6px 10px;font-size:.78rem">' + (ev.camera_name || ev.camera_id || '\u2014') + '</td>'
      + '<td style="padding:6px 10px;font-size:.78rem;font-weight:700;color:#1d4ed8">' + (ev.direcao || '\u2014') + '</td>'
      + '<td style="padding:6px 10px;font-size:.78rem;color:#6b7280">' + conf + '</td>'
      + '<td style="padding:6px 10px;font-size:.78rem;color:#6b7280">' + intervalo + '</td>'
      + '</tr>';
  }).join('');
  var timelineHtml = events.length
    ? '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">'
        + '<thead><tr style="background:#e5e7eb">'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">#</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Data / Hora</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Câmera</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Direção</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Conf.</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Intervalo</th>'
        + '</tr></thead><tbody>' + evRows + '</tbody></table></div>'
    : '<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px;font-size:.82rem;color:#6b7280">Nenhuma passagem no período.</div>';

  var lastDec = d.last_decision;
  var decBg = { confirmado: '#fef2f2', falso_positivo: '#f0fdf4', ignorar: '#f8fafc' };
  var decBorder = { confirmado: '#fca5a5', falso_positivo: '#86efac', ignorar: '#cbd5e1' };
  var decisaoHtml = '<div style="margin-bottom:12px;padding:14px 16px;background:#fff;border:1px solid #e5e7eb;border-radius:10px">'
    + '<div style="font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Parecer tático</div>'
    + '<div style="font-size:.88rem;font-weight:800;color:' + acao.color + ';margin-bottom:4px">' + acao.titulo + '</div>'
    + '<div style="font-size:.82rem;color:#374151;line-height:1.45">' + acao.detalhe + '</div>'
    + '</div>';
  decisaoHtml += lastDec
    ? '<div style="margin-bottom:12px;padding:14px 16px;background:' + (decBg[lastDec.decision] || '#f8fafc') + ';border:1px solid ' + (decBorder[lastDec.decision] || '#cbd5e1') + ';border-radius:10px">'
        + '<div style="font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Última decisão operacional</div>'
        + '<div style="font-size:.86rem;font-weight:800;color:#111827;margin-bottom:4px">' + _decisionLabel(lastDec.decision) + '</div>'
        + '<div style="font-size:.8rem;color:#374151;line-height:1.45">'
          + (lastDec.note ? lastDec.note + '<br>' : '')
          + '<span style="color:#6b7280">Registrado por ' + (lastDec.operator || 'sistema') + ' em ' + _fmtTs(lastDec.created_at) + '.</span>'
        + '</div>'
      + '</div>'
    : '<div style="margin-bottom:12px;padding:14px 16px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:10px;font-size:.82rem;color:#6b7280">Nenhuma decisão operacional registrada para esta placa até o momento.</div>';

  var scoreBreakdownHtml = '';
  if (d.score_breakdown && d.score_breakdown.length) {
    var sbRows = d.score_breakdown.map(function(b) {
      return '<tr style="border-bottom:1px solid #e5e7eb">'
        + '<td style="padding:6px 10px;font-size:.78rem">' + b.label + '</td>'
        + '<td style="padding:6px 10px;text-align:center;font-size:.78rem">' + b.value + '</td>'
        + '<td style="padding:6px 10px;text-align:center;font-size:.78rem;color:#1d4ed8">\u00d7' + b.multiplier + '</td>'
        + '<td style="padding:6px 10px;text-align:center;font-size:.78rem;font-weight:700">+' + b.points + '</td>'
        + '<td style="padding:6px 10px;font-size:.75rem;color:#6b7280">' + (b.reason || '') + '</td>'
        + '</tr>';
    }).join('');
    scoreBreakdownHtml = '<div style="margin-bottom:12px;overflow-x:auto">'
      + '<table style="width:100%;border-collapse:collapse;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">'
      + '<thead><tr style="background:#e5e7eb">'
        + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Fator</th>'
        + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Val.</th>'
        + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Mult.</th>'
        + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Pts</th>'
        + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Justificativa</th>'
      + '</tr></thead><tbody>' + sbRows
      + '<tr style="background:#e5e7eb;font-weight:700"><td colspan="3" style="padding:6px 10px;font-size:.78rem">TOTAL</td>'
        + '<td style="padding:6px 10px;font-size:.78rem;text-align:center">+' + score + '</td><td></td></tr>'
      + '</tbody></table></div>';
  }

  var centralHtml = '';
  if (tc) {
    var rs = tc.route_similarity || {};
    var tcBadges = (tc.threat_badges || []).map(function(b) {
      return '<span style="display:inline-block;background:#a16207;color:#fff7db;font-size:.65rem;font-weight:700;padding:2px 8px;border-radius:99px;margin-right:4px;margin-top:4px">' + b + '</span>';
    }).join('');
    var simPct = (rs.similarity_ratio != null && rs.similarity_ratio > 0) ? Math.round(rs.similarity_ratio * 100) + '%' : '\u2014';
    centralHtml = '<div style="padding:14px 16px;background:#fff;border:1px solid #e5e7eb;border-radius:10px">'
      + '<div style="font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Central de ameaça</div>'
      + (tcBadges ? '<div style="margin-bottom:8px">' + tcBadges + '</div>' : '')
      + '<table style="width:100%;border-collapse:collapse"><tbody>'
      + '<tr style="border-bottom:1px solid #e5e7eb"><td style="padding:6px 10px;font-size:.75rem;font-weight:700;color:#6b7280;white-space:nowrap;background:#f9fafb;border:1px solid #e5e7eb;width:40%">Alvo vinculado</td><td style="padding:6px 10px;font-size:.82rem;border:1px solid #e5e7eb">' + (tc.matched_target ? '<strong style="color:#16a34a">\u2705 Sim</strong>' : '<span style="color:#6b7280">\u2014 Não</span>') + '</td></tr>'
      + (rs.matched || (rs.similarity_ratio && rs.similarity_ratio > 0) ? '<tr style="border-bottom:1px solid #e5e7eb"><td style="padding:6px 10px;font-size:.75rem;font-weight:700;color:#6b7280;white-space:nowrap;background:#f9fafb;border:1px solid #e5e7eb">Similaridade de rota</td><td style="padding:6px 10px;font-size:.82rem;font-weight:700;color:#7c3aed;border:1px solid #e5e7eb">' + simPct + (rs.best_alvo ? ' \u2014 similar a ' + rs.best_alvo : '') + '</td></tr>' : '')
      + (rs.common_cameras && rs.common_cameras.length ? '<tr><td style="padding:6px 10px;font-size:.75rem;font-weight:700;color:#6b7280;white-space:nowrap;background:#f9fafb;border:1px solid #e5e7eb">Câmeras em comum</td><td style="padding:6px 10px;font-size:.82rem;border:1px solid #e5e7eb">' + rs.common_cameras.join(', ') + '</td></tr>' : '')
      + '</tbody></table>'
      + '</div>';
  }

  var analiseHtml = decisaoHtml
    + (scoreBreakdownHtml || '<div style="margin-bottom:12px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px;font-size:.82rem;color:#6b7280">Nenhum breakdown de score disponível para esta placa.</div>')
    + (centralHtml || '<div style="padding:14px 16px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;font-size:.82rem;color:#6b7280">Nenhum vínculo adicional com alvo ou rota semelhante foi identificado na central.</div>');

  var rpiHtml = _relEngine.render([
    _relEngine.buildHeader({
      titulo: 'Relatório de Placa Individual',
      subtitulo: 'Placa: <strong>' + plate + '</strong>',
      risco: level,
      score: score,
      now: now
    }),
    kpisHtml,
    _relEngine.section('1. Identificação & Avaliação Tática', dadosHtml),
    _relEngine.section('2. Acompanhamento / Parceiros (' + partners.length + ')', comboioHtml),
    _relEngine.section('3. Linha do Tempo — Passagens (' + events.length + ')', timelineHtml),
    _relEngine.section('4. Decisão Operacional & Análise', analiseHtml),
    _relEngine.buildFooter(now)
  ], 'rel-print');

  _relAbrirModal(
    plate,
    rpiHtml,
    function() {
      var rd = _batedorReportData;
      if (!rd) return;
      var evs = (rd.d && rd.d.events) || [];
      var tss = evs.map(function(e){ return e.ts; }).filter(Boolean).sort();
      var nowMs = Date.now();
      var tsFrom = tss.length
        ? _toLocalDTInput(new Date(new Date(tss[0]).getTime() - 3600000))
        : _toLocalDTInput(new Date(nowMs - 7*86400000));
      var tsTo = tss.length
        ? _toLocalDTInput(new Date(new Date(tss[tss.length-1]).getTime() + 3600000))
        : _toLocalDTInput(new Date(nowMs));
      _verRotaNaMapa(rd.plate, tsFrom, tsTo, evs.length + ' passagem(ns)');
    },
    null,
    null,
    d.is_alvo ? null : function() {
      _vehicleTargetFlow = {
        stage: 'target-choice',
        message: '🎯 Alvo salvo com sucesso!',
        restore: async function() {
          await _cenSingleRestoreReportModal(plate);
        }
      };
      closeRelModal(false);
      _addPlateAsAlvo(plate);
    },
    false
  );
}
// -- Relat�rio do Grupo Suspeito ----------------------------------------------
function _cgsGerarRelatorio() {
  var g = _cgsCurrentGroup;
  if (!g) return;

  var tituloEl = document.getElementById('cgs-rel-titulo');
  if (tituloEl) tituloEl.textContent = g.plates.join(' + ');

  var dash = '—';
  var fmtTs = function(iso) {
    if (!iso) return dash;
    return new Date(iso).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  };
  var fmtSec = function(s) {
    if (!s) return dash;
    s = Math.round(s);
    if (s < 60) return s + 's';
    if (s < 3600) {
      var m = Math.floor(s / 60);
      return m + ' min' + (s % 60 ? ' ' + (s % 60) + 's' : '');
    }
    var h = Math.floor(s / 3600);
    var rm = Math.floor((s % 3600) / 60);
    return h + 'h' + (rm ? ' ' + rm + 'min' : '');
  };
  var field = function(label, value) {
    return '<tr><td style="background:#f9fafb;font-weight:700;font-size:.76rem;color:#374151;white-space:nowrap;padding:6px 10px;width:38%;border:1px solid #e5e7eb">' + label + '</td>'
      + '<td style="font-size:.82rem;padding:6px 10px;border:1px solid #e5e7eb;color:#111">' + (value || dash) + '</td></tr>';
  };
  var miniCard = function(label, value, color) {
    return '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:10px 12px">'
      + '<div style="font-size:.66rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:4px">' + label + '</div>'
      + '<div style="font-size:1rem;font-weight:800;color:' + (color || '#111827') + '">' + value + '</div>'
      + '</div>';
  };

  var now = new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  var leaderRatio = Number(g.leader_ratio || 0);
  var leaderStatus = g.leader
    ? (leaderRatio >= 0.70 ? 'Liderança estável (' + Math.round(leaderRatio * 100) + '% das passagens em 1º)' : 'Sem liderança fixa (' + Math.round(leaderRatio * 100) + '% das passagens em 1º)')
    : 'Sem líder definido';
  var locStr = (g.cameras_names && g.cameras_names.length) ? g.cameras_names.join(', ') : dash;
  var alvosStr = (g.alvos && g.alvos.length)
    ? g.alvos.map(function(a){ return a.plate + (a.descricao ? ' — ' + a.descricao : ''); }).join('; ')
    : dash;
  var parecer = (function() {
    if ((g.alvos && g.alvos.length) || (g.threat_center && g.threat_center.matched_target)) {
      return {
        titulo: 'Parecer: grupo com vínculo operacional prioritário',
        detalhe: 'Há alvo cadastrado ou correspondência direta com alvo no grupo. O relatório deve sustentar monitoramento e pronta resposta.',
        bg: '#fef2f2',
        border: '#fca5a5',
        color: '#b91c1c'
      };
    }
    if (g.risco === 'ALTO' && leaderRatio >= 0.70 && Number(g.distinct_days || 0) >= 2) {
      return {
        titulo: 'Parecer: padrão consistente de atuação conjunta',
        detalhe: 'O grupo aparece com risco alto, recorrência em dias diferentes e liderança repetida. O foco é validar batedor, ordem e rota.',
        bg: '#fff7ed',
        border: '#fdba74',
        color: '#c2410c'
      };
    }
    if (Number(g.distinct_days || 0) >= 2 || Number(g.cameras_count || 0) >= 3) {
      return {
        titulo: 'Parecer: grupo relacional relevante',
        detalhe: 'O conjunto de veículos se repete em múltiplas câmeras ou dias. Vale manter observação sobre liderança, rota e reaproximações.',
        bg: '#fefce8',
        border: '#fde68a',
        color: '#a16207'
      };
    }
    return {
      titulo: 'Parecer: grupo em observação',
      detalhe: 'O vínculo está identificado, mas ainda depende de mais recorrência para consolidar padrão operacional.',
      bg: '#f8fafc',
      border: '#cbd5e1',
      color: '#334155'
    };
  })();

  var placasRows = g.plates.map(function(p) {
    var isAlvo = g.alvos && g.alvos.some(function(a){ return a.plate === p; });
    var isLeader = p === g.leader && g.leader_ratio >= 0.70;
    var role = isAlvo ? 'ALVO' : isLeader ? 'BATEDOR' : 'MEMBRO';
    var roleColor = isAlvo ? '#7c3aed' : isLeader ? '#dc2626' : '#374151';
    var descr = '';
    if (isAlvo && g.alvos) {
      var alvoItem = g.alvos.find(function(x){ return x.plate === p; });
      if (alvoItem && alvoItem.descricao) descr = alvoItem.descricao;
    }
    return '<tr>'
      + '<td style="font-family:monospace;font-size:.9rem;font-weight:800;padding:6px 10px;border:1px solid #e5e7eb">' + p + '</td>'
      + '<td style="padding:6px 10px;border:1px solid #e5e7eb"><span style="font-size:.7rem;font-weight:800;background:' + roleColor + ';color:#fff;padding:2px 8px;border-radius:99px">' + role + '</span></td>'
      + '<td style="font-size:.78rem;padding:6px 10px;border:1px solid #e5e7eb;color:#374151">' + (descr || dash) + '</td>'
      + '</tr>';
  }).join('');

  var placasTable = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:12px">'
    + miniCard('Veículos no grupo', String(g.group_size || g.plates.length || 0), '#111827')
    + miniCard('Alvos cadastrados', String((g.alvos || []).length), (g.alvos || []).length ? '#b91c1c' : '#111827')
    + miniCard('Líder / batedor', g.leader || dash, g.leader ? '#b91c1c' : '#111827')
    + miniCard('Dias juntos', g.distinct_days ? String(g.distinct_days) + ' d' : dash, '#1d4ed8')
    + '</div>'
    + '<table style="width:100%;border-collapse:collapse">'
    + '<thead><tr>'
      + '<th style="background:#f3f4f6;font-size:.7rem;text-transform:uppercase;padding:6px 10px;border:1px solid #e5e7eb;text-align:left">Placa</th>'
      + '<th style="background:#f3f4f6;font-size:.7rem;text-transform:uppercase;padding:6px 10px;border:1px solid #e5e7eb;text-align:left">Papel</th>'
      + '<th style="background:#f3f4f6;font-size:.7rem;text-transform:uppercase;padding:6px 10px;border:1px solid #e5e7eb;text-align:left">Cadastro</th>'
    + '</tr></thead>'
    + '<tbody>' + placasRows + '</tbody>'
    + '</table>';

  var avaliacaoTable = '<div style="margin-bottom:12px;padding:14px 16px;background:' + parecer.bg + ';border:1px solid ' + parecer.border + ';border-radius:10px">'
    + '<div style="font-size:.82rem;font-weight:800;color:' + parecer.color + ';margin-bottom:4px">' + parecer.titulo + '</div>'
    + '<div style="font-size:.82rem;color:#374151;line-height:1.45">' + parecer.detalhe + '</div>'
    + '</div>'
    + '<table style="width:100%;border-collapse:collapse"><tbody>'
    + field('Padrão do grupo', g.padrao || dash)
    + field('Risco relacional', g.risco || dash)
    + field('Score do grupo', g.score != null ? String(g.score) + ' pts' : dash)
    + field('Veículos envolvidos', g.group_size ? String(g.group_size) : dash)
    + field('Câmeras em comum', g.cameras_count ? String(g.cameras_count) + 'x' : dash)
    + field('Dias distintos juntos (90d)', g.distinct_days ? String(g.distinct_days) + ' dias' : dash)
    + field('Líder / batedor', g.leader || dash)
    + field('Consistência da liderança', leaderStatus)
    + field('Localidades', locStr)
    + field('Primeira vez juntos', fmtTs(g.first_seen))
    + field('Última vez juntos', fmtTs(g.last_seen))
    + field('Span da viagem', fmtSec(g.trip_span_sec))
    + '</tbody></table>';

  var tc = g.threat_center || {};
  var tcBadges = (tc.threat_badges || []).map(function(b) {
    var isLeader = b === 'LÍDER_É_ALVO';
    return '<span style="font-size:.7rem;font-weight:800;background:' + (isLeader ? '#dc2626' : '#a07a24') + ';color:' + (isLeader ? '#fff' : '#fff7db') + ';padding:2px 8px;border-radius:99px">' + (isLeader ? 'LÍDER É ALVO' : 'ALVO NO GRUPO') + '</span>';
  }).join(' ');
  var rs = tc.route_similarity || {};
  var simText = (rs.similarity_ratio != null && rs.similarity_ratio > 0)
    ? Math.round(rs.similarity_ratio * 100) + '%' + (rs.best_alvo ? ' — similar a ' + rs.best_alvo : '')
    : dash;
  var tcBody = (tc.matched_target || (g.alvos && g.alvos.length))
    ? '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:12px">'
        + miniCard('Alvos no grupo', String((g.alvos || []).length), (g.alvos || []).length ? '#b91c1c' : '#111827')
        + miniCard('Score extra por alvo', tc.score_delta ? '+' + tc.score_delta + ' pts' : '+0 pts', '#a16207')
        + miniCard('Tipo de vínculo', tc.match_type || dash, '#1d4ed8')
      + '</div>'
      + '<table style="width:100%;border-collapse:collapse"><tbody>'
      + field('Alvos cadastrados no grupo', alvosStr)
      + field('Badges ativados', tcBadges || dash)
      + field('Tipo de correspondência', tc.match_type || dash)
      + field('Placas alvo correspondentes', tc.matched_plates && tc.matched_plates.length ? tc.matched_plates.join(', ') : dash)
      + field('Acréscimo de score', '+' + (tc.score_delta || 0) + ' pts')
      + field('Similaridade de rota', simText)
      + '</tbody></table>'
    : '<div style="padding:14px 16px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;font-size:.82rem;color:#6b7280">Nenhum vínculo com alvos cadastrados foi identificado neste grupo no recorte analisado.</div>';

  var camsCnf = (g.cameras_confirmed || []).slice().sort(function(a, b) {
    var ai = Number(a && a.timeline_index);
    var bi = Number(b && b.timeline_index);
    if (Number.isFinite(ai) && Number.isFinite(bi) && ai !== bi) return ai - bi;
    return new Date(a.ts_min) - new Date(b.ts_min);
  });

  var timelineBody;
  if (!camsCnf.length) {
    timelineBody = '<div style="font-size:.82rem;color:#6b7280">' + dash + '</div>';
  } else {
    var tlRows = camsCnf.map(function(c, i) {
      var tsStr = c.ts_min ? new Date(c.ts_min).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : dash;
      var ordem = c.plate_order && c.plate_order.length
        ? c.plate_order.map(function(p, idx) {
            var isLeader = p === g.leader;
            return (idx + 1) + 'º ' + p + (isLeader ? ' [BATEDOR]' : '');
          }).join(' → ')
        : dash;
      return '<tr>'
        + '<td style="font-size:.76rem;font-weight:700;padding:6px 10px;border:1px solid #e5e7eb;text-align:center;color:#6b7280">' + (i + 1) + '</td>'
        + '<td style="font-size:.8rem;font-weight:700;padding:6px 10px;border:1px solid #e5e7eb">' + (c.cam_nome || c.camera_id || dash) + '</td>'
        + '<td style="font-size:.78rem;padding:6px 10px;border:1px solid #e5e7eb;white-space:nowrap">' + tsStr + '</td>'
        + '<td style="font-size:.76rem;padding:6px 10px;border:1px solid #e5e7eb;white-space:nowrap">' + (c.span_sec ? fmtSec(c.span_sec) : '0s') + '</td>'
        + '<td style="font-size:.74rem;padding:6px 10px;border:1px solid #e5e7eb;color:#374151">' + ordem + '</td>'
        + '</tr>';
    }).join('');
    timelineBody = '<table style="width:100%;border-collapse:collapse">'
      + '<thead><tr>'
        + '<th style="background:#f3f4f6;font-size:.68rem;text-transform:uppercase;padding:5px 10px;border:1px solid #e5e7eb;width:36px">#</th>'
        + '<th style="background:#f3f4f6;font-size:.68rem;text-transform:uppercase;padding:5px 10px;border:1px solid #e5e7eb">Câmera</th>'
        + '<th style="background:#f3f4f6;font-size:.68rem;text-transform:uppercase;padding:5px 10px;border:1px solid #e5e7eb">Horário</th>'
        + '<th style="background:#f3f4f6;font-size:.68rem;text-transform:uppercase;padding:5px 10px;border:1px solid #e5e7eb">Span</th>'
        + '<th style="background:#f3f4f6;font-size:.68rem;text-transform:uppercase;padding:5px 10px;border:1px solid #e5e7eb">Ordem das placas</th>'
        + '</tr></thead>'
      + '<tbody>' + tlRows + '</tbody>'
      + '</table>';
  }

  var kpisHtml = _relEngine.buildKPIs([
    { icon: '\uD83D\uDD34', label: 'Risco do grupo', value: g.risco || dash, color: _relEngine.riskColor(g.risco) },
    { icon: '\uD83D\uDCCA', label: 'Score relacional', value: g.score != null ? g.score + ' pts' : dash },
    { icon: '\uD83D\uDCF7', label: 'Câmeras em comum', value: g.cameras_count ? g.cameras_count + 'x' : dash },
    { icon: '\uD83D\uDE97', label: 'Veículos', value: g.group_size ? String(g.group_size) : dash },
    { icon: '\uD83D\uDCC5', label: 'Dias juntos', value: g.distinct_days ? g.distinct_days + ' d' : dash },
    { icon: '\u23F1', label: 'Span da viagem', value: g.trip_span_sec ? fmtSec(g.trip_span_sec) : dash },
    g.leader ? { icon: '\uD83C\uDFAF', label: 'Líder / batedor', value: g.leader, color: '#dc2626' } : null
  ]);

  var scoreBody = (g.score_reason && g.score_reason.length)
    ? '<div style="margin-bottom:12px;padding:14px 16px;background:' + parecer.bg + ';border:1px solid ' + parecer.border + ';border-radius:10px">'
        + '<div style="font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Parecer analítico</div>'
        + '<div style="font-size:.88rem;font-weight:800;color:' + parecer.color + ';margin-bottom:6px">' + parecer.titulo + '</div>'
        + '<div style="font-size:.82rem;color:#374151;line-height:1.45">' + parecer.detalhe + '</div>'
      + '</div>'
      + '<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px">'
        + '<div style="font-size:.75rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">Justificativa do score</div>'
        + '<ul style="margin:0;padding-left:18px">' + g.score_reason.map(function(r){ return '<li style="font-size:.78rem;color:#374151;padding:2px 0">' + r + '</li>'; }).join('') + '</ul>'
      + '</div>'
    : '<div style="padding:14px 16px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;font-size:.82rem;color:#6b7280">Nenhuma justificativa detalhada de score disponível para este grupo.</div>';

  var cgsHtml = _relEngine.render([
    _relEngine.buildHeader({ titulo: 'Relatório de Grupo Suspeito', subtitulo: 'Placas: ' + g.plates.join(' · '), risco: g.risco, score: g.score, now: now }),
    kpisHtml,
    _relEngine.section('1. Composição do Grupo', placasTable),
    _relEngine.section('2. Avaliação Relacional do Grupo', avaliacaoTable),
    _relEngine.section('3. Vínculo com Alvos / Central de Ameaça', tcBody),
    _relEngine.section('4. Linha do Tempo — Passagens Conjuntas', timelineBody),
    _relEngine.section('5. Parecer Analítico / Justificativa do Score', scoreBody),
    _relEngine.buildFooter(now)
  ], 'rel-print');

  _relAbrirModal(g.plates.join(' + '), cgsHtml, _cgsVerRotaNoMapa, _cgsVoltarAoDetalhe, 'Voltar');
}
function _cgsExportarPDF() { _relExportarPDF(); } // compat: usa motor unificado

// ── Rota do Grupo Suspeito no Mapa ───────────────────────────────────────
function _cgsVoltarAoDetalhe() {
  openModal('cgs-detalhe-modal');
}

async function _cgsVerRotaNoMapa() {
  var g = _cgsCurrentGroup;
  if (!g) return;
  // Usa a placa líder (ou primeira do grupo) como representante
  var plate = g.leader || g.plates[0];
  if (!plate) return;
  // Deriva período a partir das câmeras confirmadas do grupo
  var confirmed = g.cameras_confirmed || [];
  var tss = [];
  confirmed.forEach(function(c) {
    if (c.ts_min) tss.push(c.ts_min);
    if (c.ts_max) tss.push(c.ts_max);
  });
  tss.sort();
  var nowMs = Date.now();
  var tsFrom = tss.length
    ? _toLocalDTInput(new Date(new Date(tss[0]).getTime() - 3600000))
    : _toLocalDTInput(new Date(nowMs - 7*86400000));
  var tsTo = tss.length
    ? _toLocalDTInput(new Date(new Date(tss[tss.length-1]).getTime() + 3600000))
    : _toLocalDTInput(new Date(nowMs));
  var roleLabel = (g.leader && g.leader === plate) ? ' (l\u00edder)' : '';
  var infoLabel = 'Grupo \u2022 ' + plate + roleLabel + ' \u2022 ' + g.plates.length + ' ve\u00edculo(s)';
  _verRotaNaMapa(plate, tsFrom, tsTo, infoLabel);
}

function _cgsDesenharRotaGrupo(g, points, noGpsCams) {
  if (!_googleMap || !_checkGoogleMapsLoaded()) {
    alert('Aguarde o Google Maps carregar.');
    return;
  }

  // limpa camadas anteriores (trajetória individual, se houver)
  _clearTrajectoryLayers();
  _mapaInfoWindows.forEach(function(iw) { iw.close(); });
  _mapaInfoWindows = [];

  var ROTA_COLOR = _TRAJ_COLOR;
  var bounds = new google.maps.LatLngBounds();

  // ordena cronologicamente e numera
  points.forEach(function(p, i) { p.seq = i + 1; bounds.extend(new google.maps.LatLng(p.lat, p.lng)); });

  // ── Polyline: sombra + linha principal ─────────────────────────────
  if (points.length >= 2) {
    var path = points.map(function(p) { return {lat: p.lat, lng: p.lng}; });
    _trajetoriaLayers.push(new google.maps.Polyline({
      path: path, strokeColor: _TRAJ_SHADOW, strokeOpacity: 0.22, strokeWeight: 8,
      map: _googleMap, zIndex: 1
    }));
    _trajetoriaLayers.push(new google.maps.Polyline({
      path: path, strokeColor: ROTA_COLOR, strokeOpacity: 0.93, strokeWeight: 5,
      map: _googleMap, zIndex: 2
    }));

    // setas direcionais
    function bearing(p1, p2) {
      var dLng = (p2.lng - p1.lng) * Math.PI / 180;
      var la1  = p1.lat * Math.PI / 180, la2 = p2.lat * Math.PI / 180;
      var y = Math.sin(dLng) * Math.cos(la2);
      var x = Math.cos(la1) * Math.sin(la2) - Math.sin(la1) * Math.cos(la2) * Math.cos(dLng);
      return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
    }
    for (var i = 0; i < points.length - 1; i++) {
      var p1 = points[i], p2 = points[i+1];
      var midLat = (p1.lat + p2.lat) / 2, midLng = (p1.lng + p2.lng) / 2;
      var ang = bearing(p1, p2);
      var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">'
        + '<circle cx="11" cy="11" r="10" fill="' + ROTA_COLOR + '" stroke="#fff" stroke-width="1.5"/>'
        + '<polygon points="11,3 15.5,16 11,13 6.5,16" fill="#fff" transform="rotate(' + ang + ',11,11)"/>'
        + '</svg>';
      _trajetoriaLayers.push(new google.maps.Marker({
        position: {lat: midLat, lng: midLng}, map: _googleMap, zIndex: 10,
        icon: { url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg),
                scaledSize: new google.maps.Size(22, 22), anchor: new google.maps.Point(11, 11) }
      }));
    }
  }

  // ── Marcadores numerados com popup rico ───────────────────────────────
  var fmtTs = function(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  };
  var fmtSec = function(s) {
    if (!s) return '0s';
    s = Math.round(s);
    if (s < 60)   return s + 's';
    if (s < 3600) { var m = Math.floor(s/60); return m + 'min' + (s%60 ? s%60 + 's' : ''); }
    var h = Math.floor(s/3600), rm = Math.floor((s%3600)/60);
    return h + 'h' + (rm ? rm + 'min' : '');
  };

  points.forEach(function(p) {
    var isFirst = p.seq === 1;
    var isLast  = p.seq === points.length;
    var dotBg = isFirst ? '#16a34a' : isLast ? '#dc2626' : ROTA_COLOR;
    var dotFg = isFirst || isLast ? '#fff' : '#000';

    var circSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">'
      + '<circle cx="14" cy="14" r="13" fill="' + dotBg + '" stroke="#fff" stroke-width="2.5"/>'
      + '<text x="14" y="18.5" text-anchor="middle" font-size="11" font-weight="900" font-family="system-ui" fill="' + dotFg + '">' + p.seq + '</text>'
      + '</svg>';

    var ordemHtml = (p.plateOrder || p.allPlates).map(function(pl, idx) {
      var isLeader = pl === g.leader;
      var color = isLeader ? '#dc2626' : '#374151';
      return '<span style="font-family:monospace;font-weight:700;color:' + color + '">' + (idx+1) + 'º ' + pl + (isLeader ? ' ▶' : '') + '</span>';
    }).join(' &rarr; ');

    var popup = '<div style="font-family:system-ui;min-width:240px;max-width:300px">'
      + '<div style="font-weight:800;font-size:.95rem;color:' + ROTA_COLOR + ';margin-bottom:6px;border-bottom:1px solid #e5e7eb;padding-bottom:4px">'
        + '&#128247; ' + p.cam_nome + '</div>'
      + '<div style="font-size:.8rem;line-height:2">'
        + '<b style="color:#6b7280">Passagem #:</b> ' + p.seq + ' de ' + points.length + '<br>'
        + '<b style="color:#6b7280">Horário entrada:</b> ' + fmtTs(p.ts) + '<br>'
        + (p.tsMax ? '<b style="color:#6b7280">Horário saída:</b> ' + fmtTs(p.tsMax) + '<br>' : '')
        + (p.spanSec ? '<b style="color:#6b7280">Span:</b> ' + fmtSec(p.spanSec) + '<br>' : '')
        + (p.direcao ? '<b style="color:#6b7280">Direção:</b> <span style="color:#f59e0b;font-weight:700">' + p.direcao + '</span><br>' : '')
        + '<b style="color:#6b7280">Ordem das placas:</b><br><div style="margin-top:2px">' + ordemHtml + '</div>'
      + '</div>'
      + (isFirst ? '<div style="margin-top:6px;font-size:.7rem;background:#dcfce7;color:#15803d;border-radius:4px;padding:2px 8px;font-weight:700">▶ INÍCIO DA ROTA</div>' : '')
      + (isLast  ? '<div style="margin-top:6px;font-size:.7rem;background:#fee2e2;color:#dc2626;border-radius:4px;padding:2px 8px;font-weight:700">■ FIM DA ROTA</div>' : '')
      + '</div>';

    var iw = new google.maps.InfoWindow({ content: popup });
    var mk = new google.maps.Marker({
      position: {lat: p.lat, lng: p.lng},
      map: _googleMap,
      icon: {
        url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(circSvg),
        scaledSize: new google.maps.Size(28, 28),
        anchor: new google.maps.Point(14, 14)
      },
      title: p.cam_nome,
      zIndex: 20
    });
    mk.addListener('click', function() {
      _mapaInfoWindows.forEach(function(w) { w.close(); });
      iw.open(_googleMap, mk);
    });
    _trajetoriaLayers.push(mk);
    _mapaInfoWindows.push(iw);
  });

  // ── Labels INÍCIO / FIM ──────────────────────────────────────────────
  var mkLabel = function(pos, label, bg) {
    return new google.maps.Marker({
      position: pos, map: _googleMap, zIndex: 50,
      icon: {
        url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(
          '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="none"/></svg>'
        ),
        scaledSize: new google.maps.Size(1, 1), anchor: new google.maps.Point(0, 0)
      },
      label: { text: label, color: '#fff', fontSize: '10px', fontWeight: 'bold' }
    });
  };
  if (points.length >= 1) _trajetoriaLayers.push(mkLabel({lat: points[0].lat, lng: points[0].lng}, '▶ INÍCIO', '#16a34a'));
  if (points.length >= 2) _trajetoriaLayers.push(mkLabel({lat: points[points.length-1].lat, lng: points[points.length-1].lng}, '■ FIM', '#dc2626'));

  // ── Fit bounds ──────────────────────────────────────────────────────
  if (!bounds.isEmpty()) {
    _googleMap.fitBounds(bounds, {top:80, right:60, bottom:60, left:60});
    if (_googleMap.getZoom() > 14) _googleMap.setZoom(14);
  }

  // ── Painel lateral de análise ──────────────────────────────────────
  var noGps = document.getElementById('map-no-gps');
  if (noGps) {
    var riscoBg    = g.risco === 'ALTO' ? '#dc2626' : g.risco === 'MÉDIO' ? '#d97706' : '#6b7280';
    var riscoColor = g.risco === 'ALTO' ? '#fca5a5' : g.risco === 'MÉDIO' ? '#fcd34d' : '#86efac';
    var scoreBg    = g.score >= 80 ? '#dc2626' : g.score >= 40 ? '#d97706' : '#6b7280';

    // horários — points já ordenados cronologicamente
    var tFirst = points.length ? fmtTs(points[0].ts) : '—';
    var tLast  = points.length ? fmtTs(points[points.length - 1].tsMax || points[points.length - 1].ts) : '—';

    // placas com badges
    var placasBadges = g.plates.map(function(p) {
      var isAlvo   = g.alvos && g.alvos.some(function(a) { return a.plate === p; });
      var isLeader = p === g.leader && g.leader_ratio >= 0.70;
      var role     = isAlvo ? 'ALVO' : isLeader ? 'BATEDOR' : 'MEMBRO';
      var roleBg   = isAlvo ? '#7c3aed' : isLeader ? '#dc2626' : '#374151';
      var plateFg  = isAlvo ? '#c4b5fd' : isLeader ? '#f87171' : 'var(--text)';
      return '<span style="display:inline-flex;align-items:center;gap:5px;background:var(--card);border:1px solid var(--border);'
        + 'border-radius:8px;padding:4px 10px;white-space:nowrap">'
        + '<span style="font-family:monospace;font-size:.88rem;font-weight:800;color:' + plateFg + '">' + p + '</span>'
        + '<span style="font-size:.62rem;font-weight:700;background:' + roleBg + ';color:#fff;padding:1px 6px;border-radius:99px">' + role + '</span>'
        + '</span>';
    }).join('');

    var missStr = noGpsCams.length
      ? '<div style="font-size:.72rem;color:var(--muted);margin-top:6px">&#9888; Sem GPS: ' + noGpsCams.join(', ') + '</div>'
      : '';

    // row helper
    var row = function(icon, label, value) {
      return '<div style="display:flex;justify-content:space-between;align-items:flex-start;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.06)">'
        + '<span style="font-size:.7rem;color:var(--muted);white-space:nowrap;padding-right:8px">' + icon + ' ' + label + '</span>'
        + '<span style="font-size:.78rem;font-weight:700;color:var(--text);text-align:right">' + value + '</span>'
        + '</div>';
    };

    noGps.innerHTML =
      // ── cabeçalho do painel ──────────────────────────────────────
      '<div style="background:var(--card2,var(--card));border:1px solid rgba(245,158,11,.35);border-radius:12px;overflow:hidden;margin-top:4px">'

        // barra de ação
        + '<div style="background:rgba(245,158,11,.1);border-bottom:1px solid rgba(245,158,11,.25);padding:8px 14px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">'
          + '<div style="display:flex;align-items:center;gap:8px">'
            + '<span style="font-size:.9rem">&#128101;</span>'
            + '<span style="font-size:.8rem;font-weight:800;color:#f59e0b">Grupo Suspeito</span>'
            + '<span style="font-size:.72rem;background:' + riscoBg + ';color:' + riscoColor + ';padding:2px 9px;border-radius:99px;font-weight:800">' + g.risco + '</span>'
            + '<span style="font-size:.72rem;background:' + scoreBg + ';color:#fff;padding:2px 9px;border-radius:99px;font-weight:800">' + g.score + ' pts</span>'
            + (g.threat_center && g.threat_center.threat_badges && g.threat_center.threat_badges.length
              ? g.threat_center.threat_badges.map(function(badge) {
                  var isLider = badge === 'LÍDER_É_ALVO';
                  return '<span style="font-size:.62rem;font-weight:800;background:' + (isLider ? '#dc2626' : '#a07a24') + ';color:' + (isLider ? '#fff' : '#fff7db') + ';padding:2px 7px;border-radius:99px">' + (isLider ? '\u2605 L\u00cdDER ALVO' : '\u26a1 ALVO') + '</span>';
                }).join('')
              : '')
          + '</div>'
          + '<div style="display:flex;gap:6px">'
            + '<button class="btn btn-outline btn-xs" onclick="_cgsVoltarAoDetalhe()">&#8592; Detalhe</button>'
            + '<button class="btn btn-outline btn-xs" onclick="_limparTrajetoria()">&#10005; Limpar</button>'
          + '</div>'
        + '</div>'

        // corpo do painel
        + '<div style="padding:10px 14px">'

          // ── placas ────────────────────────────────────────────────
          + '<div style="font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);font-weight:700;margin-bottom:6px">&#128663; Placas Envolvidas</div>'
          + '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px">' + placasBadges + '</div>'

          // ── campos ────────────────────────────────────────────────
          + row('&#127807;', 'Padrão',        g.padrao || '—')
          + row('&#127942;', 'Líder / Batedor', (g.leader ? g.leader + (g.leader_ratio ? ' (' + Math.round(g.leader_ratio * 100) + '%)' : '') : '—'))
          + row('&#128247;', 'Câmeras mapeadas', points.length + (noGpsCams.length ? ' / ' + (points.length + noGpsCams.length) + ' total' : ''))
          + row('&#128197;', 'Primeiro horário', tFirst)
          + row('&#128336;', 'Último horário',   tLast)

          + missStr

        + '</div>'
      + '</div>';
  }
}

// ===================================================================
// CENTRAL DE AMEAÇAS — tempo real + paginação
// ===================================================================

var _cenLiveEnabled = false;
var _cenLiveTimer   = null;
var _cenAllItems    = [];   // cache bruto
var _cenPage        = 0;
var _cenPageSize    = 10;
var _cenSingleInitDone = false;
var _cenSingleState = {
  plate: '',
  report: null,
  opts: null,
  centralItem: null,
};
var _cenSingleRecentSearches = [];

function toggleCenLive() {
  _cenLiveEnabled = !_cenLiveEnabled;
  var btn = document.getElementById('btn-cen-live');
  if (_cenLiveEnabled) {
    btn.classList.remove('btn-outline'); btn.classList.add('btn-success');
    btn.innerHTML = '<span class="dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#22c55e;animation:pulse 1s infinite;margin-right:4px"></span> AO VIVO';
    loadCentral(false);
    _cenScheduleNext();
  } else {
    _cenStopTimer();
    btn.classList.remove('btn-success'); btn.classList.add('btn-outline');
    btn.innerHTML = '&#9654; <span id="cen-live-label">Monitorar</span>';
  }
}

function _cenStopTimer() {
  if (_cenLiveTimer) { clearTimeout(_cenLiveTimer); _cenLiveTimer = null; }
}

function _cenScheduleNext() {
  if (!_cenLiveEnabled) return;
  var sec = parseInt(document.getElementById('cen-interval').value, 10) || 60;
  _cenLiveTimer = setTimeout(function() {
    loadCentral(false).then(function() { _cenScheduleNext(); });
  }, sec * 1000);
}

function cenTipoChange() {
  // filtro Tipo removido — câmeras e sinais sempre visíveis
  cenApplyFilter();
}

function _cenPlateInput(el) {
  if (!el) return;
  var v = (el.value || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 7);
  if (el.value !== v) el.value = v;
  cenApplyFilter();
}

function cenApplyFilter() {
  _cenPage = 0;
  _cenRenderPage();
}

async function _loadCenGrupos(w, cowin, gsizes, orderMode, leaderRatio, payloadMax, tsFrom, tsTo) {
  try {
    var mc = (document.getElementById('cen-min-cameras') || {}).value || '1';
    var url = '/api/batedor/grupos_comboio?window=' + encodeURIComponent(w)
            + '&co_window=' + encodeURIComponent(cowin)
            + '&group_sizes=' + encodeURIComponent(gsizes)
            + '&min_cameras=' + encodeURIComponent(mc)
            + '&order_mode=' + encodeURIComponent(orderMode)
            + '&leader_ratio=' + encodeURIComponent(leaderRatio)
            + '&payload_max_front=' + encodeURIComponent(payloadMax);
    if (tsFrom)  url += '&ts_from=' + encodeURIComponent(tsFrom);
    if (tsTo)    url += '&ts_to=' + encodeURIComponent(tsTo);
    var r = await fetch(url);
    if (!r.ok) return;
    var data = await r.json();
    var groups = data.groups || [];
    // Enriquece _cenAllItems com dados de grupos
    var plateGroups = {};
    groups.forEach(function(g) {
      (g.plates || []).forEach(function(p) {
        if (!plateGroups[p]) plateGroups[p] = [];
        var others = (g.plates || []).filter(function(x){ return x !== p; });
        others.forEach(function(o) {
          plateGroups[p].push({ plate: o, cameras_together: g.cameras_count || 1, leader: g.leader || '', role: (g.plate_stats||[]).find(function(s){return s.plate===p;})||{} });
        });
      });
    });
    _cenAllItems.forEach(function(item) {
      if (plateGroups[item.plate]) {
        var seen = {};
        var merged = (item.in_grupos || []).concat(plateGroups[item.plate]);
        item.in_grupos = merged.filter(function(g) {
          if (seen[g.plate]) return false;
          seen[g.plate] = true;
          return true;
        });
        if (!item.sinais || item.sinais < 2) item.sinais = (item.sinais || 1) + 1;
      }
    });
    _cenRenderPage();
  } catch(e) { /* silencioso */ }
}

function cenOrderModeChange() {
  var mode = (document.getElementById('cen-ordermode') || {}).value;
  var opts = document.getElementById('cen-leader-opts');
  if (opts) opts.style.display = (mode === 'leader_front') ? 'inline' : 'none';
  cenGroupSizeChange();
}

function cenGroupSizeChange() {
  var gs = (document.getElementById('cen-gsizes') || {}).value || '2';
  var mode = (document.getElementById('cen-ordermode') || {}).value;
  var plLabel = document.getElementById('cen-payload-label');
  if (plLabel) plLabel.style.display = (mode === 'leader_front' && gs === '3+') ? 'inline' : 'none';
  loadCentral(true);
}

function _cenGetValue(primaryId, fallbackId, defaultValue) {
  var primaryEl = primaryId ? document.getElementById(primaryId) : null;
  if (primaryEl && primaryEl.value != null) return primaryEl.value;
  var fallbackEl = fallbackId ? document.getElementById(fallbackId) : null;
  if (fallbackEl && fallbackEl.value != null) return fallbackEl.value;
  return defaultValue;
}

function _cenSetText(id, value) {
  var el = document.getElementById(id);
  if (el) el.textContent = value;
}

async function loadCentral(showSpinner) {
  if (showSpinner === undefined) showSpinner = true;
  var w = _cenGetValue('cen-window', 'cen-single-window', '24h');
  var tsFrom = null, tsTo = null;
  if (w === 'custom') {
    tsFrom = _toIso(_cenGetValue('cen-ts-from', 'cen-single-ts-from', ''));
    tsTo   = _toIso(_cenGetValue('cen-ts-to', 'cen-single-ts-to', ''));
    if (!tsFrom || !tsTo) { alert('Informe o período personalizado (De / Até).'); return; }
    w = '1h';
  }
  var prefix  = '';
  var gsizes    = (document.getElementById('cen-gsizes')     || {}).value || '2';
  var cowin     = (document.getElementById('cen-cowin')      || {}).value || '300';
  var orderMode = (document.getElementById('cen-ordermode')  || {}).value || 'any';
  var leaderR   = percentInputToRatio((document.getElementById('cen-leader-ratio')|| {}).value || '70', 0.70);
  var payloadM  = (document.getElementById('cen-payload-max') || {}).value || '0';

  if (showSpinner) {
    var _cst = document.getElementById('central-status');
    if (_cst) _cst.innerHTML = '<span class="spinner"></span>';
    var centralBody = document.getElementById('central-tbody');
    if (centralBody) {
      centralBody.innerHTML =
        '<tr><td colspan="10" style="text-align:center;color:var(--muted);padding:32px"><span class="spinner"></span> Analisando…</td></tr>';
    }
  }
  try {
    var url = '/api/batedor/central?window=' + w + '&limit=300';
    if (tsFrom)  url += '&ts_from=' + encodeURIComponent(tsFrom) + '&ts_to=' + encodeURIComponent(tsTo);
    if (prefix)  url += '&plate_prefix='  + encodeURIComponent(prefix.trim().toUpperCase());
    var r = await fetch(url);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    var data = await r.json();
    var all = data.items || [];
    _cenAllItems = all;
    _cenPage     = 0;
    // cards (sempre com dados brutos completos)
    _cenSetText('cen-total', all.length);
    _cenSetText('cen-multi', all.filter(function(i){ return (i.companions_count || 0) > 0 || !!i.in_comboio; }).length || '-');
    _cenSetText('cen-alvos', all.filter(function(i){ return i.is_alvo; }).length || '-');
    _cenRenderPage();
    var ts = new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
    var _cst = document.getElementById('central-status');
    if (_cst) _cst.textContent = '';
    // ---- Grupos em Comboio integrado ----
    _loadCenGrupos(w, cowin, gsizes, orderMode, leaderR, payloadM, tsFrom, tsTo);
  } catch(e) {
    var _cst = document.getElementById('central-status');
    if (_cst) _cst.textContent = 'Erro: ' + e.message;
    if (showSpinner) {
      var centralBodyError = document.getElementById('central-tbody');
      if (centralBodyError) {
        centralBodyError.innerHTML =
          '<tr><td colspan="8" style="text-align:center;color:var(--danger);padding:24px">Erro: ' + e.message + '</td></tr>';
      }
    }
    // para o live se der erro
    _cenLiveEnabled = false; _cenStopTimer();
    var btn = document.getElementById('btn-cen-live');
    if (btn) { btn.classList.remove('btn-success'); btn.classList.add('btn-outline');
               btn.innerHTML = '&#9654; <span id="cen-live-label">Monitorar</span>'; }
  }
}

function _cenRenderPage() {
  var mc = parseInt(_cenGetValue('cen-min-cameras', 'cen-single-min-cameras', '0'), 10) || 0;
  var plateFl = String(_cenGetValue('cen-filter-plate', 'cen-single-plate', '') || '').trim().toUpperCase();
  var riscoFl = (document.getElementById('cen-risco') || {value:''}).value || '';
  var items = _cenAllItems.filter(function(i) {
    // filtro placa
    if (plateFl && i.plate.toUpperCase().indexOf(plateFl) === -1) return false;
    // filtro mín câmeras
    if (mc > 0) {
      var cams = 0;
      if (i.in_suspeitos && i.in_suspeitos.cameras) cams = Math.max(cams, i.in_suspeitos.cameras);
      if (i.in_comboio   && i.in_comboio.cameras)   cams = Math.max(cams, i.in_comboio.cameras);
      if (cams < mc) return false;
    }
    // filtro risco
    if (riscoFl) {
      var r = (i.risco || i.risk_level || '').toUpperCase();
      if (r !== riscoFl) return false;
    }
    return true;
  });
  var total = items.length;
  var pages = Math.max(1, Math.ceil(total / _cenPageSize));
  if (_cenPage >= pages) _cenPage = pages - 1;
  var start = _cenPage * _cenPageSize;
  var page  = items.slice(start, start + _cenPageSize);

  _cenSetText('cen-top-score', items.length ? items[0].score_total : '-');

  var pg = document.getElementById('cen-pagination');
  if (pg && total > _cenPageSize) {
    pg.style.display = 'flex';
    _cenSetText('cen-page-info', 'Página ' + (_cenPage + 1) + ' de ' + pages + ' · ' + total + ' placa(s)');
    var prevBtn = document.getElementById('cen-btn-prev');
    var nextBtn = document.getElementById('cen-btn-next');
    if (prevBtn) prevBtn.disabled = _cenPage === 0;
    if (nextBtn) nextBtn.disabled = _cenPage >= pages - 1;
  } else if (pg && total > 0) {
    pg.style.display = 'flex';
    _cenSetText('cen-page-info', total + ' placa(s)');
    var prevBtnSingle = document.getElementById('cen-btn-prev');
    var nextBtnSingle = document.getElementById('cen-btn-next');
    if (prevBtnSingle) prevBtnSingle.disabled = true;
    if (nextBtnSingle) nextBtnSingle.disabled = true;
  } else if (pg) {
    pg.style.display = 'none';
  }
  renderCentral(page, total);
}

function cenPageNav(delta) {
  _cenPage = Math.max(0, _cenPage + delta);
  _cenRenderPage();
}

function _cenScoreClass(s) {
  if (s >= 75) return 'badge-red';
  if (s >= 35) return 'badge-yellow';
  return 'badge-green';
}

function _tcHasThreat(item) {
  var tc = item && item.threat_center;
  if (!tc) return false;
  return !!(tc.matched_target || (tc.threat_badges && tc.threat_badges.length));
}

function _tcHasRouteSimilarity(item) {
  var tc = item && item.threat_center;
  if (!tc) return false;
  var rs = tc.route_similarity;
  if (!rs) return false;
  return !!(rs.matched === true || (rs.similarity_ratio && rs.similarity_ratio > 0));
}

function _sinaisBadges(item) {
  var parts = [];
  if (item.in_suspeitos) parts.push('<span class="badge badge-yellow" title="Suspeito — ' + item.in_suspeitos.passes + ' pass. em ' + item.in_suspeitos.cameras + ' câm.">&#128270; S</span>');
  if (item.in_comboio)   parts.push('<span class="badge badge-red"    title="Comboio — ' + item.in_comboio.cameras + ' câm. confirmadas, trip ' + (item.in_comboio.trip_span_sec||0) + 's">&#128663;&#128663; C</span>');
  if (item.in_grupos && item.in_grupos.length) {
    var gs = item.in_grupos.map(function(g){ return g.plate + ' (' + g.cameras_together + 'câm)'; }).join(', ');
    parts.push('<span class="badge" style="background:rgba(34,197,94,.2);color:#86efac" title="Grupos — junto com: ' + gs + '">&#128101; G</span>');
  }
  if (item.is_alvo) parts.push('<span class="badge cen-target-badge" title="Alvo rastreado: ' + (item.alvo_descricao||'') + '">&#127919; A</span>');
  if (_tcHasRouteSimilarity(item)) {
    var _rs = item.threat_center.route_similarity;
    var _pct = Math.round((_rs.similarity_ratio || 0) * 100);
    parts.push('<span class="badge cen-route-badge" title="Rota parecida com alvo ' + (_rs.best_alvo||'?') + ' — ' + _pct + '% câmeras em comum">&#128336; ROTA ' + _pct + '%</span>');
  }
  if (item.sinais >= 3) parts.unshift('<span class="badge badge-red" style="font-size:.7rem">&#9889; MÚLTIPLOS</span>');
  return parts.join(' ');
}

function _grupoLinks(grupos) {
  if (!grupos || !grupos.length) return '<span style="color:var(--muted)">-</span>';
  return grupos.map(function(g){
    return '<span class="badge" style="background:rgba(34,197,94,.15);color:#86efac;cursor:pointer" onclick="openDetail(\'' + (g.plate||'').replace(/'/g,"\\'") + '\')">'
      + g.plate + ' <small>(' + g.cameras_together + '&#128247;)</small></span>';
  }).join(' ');
}

function _cenAtividadeCell(item) {
  var sc = item && item.in_suspeitos;
  if (!sc) return '<span style="color:var(--muted)">Baixa atividade</span>';
  return '<div style="display:flex;flex-direction:column;gap:2px">'
    + '<span style="font-size:.78rem;font-weight:700;color:var(--text)">' + sc.passes + ' passagem(ns)</span>'
    + '<span style="font-size:.74rem;color:var(--muted)">' + sc.cameras + ' câm. distintas</span>'
    + '</div>';
}

function _cenAcompanhamentoCell(item) {
  var groups = item && item.in_grupos ? item.in_grupos : [];
  var top = groups.length ? groups[0] : null;
  var count = Number(item && item.companions_count) || groups.length || 0;
  if (!count && !item.in_comboio) return '<span style="color:var(--muted)">Sem acompanhamento</span>';
  var html = '<div style="display:flex;flex-direction:column;gap:2px">';
  html += '<span style="font-size:.78rem;font-weight:700;color:#86efac">' + count + ' parceiro(s)</span>';
  if (top) {
    html += '<span style="font-size:.74rem;color:var(--muted)">Mais forte: '
      + '<span style="font-family:monospace;color:var(--text)">' + top.plate + '</span> · '
      + top.cameras_together + ' câm.</span>';
  } else if (item.in_comboio) {
    html += '<span style="font-size:.74rem;color:var(--muted)">Comboio detectado em ' + item.in_comboio.cameras + ' câm.</span>';
  }
  html += '</div>';
  return html;
}

function renderCentral(items, total) {
  var tb = document.getElementById('central-tbody');
  if (!tb) return;
  var plateFl = String(_cenGetValue('cen-filter-plate', 'cen-single-plate', '') || '').trim().toUpperCase();
  if (!items.length) {
    var emptyMsg = (total === 0 ? 'Nenhuma placa em atenção encontrada com os filtros atuais.' : 'Sem resultados nesta página.');
    if (plateFl) emptyMsg = 'Placa não encontrada com os filtros informados.';
    tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:32px">'
      + emptyMsg
      + '</td></tr>';
    return;
  }
  tb.innerHTML = items.map(function(item) {
    var alvoCell = item.is_alvo
      ? '<span class="badge cen-target-badge" title="' + (item.alvo_descricao||'') + '">&#127919; SIM</span>'
      : '<span style="color:var(--muted)">&#8212;</span>';
    var rowStyle = item.risk_level === 'ALTO' ? 'background:rgba(239,68,68,.06)' : item.is_alvo ? 'background:rgba(196,166,74,.08)' : '';
    return '<tr style="' + rowStyle + '">'
      + '<td>' + plateHtml(item.plate) + '</td>'
      + '<td><span class="badge ' + _cenScoreClass(item.score_total) + '">' + item.score_total + '</span></td>'
      + '<td style="white-space:nowrap">' + _sinaisBadges(item) + '</td>'
      + '<td>' + _cenAtividadeCell(item) + '</td>'
      + '<td>' + _cenAcompanhamentoCell(item) + '</td>'
      + '<td>' + alvoCell + '</td>'
      + '<td style="white-space:nowrap">' + fmtTs(item.last_seen)  + '</td>'
      + '<td class="action-cell"><div class="action-buttons">'
      + '<button class="btn btn-outline btn-xs" title="Hist&oacute;rico de eventos" onclick="openDetail(\'' + (item.plate||'').replace(/'/g,"\\'") + '\')">&#128269; Visualizar</button>'
      + '</div></td>'
      + '</tr>';
  }).join('');
}

// ===== HISTORICO DE DRILL-DOWN DO RELATORIO =====
var _reportHistory = [];
var _reportCurrentPlate = null;
var _reportCurrentOpts = null;

function _normalizeReportOpts(opts) {
  var out = Object.assign({}, opts || {});
  if (!out.window && !out.ts_from && !out.ts_to) out.window = '2h';
  return out;
}

function _reportWindowChange() {
  var win = document.getElementById('report-filter-window');
  var row = document.getElementById('report-filter-custom-row');
  if (!win || !row) return;
  row.style.display = win.value === 'custom' ? 'flex' : 'none';
}

function _applyReportPeriodFilter() {
  if (!_reportCurrentPlate) return;
  var current = _normalizeReportOpts(_reportCurrentOpts);
  var winEl = document.getElementById('report-filter-window');
  var fromEl = document.getElementById('report-filter-from');
  var toEl = document.getElementById('report-filter-to');
  var nextOpts = Object.assign({}, current);
  var win = winEl ? (winEl.value || '2h') : '2h';
  delete nextOpts.ts_from;
  delete nextOpts.ts_to;
  if (win === 'custom') {
    var tsFrom = _toIso(fromEl ? fromEl.value : '');
    var tsTo = _toIso(toEl ? toEl.value : '');
    if (!tsFrom || !tsTo) {
      alert('Informe o período personalizado.');
      return;
    }
    nextOpts.window = 'custom';
    nextOpts.ts_from = tsFrom;
    nextOpts.ts_to = tsTo;
  } else {
    nextOpts.window = win;
  }
  _reportCurrentOpts = nextOpts;
  openBatedorReport(_reportCurrentPlate, true, nextOpts);
}

async function openBatedorReport(plate, _fromHistory, opts) {
  plate = (plate || '').trim().toUpperCase();
  if (!plate) return;

  if (!_fromHistory && _reportCurrentPlate && _reportCurrentPlate !== plate) {
    _reportHistory.push(_reportCurrentPlate);
  } else if (!_fromHistory && !_reportCurrentPlate) {
    _reportHistory = [];
  }
  _reportCurrentPlate = plate;
  _reportCurrentOpts = _normalizeReportOpts(opts);
  _detailModalReturnFn = function() { openBatedorReport(plate, true, _reportCurrentOpts); };
  opts = _reportCurrentOpts;

  var _filterDesc = '';
  if (opts && typeof opts === 'object') {
    var _fparts = [];
    if (opts.window && opts.window !== 'custom') _fparts.push(opts.window);
    else if (opts.ts_from && opts.ts_to) _fparts.push('per\u00edodo custom');
    if (opts.camera_id)       _fparts.push('\uD83D\uDCF7 ' + opts.camera_id);
    if (opts.direction)       _fparts.push(opts.direction === 'CRESCENTE' ? '\u2191' : '\u2193');
    if (opts.min_confidence > 0) _fparts.push('conf\u2265' + Math.round(opts.min_confidence * 100) + '%');
    if (opts.min_cameras > 1)    _fparts.push('\u2265' + opts.min_cameras + ' c\u00e2m.');
    if (opts.vehicle_type)  _fparts.push(opts.vehicle_type);
    if (opts.vehicle_color) _fparts.push(opts.vehicle_color);
    if (_fparts.length) _filterDesc = ' <span style="font-size:.72rem;color:var(--accent2);font-weight:400">(\u00b7 ' + _fparts.join(' \u00b7 ') + ')</span>';
  }

  document.getElementById('detail-modal-plate').innerHTML = 'Placa ' + plate + _filterDesc;
  document.getElementById('detail-modal-body').innerHTML = '<p style="color:var(--muted)"><span class="spinner"></span> Analisando ' + plate + '...</p>';
  var _mb = document.getElementById('detail-modal-map-btn');
  if (_mb) _mb.style.display = 'none';
  openModal('detail-modal');

  var _url = '/api/vehicle/report?plate=' + encodeURIComponent(plate);
  if (opts && typeof opts === 'object') {
    if (opts.window && opts.window !== 'custom') _url += '&window=' + encodeURIComponent(opts.window);
    if (opts.ts_from) _url += '&ts_from=' + encodeURIComponent(opts.ts_from);
    if (opts.ts_to)   _url += '&ts_to='   + encodeURIComponent(opts.ts_to);
    if (opts.camera_id)          _url += '&filter_camera='    + encodeURIComponent(opts.camera_id);
    if (opts.direction)          _url += '&filter_direction='  + encodeURIComponent(opts.direction);
    if (opts.min_confidence > 0) _url += '&min_confidence='   + opts.min_confidence;
    if (opts.min_cameras > 1)    _url += '&min_cameras='      + opts.min_cameras;
    if (opts.vehicle_type)       _url += '&vehicle_type='     + encodeURIComponent(opts.vehicle_type);
    if (opts.vehicle_color)      _url += '&vehicle_color='    + encodeURIComponent(opts.vehicle_color);
  } else {
    var w = '2h';
    try { var cw = document.getElementById('cen-window').value; if (cw && cw !== 'custom') w = cw; } catch(e) {}
    _url += '&window=' + encodeURIComponent(w);
  }

  try {
    var resp = await fetch(_url);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var d = await resp.json();

    var reportWindowValue = (opts && opts.window) ? opts.window : '2h';
    var reportFromValue = (opts && opts.ts_from) ? _toLocalDTInput(new Date(opts.ts_from)) : '';
    var reportToValue = (opts && opts.ts_to) ? _toLocalDTInput(new Date(opts.ts_to)) : '';
    var reportFilterHtml = '<div style="margin-bottom:14px;padding:12px 14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:12px">'
      + '<div style="font-size:.76rem;color:var(--accent2);font-weight:800;text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px">&#128197; Per\u00edodo da an\u00e1lise</div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:end">'
      + '<label style="display:flex;flex-direction:column;gap:4px;font-size:.76rem;color:var(--muted)">Período'
      + '<select id="report-filter-window" class="cen-ctl" onchange="_reportWindowChange()" style="min-width:120px">'
      + '<option value="1h"' + (reportWindowValue === '1h' ? ' selected' : '') + '>1 hora</option>'
      + '<option value="2h"' + (reportWindowValue === '2h' ? ' selected' : '') + '>2 horas</option>'
      + '<option value="6h"' + (reportWindowValue === '6h' ? ' selected' : '') + '>6 horas</option>'
      + '<option value="12h"' + (reportWindowValue === '12h' ? ' selected' : '') + '>12 horas</option>'
      + '<option value="24h"' + (reportWindowValue === '24h' ? ' selected' : '') + '>24 horas</option>'
      + '<option value="7d"' + (reportWindowValue === '7d' ? ' selected' : '') + '>7 dias</option>'
      + '<option value="30d"' + (reportWindowValue === '30d' ? ' selected' : '') + '>30 dias</option>'
      + '<option value="custom"' + (reportWindowValue === 'custom' ? ' selected' : '') + '>Período personalizado</option>'
      + '</select></label>'
      + '<div id="report-filter-custom-row" style="display:' + (reportWindowValue === 'custom' ? 'flex' : 'none') + ';flex-wrap:wrap;gap:8px;align-items:end">'
      + '<label style="display:flex;flex-direction:column;gap:4px;font-size:.76rem;color:var(--muted)">De'
      + '<input type="datetime-local" id="report-filter-from" class="cen-ctl" value="' + reportFromValue + '"></label>'
      + '<label style="display:flex;flex-direction:column;gap:4px;font-size:.76rem;color:var(--muted)">Até'
      + '<input type="datetime-local" id="report-filter-to" class="cen-ctl" value="' + reportToValue + '"></label>'
      + '</div>'
      + '<button class="btn btn-outline btn-sm" onclick="_applyReportPeriodFilter()">Aplicar</button>'
      + '</div></div>';
    var _escPlate = plate.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
    var events = (d.events || []).slice();
    var eventsChrono = events.slice().sort(function(a, b) {
      return new Date(a && a.ts ? a.ts : 0) - new Date(b && b.ts ? b.ts : 0);
    });
    var firstEvent = eventsChrono.length ? eventsChrono[0] : null;
    var lastEvent = eventsChrono.length ? eventsChrono[eventsChrono.length - 1] : null;
    var partners = d.convoy_partners || [];
    var totalPasses = d.summary ? d.summary.total_passes : events.length;
    var camerasCount = d.summary ? d.summary.cameras_count : '—';
    var partnersCount = d.summary ? d.summary.partners_count : partners.length;
    var avgConfLabel = (d.summary && d.summary.avg_confidence > 0) ? formatConfidencePercent(d.summary.avg_confidence) + '%' : '—';
    var domDirLabel = d.summary && d.summary.dom_direction
      ? (d.summary.dom_direction === 'CRESCENTE' ? '\u2191 CRESCENTE' : '\u2193 DECRESCENTE')
      : '—';
    var riskLabel = d.level === 'alerta' ? 'ALTO' : d.level === 'suspeito' ? 'M\u00c9DIO' : 'NORMAL';
    var riskValueColor = d.level === 'alerta' ? '#fca5a5' : d.level === 'suspeito' ? '#fcd34d' : '#86efac';
    var riskBadgeBg = d.level === 'alerta' ? 'rgba(220,38,38,.22)' : d.level === 'suspeito' ? 'rgba(217,119,6,.22)' : 'rgba(34,197,94,.14)';
    var riskBadgeBorder = d.level === 'alerta' ? 'rgba(239,68,68,.32)' : d.level === 'suspeito' ? 'rgba(245,158,11,.32)' : 'rgba(34,197,94,.22)';
    var patternLabel = d.is_alvo ? 'ALVO RASTREADO' : (partners.length ? 'COMBOIO / ACOMPANHADO' : ((Number(camerasCount) || 0) > 1 ? 'MULTI-C\u00c2MERA' : 'MONITORAMENTO'));
    var lastSeenLabel = lastEvent ? fmtTs(lastEvent.ts) : '—';
    var headerBadgesHtml = (d.badges || []).map(function(b){
      var bg = b === 'ALVO' ? 'rgba(220,38,38,.75)' : (b === 'MULTI-C\u00c2MERA' || b === 'COMBOIO') ? 'rgba(202,138,4,.6)' : 'rgba(59,130,246,.4)';
      var color = b === 'ALVO' ? '#fff' : (b === 'MULTI-C\u00c2MERA' || b === 'COMBOIO') ? '#fff7db' : '#dbeafe';
      return '<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:999px;background:' + bg + ';color:' + color + ';font-size:.68rem;font-weight:800">' + b + '</span>';
    }).join('');
    var historyBtnHtml = '';
    if (_reportHistory.length > 0) {
      var prevPlate = _reportHistory[_reportHistory.length - 1];
      historyBtnHtml = '<button class="btn btn-outline btn-sm" onclick="_reportGoBack()" style="font-size:.8rem;font-weight:700">&#8592; Anterior: ' + prevPlate + '</button>';
    }
    function _plateMetricCard(label, value, sub, valueColor) {
      return '<div style="border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:12px 14px;background:rgba(0,0,0,.12)">'
        + '<div style="font-size:.69rem;color:var(--muted);font-weight:800;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px">' + label + '</div>'
        + '<div style="font-size:1.55rem;font-weight:800;color:' + (valueColor || '#fff') + ';line-height:1.1">' + value + '</div>'
        + (sub ? '<div style="font-size:.78rem;color:var(--muted);margin-top:6px">' + sub + '</div>' : '')
        + '</div>';
    }
    function _plateInfoCard(label, value, tone) {
      return '<div style="border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:12px 14px;background:rgba(255,255,255,.03)">'
        + '<div style="font-size:.69rem;color:var(--muted);font-weight:800;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">' + label + '</div>'
        + '<div style="font-size:.95rem;font-weight:800;color:' + (tone || '#f8fafc') + '">' + value + '</div>'
        + '</div>';
    }
    function _plateSection(title, body, accentColor, borderColor) {
      return '<div style="margin-bottom:14px;border:1px solid ' + (borderColor || 'rgba(255,255,255,.08)') + ';background:rgba(255,255,255,.03);border-radius:14px;padding:14px 16px">'
        + '<div style="font-size:.9rem;font-weight:800;margin-bottom:12px;color:' + (accentColor || 'var(--accent2)') + ';text-transform:uppercase;letter-spacing:.05em">' + title + '</div>'
        + body
        + '</div>';
    }
    var actionButtonsHtml = '<div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end">';
    if (historyBtnHtml) actionButtonsHtml += historyBtnHtml;
    if (!d.is_alvo) {
      actionButtonsHtml += '<button class="btn btn-sm" style="background:#dc2626;color:#fff;font-weight:700" onclick="_addPlateAsAlvo(\'' + _escPlate + '\')">&#127919; Criar alvo</button>';
    }
    actionButtonsHtml += '<button class="btn btn-sm" style="background:#1d4ed8;color:#fff;font-weight:700" onclick="_abrirRelatorioPlacaIndividual()">&#128196; Gerar relat\u00f3rio</button>'
      + '<button class="btn btn-sm" style="background:#15803d;color:#fff;font-weight:700" onclick="verTrajetoriaNoMapa()">&#127760; Ver rota no mapa</button>'
      + '<button class="btn btn-outline btn-sm" onclick="_toggleScoreBreakdown()" style="font-size:.8rem;font-weight:700">&#128202; Ver score</button>'
      + '</div>';
    var headerHtml = '<div style="margin-bottom:14px;border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:16px 18px;background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(255,255,255,.02))">'
      + '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">'
      + '<div style="min-width:260px;flex:1">'
      + '<div style="font-size:.72rem;color:var(--accent2);font-weight:800;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">1. Identifica\u00e7\u00e3o &amp; avalia\u00e7\u00e3o t\u00e1tica</div>'
      + '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">'
      + '<div style="font-size:1.5rem;font-weight:900;color:#fff;font-family:monospace;letter-spacing:.04em">' + plate + '</div>'
      + '<span style="display:inline-flex;align-items:center;gap:5px;padding:5px 11px;border-radius:999px;background:' + riskBadgeBg + ';border:1px solid ' + riskBadgeBorder + ';color:' + riskValueColor + ';font-size:.75rem;font-weight:800">' + riskLabel + '</span>'
      + headerBadgesHtml
      + '</div>'
      + '<div style="font-size:.84rem;color:var(--muted);line-height:1.5">Tela reorganizada para destacar o que a placa fez, com quem ela anda e qual decis\u00e3o operacional faz sentido agora.</div>'
      + '</div>'
      + actionButtonsHtml
      + '</div>'
      + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-top:14px">'
      + _plateMetricCard('Risco', riskLabel, d.is_alvo ? 'placa j\u00e1 cadastrada como alvo' : 'leitura operacional atual', riskValueColor)
      + _plateMetricCard('Score', d.score, 'pontua\u00e7\u00e3o individual', '#fff')
      + _plateMetricCard('Passagens', totalPasses, firstEvent ? 'desde ' + fmtTs(firstEvent.ts) : '', '#fff')
      + _plateMetricCard('C\u00e2meras', camerasCount, 'locais distintos', '#fff')
      + _plateMetricCard('Parceiros', partnersCount, partners.length ? 'h\u00e1 acompanhamento confirmado' : 'sem comboio confirmado', partners.length ? '#fca5a5' : '#fff')
      + _plateMetricCard('Conf. m\u00e9dia', avgConfLabel, 'qualidade das leituras', '#fff')
      + '</div>'
      + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:10px">'
      + _plateInfoCard('Dire\u00e7\u00e3o predominante', domDirLabel, d.summary && d.summary.dom_direction === 'CRESCENTE' ? '#93c5fd' : d.summary && d.summary.dom_direction === 'DECRESCENTE' ? '#fcd34d' : '#f8fafc')
      + _plateInfoCard('Padr\u00e3o observado', patternLabel, '#f8fafc')
      + _plateInfoCard('\u00daltimo visto', lastSeenLabel, '#f8fafc')
      + '</div>'
      + (d.is_alvo
        ? '<div style="margin-top:12px;border:1px solid rgba(168,85,247,.38);background:rgba(124,58,237,.12);border-radius:12px;padding:12px 14px">'
          + '<div style="font-size:.76rem;font-weight:800;color:#e9d5ff;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">&#127919; V\u00ednculo com alvo cadastrado</div>'
          + '<div style="font-size:.92rem;font-weight:800;color:#fff;font-family:monospace;margin-bottom:5px">' + plate + '</div>'
          + '<div style="font-size:.8rem;color:#ede9fe">' + (d.alvo_descricao || 'Sem descri\u00e7\u00e3o registrada para este alvo.') + '</div>'
          + (d.alvo_list ? '<div style="font-size:.76rem;color:#d8b4fe;margin-top:6px">Lista: ' + d.alvo_list + '</div>' : '')
          + '</div>'
        : '')
      + '</div>';

    var lastDec = d.last_decision;
    var decLabels = { confirmado: '&#9989; Suspeito confirmado', falso_positivo: '&#10060; Falso positivo', ignorar: '&#9197; Ignorado' };
    var decBg = { confirmado: 'rgba(220,38,38,.2)', falso_positivo: 'rgba(34,197,94,.1)', ignorar: 'rgba(100,100,100,.15)' };
    var decBorder = { confirmado: 'rgba(220,38,38,.5)', falso_positivo: 'rgba(34,197,94,.3)', ignorar: 'rgba(120,120,120,.3)' };
    var decisionHtml = _plateSection('2. Decis\u00e3o operacional',
      (lastDec
        ? '<div style="background:' + (decBg[lastDec.decision]||'rgba(100,100,100,.1)') + ';border:1px solid ' + (decBorder[lastDec.decision]||'rgba(120,120,120,.3)') + ';border-radius:10px;padding:10px 12px;margin-bottom:10px;font-size:.82rem;line-height:1.5">'
          + '<strong>' + (decLabels[lastDec.decision]||lastDec.decision) + '</strong>'
          + (lastDec.note ? ' \u2014 ' + lastDec.note : '')
          + ' <span style="color:var(--muted);font-size:.72rem">por ' + (lastDec.operator||'sistema') + ' em ' + fmtTs(lastDec.created_at) + '</span></div>'
        : '<div style="margin-bottom:10px;padding:12px 14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;font-size:.82rem;color:var(--muted)">Nenhuma decis\u00e3o registrada para esta placa at\u00e9 o momento.</div>'),
      'var(--accent2)'
    );

    var breakdownHtml = '<div id="score-breakdown-panel" style="display:none;margin:12px 0 14px">'
      + '<div style="font-size:.84rem;font-weight:800;margin:0 0 8px;color:var(--accent2);text-transform:uppercase;letter-spacing:.05em">&#128202; Composi\u00e7\u00e3o do score</div>'
      + '<div class="table-wrap"><table><thead><tr><th>Fator</th><th>Val.</th><th>Mult.</th><th>Pts</th><th>Obs</th></tr></thead><tbody>'
      + (d.score_breakdown||[]).map(function(b){
          return '<tr><td style="font-size:.8rem">' + b.label + '</td>'
            + '<td style="text-align:center">' + b.value + '</td>'
            + '<td style="text-align:center;color:var(--accent)">&times;' + b.multiplier + '</td>'
            + '<td style="text-align:center"><strong>+' + b.points + '</strong></td>'
            + '<td style="font-size:.75rem;color:var(--muted)">' + (b.reason||'') + '</td></tr>';
        }).join('')
      + '<tr style="font-weight:700;background:rgba(139,92,246,.1)"><td colspan="3">TOTAL</td><td>+' + d.score + '</td><td></td></tr>'
      + '</tbody></table></div></div>';

    var partnersHtml;
    if (partners.length) {
      var _allPartnerPlates = partners.map(function(p){ return p.plate; });
      var _groupForComboio = [plate].concat(_allPartnerPlates);
      var maxPartnerCameras = partners.reduce(function(acc, p) { return Math.max(acc, Number(p.cameras_together || 0)); }, 0);
      var maxPartnerSpan = partners.reduce(function(acc, p) { return Math.max(acc, Number(p.trip_span_sec || 0)); }, 0);
      var maxPartnerSpanLabel = maxPartnerSpan >= 60 ? Math.round(maxPartnerSpan / 60) + ' min' : (maxPartnerSpan ? maxPartnerSpan + ' s' : '—');
      partnersHtml = _plateSection('4. Parceiros confirmados',
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:12px">'
        + _plateInfoCard('Parceiros confirmados', partners.length, '#fca5a5')
        + _plateInfoCard('Maior cruzamento', maxPartnerCameras + ' c\u00e2m.', '#f8fafc')
        + _plateInfoCard('Maior span', maxPartnerSpanLabel, '#f8fafc')
        + '</div>'
        + '<div style="background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.15);border-radius:10px;padding:8px 12px;margin-bottom:10px;font-size:.76rem;color:#fca5a5">'
        + '&#9888; S\u00f3 aparece quem passou <strong>junto na mesma c\u00e2mera</strong> (janela \u2264 300s) em <strong>\u22652 c\u00e2meras</strong> distintas, com viagem \u22641 hora.'
        + '</div>'
        + '<div class="table-wrap"><table><thead><tr><th>Parceiro</th><th>C\u00e2m. confirmadas</th><th>Trip span</th><th>\u00daltimo</th><th>C\u00e2meras</th><th>A\u00e7\u00f5es</th></tr></thead><tbody>'
        + partners.map(function(p){
            var alvoMark = p.is_alvo ? ' <span class="badge badge-danger" style="font-size:.64rem">ALVO</span>' : '';
            var camNames = (p.cameras_detail||[]).map(function(c){ return c.cam_nome||c.camera_id; }).join(', ');
            var tripMin  = Math.round((p.trip_span_sec||0)/60);
            return '<tr>'
              + '<td>' + plateHtml(p.plate) + alvoMark + '</td>'
              + '<td style="text-align:center;font-weight:700;color:var(--accent2)">' + p.cameras_together + '</td>'
              + '<td style="text-align:center">' + (tripMin > 0 ? tripMin + ' min' : (p.trip_span_sec||0) + 's') + '</td>'
              + '<td style="font-size:.75rem">' + fmtTs(p.last_seen) + '</td>'
              + '<td style="font-size:.73rem;color:var(--muted);max-width:200px;overflow:hidden;text-overflow:ellipsis" title="' + camNames + '">' + camNames + '</td>'
              + '<td><button class="btn btn-xs" style="background:rgba(139,92,246,.45);color:#fff" onclick="openBatedorReport(\'' + p.plate.replace(/'/g,"\\'") + '\')">\uD83D\uDCC4 Relat\u00f3rio</button></td>'
              + '</tr>';
          }).join('')
        + '</tbody></table></div>'
        + '<div style="margin-top:10px"><button class="btn btn-sm" style="background:#ef4444;color:#fff;font-weight:700" onclick="openComboioReport(\'' + plate.replace(/'/g,"\\'") + '\',' + JSON.stringify(_groupForComboio).replace(/'/g,"\\'") + ')">&#128663;&#128663; Relat\u00f3rio do comboio</button></div>',
        '#fca5a5',
        'rgba(239,68,68,.18)'
      );
    } else {
      partnersHtml = _plateSection('4. Parceiros confirmados',
        '<div style="background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.2);border-radius:10px;padding:12px 14px;font-size:.82rem;color:#86efac">&#10003; Nenhum parceiro em comboio confirmado na janela de ' + reportWindowValue + '. <small style="color:var(--muted)">(Requer mesma c\u00e2mera \u00d72+ c\u00e2meras, trip \u22641h)</small></div>',
        '#86efac',
        'rgba(34,197,94,.18)'
      );
    }

    events.forEach(function(ev){ _imgMeta[ev.id] = { camName: ev.camera_name||ev.camera_id||'', ts: ev.ts||'' }; });
    var evRows = events.map(function(ev) {
      var dtObj = ev.ts ? new Date(ev.ts) : null;
      var dtFmt = dtObj ? dtObj.toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '-';
      var conf = ev.confidence > 0 ? formatConfidencePercent(ev.confidence) + '%' : '-';
      var confPct = ev.confidence > 0 ? formatConfidencePercent(ev.confidence) : 0;
      var confColor = confPct >= 85 ? '#4ade80' : confPct >= 60 ? '#facc15' : '#f87171';
      var thumb = ev.image_path
        ? '<img class="thumb" src="/api/events/' + ev.id + '/thumbnail?w=100&h=68" loading="lazy" onclick="openImage(' + ev.id + ',\'' + plate.replace(/'/g,"\\'") + '\')" style="border-radius:4px;cursor:pointer">'
        : '<div class="thumb-none">-</div>';
      return '<tr><td>' + thumb + '</td>'
        + '<td style="font-size:.78rem;white-space:nowrap">' + dtFmt + '</td>'
        + '<td style="font-size:.79rem">' + (ev.camera_name||ev.camera_id||'-') + '</td>'
        + '<td>' + _dirCell(ev.direcao) + '</td>'
        + '<td style="font-size:.75rem;color:var(--muted)">' + (ev.vehicle_type||'-') + '</td>'
        + '<td style="text-align:center;font-size:.75rem"><span style="display:inline-block;min-width:52px;padding:3px 8px;border-radius:999px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);color:' + confColor + ';font-weight:800">' + conf + '</span></td>'
        + '</tr>';
    }).join('');
    var evSummaryHtml = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:12px">'
      + _plateInfoCard('Total no per\u00edodo', events.length, '#f8fafc')
      + _plateInfoCard('Primeira passagem', firstEvent ? fmtTs(firstEvent.ts) : '—', '#f8fafc')
      + _plateInfoCard('\u00daltima passagem', lastSeenLabel, '#f8fafc')
      + '</div>';
    var evHtml = _plateSection('5. Passagens registradas',
      evSummaryHtml
      + (events.length
        ? '<div class="table-wrap"><table><thead><tr><th>Foto</th><th>Data/Hora</th><th>C\u00e2mera</th><th>Dire\u00e7\u00e3o</th><th>Tipo</th><th>Conf.</th></tr></thead><tbody>' + evRows + '</tbody></table></div>'
        : '<p style="color:var(--muted);font-size:.82rem">Nenhuma passagem no per\u00edodo.</p>'),
      '#f8fafc'
    );

    var threatCenterHtml = '';
    var _cenItem = (_cenAllItems || []).find(function(it){ return it.plate === plate; });
    if (_cenItem && _cenItem.threat_center) {
      var _tc  = _cenItem.threat_center;
      var _rs  = _tc.route_similarity || {};
      var _matchedLabel  = _tc.matched_target  ? '<span style="color:#c4b5fd;font-weight:700">&#9989; Sim</span>' : '<span style="color:var(--muted)">&#8212; Não</span>';
      var _routeLabel    = _rs.matched         ? '<span style="color:#d8b4fe;font-weight:700">&#9989; Sim</span>'  : '<span style="color:var(--muted)">&#8212; Não</span>';
      var _badgesHtml = (_tc.threat_badges && _tc.threat_badges.length)
        ? '<div style="margin-bottom:8px">' + _tc.threat_badges.map(function(b){ return '<span class="badge" style="background:rgba(139,92,246,.4);color:#ddd8fe;font-size:.72rem">' + b + '</span>'; }).join(' ') + '</div>'
        : '';
      var _matchPlates = (_tc.matched_plates && _tc.matched_plates.length)
        ? '<div style="font-size:.78rem;margin-bottom:4px"><span style="color:var(--muted)">Placas alvo no grupo:</span> <span style="color:#c4b5fd">' + _tc.matched_plates.join(', ') + '</span></div>'
        : '';
      var _bestAlvo = _rs.best_alvo
        ? '<div style="font-size:.78rem;margin-bottom:4px"><span style="color:var(--muted)">Alvo mais similar:</span> <span style="color:#c4b5fd;font-weight:700">' + _rs.best_alvo + '</span></div>'
        : '';
      var _commonCams = (_rs.common_cameras && _rs.common_cameras.length)
        ? '<div style="font-size:.76rem;margin-bottom:4px"><span style="color:var(--muted)">C\u00e2meras em comum:</span> ' + _rs.common_cameras.join(', ') + '</div>'
        : '';
      var _commonCities = (_rs.common_cities && _rs.common_cities.length)
        ? '<div style="font-size:.76rem"><span style="color:var(--muted)">Cidades em comum:</span> ' + _rs.common_cities.join(', ') + '</div>'
        : '';
      var _tcParecer = _tc.matched_target
        ? 'Parecer: a placa possui v\u00ednculo direto com alvo cadastrado ou correspond\u00eancia operacional relevante.'
        : _rs.matched
          ? 'Parecer: a placa n\u00e3o est\u00e1 cadastrada como alvo, mas repetiu rota compat\u00edvel com alvo monitorado.'
          : 'Parecer: sem v\u00ednculo direto com alvo, mantendo monitoramento apenas pelo padr\u00e3o operacional.';
      threatCenterHtml = _plateSection('3. Central de amea\u00e7as',
        '<div style="background:rgba(139,92,246,.08);border:1px solid rgba(139,92,246,.22);border-radius:10px;padding:10px 12px;margin-bottom:10px;font-size:.82rem;color:#ede9fe;line-height:1.5">' + _tcParecer + '</div>'
        + _badgesHtml
        + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:10px">'
        + _plateInfoCard('Alvo cadastrado', _matchedLabel, '#ede9fe')
        + _plateInfoCard('Rota parecida', _routeLabel, '#ede9fe')
        + _plateInfoCard('Similaridade', (_rs.similarity_ratio != null && _rs.similarity_ratio > 0) ? (Math.round(_rs.similarity_ratio * 100) + '%') : '—', '#ede9fe')
        + '</div>'
        + _matchPlates + _bestAlvo + _commonCams + _commonCities,
        'var(--accent2)',
        'rgba(139,92,246,.35)'
      );
    } else {
      threatCenterHtml = _plateSection('3. Central de amea\u00e7as',
        '<div style="padding:12px 14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;font-size:.82rem;color:var(--muted)">Nenhum v\u00ednculo relevante com alvo ou rota similar foi identificado para esta placa no momento.</div>',
        'var(--accent2)'
      );
    }

    document.getElementById('detail-modal-body').innerHTML =
      headerHtml + breakdownHtml + reportFilterHtml + decisionHtml + threatCenterHtml + partnersHtml + evHtml;

    _mapaTrajetoria = { plates: [plate], points: events.map(function(ev){
      return { camera_id: ev.camera_id, ts: ev.ts||'', plate: plate, cam_nome: ev.camera_name||ev.camera_id||'' };
    })};
    _batedorReportData = { plate: plate, d: d };
    if (_mb) _mb.style.display = 'none';
  } catch(e) {
    document.getElementById('detail-modal-body').innerHTML = '<p style="color:var(--danger)">Erro ao carregar relat\u00f3rio: ' + e.message + '</p>';
  }
}

function _reportGoBack() {
  if (_reportHistory.length === 0) return;
  var prev = _reportHistory.pop();
  openBatedorReport(prev, true);
}

async function _submitDecision(plate, score, level, decision) {
  var note = '';
  if (decision === 'confirmado') {
    var r = prompt('Observação (será usada como descrição do alvo rastreado):', '');
    if (r === null) return;
    note = r;
  }
  try {
    var resp = await fetch('/api/vehicle/report/decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plate: plate, score_total: score, level: level, decision: decision, note: note, window: '2h' })
    });
    if (!resp.ok) {
      var err = await resp.json().catch(function(){ return { detail: 'Erro ' + resp.status }; });
      alert('Erro: ' + (err.detail || resp.status)); return;
    }

    // ── Quando confirmado: adicionar automaticamente aos Alvos Rastreados ──
    if (decision === 'confirmado') {
      var descAlvo = note || ('Confirmado via Central de Ameaças — Score ' + score + ' (' + level + ')');
      var alvResp = await fetch('/api/alvos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plate: plate, descricao: descAlvo })
      });
      if (alvResp.ok) {
        _flashMsg('🎯 ' + plate + ' salvo nos Alvos Rastreados!', '#22c55e');
        // atualiza cache se a aba estiver aberta
        if (typeof loadAlvos === 'function') loadAlvos();
      } else {
        _flashMsg('⚠ Não foi possível salvar nos Alvos Rastreados.', '#d97706');
      }
    }

    openBatedorReport(plate, true);
  } catch(e) { alert('Erro ao registrar decisão: ' + e.message); }
}

function _flashMsg(msg, bg) {
  var el = document.createElement('div');
  el.style.cssText = 'position:fixed;bottom:28px;right:28px;z-index:9999;background:' + (bg||'#6d28d9') + ';color:#fff;padding:11px 20px;border-radius:10px;font-weight:700;font-size:.88rem;box-shadow:0 4px 24px rgba(0,0,0,.45);transition:opacity .4s';
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(function(){ el.style.opacity='0'; setTimeout(function(){ el.remove(); }, 500); }, 3000);
}

function _toggleScoreBreakdown() {
  var p = document.getElementById('score-breakdown-panel');
  if (p) p.style.display = p.style.display === 'none' ? '' : 'none';
}
async function _addPlateAsAlvo(plate) {
  plate = String(plate || '').trim().toUpperCase();
  if (!plate) return;
  var keepCurrentContext = !!(_vehicleTargetFlow && typeof _vehicleTargetFlow.restore === 'function');
  closeModal('detail-modal');
  if (!keepCurrentContext) {
    var vehTab = document.querySelector('.nav-item[onclick*="veiculos"]');
    if (vehTab) switchTab('veiculos', vehTab);
    document.getElementById('view-list-detail').style.display = 'none';
    document.getElementById('view-listas').style.display = 'block';
  }
  try {
    if (!listsCache || !listsCache.length) {
      await loadLists();
    }
    if (!listsCache || !listsCache.length) {
      alert('Nenhuma lista de monitoramento cadastrada. Crie uma lista em Veículos para continuar.');
      openListModal();
      return;
    }
    document.getElementById('vehicle-target-plate').value = plate;
    document.getElementById('vehicle-target-error').textContent = '';
    var sel = document.getElementById('vehicle-target-list');
    sel.innerHTML = listsCache.map(function(l){
      return '<option value="' + l.id + '">' + (l.name || ('Lista #' + l.id)) + '</option>';
    }).join('');
    if (_vehicleTargetFlow && _vehicleTargetFlow.listId) sel.value = String(_vehicleTargetFlow.listId);
    else if (listsCache.length) sel.value = String(listsCache[0].id);
    openModal('vehicle-target-modal');
    _vehicleTargetFocusChooser();
  } catch (e) {
    alert('Erro ao preparar cadastro em Veículos: ' + e.message);
  }
}

function _confirmVehicleTargetChoice() {
  var plate = (document.getElementById('vehicle-target-plate').value || '').trim().toUpperCase();
  var selEl = document.getElementById('vehicle-target-list');
  var listId = parseInt(selEl.value || '0', 10);
  var listName = selEl && selEl.options && selEl.selectedIndex >= 0
    ? (selEl.options[selEl.selectedIndex].text || ('Lista #' + listId))
    : ('Lista #' + listId);
  var errEl = document.getElementById('vehicle-target-error');
  if (!plate) {
    errEl.textContent = 'Placa não informada.';
    return;
  }
  if (!listId) {
    errEl.textContent = 'Escolha uma lista.';
    return;
  }
  if (_vehicleTargetFlow) {
    _vehicleTargetFlow.stage = 'vehicle-form';
    _vehicleTargetFlow.listId = listId;
    _vehicleTargetFlow.listName = listName;
    _vehicleTargetFlow.message = '🎯 Alvo salvo na lista "' + listName + '"!';
  }
  closeModal('vehicle-target-modal');
  openListDetail(listId);
  openAddVehicleModal({ plate: plate, isAlvo: true, listId: listId });
}
function _dirCell(dir) {
  if (dir === 'CRESCENTE')   return '<span style="color:var(--accent);font-size:.75rem;font-weight:700">&#8593; CRESCENTE</span>';
  if (dir === 'DECRESCENTE') return '<span style="color:var(--accent);font-size:.75rem;font-weight:700">&#8595; DECRESCENTE</span>';
  return '<span style="color:var(--muted);font-size:.72rem">&#8212;</span>';
}
function _domDir(cameraList) {
  if (!cameraList || !window._camsData) return null;
  var names = (cameraList + '').split(',').map(function(x){ return x.trim().toLowerCase(); }).filter(Boolean);
  var nC = 0, nD = 0;
  (window._camsData || []).forEach(function(c) {
    var n = (c.nome || '').toLowerCase(); var ip = (c.ip || '').toLowerCase();
    if (names.indexOf(n) >= 0 || names.indexOf(ip) >= 0 || names.indexOf((c.camera_id||'').toLowerCase()) >= 0) {
      if (c.direcao === 'CRESCENTE') nC++; if (c.direcao === 'DECRESCENTE') nD++;
    }
  });
  if (nC > 0 && nC >= nD) return 'CRESCENTE';
  if (nD > 0 && nD > nC) return 'DECRESCENTE';
  return null;
}
function openDetail(plate) { _reportHistory = []; _reportCurrentPlate = null; openBatedorReport(plate); }

// ===== RELATÓRIO DE COMBOIO =====
var _comboioData = null;
var _comboioMap = null;
var _comboioMapLayers = [];

function openComboioReport(targetPlate, groupPlates, opts) {
  targetPlate = (targetPlate || '').trim().toUpperCase();
  if (!targetPlate || !groupPlates || groupPlates.length < 1) return;

  var allPlates = groupPlates.slice();
  if (allPlates.indexOf(targetPlate) < 0) allPlates.unshift(targetPlate);

  document.getElementById('comboio-modal-plate').textContent = targetPlate;
  document.getElementById('comboio-modal-body').innerHTML =
    '<div class="report-light-surface" style="text-align:center;padding:40px"><span class="spinner"></span><br><span style="color:var(--muted);font-size:.84rem">Analisando comboio de ' + allPlates.length + ' ve\u00edculos\u2026</span></div>';
  openModal('comboio-modal');

  loadComboioReport(targetPlate, allPlates, opts || {});
}

async function loadComboioReport(targetPlate, allPlates, opts) {
  var url = '/api/comboio/report?target_plate=' + encodeURIComponent(targetPlate)
          + '&plates=' + encodeURIComponent(allPlates.join(','));
  if (opts.window_s)       url += '&window_s=' + opts.window_s;
  if (opts.max_trip_gap_s) url += '&max_trip_gap_s=' + opts.max_trip_gap_s;
  if (opts.window)         url += '&window=' + encodeURIComponent(opts.window);
  if (opts.ts_from)        url += '&ts_from=' + encodeURIComponent(opts.ts_from);
  if (opts.ts_to)          url += '&ts_to='   + encodeURIComponent(opts.ts_to);

  try {
    var resp = await fetch(url);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var data = await resp.json();
    _comboioData = data;
    _renderComboioReport(data);
  } catch(e) {
    document.getElementById('comboio-modal-body').innerHTML =
      '<div class="report-light-surface" style="padding:20px;color:#dc2626">&#9888; Erro ao carregar relat\u00f3rio: ' + e.message + '</div>';
  }
}

function _renderComboioReport(d) {
  var html = '';

  // ── 1. CABEÇALHO ──
  html += _comboioRenderHeader(d);

  // ── 2. VEÍCULOS DO GRUPO ──
  html += _comboioRenderGroupCards(d.group, d.target_plate);

  // ── 3. EVENTOS CONFIRMADOS ──
  html += _comboioRenderEvents(d.confirmed_events, d.group.plates);

  // ── 4. MÉTRICAS ──
  html += _comboioRenderMetrics(d.metrics, d.confirmed_events, d.group.plates);

  // ── 5. TRAJETÓRIA ──
  html += _comboioRenderTrajectorySection(d.trajectory);

  // ── 6. AÇÕES ──
  html += _comboioRenderActions(d);

  document.getElementById('comboio-modal-body').innerHTML = '<div class="report-light-surface report-light-surface--comboio">' + html + '</div>';

  // Inicializar mapa se houver pontos
  setTimeout(function(){ _comboioInitMap(d.trajectory); }, 100);
}

function _comboioRenderHeader(d) {
  var pStart = d.period ? fmtTs(d.period.start) : '-';
  var pEnd   = d.period ? fmtTs(d.period.end) : '-';
  var statusLabel = { pending: '\u23F3 Pendente', confirmed: '\u2705 Confirmado', false_positive: '\u274C Falso Positivo' };
  var statusBg    = { pending: 'rgba(234,179,8,.2)', confirmed: 'rgba(220,38,38,.2)', false_positive: 'rgba(34,197,94,.15)' };
  var statusBdr   = { pending: 'rgba(234,179,8,.5)', confirmed: 'rgba(220,38,38,.5)', false_positive: 'rgba(34,197,94,.4)' };
  var st = d.group.status || 'pending';

  return '<div style="margin-bottom:16px">'
    + '<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:10px">'
    + '<div style="font-size:1.1rem;font-weight:700;color:var(--text)">&#128663;&#128663; Relat\u00f3rio de Comboio</div>'
    + '<span class="badge" style="background:' + (statusBg[st]||statusBg.pending) + ';border:1px solid ' + (statusBdr[st]||statusBdr.pending) + ';color:var(--text);font-size:.78rem">' + (statusLabel[st]||st) + '</span>'
    + '</div>'
    + '<div style="font-size:.84rem;color:var(--muted);margin-bottom:4px">Placa pesquisada: <strong style="color:var(--text);font-size:.92rem">' + d.target_plate + '</strong></div>'
    + '<div style="display:flex;flex-wrap:wrap;gap:16px;font-size:.76rem;color:var(--muted)">'
    + '<span>&#128197; ' + pStart + ' \u2014 ' + pEnd + '</span>'
    + '<span>&#9201; window_s = <strong>' + d.params.window_s + '</strong></span>'
    + '<span>&#128247; min_cameras = <strong>' + d.params.min_cameras + '</strong></span>'
    + '<span>&#128336; max_trip_gap = <strong>' + d.params.max_trip_gap_s + 's</strong></span>'
    + '</div></div>';
}

function _comboioRenderGroupCards(group, targetPlate) {
  var plates = group.plates || [];
  var imgs = group.vehicle_images || {};
  var alvos = group.alvos || {};

  var cards = plates.map(function(p) {
    var isTarget = (p === targetPlate);
    var borderColor = isTarget ? '#ef4444' : 'rgba(255,255,255,.1)';
    var bgColor = isTarget ? 'rgba(239,68,68,.08)' : 'var(--bg2)';
    var imgUrl = imgs[p];
    var imgHtml = imgUrl
      ? '<img src="' + imgUrl + '" style="width:100%;height:100px;object-fit:cover;border-radius:6px;background:#111" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'" loading="lazy"><div style="display:none;width:100%;height:100px;align-items:center;justify-content:center;background:rgba(255,255,255,.04);border-radius:6px;color:var(--muted);font-size:.75rem">Sem imagem</div>'
      : '<div style="width:100%;height:100px;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.04);border-radius:6px;color:var(--muted);font-size:.75rem">&#128247; Sem imagem</div>';
    var alvoTag = alvos[p] ? ' <span class="badge badge-danger" style="font-size:.6rem">ALVO</span>' : '';
    var targetTag = isTarget ? '<div style="font-size:.62rem;text-transform:uppercase;color:#ef4444;font-weight:700;margin-bottom:3px">&#9733; VE\u00cdCULO PESQUISADO</div>' : '';

    return '<div style="border:2px solid ' + borderColor + ';border-radius:10px;padding:10px;background:' + bgColor + ';min-width:140px;max-width:200px;flex:1">'
      + targetTag
      + imgHtml
      + '<div style="margin-top:8px;text-align:center">'
      + plateHtml(p) + alvoTag
      + '</div>'
      + '<div style="text-align:center;margin-top:6px"><button class="btn btn-xs btn-outline" style="font-size:.68rem" onclick="openBatedorReport(\'' + p.replace(/'/g,"\\'") + '\')">&#128196; Detalhes</button></div>'
      + '</div>';
  });

  return '<div style="margin-bottom:18px">'
    + '<div style="font-size:.85rem;font-weight:700;color:var(--accent2);margin-bottom:8px">&#128101; Ve\u00edculos do Grupo (' + plates.length + ')</div>'
    + '<div style="display:flex;flex-wrap:wrap;gap:12px">' + cards.join('') + '</div>'
    + '</div>';
}

function _comboioRenderEvents(events, plates) {
  if (!events || !events.length) {
    return '<div style="background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.2);border-radius:8px;padding:12px;margin-bottom:18px;font-size:.82rem;color:#fde68a">'
      + '&#9888; Nenhuma c\u00e2mera com co-detec\u00e7\u00e3o confirmada do grupo neste per\u00edodo.</div>';
  }

  var ths = '<th style="text-align:left">C\u00e2mera</th>';
  plates.forEach(function(p) { ths += '<th style="text-align:center;min-width:90px">' + p + '</th>'; });
  ths += '<th style="text-align:center">\u0394 c\u00e2m.</th><th style="text-align:center">Gap m\u00e9d.</th>';

  var rows = events.map(function(ev, i) {
    var cls = (i % 2 === 0) ? '' : ' style="background:rgba(255,255,255,.02)"';
    var tr = '<tr' + cls + '><td style="font-weight:600;font-size:.82rem">' + (ev.camera_name || ev.camera_id) + '</td>';
    plates.forEach(function(p) {
      var ts = ev.timestamps[p];
      if (ts) {
        var dt = new Date(ts);
        tr += '<td style="text-align:center;font-size:.76rem;white-space:nowrap">' + dt.toLocaleString('pt-BR', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}) + '</td>';
      } else {
        tr += '<td style="text-align:center;color:var(--muted)">-</td>';
      }
    });
    var deltaColor = ev.delta_s <= 60 ? '#86efac' : ev.delta_s <= 180 ? '#fde68a' : '#fca5a5';
    tr += '<td style="text-align:center;font-weight:700;color:' + deltaColor + '">' + ev.delta_s + 's</td>';
    tr += '<td style="text-align:center;font-size:.8rem;color:var(--muted)">' + ev.avg_gap_s + 's</td>';
    tr += '</tr>';
    return tr;
  });

  return '<div style="margin-bottom:18px">'
    + '<div style="font-size:.85rem;font-weight:700;color:var(--accent2);margin-bottom:8px">&#128247; Eventos \u2014 Passaram Juntos (' + events.length + ' c\u00e2meras)</div>'
    + '<div class="table-wrap"><table><thead><tr>' + ths + '</tr></thead><tbody>' + rows.join('') + '</tbody></table></div>'
    + '</div>';
}

function _comboioRenderMetrics(metrics, events, plates) {
  // 4.1 Distância temporal por ponto
  var perPointRows = '';
  if (events && events.length) {
    events.forEach(function(ev) {
      perPointRows += '<tr><td style="font-size:.82rem">' + (ev.camera_name || ev.camera_id) + '</td>'
        + '<td style="text-align:center;font-weight:700">' + ev.delta_s + 's</td>'
        + '<td style="text-align:center">' + ev.avg_gap_s + 's</td></tr>';
    });
  }
  var perPointHtml = perPointRows
    ? '<div style="margin-bottom:12px"><div style="font-size:.8rem;font-weight:600;color:var(--muted);margin-bottom:6px">Dist\u00e2ncia temporal entre ve\u00edculos por ponto</div>'
      + '<div class="table-wrap"><table style="font-size:.82rem"><thead><tr><th>C\u00e2mera</th><th>Span</th><th>Gap m\u00e9d.</th></tr></thead><tbody>' + perPointRows + '</tbody></table></div></div>'
    : '';

  // 4.2 Média geral
  var tripHuman = metrics.trip_span_human || (Math.floor(metrics.trip_span_s/60) + 'm ' + (metrics.trip_span_s%60) + 's');

  return '<div style="margin-bottom:18px;background:var(--bg2);border-radius:10px;padding:14px 18px">'
    + '<div style="font-size:.85rem;font-weight:700;color:var(--accent2);margin-bottom:10px">&#128202; M\u00e9tricas do Comboio</div>'
    + '<div style="display:flex;flex-wrap:wrap;gap:18px;margin-bottom:14px">'
    + '<div style="text-align:center">'
    + '<div style="font-size:1.4rem;font-weight:700;color:var(--accent)">' + tripHuman + '</div>'
    + '<div style="font-size:.72rem;color:var(--muted);text-transform:uppercase">Dura\u00e7\u00e3o do percurso</div></div>'
    + '<div style="text-align:center">'
    + '<div style="font-size:1.4rem;font-weight:700;color:var(--accent2)">' + metrics.avg_gap_overall_s + 's</div>'
    + '<div style="font-size:.72rem;color:var(--muted);text-transform:uppercase">Gap m\u00e9dio geral</div></div>'
    + '<div style="text-align:center">'
    + '<div style="font-size:1.4rem;font-weight:700">' + metrics.total_cameras_confirmed + '</div>'
    + '<div style="font-size:.72rem;color:var(--muted);text-transform:uppercase">C\u00e2meras confirmadas</div></div>'
    + '<div style="text-align:center">'
    + '<div style="font-size:1.4rem;font-weight:700">' + metrics.total_vehicles + '</div>'
    + '<div style="font-size:.72rem;color:var(--muted);text-transform:uppercase">Ve\u00edculos</div></div>'
    + '</div>'
    + perPointHtml
    + '</div>';
}

function _comboioRenderTrajectorySection(traj) {
  var hasPoints = false;
  if (traj && traj.target && traj.target.points && traj.target.points.length) hasPoints = true;
  if (!hasPoints && traj && traj.partners) {
    traj.partners.forEach(function(p) { if (p.points && p.points.length) hasPoints = true; });
  }

  return '<div style="margin-bottom:18px">'
    + '<div style="font-size:.85rem;font-weight:700;color:var(--accent2);margin-bottom:8px">&#128506; Trajet\u00f3ria</div>'
    + (hasPoints
      ? '<div id="comboio-map-container" style="height:350px;border-radius:10px;border:1px solid rgba(255,255,255,.1);background:#111"></div>'
        + '<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:8px;align-items:center" id="comboio-map-toggles"></div>'
      : '<div style="background:rgba(255,255,255,.04);border-radius:10px;padding:20px;text-align:center;color:var(--muted);font-size:.82rem">&#128506; Sem dados GPS dispon\u00edveis para as c\u00e2meras deste per\u00edodo.</div>')
    + '</div>';
}

function _comboioInitMap(traj) {
  var container = document.getElementById('comboio-map-container');
  if (!container) return;

  // Limpar mapa anterior
  if (_comboioMap) { _comboioMap.remove(); _comboioMap = null; }
  _comboioMapLayers = [];

  _comboioMap = L.map(container, { zoomControl: true, scrollWheelZoom: true });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap',
    maxZoom: 18
  }).addTo(_comboioMap);

  var allLatLngs = [];
  var colors = ['#ef4444', '#3b82f6', '#22c55e', '#f59e0b', '#a855f7', '#ec4899'];
  var togglesEl = document.getElementById('comboio-map-toggles');
  var togglesHtml = '';

  // Desenhar target
  if (traj.target && traj.target.points && traj.target.points.length) {
    var pts = traj.target.points;
    var latlngs = pts.map(function(p) { return [p.lat, p.lon]; });
    allLatLngs = allLatLngs.concat(latlngs);
    var line = L.polyline(latlngs, { color: colors[0], weight: 3, opacity: 0.9 }).addTo(_comboioMap);
    _comboioMapLayers.push(line);

    // Marcadores
    pts.forEach(function(p, i) {
      var m = L.circleMarker([p.lat, p.lon], { radius: 6, color: colors[0], fillColor: colors[0], fillOpacity: 0.8, weight: 2 })
        .bindPopup('<strong>' + traj.target.plate + '</strong><br>' + (p.camera_name||p.camera_id) + '<br>' + fmtTs(p.ts))
        .addTo(_comboioMap);
      _comboioMapLayers.push(m);
      if (i === 0) {
        L.marker([p.lat, p.lon], { icon: L.divIcon({ html: '<div style="background:#ef4444;color:#fff;padding:2px 6px;border-radius:4px;font-size:.7rem;font-weight:700;white-space:nowrap">IN\u00cdCIO</div>', className: '' }) }).addTo(_comboioMap);
      }
      if (i === pts.length - 1) {
        L.marker([p.lat, p.lon], { icon: L.divIcon({ html: '<div style="background:#22c55e;color:#fff;padding:2px 6px;border-radius:4px;font-size:.7rem;font-weight:700;white-space:nowrap">FIM</div>', className: '' }) }).addTo(_comboioMap);
      }
    });
    togglesHtml += '<label style="font-size:.76rem;cursor:pointer;color:' + colors[0] + ';font-weight:700"><input type="checkbox" checked data-comboio-layer="target" onchange="_comboioToggleLayer(this)"> ' + traj.target.plate + ' (alvo)</label>';
  }

  // Desenhar partners
  if (traj.partners) {
    traj.partners.forEach(function(partner, idx) {
      if (!partner.points || !partner.points.length) return;
      var c = colors[(idx + 1) % colors.length];
      var pts = partner.points;
      var latlngs = pts.map(function(p) { return [p.lat, p.lon]; });
      allLatLngs = allLatLngs.concat(latlngs);
      var line = L.polyline(latlngs, { color: c, weight: 2.5, opacity: 0.7, dashArray: '8 4' }).addTo(_comboioMap);
      _comboioMapLayers.push(line);
      pts.forEach(function(p) {
        var m = L.circleMarker([p.lat, p.lon], { radius: 5, color: c, fillColor: c, fillOpacity: 0.7, weight: 1 })
          .bindPopup('<strong>' + partner.plate + '</strong><br>' + (p.camera_name||p.camera_id) + '<br>' + fmtTs(p.ts))
          .addTo(_comboioMap);
        _comboioMapLayers.push(m);
      });
      togglesHtml += '<label style="font-size:.76rem;cursor:pointer;color:' + c + ';font-weight:700;margin-left:8px"><input type="checkbox" checked data-comboio-layer="p' + idx + '" onchange="_comboioToggleLayer(this)"> ' + partner.plate + '</label>';
    });
  }

  if (togglesEl) togglesEl.innerHTML = togglesHtml;

  if (allLatLngs.length) {
    _comboioMap.fitBounds(allLatLngs, { padding: [30, 30] });
  }
  setTimeout(function(){ if (_comboioMap) _comboioMap.invalidateSize(); }, 200);
}

function _comboioToggleLayer(checkbox) {
  // Simplified toggle — redraws entirely
  if (!_comboioData || !_comboioData.trajectory) return;
  _comboioInitMap(_comboioData.trajectory);
}

function _comboioRenderActions(d) {
  var decLabels = { confirmado: '&#9989; Suspeito confirmado', falso_positivo: '&#10060; Falso positivo', ignorar: '&#9197; Ignorado' };
  var decBg = { confirmado: 'rgba(220,38,38,.2)', falso_positivo: 'rgba(34,197,94,.1)', ignorar: 'rgba(100,100,100,.15)' };
  var decBorder = { confirmado: 'rgba(220,38,38,.5)', falso_positivo: 'rgba(34,197,94,.3)', ignorar: 'rgba(120,120,120,.3)' };
  var lastDec = d.last_decision;

  var decHtml = '';
  if (lastDec) {
    decHtml = '<div style="background:' + (decBg[lastDec.decision]||decBg.ignorar) + ';border:1px solid ' + (decBorder[lastDec.decision]||decBorder.ignorar) + ';border-radius:7px;padding:8px 12px;margin-bottom:10px;font-size:.82rem">'
      + '<strong>' + (decLabels[lastDec.decision]||lastDec.decision) + '</strong>'
      + (lastDec.note ? ' \u2014 ' + lastDec.note : '')
      + ' <span style="color:var(--muted);font-size:.72rem">por ' + (lastDec.operator||'sistema') + ' em ' + fmtTs(lastDec.created_at) + '</span></div>';
  } else {
    decHtml = '<div style="font-size:.78rem;color:var(--muted);margin-bottom:8px">Nenhuma decis\u00e3o registrada ainda.</div>';
  }

  var platesJson = _json_escape(JSON.stringify(d.group.plates));
  var paramsJson = _json_escape(JSON.stringify(d.params));

  return '<div style="border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:14px 18px">'
    + '<div style="font-size:.85rem;font-weight:700;color:var(--accent2);margin-bottom:10px">&#128203; A\u00e7\u00f5es</div>'
    + decHtml
    + '<div style="display:flex;flex-wrap:wrap;gap:8px">'
    + '<button class="btn btn-sm" style="background:rgba(139,92,246,.7);color:#fff;font-size:.84rem;padding:10px 18px" onclick="_comboioAddAlvo(\'' + d.target_plate.replace(/'/g,"\\'") + '\')">&#127919; Cadastrar como Alvo</button>'
    + '<button class="btn btn-sm" style="background:rgba(220,38,38,.7);color:#fff;font-size:.84rem;padding:10px 18px" onclick="_comboioConfirm(\'' + d.target_plate.replace(/'/g,"\\'") + '\',' + platesJson + ',' + paramsJson + ')">&#9989; Confirmar Suspeito</button>'
    + '<button class="btn btn-sm" style="background:rgba(34,197,94,.5);color:#fff;font-size:.84rem;padding:10px 18px" onclick="_comboioFalsePositive(\'' + d.target_plate.replace(/'/g,"\\'") + '\',' + platesJson + ',' + paramsJson + ')">&#10060; Falso Positivo</button>'
    + '</div></div>';
}

function _json_escape(s) { return s.replace(/'/g, "\\'"); }

function _openComboioFromCentral(plate) {
  // Buscar parceiros da Central
  var item = (_cenAllItems || []).find(function(i) { return i.plate === plate; });
  var groupPlates = [plate];
  if (item && item.in_grupos && item.in_grupos.length) {
    item.in_grupos.forEach(function(g) {
      if (groupPlates.indexOf(g.plate) < 0) groupPlates.push(g.plate);
    });
  }
  if (groupPlates.length < 2) {
    // Fallback: abrir relatório normal
    openBatedorReport(plate);
    return;
  }
  var w = '1h';
  try { w = document.getElementById('cen-window').value || '1h'; } catch(e){}
  openComboioReport(plate, groupPlates, { window: w });
}

async function _comboioConfirm(plate, groupPlates, params) {
  var note = prompt('Observa\u00e7\u00e3o (opcional):', '');
  if (note === null) return;
  try {
    var resp = await fetch('/api/comboio/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_plate: plate, group_plates: groupPlates, params: params, note: note })
    });
    if (!resp.ok) { var err = await resp.json().catch(function(){return {};}); alert('Erro: ' + (err.detail||resp.status)); return; }
    _flashMsg('&#9989; Comboio de ' + plate + ' confirmado!', '#dc2626');
    // Recarregar
    if (_comboioData) loadComboioReport(plate, _comboioData.group.plates, { window_s: _comboioData.params.window_s, max_trip_gap_s: _comboioData.params.max_trip_gap_s });
  } catch(e) { alert('Erro: ' + e.message); }
}

async function _comboioFalsePositive(plate, groupPlates, params) {
  var note = prompt('Motivo do falso positivo (opcional):', '');
  if (note === null) return;
  try {
    var resp = await fetch('/api/comboio/false_positive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_plate: plate, group_plates: groupPlates, params: params, note: note })
    });
    if (!resp.ok) { var err = await resp.json().catch(function(){return {};}); alert('Erro: ' + (err.detail||resp.status)); return; }
    _flashMsg('&#10060; Comboio de ' + plate + ' marcado como falso positivo.', '#22c55e');
    if (_comboioData) loadComboioReport(plate, _comboioData.group.plates, { window_s: _comboioData.params.window_s, max_trip_gap_s: _comboioData.params.max_trip_gap_s });
  } catch(e) { alert('Erro: ' + e.message); }
}

async function _comboioAddAlvo(plate) {
  var desc = prompt('Descri\u00e7\u00e3o para o alvo (opcional):', 'Alvo de comboio');
  if (desc === null) return;
  try {
    var resp = await fetch('/api/alvos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plate: plate, descricao: desc || 'Alvo de comboio' })
    });
    if (!resp.ok) { var err = await resp.json().catch(function(){return {};}); alert('Erro: ' + (err.detail||resp.status)); return; }
    _flashMsg('&#127919; ' + plate + ' cadastrado como Alvo!', '#6d28d9');
    if (_comboioData) loadComboioReport(plate, _comboioData.group.plates, { window_s: _comboioData.params.window_s, max_trip_gap_s: _comboioData.params.max_trip_gap_s });
  } catch(e) { alert('Erro: ' + e.message); }
}

// ===== LISTAS =====
const API_VEHICLE_LISTS = '/api/vehicles/lists';

async function fetchVehicleLists() {
  try {
    console.log('[Veículos] Chamando endpoint:', API_VEHICLE_LISTS);
    var r = await fetch(API_VEHICLE_LISTS);
    
    console.log('[Veículos] Status HTTP:', r.status);
    
    // Verificar autenticação
    if (r.status === 401) {
      throw new Error('Sessão expirada — faça login novamente');
    }
    
    if (r.status === 403) {
      throw new Error('Acesso negado a listas de veículos');
    }
    
    if (!r.ok) {
      throw new Error('Erro ' + r.status + ' ao carregar listas');
    }
    
    var d = null;
    try {
      d = await r.json();
    } catch (parseErr) {
      console.error('[Veículos] Erro ao parsear JSON:', parseErr);
      throw new Error('Resposta inválida do servidor (JSON malformado)');
    }
    
    console.log('[Veículos] Resposta recebida:', d);
    
    // Validar estrutura da resposta
    if (!d || typeof d !== 'object') {
      console.error('[Veículos] Resposta não é um objeto:', d);
      throw new Error('Formato de resposta inválido');
    }
    
    var items = d.items || [];
    if (!Array.isArray(items)) {
      console.error('[Veículos] Campo "items" não é um array:', items);
      throw new Error('Estrutura de resposta inválida (items não é array)');
    }
    
    console.log('[Veículos] Carregadas ' + items.length + ' lista(s)');
    return items;
  } catch(err) {
    console.error('[Veículos] Erro em fetchVehicleLists:', err.message);
    throw err;
  }
}

async function loadLists() {
  var listGrid = document.getElementById('lists-grid');
  try {
    // Mostrar estado de carregamento inicial
    listGrid.innerHTML = '<div class="empty-state"><div class="icon">&#128193;</div>Carregando listas...</div>';
    
    listsCache = await fetchVehicleLists();
    console.log('[Veículos] loadLists() sucesso, renderizando', listsCache.length, 'lista(s)');
    renderLists(listsCache);
  } catch(err) {
    console.error('[Veículos] Erro em loadLists():', err.message);
    
    var errorMsg = err.message || 'Erro desconhecido ao carregar listas';
    var errorHtml = '<div class="empty-state" style="color:#ef4444">' +
      '<div class="icon">⚠️</div>' +
      '<div style="font-weight:600;margin-top:8px">' + errorMsg + '</div>' +
      '<small style="margin-top:6px;display:block;color:var(--muted);opacity:.8">Verifique o console (F12) para mais detalhes</small>' +
      '<button class="btn btn-outline btn-xs" onclick="loadLists()" style="margin-top:10px">🔄 Tentar novamente</button>' +
      '</div>';
    listGrid.innerHTML = errorHtml;
  } finally {
    // Garantir que o spinner nunca fica preso
    console.log('[Veículos] loadLists() finalizado');
  }
}

function renderLists(lists) {
  var g = document.getElementById('lists-grid');
  
  if (!lists || !Array.isArray(lists)) {
    console.error('[Veículos] renderLists recebeu valor inválido:', lists);
    g.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div>Erro ao renderizar listas (dados inválidos)</div>';
    return;
  }
  
  if (lists.length === 0) {
    console.log('[Veículos] Nenhuma lista encontrada');
    g.innerHTML = '<div class="empty-state"><div class="icon">📋</div>Nenhuma lista criada ainda.<br><small style="margin-top:6px;display:block;opacity:.7">Clique em "+ Nova Lista" para começar.</small></div>';
    return;
  }
  
  console.log('[Veículos] Renderizando', lists.length, 'lista(s)');
  
  try {
    g.innerHTML = lists.map(function(l) {
      if (!l || typeof l !== 'object' || !l.id || !l.name) {
        console.warn('[Veículos] Item de lista inválido:', l);
        return ''; // Ignorar item inválido
      }
      
      return '<div class="list-card" onclick="goToCadastro(' + l.id + ')">' +
        '<div class="list-card-actions">' +
          '<button class="btn btn-outline btn-xs" onclick="event.stopPropagation();importListToAlvos(' + l.id + ',\'' + l.name.replace(/'/g,"\\'") + '\')" title="Enviar todas as placas para Alvos Rastreados" style="color:#a78bfa;border-color:rgba(167,139,250,.45)">&#127919; Alvos</button>' +
          '<button class="btn btn-outline btn-xs" onclick="event.stopPropagation();openListModal(' + l.id + ')" title="Editar nome">&#9998; Editar</button>' +
          '<button class="btn btn-danger btn-xs" onclick="event.stopPropagation();deleteList(' + l.id + ',\'' + l.name.replace(/'/g,"\\'") + '\')" title="Excluir">&#128465; Excluir</button>' +
        '</div>' +
        '<div><span class="list-card-name" style="font-size:.94rem">' + (l.name || 'Lista sem nome') + '</span></div>' +
        '<div style="margin-top:10px">' +
          '<div class="list-card-count">' + (l.vehicle_count || 0) + ' veiculo(s)</div>' +
        '</div>' +
        '</div>';
    }).join('');
  } catch(err) {
    console.error('[Veículos] Erro ao renderizar listas:', err);
    g.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div>Erro ao exibir listas</div>';
  }
}

async function importListToAlvos(listId, listName) {
  if (!confirm('Enviar todas as placas da lista "' + listName + '" para Alvos Rastreados?\n\nAs placas já cadastradas terão a descrição atualizada.')) return;
  try {
    var resp = await fetch('/api/alvos/import-list/' + listId, { method: 'POST',
      headers: { 'Content-Type': 'application/json' } });
    var data = await resp.json();
    if (!resp.ok) { alert('Erro: ' + (data.detail || resp.status)); return; }
    alert('\u2705 ' + data.total + ' placa(s) da lista "' + data.list_name + '" enviadas para Alvos Rastreados!');
    // Se estiver na aba batedor/alvos, recarrega
    var alvoPane = document.getElementById('bat-sub-alvos');
    if (alvoPane && alvoPane.classList.contains('active')) loadAlvos();
  } catch(e) {
    alert('Erro ao importar: ' + e);
  }
}

function goToCadastro(listId) {
  openListDetail(listId);
}

var _currentDetailListId = null;

function openListDetail(listId) {
  _currentDetailListId = listId;
  var l = listsCache.find(function(x){ return x.id === listId; });
  document.getElementById('list-detail-name').textContent = l ? l.name : 'Lista #' + listId;
  document.getElementById('list-detail-search').value = '';
  document.getElementById('view-listas').style.display = 'none';
  document.getElementById('view-list-detail').style.display = 'block';
  loadListVehicles();
}

function backToLists() {
  _currentDetailListId = null;
  document.getElementById('view-list-detail').style.display = 'none';
  document.getElementById('view-listas').style.display = 'block';
  loadLists();
}

function openListModal(id) {
  editListId = id || null;
  document.getElementById('list-modal-title').textContent = id ? 'Editar Lista' : 'Nova Lista';
  document.getElementById('list-form-error').textContent = '';
  if (id) {
    var l = listsCache.find(function(x){ return x.id === id; });
    if (l) {
      document.getElementById('list-name').value = l.name;
    }
  } else {
    document.getElementById('list-name').value = '';
  }
  openModal('list-modal');
  setTimeout(function(){ document.getElementById('list-name').focus(); }, 80);
}

async function saveList() {
  var name = document.getElementById('list-name').value.trim();
  var errEl = document.getElementById('list-form-error');
  if (!name) { errEl.textContent = 'O nome e obrigatorio.'; return; }
  errEl.textContent = '';
  try {
    var method = editListId ? 'PUT' : 'POST';
    var url    = editListId ? API_VEHICLE_LISTS + '/' + editListId : API_VEHICLE_LISTS;
    var r = await fetch(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name })
    });
    if (!r.ok) { var d = await r.json(); throw new Error(d.detail || r.status); }
    closeModal('list-modal');
    await Promise.all([loadLists(), loadMonPlates()]);
  } catch(e) {
    errEl.textContent = 'Erro: ' + e.message;
  }
}

async function deleteList(id, name) {
  if (!confirm('Excluir a lista "' + name + '"?\nTodos os veiculos da lista tambem serao removidos.')) return;
  await fetch(API_VEHICLE_LISTS + '/' + id, { method: 'DELETE' });
  await Promise.all([loadLists(), loadMonPlates()]);
}

// ===== VEICULOS DENTRO DA LISTA =====
async function loadListVehicles() {
  if (!_currentDetailListId) return;
  var plate = document.getElementById('list-detail-search').value.trim();
  var p = new URLSearchParams();
  p.set('list_id', _currentDetailListId);
  if (plate) p.set('plate', plate);
  try {
    var r = await fetch('/api/vehicles?' + p);
    var d = await r.json();
    var items = d.items || [];
    renderListVehicles(items);
    document.getElementById('list-detail-status').textContent = items.length + ' veiculo(s)';
    document.getElementById('list-detail-count').textContent = items.length + ' veiculo(s) cadastrado(s)';
  } catch(e) {
    document.getElementById('list-detail-tbody').innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:24px">Erro: ' + e.message + '</td></tr>';
  }
}

function renderListVehicles(items) {
  var tb = document.getElementById('list-detail-tbody');
  if (!items.length) {
    tb.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:32px">Nenhum veiculo cadastrado nesta lista.<br><small style="opacity:.7;margin-top:6px;display:block">Clique em "+ Adicionar Placa" para comecar.</small></td></tr>';
    return;
  }
  var temaAtual = normalizeThemeName(document.documentElement.getAttribute('data-theme'));
  var isTemaBranco = (temaAtual === 'branco');
  tb.innerHTML = items.map(function(v) {
    var isAlvo = !!v.is_alvo;
    var plateBadge = isAlvo
      ? ' <span style="display:inline-block;background:rgba(220,38,38,.18);color:#fca5a5;padding:1px 6px;font-size:.68rem;border-radius:4px;font-weight:700;letter-spacing:.04em;vertical-align:middle">ALVO</span>'
      : '';
    var rowStyle = (!isTemaBranco && isAlvo) ? ' style="background:rgba(220,38,38,.055)"' : '';
    var alvoToggleBtn = isAlvo
      ? ''
      : '<button class="btn btn-outline btn-xs" onclick="toggleVehicleAlvo(' + v.id + ',\'' + v.plate.replace(/'/g,"\\'") + '\',false)" title="Marcar como alvo" style="border-color:rgba(239,68,68,.4);color:#fca5a5">&#127919; Tornar Alvo</button>';
    var visualizarBtn = '<button class="btn btn-outline btn-xs" onclick="openViewVehicleModal(' + v.id + ')" title="Visualizar">&#128269; Visualizar</button>';
    var editarBtn = '<button class="btn btn-outline btn-xs" onclick="openEditVehicleModal(' + v.id + ')" title="Editar">&#9998; Editar</button>';
    var excluirBtn = '<button class="btn btn-danger btn-xs" onclick="deleteVehicle(' + v.id + ',\'' + v.plate.replace(/'/g,"\\'") + '\')" title="Excluir">&#128465; Excluir</button>';
    return '<tr data-vid="' + v.id + '" data-plate="' + v.plate.replace(/"/g,'&quot;') + '" data-notes="' + (v.notes||'').replace(/"/g,'&quot;') + '" data-is-alvo="' + (isAlvo ? '1' : '0') + '"' + rowStyle + '>' +
      '<td style="color:var(--muted);font-size:.74rem">' + v.id + '</td>' +
      '<td><span style="font-size:.88rem;font-weight:700;letter-spacing:.04em">' + v.plate + '</span>' + plateBadge + '</td>' +
      '<td style="font-size:.79rem;color:var(--muted)">' + (v.notes||'-') + '</td>' +
      '<td style="text-align:center">' + (isAlvo ? '<span style="color:#fca5a5;font-size:.75rem">&#127919;</span>' : '<span style="color:var(--muted);font-size:.75rem">&mdash;</span>') + '</td>' +
      '<td style="font-size:.76rem;color:var(--muted)">' + fmtTs(v.created_at) + '</td>' +
      '<td class="action-cell">' +
        '<div class="action-buttons">' +
          alvoToggleBtn + ' ' +
          visualizarBtn + ' ' +
          editarBtn + ' ' +
          excluirBtn +
        '</div>' +
      '</td>' +
      '</tr>';
  }).join('');
}

function setVehicleModalReadOnly(readOnly) {
  var plate = document.getElementById('veh-plate');
  var notes = document.getElementById('veh-notes');
  var alvo = document.getElementById('veh-is-alvo');
  var saveBtn = document.getElementById('veh-save-btn');
  if (plate) plate.disabled = !!readOnly;
  if (notes) notes.disabled = !!readOnly;
  if (alvo) alvo.disabled = !!readOnly;
  if (saveBtn) saveBtn.style.display = readOnly ? 'none' : '';
}

function openAddVehicleModal(opts) {
  opts = opts || {};
  _editVehicleId = null;
  setVehicleModalReadOnly(false);
  document.getElementById('veh-plate').value = (opts.plate || '').toUpperCase();
  document.getElementById('veh-notes').value = opts.notes || '';
  document.getElementById('veh-is-alvo').checked = !!opts.isAlvo;
  document.getElementById('veh-form-error').textContent = '';
  document.getElementById('veh-list-id').value = opts.listId || _currentDetailListId || '';
  document.getElementById('veh-modal-title').textContent = 'Cadastrar Placa';
  document.getElementById('veh-save-btn').textContent = 'Cadastrar';
  openModal('vehicle-modal');
  setTimeout(function(){ document.getElementById('veh-plate').focus(); }, 80);
}

async function toggleVehicleAlvo(vehicleId, plate, currentIsAlvo) {
  var newAlvo = !currentIsAlvo;
  try {
    var r = await fetch('/api/vehicles/' + vehicleId, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_alvo: newAlvo })
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    var msg = newAlvo
      ? '\u2713 Placa ' + plate + ' marcada como alvo'
      : '\u2713 Placa ' + plate + ' removida dos alvos';
    var stEl = document.getElementById('list-detail-status');
    if (stEl) {
      stEl.textContent = msg;
      stEl.style.color = newAlvo ? '#fca5a5' : 'var(--muted)';
      setTimeout(function(){ if(stEl.textContent===msg){ stEl.textContent=''; stEl.style.color=''; } }, 4000);
    }
    loadListVehicles();
    if (typeof loadAlvos === 'function') loadAlvos();
  } catch(e) {
    var stEl = document.getElementById('list-detail-status');
    if (stEl) { stEl.textContent = 'Erro ao atualizar: ' + e.message; stEl.style.color = 'var(--danger)'; }
  }
}

async function openEditVehicleModal(vehicleId) {
  var rows = document.querySelectorAll('#list-detail-tbody tr[data-vid]');
  var vehicleData = null;
  for (var i = 0; i < rows.length; i++) {
    if (parseInt(rows[i].getAttribute('data-vid')) === vehicleId) {
      vehicleData = {
        id: vehicleId,
        plate: rows[i].getAttribute('data-plate') || '',
        notes: rows[i].getAttribute('data-notes') || '',
        is_alvo: rows[i].getAttribute('data-is-alvo') === '1'
      };
      break;
    }
  }
  if (!vehicleData) return;
  
  _editVehicleId = vehicleId;
  setVehicleModalReadOnly(false);
  document.getElementById('veh-plate').value = vehicleData.plate;
  document.getElementById('veh-notes').value = vehicleData.notes;
  document.getElementById('veh-is-alvo').checked = vehicleData.is_alvo;
  document.getElementById('veh-form-error').textContent = '';
  document.getElementById('veh-list-id').value = _currentDetailListId || '';
  document.getElementById('veh-modal-title').textContent = 'Editar Placa';
  document.getElementById('veh-save-btn').textContent = 'Salvar';
  openModal('vehicle-modal');
  setTimeout(function(){ document.getElementById('veh-plate').focus(); }, 80);
}

async function openViewVehicleModal(vehicleId) {
  var rows = document.querySelectorAll('#list-detail-tbody tr[data-vid]');
  var vehicleData = null;
  for (var i = 0; i < rows.length; i++) {
    if (parseInt(rows[i].getAttribute('data-vid')) === vehicleId) {
      vehicleData = {
        id: vehicleId,
        plate: rows[i].getAttribute('data-plate') || '',
        notes: rows[i].getAttribute('data-notes') || '',
        is_alvo: rows[i].getAttribute('data-is-alvo') === '1'
      };
      break;
    }
  }
  if (!vehicleData) return;

  _editVehicleId = null;
  setVehicleModalReadOnly(true);
  document.getElementById('veh-plate').value = vehicleData.plate;
  document.getElementById('veh-notes').value = vehicleData.notes;
  document.getElementById('veh-is-alvo').checked = vehicleData.is_alvo;
  document.getElementById('veh-form-error').textContent = '';
  document.getElementById('veh-list-id').value = _currentDetailListId || '';
  document.getElementById('veh-modal-title').textContent = 'Visualizar Placa';
  openModal('vehicle-modal');
}

async function saveVehicle() {
  var plate  = document.getElementById('veh-plate').value.trim().toUpperCase();
  var listId = document.getElementById('veh-list-id').value;
  var notes  = document.getElementById('veh-notes').value.trim();
  var isAlvo = document.getElementById('veh-is-alvo').checked;
  var errEl  = document.getElementById('veh-form-error');
  var targetFlow = _vehicleTargetFlow;
  if (!plate)  { errEl.textContent = 'Placa é obrigatória.'; return; }
  if (!listId) { errEl.textContent = 'Erro: lista não identificada.'; return; }
  errEl.textContent = '';
  try {
    var method, url, bodyObj;
    if (_editVehicleId) {
      method  = 'PUT';
      url     = '/api/vehicles/' + _editVehicleId;
      bodyObj = { plate: plate, notes: notes || null, is_alvo: isAlvo };
    } else {
      method  = 'POST';
      url     = '/api/vehicles';
      bodyObj = { plate: plate, list_id: parseInt(listId), notes: notes || null, is_alvo: isAlvo };
    }
    var bodyStr = JSON.stringify(bodyObj);

    var r = await fetch(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: bodyStr
    });
    var responseData = await r.json();

    if (!r.ok) { throw new Error(responseData.detail || r.status); }

    closeModal('vehicle-modal');
    _vehicleTargetFlow = null;

    // Limpa o formulário após salvar com sucesso
    _editVehicleId = null;
    document.getElementById('veh-plate').value = '';
    document.getElementById('veh-notes').value = '';
    document.getElementById('veh-is-alvo').checked = false;
    document.getElementById('veh-form-error').textContent = '';
    document.getElementById('veh-modal-title').textContent = 'Cadastrar Placa';
    document.getElementById('veh-save-btn').textContent = 'Cadastrar';

    // Atualiza TODAS as listas relevantes; allSettled garante que falha em
    // uma não impede as outras de rodarem.
    var reloads = await Promise.allSettled([
      loadListVehicles(),
      loadMonPlates(),
      loadLists(),
      typeof loadAlvos === 'function' ? loadAlvos() : Promise.resolve()
    ]);
    reloads.forEach(function(res, idx) {
      if (res.status === 'rejected') {
        console.warn('[vehicle:save] reload[' + idx + '] falhou:', res.reason);
      }
    });

    // Feedback visual de sucesso
    if (isAlvo && targetFlow && typeof targetFlow.restore === 'function') {
      try {
        await targetFlow.restore();
      } catch (restoreErr) {
        console.warn('[vehicle:save] restore alvo falhou:', restoreErr);
      }
      _flashMsg(targetFlow.message || ('🎯 ' + plate + ' salvo nos Alvos Rastreados!'), '#22c55e');
    } else if (isAlvo) {
      _flashMsg('🎯 ' + plate + ' salvo nos Alvos Rastreados!', '#22c55e');
    } else {
      _flashMsg('✅ Veículo ' + plate + ' salvo com sucesso!', '#2563eb');
    }
  } catch(e) {
    errEl.textContent = 'Erro: ' + e.message;
  }
}

async function deleteVehicle(id, plate) {
  if (!confirm('Remover "' + plate + '" da lista?')) return;
  await fetch('/api/vehicles/' + id, { method: 'DELETE' });
  await Promise.all([loadListVehicles(), loadMonPlates(), loadLists(),
    typeof loadAlvos === 'function' ? loadAlvos() : Promise.resolve()]);
}

// ===== RELOGIO =====
setInterval(function() {
  var el = document.getElementById('sb-clock');
  if (el) el.textContent = new Date().toLocaleString('pt-BR', {
    day:'2-digit', month:'2-digit', year:'numeric',
    hour:'2-digit', minute:'2-digit', second:'2-digit'
  });
}, 1000);

// ===== AUTO-REFRESH (configurável) =====
var _refreshIntervalId = null;
function _startAutoRefresh() {
  if (_refreshIntervalId) clearInterval(_refreshIntervalId);
  var ms = parseInt(localStorage.getItem('bpfron_refresh_interval') || '15000');
  if (ms > 0) {
    _refreshIntervalId = setInterval(function() {
      if (currentTab === 'eventos') loadEvents(); // sem argumento: preserva modo incremental
    }, ms);
  }
}
_startAutoRefresh();

// ===== ALARME BACKGROUND (independente de aba) =====
// Roda a cada 15s sempre que o alarme estiver ATIVO.
// Busca apenas os últimos 30 eventos, compara com monPlates,
// e dispara triggerAlarm sem tocar na UI da aba Eventos.
var _bgAlarmIntervalId = null;
var _bgAlarmMaxId      = 0;   // maior ID já visto pelo poller

async function _bgAlarmTick() {
  try {
    var r = await fetch('/api/events?limit=30&offset=0');
    if (!r.ok) return;
    var data = await r.json();
    var items = data.items || [];
    if (!items.length) return;

    // Na primeira execução inicializa o cursor com o maior ID atual
    // para não disparar alarme para eventos antigos
    if (_bgAlarmMaxId === 0) {
      _bgAlarmMaxId = Math.max.apply(null, items.map(function(e){ return e.id; }));
      return;
    }

    var alarmed = new Set();
    items.forEach(function(ev) {
      if (ev.id <= _bgAlarmMaxId) return;           // já visto
      var pm = ev.plate && monPlates[ev.plate.toUpperCase()];
      if (pm && !alarmed.has(ev.plate)) {
        alarmed.add(ev.plate);
        triggerAlarm(ev.plate, pm, ev.direcao || null);
      }
    });

    // Avança o cursor
    var maxNow = Math.max.apply(null, items.map(function(e){ return e.id; }));
    if (maxNow > _bgAlarmMaxId) _bgAlarmMaxId = maxNow;

  } catch(e) { /* silencioso — não interrompe o loop */ }
}

function _startBgAlarm() {
  _stopBgAlarm();
  _bgAlarmMaxId = 0;   // força re-inicialização do cursor na próxima tick
  _bgAlarmTick();      // primeira execução imediata (só inicializa cursor)
  _bgAlarmIntervalId = setInterval(_bgAlarmTick, 15000);
}

function _stopBgAlarm() {
  if (_bgAlarmIntervalId) { clearInterval(_bgAlarmIntervalId); _bgAlarmIntervalId = null; }
}

// ===== ALVOS RASTREADOS =====

function _alvoRepWindowChange() {
  var v = (document.getElementById('alvo-rep-window') || {}).value || '';
  var dr = document.getElementById('alvo-rep-date-row');
  if (dr) dr.style.display = v === 'custom' ? 'flex' : 'none';
}

function _restoreAlvoRepFilters() {
  try {
    var raw = localStorage.getItem('alvoRepFilters');
    if (!raw) return;
    var f = JSON.parse(raw);
    var map = {
      'alvo-rep-window':      f.window   || '',
      'alvo-rep-camera':      f.camera_id || '',
      'alvo-rep-direction':   f.direction || '',
      'alvo-rep-confidence':  f.min_confidence ? ratioToPercentInput(f.min_confidence, '') : '',
      'alvo-rep-min-cameras': f.min_cameras    ? String(f.min_cameras)   : '',
      'alvo-rep-vtype':       f.vehicle_type   || '',
      'alvo-rep-vcolor':      f.vehicle_color  || ''
    };
    Object.keys(map).forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.value = map[id];
    });
    if (f.ts_from) { var el = document.getElementById('alvo-rep-ts-from'); if (el) el.value = f.ts_from; }
    if (f.ts_to)   { var el = document.getElementById('alvo-rep-ts-to');   if (el) el.value = f.ts_to; }
  } catch(e) { /* silencioso */ }
}

function _updateAlvoRepFilterBadge() {
  /* placeholder — badge visual de filtros ativos (sem elemento dedicado no DOM ainda) */
}

function _applyAlvoRepFilters() {
  var f = _getAlvoRepFilters();
  try { localStorage.setItem('alvoRepFilters', JSON.stringify(f)); } catch(e){}
  _updateAlvoRepFilterBadge();
  var btn = document.getElementById('alvo-rep-apply-btn');
  if (btn) {
    var orig = btn.innerHTML;
    btn.innerHTML = '&#10003; Filtros salvos!';
    btn.disabled = true;
    setTimeout(function(){ btn.innerHTML = orig; btn.disabled = false; }, 1800);
  }
}

function _resetCenFilters() {
  var plate = document.getElementById('cen-filter-plate');
  if (plate) plate.value = '';
  var win = document.getElementById('cen-window');
  if (win) { win.value = '1h'; cenWindowChange(); }
  var minCam = document.getElementById('cen-min-cameras');
  if (minCam) minCam.value = '2';
  var interval = document.getElementById('cen-interval');
  if (interval) interval.value = '60';
  var gs = document.getElementById('cen-gsizes');
  if (gs) gs.value = '2';
  var cowin = document.getElementById('cen-cowin');
  if (cowin) cowin.value = '300';
  var om = document.getElementById('cen-ordermode');
  if (om) { om.value = 'any'; cenOrderModeChange(); }
  var lr = document.getElementById('cen-leader-ratio');
  if (lr) lr.value = '70';
  var pm = document.getElementById('cen-payload-max');
  if (pm) pm.value = '0';
  var risco = document.getElementById('cen-risco');
  if (risco) risco.value = '';
}

var _alvoRepSavedCamera = null;

function _getAlvoRepFilters() {
  var w  = (document.getElementById('alvo-rep-window')      || {}).value || '2h';
  var tsFrom = null, tsTo = null;
  if (w === 'custom') {
    tsFrom = (document.getElementById('alvo-rep-ts-from') || {}).value || null;
    tsTo   = (document.getElementById('alvo-rep-ts-to')   || {}).value || null;
    if (!tsFrom || !tsTo) w = '24h'; // fallback se não preenchido
  }
  var camEl   = document.getElementById('alvo-rep-camera');
  var dirEl   = document.getElementById('alvo-rep-direction');
  var confEl  = document.getElementById('alvo-rep-confidence');
  var minCEl  = document.getElementById('alvo-rep-min-cameras');
  var vtypeEl = document.getElementById('alvo-rep-vtype');
  var vcolorEl= document.getElementById('alvo-rep-vcolor');
  return {
    window:         (w !== 'custom') ? w : null,
    ts_from:        tsFrom,
    ts_to:          tsTo,
    camera_id:      camEl   ? (camEl.value   || null) : null,
    direction:      dirEl   ? (dirEl.value   || null) : null,
    min_confidence: confEl  ? percentInputToRatio(confEl.value, 0) : 0,
    min_cameras:    minCEl  ? (parseInt(minCEl.value, 10) || 0) : 0,
    vehicle_type:   vtypeEl ? (vtypeEl.value  || null) : null,
    vehicle_color:  vcolorEl? (vcolorEl.value || null) : null,
  };
}

async function _loadAlvoCameras() {
  _restoreAlvoRepFilters();
  var sel = document.getElementById('alvo-rep-camera');
  if (!sel) return;
  try {
    var resp = await fetch('/api/cameras');
    if (!resp.ok) return;
    var data = await resp.json();
    var cameras = data.cameras || data.items || data || [];
    var current = sel.value || _alvoRepSavedCamera || '';
    sel.innerHTML = '<option value="">&#8212; Todas &#8212;</option>';
    cameras.forEach(function(c) {
      var id   = c.camera_id || c.id || '';
      var nome = c.nome || c.name || id;
      var opt  = document.createElement('option');
      opt.value       = id;
      opt.textContent = nome;
      if (id === current) opt.selected = true;
      sel.appendChild(opt);
    });
    _alvoRepSavedCamera = null;
  } catch(e) { /* silencioso */ }
}

async function loadAlvos() {
  var tb = document.getElementById('alvos-tbody');
  var st = document.getElementById('alvos-status');
  if (!tb) return;
  tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:32px"><span class="spinner"></span></td></tr>';
  if (st) st.innerHTML = '<span class="spinner"></span>';
  try {
    var resp = await fetch('/api/alvos');
    var data = await resp.json();
    var alvos = data.alvos || [];
    // atualiza cards
    var totalEl   = document.getElementById('alvo-total');
    var recenteEl = document.getElementById('alvo-recente');
    var antigoEl  = document.getElementById('alvo-antigo');
    if (totalEl)   totalEl.textContent   = alvos.length || '0';
    if (recenteEl) recenteEl.textContent = alvos.length ? new Date(alvos[0].created_at).toLocaleDateString('pt-BR') : '—';
    if (antigoEl)  antigoEl.textContent  = alvos.length ? new Date(alvos[alvos.length-1].created_at).toLocaleDateString('pt-BR') : '—';
    document.getElementById('alvo-com-comp').textContent = '—';
    if (st) st.textContent = alvos.length + ' alvo(s)';
    if (alvos.length === 0) {
      tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:40px">Nenhum alvo cadastrado. Adicione uma placa acima para come&ccedil;ar o rastreamento.</td></tr>';
      return;
    }
    var _role = window._authRole || 'visualizador';
    tb.innerHTML = alvos.map(function(a) {
      var desde   = new Date(a.created_at).toLocaleDateString('pt-BR');
      var descEsc = (a.descricao || '').replace(/'/g, "&#39;");
      var lastSeen = (function() {
        if (!a.last_seen) return '<span style="color:var(--muted);font-size:.78rem">&#8212;</span>';
        var d   = new Date(a.last_seen);
        var now = new Date();
        var dtStr = d.toLocaleString('pt-BR', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
        var sameDay = d.getFullYear()===now.getFullYear() && d.getMonth()===now.getMonth() && d.getDate()===now.getDate();
        var diffH   = (now - d) / 3600000;
        if (sameDay) {
          return '<span style="display:inline-flex;align-items:center;gap:5px">'
            + '<span style="background:#16a34a;color:#fff;font-size:.65rem;font-weight:800;padding:2px 6px;border-radius:99px;letter-spacing:.04em">HOJE</span>'
            + '<span style="color:#4ade80;font-weight:600;font-size:.78rem">' + d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'}) + '</span>'
            + '</span>';
        } else if (diffH <= 48) {
          return '<span style="color:#fbbf24;font-size:.78rem" title="' + dtStr + '">&#128308; ontem &nbsp;' + d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'}) + '</span>';
        } else if (diffH <= 168) {
          return '<span style="color:var(--muted);font-size:.78rem" title="' + dtStr + '">&#128997; ' + dtStr + '</span>';
        } else {
          return '<span style="color:var(--muted);font-size:.78rem">' + dtStr + '</span>';
        }
      })();
      // Botões de ação por perfil
      var btnVer    = '<button class="btn btn-outline btn-xs" onclick="alvoVer(' + a.id + ',&#39;' + a.plate + '&#39;,&#39;' + descEsc + '&#39;,&#39;' + desde + '&#39;)" title="Visualizar alvo">&#128269; Visualizar</button>';
      var btnEditar = (_role === 'admin' || _role === 'operador')
        ? '<button class="btn btn-outline btn-xs" onclick="alvoEditar(' + a.id + ',&#39;' + a.plate + '&#39;,&#39;' + descEsc + '&#39;)" title="Editar alvo">&#9998; Editar</button>'
        : '';
      var btnApagar = (_role === 'admin')
        ? '<button class="btn btn-danger btn-xs" onclick="alvoApagar(' + a.id + ',&#39;' + a.plate + '&#39;)" title="Excluir alvo">&#128465; Excluir</button>'
        : '';
      var descTxt   = (a.descricao || '').trim();
      var descTitle = descTxt.replace(/"/g, '&quot;');
      var descCell  = descTxt
        ? '<span title="' + descTitle + '" style="display:block;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + descTxt + '</span>'
        : '<span style="color:var(--muted)">&#8212;</span>';
      return '<tr id="alvo-card-' + a.id + '">'
        + '<td>' + plateHtml(a.plate) + '</td>'
        + '<td style="color:var(--muted);max-width:260px">' + descCell + '</td>'
        + '<td style="white-space:nowrap;color:var(--muted);font-size:.78rem">' + desde + '</td>'
        + '<td style="white-space:nowrap;font-size:.78rem">' + lastSeen + '</td>'
        + '<td class="action-cell"><div class="action-buttons">' + btnVer + btnEditar + btnApagar + '</div></td>'
        + '</tr>';
    }).join('');
  } catch(e) {
    tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--danger);padding:24px">Erro: ' + e + '</td></tr>';
    if (st) st.textContent = 'Erro';
  }
}

function _fmtDelta(s) {
  s = Math.round(s);
  if (s < 60) return s + ' s';
  var m = Math.floor(s / 60), r = s % 60;
  return r > 0 ? m + ' min ' + r + ' s' : m + ' min';
}

async function openAlvoDetail(plate, descricao) {
  // Abre modal e mostra spinner
  _detailModalReturnFn = function() { openAlvoDetail(plate, descricao || ''); };
  document.getElementById('detail-modal-plate').innerHTML =
    '&#127919; Alvo: <span style="color:#f87171">' + plate + '</span>'
    + ' <label style="font-size:.72rem;color:var(--muted);margin-left:18px">Janela co-detecção: <input id="alvo-co-window" type="number" min="1" max="1000" value="' + _alvoCoWindow + '" style="width:62px;padding:2px 4px;border-radius:4px;border:1px solid var(--border);background:var(--bg);color:var(--fg);font-size:.75rem" onchange="var v=Math.max(1,Math.min(1000,parseInt(this.value)||300));this.value=v;_alvoCoWindow=v;openAlvoDetail(\'' + plate.replace(/'/g,"\\'") + '\',\'' + (descricao||'').replace(/'/g,"\\'") + '\')">s</label>';
  document.getElementById('detail-modal-body').innerHTML =
    '<p style="color:var(--muted)"><span class="spinner"></span> Buscando companheiros&hellip;</p>';
  openModal('detail-modal');

  try {
    var resp = await fetch('/api/batedor/companions/' + encodeURIComponent(plate) + '?window=24h&co_window=' + _alvoCoWindow + '&min_cameras=2&trip_max=3600&limit=20');
    var data = await resp.json();
    var companions = data.companions || [];

    if (companions.length === 0) {
      document.getElementById('detail-modal-body').innerHTML =
        '<div style="background:rgba(0,0,0,.03);border-radius:8px;padding:24px;text-align:center;color:var(--muted)">'
        + '&#128269; Nenhum comboio confirmado para <strong>' + plate + '</strong> nas &uacute;ltimas 24h.<br><small>(&ge;2 ve&iacute;culos juntos na mesma c&acirc;mera, em &ge;2 c&acirc;meras distintas, viagem &le;1h)</small></div>';
      return;
    }

    var headerHtml = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">'
      + '<button class="btn btn-sm" style="background:#ef4444;color:#fff;font-weight:700" onclick="verTrajetoriaNoMapa()">&#128663; Trajetória no Mapa</button>'
      + '</div>';
    if (descricao) {
      headerHtml += '<div style="background:rgba(239,68,68,.07);border:1px solid rgba(239,68,68,.2);border-radius:8px;padding:10px 14px;margin-bottom:18px;font-size:.82rem;color:var(--muted)">'
        + '&#128203; <strong>Motivo do rastreamento:</strong> ' + descricao + '</div>';
    }

    var sectionsHtml = companions.map(function(c) {
      var evidences = c.evidence || [];
      var tot = (c.companion_leads + c.target_leads) || 1;
      var compLeadPct = Math.round(c.companion_leads / tot * 100);
      var tgtLeadPct  = Math.round(c.target_leads   / tot * 100);

      // Banner de papel
      var bannerHtml;
      if (compLeadPct >= 70) {
        bannerHtml = '<div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:9px 14px;margin-bottom:10px;font-size:.82rem">'
          + '<strong style="color:#f87171">&#128680; Poss&iacute;vel BATEDOR de ' + plate + '</strong><br>'
          + '<span style="color:var(--muted)">Chega antes em <strong>' + compLeadPct + '%</strong> das passagens ('
          + c.companion_leads + ' de ' + tot + '). M&eacute;dia de <strong>' + _fmtDelta(c.avg_co_delta_sec) + '</strong> de antecedência. '
          + 'Padr&atilde;o consistente com abertura de caminho.</span></div>';
      } else if (tgtLeadPct >= 70) {
        bannerHtml = '<div style="background:rgba(217,119,6,.1);border:1px solid rgba(217,119,6,.3);border-radius:8px;padding:9px 14px;margin-bottom:10px;font-size:.82rem">'
          + '<strong style="color:#fbbf24">&#9888;&#65039; ' + plate + ' chega na frente &mdash; ' + c.companion + ' pode ser PROTEÇÃO</strong><br>'
          + '<span style="color:var(--muted)">O alvo lidera em <strong>' + tgtLeadPct + '%</strong> das passagens. '
          + c.companion + ' segue a <strong>' + _fmtDelta(c.avg_co_delta_sec) + '</strong> de dist&acirc;ncia m&eacute;dia.</span></div>';
      } else {
        bannerHtml = '<div style="background:rgba(34,197,94,.07);border:1px solid rgba(34,197,94,.2);border-radius:8px;padding:9px 14px;margin-bottom:10px;font-size:.82rem">'
          + '<strong style="color:#4ade80">&#128664;&#128664; Comboio lado a lado</strong><br>'
          + '<span style="color:var(--muted)">Liderança alternada (' + plate + ': ' + c.target_leads + 'x / ' + c.companion + ': ' + c.companion_leads + 'x). '
          + 'Sem hierarquia fixa — provavelmente viajando em grupo.</span></div>';
      }

      // Tabela de evidências (câmera a câmera)
      var evRows = evidences.map(function(ev, i) {
        var delta = ev.co_delta_sec != null ? ev.co_delta_sec : Math.round(Math.abs(new Date(ev.ts_companion) - new Date(ev.ts_target)) / 1000);
        var badgeCls = delta <= 60 ? 'red' : delta <= 300 ? 'yellow' : 'green';
        var order = ev.plate_order || [];
        var idxT = order.indexOf(plate), idxC = order.indexOf(c.companion);
        var targetFirst = (idxT >= 0 && idxC >= 0) ? idxT <= idxC : (new Date(ev.ts_target) <= new Date(ev.ts_companion));
        var yoloVcT = ev.yolo_vc_target;
        var yoloVcC = ev.yolo_vc_companion;
        var yoloBadgeT = (yoloVcT >= 0)
          ? '<span class="badge badge-' + (yoloVcT >= 2 ? 'red' : 'green') + '" title="' + yoloVcT + ' veículo(s)">' + yoloVcT + '</span>'
          : '<span style="color:var(--muted)">-</span>';
        var yoloBadgeC = (yoloVcC >= 0)
          ? '<span class="badge badge-' + (yoloVcC >= 2 ? 'red' : 'green') + '" title="' + yoloVcC + ' veículo(s)">' + yoloVcC + '</span>'
          : '<span style="color:var(--muted)">-</span>';
        var dirCell = ev.direcao === 'CRESCENTE'
          ? '<span style="color:var(--accent);font-size:.75rem;font-weight:700">&#8593; CRESC.</span>'
          : ev.direcao === 'DECRESCENTE'
            ? '<span style="color:var(--accent);font-size:.75rem;font-weight:700">&#8595; DECRESC.</span>'
            : '<span style="color:var(--muted);font-size:.72rem">&#8212;</span>';
        var primeroBadge = '<span style="color:#4ade80;font-size:.65rem;font-weight:700;margin-left:3px" title="passou primeiro">&#9650;1&ordm;</span>';
        return '<tr>'
          + '<td style="text-align:center;font-weight:700;color:var(--muted)">' + (i+1) + '</td>'
          + '<td style="font-size:.78rem">' + (ev.camera || ev.camera_id || '?') + '</td>'
          + '<td>' + dirCell + '</td>'
          + '<td><span style="color:var(--muted);font-size:.75rem">' + fmtTs(ev.ts_target) + '</span>' + (targetFirst ? primeroBadge : '') + '</td>'
          + '<td><span style="color:var(--muted);font-size:.75rem">' + fmtTs(ev.ts_companion) + '</span>' + (!targetFirst ? primeroBadge : '') + '</td>'
          + '<td style="text-align:center"><span class="badge badge-' + badgeCls + '">' + _fmtDelta(delta) + '</span></td>'
          + '<td style="text-align:center">' + yoloBadgeT + '</td>'
          + '<td style="text-align:center">' + yoloBadgeC + '</td>'
          + '</tr>';
      }).join('');

      var lastTog = c.last_seen ? new Date(c.last_seen).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '-';
      var yoloMultiBadge = (c.yolo_multi_events > 0)
        ? ' <span class="badge badge-red" title="YOLO detectou 2+ veículos no frame">&#128293; ' + c.yolo_multi_events + ' YOLO multi</span>'
        : '';
      return '<div class="alvo-companion-section">'
        + '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">'
          + '<span class="plate-tag" style="font-size:1rem">' + c.companion + '</span>'
          + (listBadgesHtml(c.companion) ? listBadgesHtml(c.companion) : '')
          + '<span style="font-size:.78rem;color:var(--muted)">' + c.cameras_together + ' c&acirc;mera(s) &bull; trip ' + (c.trip_span_sec != null ? Math.round(c.trip_span_sec/60) + 'min' : '-') + ' &bull; min: ' + _fmtDelta(c.min_delta_sec) + ' &bull; m&aacute;x: ' + _fmtDelta(c.max_delta_sec) + ' &bull; m&eacute;d: ' + _fmtDelta(c.avg_co_delta_sec) + ' &bull; &uacute;ltimo: ' + lastTog + '</span>'
          + yoloMultiBadge
        + '</div>'
        + bannerHtml
        + '<p style="color:var(--muted);font-size:.79rem;margin-bottom:6px">&#9650;1&ordm; = passou primeiro &nbsp;|&nbsp; &#128293; = YOLO: 2+ ve&iacute;culos no frame</p>'
        + '<div class="table-wrap"><table><thead><tr>'
        + '<th>#</th><th>C&acirc;mera</th><th>Dire&ccedil;&atilde;o</th><th>Hor&aacute;rio Alvo</th><th>Hor&aacute;rio Comp.</th><th>Dif. Tempo</th><th>YOLO Alvo</th><th>YOLO Comp.</th>'
        + '</tr></thead><tbody>' + evRows + '</tbody></table></div>'
        + '</div>';
    }).join('<hr style="border-color:var(--border);margin:20px 0">');

    document.getElementById('detail-modal-body').innerHTML = headerHtml + sectionsHtml;
    // Trajetória no mapa
    var _taPoints = [], _taPlates = [plate];
    companions.forEach(function(c) {
      if (_taPlates.indexOf(c.companion) < 0) _taPlates.push(c.companion);
      (c.evidence || []).forEach(function(ev) {
        var cam = ev.camera || '';
        if (cam && ev.ts_target)    _taPoints.push({ camera_id: cam, ts: ev.ts_target,    plate: plate,       cam_nome: cam });
        if (cam && ev.ts_companion) _taPoints.push({ camera_id: cam, ts: ev.ts_companion, plate: c.companion, cam_nome: cam });
      });
    });
    var _taSeen = {};
    _taPoints = _taPoints.filter(function(p) {
      var k = p.camera_id + '|' + p.plate + '|' + p.ts;
      return _taSeen[k] ? false : (_taSeen[k] = true);
    });
    _mapaTrajetoria = _taPoints.length ? { plates: _taPlates, points: _taPoints } : null;
    var _mb4 = document.getElementById('detail-modal-map-btn');
    if (_mb4) _mb4.style.display = _taPoints.length ? '' : 'none';
  } catch(e) {
    document.getElementById('detail-modal-body').innerHTML =
      '<div style="color:var(--danger);padding:16px">Erro ao buscar dados: ' + e + '</div>';
  }
}

var _editAlvoId = null;
var _alvoDvId    = null;
var _alvoDvPlate = null;

// ── Janelas de análise automática (altere aqui para ajustar todos os blocos) ──
var ALVO_DV_PASS_WINDOW = '7d';   // Últimas Passagens + Ver Rota   (padrão: 7 dias)
var ALVO_DV_HIST_WINDOW = '90d';  // Histórico ampliado (reservado) (padrão: 90 dias)
// Formata a janela para exibição: '7d' → '7 dias', '30d' → '30 dias', '24h' → '24h'
function _alvoDvFmtWindow(w) {
  var m = String(w).match(/^(\d+)(d|h)$/i);
  if (!m) return w;
  return m[2].toLowerCase() === 'd' ? m[1] + ' dias' : m[1] + 'h';
}

// ── Alvo: Troca o período de análise de acompanhantes ────────────────────────
// ── Alvo: Fechar tela de detalhes ────────────────────────────────────────────
function alvoVerFechar() {
  var dvEl = document.getElementById('alvo-detalhe-view');
  if (dvEl) dvEl.classList.remove('active');
  var alvosTab = document.querySelector('#bat-sub-tabs [data-bat="alvos"]');
  if (alvosTab) switchBatTab('alvos', alvosTab);
}

// ── Alvo: Controla exibição dos campos de datas personalizadas ───────────────
function _alvoDvPeriodChange() {
  var sel = document.getElementById('alvo-dv-range');
  var cd  = document.getElementById('alvo-dv-custom-dates');
  if (!sel || !cd) return;
  cd.style.display = sel.value === 'custom' ? 'flex' : 'none';
}

// ── Alvo: Renderiza um card de resumo ────────────────────────────────────────
function _alvoDvMkCard(label, value) {
  return '<div class="card">'
    + '<div class="card-label">' + label + '</div>'
    + '<div style="font-size:.95rem;font-weight:600;color:var(--text);word-break:break-word">' + value + '</div>'
    + '</div>';
}

// ── Alvo: Carrega dados resumidos do alvo via API ────────────────────────────
async function _alvoDvLoadDetalhes(id, descricaoLocal, desdeLocal) {
  var cards = document.getElementById('alvo-dv-cards');
  if (!cards) return;
  var pl = _alvoDvPlate || '';
  var spin = '<span class="spinner" style="font-size:.7rem"></span>';
  cards.innerHTML =
    _alvoDvMkCard('&#128663; Placa', '<span style="font-size:1.3rem;font-family:monospace;letter-spacing:.1em;color:#f87171;font-weight:800">' + pl + '</span>') +
    _alvoDvMkCard('&#128203; Descri&ccedil;&atilde;o', descricaoLocal || '<em style="color:var(--muted);font-size:.85em">sem descri&ccedil;&atilde;o</em>') +
    _alvoDvMkCard('&#128197; Cadastrado em', desdeLocal || '&mdash;') +
    _alvoDvMkCard('&#128336; &Uacute;ltima passagem', spin) +
    _alvoDvMkCard('&#127919; Total de eventos', spin) +
    _alvoDvMkCard('&#128247; C&acirc;meras distintas', spin);
  try {
    var resp = await fetch('/api/alvos/' + id);
    if (!resp.ok) return;
    var d = await resp.json();
    var fmtDate = function(iso) { return iso ? new Date(iso).toLocaleDateString('pt-BR') : '&mdash;'; };
    var fmtTs   = function(iso) { return iso ? new Date(iso).toLocaleString('pt-BR')     : '&mdash;'; };
    cards.innerHTML =
      _alvoDvMkCard('&#128663; Placa', '<span style="font-size:1.3rem;font-family:monospace;letter-spacing:.1em;color:#f87171;font-weight:800">' + d.plate + '</span>') +
      _alvoDvMkCard('&#128203; Descri&ccedil;&atilde;o', d.descricao || '<em style="color:var(--muted);font-size:.85em">sem descri&ccedil;&atilde;o</em>') +
      _alvoDvMkCard('&#128197; Cadastrado em', fmtDate(d.created_at)) +
      _alvoDvMkCard('&#128336; &Uacute;ltima passagem', fmtTs(d.ultima_passagem)) +
      _alvoDvMkCard('&#127919; Total de eventos', d.total_eventos !== null ? String(d.total_eventos) : '&mdash;') +
      _alvoDvMkCard('&#128247; C&acirc;meras distintas', d.total_cameras !== null ? String(d.total_cameras) : '&mdash;');
    _alvoDvDetalhesCache = d;
    _alvoDvUpdatePrioridade();
  } catch(e) {}
}

// ── Alvo: Carrega as últimas passagens automáticas (sem filtro) ─────────────
var _alvoDvPassagensCache = [];
var _alvoDvDetalhesCache  = null;
var _alvoDvCompanionsCache = [];

async function _alvoDvLoadPassagens(id) {
  var el = document.getElementById('alvo-dv-passagens-recentes');
  var rotaEl = document.getElementById('alvo-dv-rota');
  if (!el) return;
  _alvoDvPassagensCache = [];
  if (rotaEl) { rotaEl.style.display = 'none'; rotaEl.innerHTML = ''; }
  el.innerHTML = '<p style="color:var(--muted);font-size:.82rem;padding:4px 0"><span class="spinner"></span> Carregando &uacute;ltimas passagens&hellip;</p>';
  try {
    var resp = await fetch('/api/alvos/' + id + '/historico?range=' + ALVO_DV_PASS_WINDOW + '&limit=20');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var d = await resp.json();
    var events = d.events || [];
    _alvoDvPassagensCache = events;
    _alvoDvUpdatePrioridade();
    var hasRota = events.length >= 2;
    var header = '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px">'
      + '<span style="font-size:.82rem;font-weight:700;color:var(--accent2);text-transform:uppercase;letter-spacing:.06em">&#128336; &Uacute;ltimas Passagens</span>'
      + (events.length ? '<span style="font-size:.76rem;color:var(--muted)">' + events.length + ' registro(s) &bull; &uacute;ltimos ' + _alvoDvFmtWindow(ALVO_DV_PASS_WINDOW) + '</span>' : '')
      + (hasRota ? '<button class="btn btn-outline btn-xs" onclick="_alvoDvVerRota()" id="btn-alvo-ver-rota" style="margin-left:auto">&#128663; Ver Rota</button>' : '')
      + (hasRota ? '<button class="btn btn-outline btn-xs" onclick="_alvoDvVerRotaMapa()" id="btn-alvo-ver-rota-mapa">&#128506; Ver no Mapa</button>' : '')
      + '</div>';
    if (events.length === 0) {
      el.innerHTML = '<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 20px">'
        + header
        + '<div style="color:var(--muted);font-size:.85rem;padding:8px 0">Nenhuma passagem registrada nos &uacute;ltimos ' + _alvoDvFmtWindow(ALVO_DV_PASS_WINDOW) + '.</div>'
        + '</div>';
      return;
    }
    var rows = events.map(function(ev) {
      var ts    = ev.occurred_at ? new Date(ev.occurred_at).toLocaleString('pt-BR', {day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'}) : '&mdash;';
      // LOCAL: channel_name costuma trazer o nome do ponto/local registrado pelo sistema de câmera
      var local = ev.channel_name && ev.channel_name !== ev.camera
        ? ev.channel_name
        : '<span style="color:var(--muted);font-size:.75rem">&mdash;</span>';
      var cam   = ev.camera || ev.camera_id || '&mdash;';
      var dir   = ev.direcao
        ? '<span style="font-size:.75rem;font-weight:700;color:var(--accent)">' + ev.direcao + '</span>'
        : '<span style="color:var(--muted)">&mdash;</span>';
      var imageUrl = normalizeImageUrl(ev.image_path);
      var img   = imageUrl
        ? '<img src="' + imageUrl + '" style="height:38px;border-radius:4px;cursor:pointer;border:1px solid var(--border);vertical-align:middle" onclick="openImageUrl(\'' + imageUrl + '\',\'Passagem do alvo\')" onerror="this.style.display=\'none\'" loading="lazy">'
        : '<span style="color:var(--muted);font-size:.72rem">&#8212;</span>';
      return '<tr>'
        + '<td style="white-space:nowrap;font-size:.78rem;color:var(--muted)">' + ts + '</td>'
        + '<td style="font-size:.78rem;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + (ev.channel_name || '') + '">' + local + '</td>'
        + '<td style="font-size:.78rem;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + cam + '">' + cam + '</td>'
        + '<td>' + dir + '</td>'
        + '<td style="text-align:center">' + img + '</td>'
        + '</tr>';
    }).join('');
    el.innerHTML = '<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden">'
      + '<div style="padding:12px 16px 8px 16px">' + header + '</div>'
      + '<div class="table-wrap" style="margin:0"><table><thead><tr>'
      + '<th style="white-space:nowrap">Data / Hora</th>'
      + '<th>Cidade / Local</th>'
      + '<th>C&acirc;mera</th>'
      + '<th>Dire&ccedil;&atilde;o</th>'
      + '<th style="text-align:center">Imagem</th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table></div>'
      + '</div>';
  } catch(e) {
    el.innerHTML = '<div style="color:var(--danger);font-size:.82rem;padding:6px 0">Erro ao carregar passagens: ' + e + '</div>';
  }
}

// ── Alvo: Relatório operacional ───────────────────────────────────────────────
function _alvoDvGerarRelatorio() {
  var d           = _alvoDvDetalhesCache;
  var passagens   = _alvoDvPassagensCache  || [];
  var companions  = _alvoDvCompanionsCache || [];
  var plate       = _alvoDvPlate || (d && d.plate) || '—';
  var now         = new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});

  var descricao    = (d && d.descricao)           || '—';
  var cadastradoEm = (d && d.created_at)          ? new Date(d.created_at).toLocaleDateString('pt-BR') : '—';
  var ultimaPass   = (d && d.ultima_passagem)     ? new Date(d.ultima_passagem).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
  var totalEv      = (d && d.total_eventos != null) ? d.total_eventos : (passagens.length ? passagens.length + '+' : '—');
  var totalCam     = (d && d.total_cameras != null) ? d.total_cameras : '—';

  // prioridade (mesma lógica de _alvoDvUpdatePrioridade)
  var prioLabel = 'SEM CLASSIFICAÇÃO', prioColor = '#9ca3af';
  var score = 0;
  if (d) {
    var ev = d.total_eventos || 0;
    score += ev >= 51 ? 30 : ev >= 21 ? 20 : ev >= 6 ? 10 : ev >= 1 ? 5 : 0;
    if (d.ultima_passagem) {
      var ageH = (Date.now() - new Date(d.ultima_passagem).getTime()) / 3600000;
      score += ageH <= 24 ? 30 : ageH <= 168 ? 15 : ageH <= 720 ? 5 : 0;
    }
    var tc = d.total_cameras || 0;
    score += tc >= 4 ? 20 : tc >= 2 ? 10 : tc >= 1 ? 5 : 0;
  }
  score += passagens.length >= 11 ? 20 : passagens.length >= 4 ? 10 : passagens.length >= 1 ? 5 : 0;
  var locSet2 = {}; passagens.forEach(function(pev){var l=(pev.channel_name&&pev.channel_name!==pev.camera)?pev.channel_name:(pev.camera||'');if(l)locSet2[l]=1;});
  var nL2 = Object.keys(locSet2).length;
  score += nL2 >= 4 ? 20 : nL2 >= 2 ? 10 : 0;
  score += companions.length >= 2 ? 25 : companions.length === 1 ? 15 : 0;
  if (companions.some(function(c){var t=(c.companion_leads+c.target_leads)||1;return Math.round(c.companion_leads/t*100)>=70;})) score+=15;
  if      (score <= 0)  { prioLabel = 'SEM CLASSIFICAÇÃO'; prioColor = '#9ca3af'; }
  else if (score <= 20) { prioLabel = 'BAIXO';   prioColor = '#4ade80'; }
  else if (score <= 50) { prioLabel = 'MÉDIO';   prioColor = '#fbbf24'; }
  else if (score <= 80) { prioLabel = 'ALTO';    prioColor = '#fb923c'; }
  else                  { prioLabel = 'CRÍTICO'; prioColor = '#f87171'; }

  // linhas da rota (ordem cronológica)
  var rotaRows = '';
  if (passagens.length) {
    var evAsc = passagens.slice().reverse();
    rotaRows = evAsc.map(function(pev, i) {
      var ts    = pev.occurred_at ? new Date(pev.occurred_at).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '—';
      var local = (pev.channel_name && pev.channel_name !== pev.camera) ? pev.channel_name : (pev.camera || pev.camera_id || '—');
      var cam   = pev.camera || pev.camera_id || '—';
      var dir   = pev.direcao || '—';
      var intervalo = '—';
      if (i > 0 && evAsc[i-1].occurred_at && pev.occurred_at) {
        var ms = new Date(pev.occurred_at) - new Date(evAsc[i-1].occurred_at);
        intervalo = _fmtInterval(Math.abs(ms)) || '—';
      }
      return '<tr style="border-bottom:1px solid #e5e7eb">'
        + '<td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280">' + (i+1) + '</td>'
        + '<td style="padding:7px 10px;font-size:.78rem;white-space:nowrap">' + ts + '</td>'
        + '<td style="padding:7px 10px;font-size:.78rem">' + local + '</td>'
        + '<td style="padding:7px 10px;font-size:.78rem">' + cam + '</td>'
        + '<td style="padding:7px 10px;font-size:.78rem;font-weight:700;color:#6366f1">' + dir + '</td>'
        + '<td style="padding:7px 10px;font-size:.78rem;color:#9ca3af">' + intervalo + '</td>'
        + '</tr>';
    }).join('');
  }

  // linhas de acompanhantes
  var compRows = '';
  if (companions.length) {
    compRows = companions.map(function(c) {
      var tot = (c.companion_leads + c.target_leads) || 1;
      var clPct = Math.round(c.companion_leads / tot * 100);
      var tgPct = Math.round(c.target_leads   / tot * 100);
      var papel = clPct >= 70 ? 'BATEDOR' : tgPct >= 70 ? 'SEGUIDOR' : 'COMBOIO';
      var papelColor = clPct >= 70 ? '#dc2626' : tgPct >= 70 ? '#d97706' : '#6366f1';
      var ev0 = (c.evidence || [])[0];
      var local = ev0 ? (ev0.camera || ev0.camera_id || '—') : '—';
      var lastTog = c.last_seen ? new Date(c.last_seen).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
      return '<tr style="border-bottom:1px solid #e5e7eb">'
        + '<td style="padding:7px 10px;font-size:.82rem;font-weight:700;font-family:monospace;letter-spacing:.06em">' + c.companion + '</td>'
        + '<td style="padding:7px 10px;font-size:.78rem;text-align:center;font-weight:700;color:' + papelColor + '">' + papel + '</td>'
        + '<td style="padding:7px 10px;font-size:.78rem;text-align:center">' + c.cameras_together + ' câm.</td>'
        + '<td style="padding:7px 10px;font-size:.78rem;white-space:nowrap">' + lastTog + '</td>'
        + '<td style="padding:7px 10px;font-size:.78rem">' + local + '</td>'
        + '</tr>';
    }).join('');
  }

  var field = function(label, value) {
    return '<div style="margin-bottom:10px">'
      + '<div style="font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:2px">' + label + '</div>'
      + '<div style="font-size:.9rem;font-weight:600;color:#111827">' + (value !== undefined && value !== null ? value : '—') + '</div>'
      + '</div>';
  };

  var th = function(t) {
    return '<th style="padding:7px 10px;font-size:.68rem;color:#6b7280;font-weight:700;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap">' + t + '</th>';
  };

  // ── monta e abre o relatório unificado ──────────────────────────────────
  var _alvoKpis = _relEngine.buildKPIs([
    { icon: '\uD83C\uDFAF', label: 'Prioridade',       value: prioLabel,                   color: prioColor },
    { icon: '\uD83D\uDCCA', label: 'Score',             value: score + ' pts',              color: prioColor },
    { icon: '\uD83D\uDCCB', label: 'Passagens',         value: String(totalEv) },
    { icon: '\uD83D\uDCF7', label: 'C\u00e2meras',      value: String(totalCam) },
    companions.length ? { icon: '\uD83D\uDC65', label: 'Acompanhantes', value: String(companions.length) } : null,
    { icon: '\uD83D\uDCC5', label: 'Janela',            value: _alvoDvFmtWindow(ALVO_DV_PASS_WINDOW) }
  ]);
  var _alvoDadosHtml = (function() {
    function _f(l, v) {
      return '<div><div style="font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:2px">' + l + '</div>'
        + '<div style="font-size:.88rem;font-weight:600;color:#111">' + (v != null ? v : '\u2014') + '</div></div>';
    }
    return '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px 20px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:14px 18px">'
      + _f('Placa', '<span style="font-family:monospace;color:#dc2626;font-weight:800">' + plate + '</span>')
      + _f('Descri\u00e7\u00e3o', descricao === '\u2014' ? '<em style="color:#9ca3af">sem descri\u00e7\u00e3o</em>' : descricao)
      + _f('Prioridade', '<span style="color:' + prioColor + ';font-weight:800">' + prioLabel + '</span>')
      + _f('Cadastrado em', cadastradoEm)
      + _f('\u00daltima passagem', ultimaPass)
      + _f('Total de eventos', String(totalEv))
      + _f('C\u00e2meras distintas', String(totalCam))
      + _f('Acompanhantes', companions.length ? String(companions.length) : '\u2014')
    + '</div>';
  })();
  var _alvoTimelineHtml = rotaRows
    ? '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">'
        + '<thead><tr style="background:#e5e7eb">'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">#</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Data / Hora</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Local</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">C\u00e2mera</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Dire\u00e7\u00e3o</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Intervalo</th>'
        + '</tr></thead><tbody>' + rotaRows + '</tbody></table></div>'
    : '<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px;font-size:.82rem;color:#9ca3af">Nenhuma passagem registrada nos \u00faltimos ' + _alvoDvFmtWindow(ALVO_DV_PASS_WINDOW) + '.</div>';
  var _alvoCompHtml = compRows
    ? '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">'
        + '<thead><tr style="background:#e5e7eb">'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Placa</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Papel</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Cooc.</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">\u00dalt. Junto</th>'
          + '<th style="padding:5px 10px;font-size:.68rem;text-transform:uppercase;border:1px solid #e5e7eb">Local / C\u00e2mera</th>'
        + '</tr></thead><tbody>' + compRows + '</tbody></table></div>'
    : '<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px;font-size:.82rem;color:#9ca3af">Nenhum acompanhante identificado nos \u00faltimos ' + _alvoDvFmtWindow((document.getElementById('alvo-dv-range')||{value:'7d'}).value||'7d') + '.</div>';
  var _alvoAnaliseHtml = (function() {
    var _ci = (_cenAllItems || []).find(function(it){ return it.plate === plate; });
    var _tc = _ci && _ci.threat_center;
    if (!_tc) return '<div style="font-size:.82rem;color:#9ca3af">Nenhum v\u00ednculo com Central de Amea\u00e7as identificado.</div>';
    var _rs = _tc.route_similarity || {};
    var _hasThreat = !!(_tc.matched_target || (_tc.threat_badges && _tc.threat_badges.length));
    var _hasRoute  = !!(_rs.matched || (_rs.similarity_ratio && _rs.similarity_ratio > 0));
    if (!_hasThreat && !_hasRoute) return '<div style="font-size:.82rem;color:#9ca3af">Sem atividade de amea\u00e7a detectada.</div>';
    var _badges = (_tc.threat_badges || []).map(function(b){
      return '<span style="display:inline-block;background:#6d28d9;color:#ede9fe;font-size:.65rem;font-weight:700;padding:2px 8px;border-radius:99px;margin-right:4px">' + b + '</span>';
    }).join('');
    var _simPct = (_rs.similarity_ratio != null && _rs.similarity_ratio > 0) ? Math.round(_rs.similarity_ratio*100)+'%' : '\u2014';
    return (_badges ? '<div style="margin-bottom:8px">' + _badges + '</div>' : '')
      + '<table style="width:100%;border-collapse:collapse"><tbody>'
      + '<tr><td style="background:#f9fafb;font-weight:700;font-size:.75rem;white-space:nowrap;padding:6px 10px;border:1px solid #e5e7eb;width:40%">Alvo vinculado</td><td style="font-size:.82rem;padding:6px 10px;border:1px solid #e5e7eb">' + (_tc.matched_target ? '<strong style="color:#16a34a">&#9989; Sim</strong>' : '<span style="color:#9ca3af">N\u00e3o</span>') + '</td></tr>'
      + (_rs.matched||_rs.similarity_ratio>0 ? '<tr><td style="background:#f9fafb;font-weight:700;font-size:.75rem;white-space:nowrap;padding:6px 10px;border:1px solid #e5e7eb">Similaridade de rota</td><td style="font-size:.82rem;padding:6px 10px;border:1px solid #e5e7eb;font-weight:700;color:#7c3aed">' + _simPct + (_rs.best_alvo ? ' \u2014 similar a ' + _rs.best_alvo : '') + '</td></tr>' : '')
      + (_rs.common_cameras&&_rs.common_cameras.length ? '<tr><td style="background:#f9fafb;font-weight:700;font-size:.75rem;white-space:nowrap;padding:6px 10px;border:1px solid #e5e7eb">C\u00e2meras em comum</td><td style="font-size:.82rem;padding:6px 10px;border:1px solid #e5e7eb">' + _rs.common_cameras.join(', ') + '</td></tr>' : '')
      + '</tbody></table>';
  })();
  var _alvoHtml = _relEngine.render([
    _relEngine.buildHeader({ titulo: 'Relat\u00f3rio Operacional \u2014 Alvo Rastreado', subtitulo: 'Placa: <strong>' + plate + '</strong>' + (descricao !== '\u2014' ? ' \u2014 ' + descricao : ''), risco: prioLabel, score: score, now: now }),
    _alvoKpis,
    _relEngine.section('1. Identifica\u00e7\u00e3o', _alvoDadosHtml),
    _relEngine.section('2. Linha do Tempo \u2014 Passagens (' + _alvoDvFmtWindow(ALVO_DV_PASS_WINDOW) + ')', _alvoTimelineHtml),
    _relEngine.section('3. Relacionamentos & Comboio', _alvoCompHtml),
    _relEngine.section('4. An\u00e1lise de Amea\u00e7a', _alvoAnaliseHtml),
    _relEngine.buildFooter(now)
  ], 'rel-print');
  var _alvoHtml_unused =
    + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px 20px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:16px 20px;margin-bottom:20px">'
      + field('Placa', '<span style="font-family:monospace;color:#dc2626;font-weight:800">' + plate + '</span>')
      + field('Descrição', descricao === '—' ? '<em style="color:#9ca3af">sem descrição</em>' : descricao)
      + field('Prioridade', '<span style="color:' + prioColor + ';font-weight:800">' + prioLabel + '</span>')
      + field('Cadastrado em', cadastradoEm)
      + field('Última passagem', ultimaPass)
      + field('Total de passagens', String(totalEv))
      + field('Câmeras / Locais', String(totalCam))
      + field('Acompanhantes', companions.length ? String(companions.length) : '—')
    + '</div>'
    // rota
    + '<div style="margin-bottom:20px">'
      + '<div style="font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">&#128336; Rota &mdash; &Uacute;ltimas passagens (' + _alvoDvFmtWindow(ALVO_DV_PASS_WINDOW) + ')</div>'
      + (passagens.length === 0
        ? '<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;font-size:.82rem;color:#9ca3af">Nenhuma passagem registrada nos &uacute;ltimos ' + _alvoDvFmtWindow(ALVO_DV_PASS_WINDOW) + '.</div>'
        : '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">'
          + '<thead><tr style="background:#e5e7eb">'
            + th('#') + th('Data / Hora') + th('Cidade / Local') + th('Câmera') + th('Direção') + th('Intervalo')
          + '</tr></thead><tbody>' + rotaRows + '</tbody></table></div>')
    + '</div>'
    // acompanhantes
    + '<div style="margin-bottom:24px">'
      + '<div style="font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#6b7280;margin-bottom:8px">&#128101; Acompanhantes / Comboio</div>'
      + (companions.length === 0
        ? '<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;font-size:.82rem;color:#9ca3af">Nenhum acompanhante identificado nos &uacute;ltimos ' + _alvoDvFmtWindow((document.getElementById('alvo-dv-range')||{value:'7d'}).value||'7d') + '.</div>'
        : '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">'
          + '<thead><tr style="background:#e5e7eb">'
            + th('Placa') + th('Papel') + th('Cooc.') + th('Últ. vez junto') + th('Local / Câmera')
          + '</tr></thead><tbody>' + compRows + '</tbody></table></div>')
    + '</div>'
    // ── Central de Ameaças (threat_center do _cenAllItems) ─────────────────
    + (function() {
        var _ci  = (_cenAllItems || []).find(function(it){ return it.plate === plate; });
        var _tc  = _ci && _ci.threat_center;
        if (!_tc) return '';
        var _rs  = _tc.route_similarity || {};
        var _hasThreat = !!(_tc.matched_target || (_tc.threat_badges && _tc.threat_badges.length));
        var _hasRoute  = !!(_rs.matched || (_rs.similarity_ratio && _rs.similarity_ratio > 0));
        if (!_hasThreat && !_hasRoute) return '';
        var _badgesHtml = (_tc.threat_badges && _tc.threat_badges.length)
          ? _tc.threat_badges.map(function(b){ return '<span style="display:inline-block;background:#6d28d9;color:#ede9fe;font-size:.65rem;font-weight:700;padding:2px 8px;border-radius:99px;margin-right:4px;letter-spacing:.04em">' + b + '</span>'; }).join('')
          : '';
        var _simPct = (_rs.similarity_ratio != null && _rs.similarity_ratio > 0)
          ? Math.round(_rs.similarity_ratio * 100) + '%' : '—';
        var _rows =
            '<tr style="border-bottom:1px solid #e5e7eb"><td style="padding:6px 10px;font-size:.75rem;color:#6b7280;font-weight:700;white-space:nowrap">Alvo cadastrado vinculado</td><td style="padding:6px 10px;font-size:.78rem">' + (_tc.matched_target ? '<strong style="color:#16a34a">&#9989; Sim</strong>' : '<span style="color:#9ca3af">— Não</span>') + '</td></tr>'
          + (_tc.matched_plates && _tc.matched_plates.length ? '<tr style="border-bottom:1px solid #e5e7eb"><td style="padding:6px 10px;font-size:.75rem;color:#6b7280;font-weight:700;white-space:nowrap">Placas alvo no grupo</td><td style="padding:6px 10px;font-size:.78rem;font-family:monospace">' + _tc.matched_plates.join(', ') + '</td></tr>' : '')
          + '<tr style="border-bottom:1px solid #e5e7eb"><td style="padding:6px 10px;font-size:.75rem;color:#6b7280;font-weight:700;white-space:nowrap">Rota parecida</td><td style="padding:6px 10px;font-size:.78rem">' + (_rs.matched ? '<strong style="color:#7c3aed">&#9989; Sim</strong>' : '<span style="color:#9ca3af">— Não</span>') + '</td></tr>'
          + '<tr style="border-bottom:1px solid #e5e7eb"><td style="padding:6px 10px;font-size:.75rem;color:#6b7280;font-weight:700;white-space:nowrap">Similaridade de rota</td><td style="padding:6px 10px;font-size:.78rem;font-weight:700;color:#7c3aed">' + _simPct + '</td></tr>'
          + (_rs.best_alvo ? '<tr style="border-bottom:1px solid #e5e7eb"><td style="padding:6px 10px;font-size:.75rem;color:#6b7280;font-weight:700;white-space:nowrap">Alvo mais similar</td><td style="padding:6px 10px;font-size:.78rem;font-family:monospace;font-weight:700">' + _rs.best_alvo + '</td></tr>' : '')
          + (_rs.common_cameras && _rs.common_cameras.length ? '<tr style="border-bottom:1px solid #e5e7eb"><td style="padding:6px 10px;font-size:.75rem;color:#6b7280;font-weight:700;white-space:nowrap">Câmeras em comum</td><td style="padding:6px 10px;font-size:.78rem">' + _rs.common_cameras.join(', ') + '</td></tr>' : '')
          + (_rs.common_cities  && _rs.common_cities.length  ? '<tr style="border-bottom:1px solid #e5e7eb"><td style="padding:6px 10px;font-size:.75rem;color:#6b7280;font-weight:700;white-space:nowrap">Cidades em comum</td><td style="padding:6px 10px;font-size:.78rem">' + _rs.common_cities.join(', ') + '</td></tr>'  : '');
        return '<div style="margin-bottom:20px;border:1px solid #7c3aed;border-radius:10px;overflow:hidden">'
          + '<div style="background:#7c3aed;padding:9px 14px;font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#fff">&#127919; Central de Amea&ccedil;as — Fase 1 &amp; 2' + (_badgesHtml ? ' &nbsp;' + _badgesHtml : '') + '</div>'
          + '<table style="width:100%;border-collapse:collapse;background:#faf5ff"><tbody>' + _rows + '</tbody></table>'
          + '</div>';
      })()
    // rodapé
    + '<div style="font-size:.68rem;color:#9ca3af;border-top:1px solid #e5e7eb;padding-top:10px;text-align:right">'
      + 'Gerado em ' + now + ' &bull; Sistema de Monitoramento BPFRON'
    + '</div></div>';

  _relAbrirModal(plate, _alvoHtml, _alvoDvVerRotaMapa);
}

function _alvoDvExportarPDF() { _relExportarPDF(); } // compat: usa motor unificado

// ── Alvo: Rota cronológica ───────────────────────────────────────────────────
function _fmtInterval(ms) {
  if (ms == null || ms < 0) return null;
  var s = Math.round(Math.abs(ms) / 1000);
  if (s < 60)   return s + 's';
  if (s < 3600) { var m = Math.floor(s/60), r = s % 60; return m + ' min' + (r ? ' ' + r + 's' : ''); }
  var h = Math.floor(s/3600), rm = Math.floor((s%3600)/60);
  return h + 'h' + (rm ? ' ' + rm + 'min' : '');
}

function _alvoDvVerRota() {
  var rotaEl = document.getElementById('alvo-dv-rota');
  var btn    = document.getElementById('btn-alvo-ver-rota');
  if (!rotaEl) return;
  // toggle fechar
  if (rotaEl.style.display !== 'none') {
    rotaEl.style.display = 'none';
    if (btn) { btn.innerHTML = '&#128663; Ver Rota'; }
    return;
  }
  // eventos em ordem cronológica (ASC) — cache vem DESC
  var events = _alvoDvPassagensCache.slice().reverse();
  if (events.length < 2) {
    rotaEl.innerHTML = '<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 18px;color:var(--muted);font-size:.85rem">Passagens insuficientes para montar a rota (m&iacute;nimo: 2).</div>';
    rotaEl.style.display = 'block';
    return;
  }
  if (btn) { btn.innerHTML = '&#10005; Fechar Rota'; }
  var html = '<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden">'
    + '<div style="padding:12px 16px 10px 16px;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border)">'
    + '<span style="font-size:.82rem;font-weight:700;color:var(--accent2);text-transform:uppercase;letter-spacing:.06em">&#128663; Rota Cronol&oacute;gica</span>'
    + '<span style="font-size:.76rem;color:var(--muted)">' + events.length + ' ponto(s) &bull; &uacute;ltimos ' + _alvoDvFmtWindow(ALVO_DV_PASS_WINDOW) + '</span>'
    + '</div>'
    + '<div style="padding:16px 20px 20px 20px">';
  var prevLocal = null;
  events.forEach(function(ev, i) {
    var ts        = ev.occurred_at ? new Date(ev.occurred_at) : null;
    var tsStr     = ts ? ts.toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '\u2014';
    var cam       = ev.camera || ev.camera_id || '\u2014';
    var local     = (ev.channel_name && ev.channel_name !== ev.camera) ? ev.channel_name : cam;
    var dir       = ev.direcao || '';
    var isFirst   = i === 0;
    var isLast    = i === events.length - 1;
    var locChange = prevLocal !== null && local !== prevLocal;
    prevLocal = local;
    // linha de intervalo entre passagens
    var intervalHtml = '';
    if (i > 0 && events[i-1].occurred_at && ev.occurred_at) {
      var delta  = new Date(ev.occurred_at) - new Date(events[i-1].occurred_at);
      var intStr = _fmtInterval(delta);
      intervalHtml = '<div style="display:flex;align-items:stretch;gap:0;margin:0 0 0 5px">'
        + '<div style="display:flex;flex-direction:column;align-items:center;width:22px;flex-shrink:0">'
        + '<div style="width:1px;flex:1;background:var(--border)"></div></div>'
        + '<div style="padding:2px 10px;font-size:.72rem;color:var(--muted);font-style:italic;align-self:center">&#8595; ' + intStr + '</div>'
        + '</div>';
    }
    var dotColor = isFirst ? '#22c55e' : isLast ? '#ef4444' : locChange ? '#f59e0b' : 'var(--primary)';
    var dirBadge = dir ? ' <span style="font-size:.7rem;font-weight:700;color:var(--accent);background:rgba(250,204,21,.12);padding:1px 7px;border-radius:99px;border:1px solid rgba(250,204,21,.25)">' + dir + '</span>' : '';
    var imgThumbUrl = normalizeImageUrl(ev.image_path);
    var imgThumb = imgThumbUrl
      ? '<img src="' + imgThumbUrl + '" style="height:30px;border-radius:4px;border:1px solid var(--border);cursor:pointer;vertical-align:middle;margin-left:4px" onclick="openImageUrl(\'' + imgThumbUrl.replace(/'/g,"\\'") + '\',\'Imagem da passagem\')" onerror="this.style.display=\'none\'" loading="lazy" title="Ver imagem">'
      : '';
    var locBanner = locChange
      ? '<div style="font-size:.7rem;color:#f59e0b;font-weight:600;margin-bottom:3px">&#128205; Nova localidade</div>'
      : '';
    html += intervalHtml
      + '<div style="display:flex;gap:10px;align-items:flex-start">'
        + '<div style="display:flex;flex-direction:column;align-items:center;flex-shrink:0;padding-top:4px">'
          + '<div style="width:14px;height:14px;border-radius:50%;background:' + dotColor + ';border:2px solid rgba(255,255,255,.15);flex-shrink:0"></div>'
        + '</div>'
        + '<div style="flex:1;background:var(--bg2);border:1px solid var(--border)' + (locChange ? ';border-left:3px solid #f59e0b' : '') + ';border-radius:8px;padding:9px 12px;margin-bottom:0">'
          + locBanner
          + '<div style="display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-bottom:4px">'
            + '<span style="font-size:.8rem;font-weight:700;color:var(--text)">' + (i+1) + '. ' + local + '</span>'
            + dirBadge
            + imgThumb
          + '</div>'
          + '<div style="display:flex;flex-wrap:wrap;gap:14px">'
            + '<span style="font-size:.74rem;color:var(--muted)">&#128247; ' + cam + '</span>'
            + '<span style="font-size:.74rem;color:var(--muted)">&#128336; ' + tsStr + '</span>'
          + '</div>'
        + '</div>'
      + '</div>';
  });
  html += '</div></div>';
  rotaEl.innerHTML = html;
  rotaEl.style.display = 'block';
  rotaEl.scrollIntoView({behavior:'smooth', block:'nearest'});
}

// ── Pipeline canônico (compartilhado): busca /trajectory e renderiza igual a Mapas > Rotas ──
async function _verRotaNaMapa(plate, tsFrom, tsTo, infoLabel) {
  if (!plate) return;
  var url = '/api/vehicles/' + encodeURIComponent(plate) + '/trajectory'
          + '?start=' + encodeURIComponent(tsFrom)
          + '&end='   + encodeURIComponent(tsTo)
          + '&dedupe_seconds=5';
  try {
    var r = await fetch(url);
    if (!r.ok) {
      var errData = await r.json().catch(function(){ return {detail:'HTTP '+r.status}; });
      throw new Error(errData.detail || 'HTTP ' + r.status);
    }
    var data = await r.json();
    if (!data.points || data.points.length === 0) {
      var fallbackData = _buildTrajectoryFallbackFromReport(plate, data);
      if (fallbackData && fallbackData.points && fallbackData.points.length) {
        data = fallbackData;
      }
    }
    if (!data.points || data.points.length === 0) {
      var msg = 'Nenhuma passagem com GPS encontrada neste per\u00edodo.';
      if (data.cameras_without_gps && data.cameras_without_gps.length)
        msg += '\nC\u00e2meras sem GPS: ' + data.cameras_without_gps.join(', ');
      alert(msg);
      return;
    }
    // Sincroniza campos da aba Mapas > Rotas
    var pf = document.getElementById('traj-plate-field');
    var sf = document.getElementById('traj-start-field');
    var ef = document.getElementById('traj-end-field');
    if (pf) pf.value = plate;
    if (sf) sf.value = tsFrom;
    if (ef) ef.value = tsTo;
    _setMapaTrajetoriaFromApiData(data, plate);
    // Abre overlay e renderiza pelo pipeline can\u00f4nico
    _abrirMapaOverlay(plate, infoLabel || ((data.total_points || data.points.length) + ' passagem(ns)'), _relModalReturnFn, 'Voltar ao Relatório');
    setTimeout(function() { renderVehicleTrajectory(data); }, 400);
  } catch(e) {
    alert('Erro ao carregar trajet\u00f3ria: ' + e.message);
  }
}

// ── Alvo: Rota no mapa ───────────────────────────────────────────────────────
async function _alvoDvVerRotaMapa() {
  var plate = _alvoDvPlate || '';
  if (!plate) return;
  var rangeEl = document.getElementById('alvo-dv-range');
  var range   = rangeEl ? rangeEl.value : '7d';
  var now = Date.now();
  var tsTo   = _toLocalDTInput(new Date(now));
  var tsFrom;
  var msMap = { '7d': 7*86400000, '15d': 15*86400000, '30d': 30*86400000, '90d': 90*86400000, '180d': 180*86400000 };
  var periodLabel = range === 'custom' ? 'per\u00edodo personalizado' : '\u00faltimos ' + range;
  if (range === 'custom') {
    var f = (document.getElementById('alvo-dv-start') || {}).value;
    var t = (document.getElementById('alvo-dv-end')   || {}).value;
    if (!f || !t) { alert('Defina as datas De e At\u00e9 para usar o per\u00edodo personalizado.'); return; }
    tsFrom = f + 'T00:00';
    tsTo   = t + 'T23:59';
    periodLabel = f + ' \u2192 ' + t;
  } else {
    tsFrom = _toLocalDTInput(new Date(now - (msMap[range] || 7*86400000)));
  }
  var btn = document.getElementById('btn-alvo-ver-rota-mapa');
  if (btn) { btn.disabled = true; btn.innerHTML = '&#128260; Carregando&hellip;'; }
  await _verRotaNaMapa(plate, tsFrom, tsTo, periodLabel);
  if (btn) { btn.disabled = false; btn.innerHTML = '&#128506; Ver no Mapa'; }
}

// ── Alvo: Indicador de risco / prioridade ───────────────────────────────────
function _alvoDvUpdatePrioridade() {
  var el = document.getElementById('alvo-dv-prioridade');
  if (!el) return;

  var d           = _alvoDvDetalhesCache;
  var passagens   = _alvoDvPassagensCache || [];
  var companions  = _alvoDvCompanionsCache || [];

  // aguarda pelo menos os detalhes carregarem
  var hasData = !!(d || passagens.length || companions.length);
  if (!hasData) {
    el.innerHTML = '<span style="display:inline-flex;align-items:center;gap:6px;font-size:.72rem;color:var(--muted);font-style:italic">Classificando&hellip;</span>';
    return;
  }

  var score = 0;
  var reasons = [];

  // 1. Total de eventos (histório completo)
  var totalEv = d ? (d.total_eventos || 0) : 0;
  if (totalEv >= 51)       { score += 30; reasons.push(totalEv + ' passagens totais'); }
  else if (totalEv >= 21)  { score += 20; reasons.push(totalEv + ' passagens totais'); }
  else if (totalEv >= 6)   { score += 10; reasons.push(totalEv + ' passagens totais'); }
  else if (totalEv >= 1)   { score +=  5; reasons.push(totalEv + ' passagem(ns) total'); }

  // 2. Recência da última passagem
  var ultima = d ? d.ultima_passagem : null;
  if (ultima) {
    var ageH = (Date.now() - new Date(ultima).getTime()) / 3600000;
    if (ageH <= 24)        { score += 30; reasons.push('passagem há menos de 24h'); }
    else if (ageH <= 168)  { score += 15; reasons.push('passagem nos últimos 7 dias'); }
    else if (ageH <= 720)  { score +=  5; reasons.push('passagem nos últimos 30 dias'); }
  }

  // 3. Câmeras distintas (mobilidade)
  var totalCam = d ? (d.total_cameras || 0) : 0;
  if (totalCam >= 4)       { score += 20; reasons.push(totalCam + ' locais distintos'); }
  else if (totalCam >= 2)  { score += 10; reasons.push(totalCam + ' locais distintos'); }
  else if (totalCam >= 1)  { score +=  5; }

  // 4. Passagens recentes (7 dias)
  var rec7d = passagens.length;
  if (rec7d >= 11)         { score += 20; reasons.push(rec7d + ' passagens em 7 dias'); }
  else if (rec7d >= 4)     { score += 10; reasons.push(rec7d + ' passagens em 7 dias'); }
  else if (rec7d >= 1)     { score +=  5; }

  // 5. Localidades distintas nos últimos 7 dias
  var locSet = {};
  passagens.forEach(function(ev) {
    var loc = (ev.channel_name && ev.channel_name !== ev.camera) ? ev.channel_name : (ev.camera || '');
    if (loc) locSet[loc] = 1;
  });
  var nLoc = Object.keys(locSet).length;
  if (nLoc >= 4)           { score += 20; reasons.push(nLoc + ' localidades distintas'); }
  else if (nLoc >= 2)      { score += 10; reasons.push(nLoc + ' localidades distintas'); }

  // 6. Acompanhantes / comboio
  var nComp = companions.length;
  var hasBatedor = companions.some(function(c) {
    var tot = (c.companion_leads + c.target_leads) || 1;
    return Math.round(c.companion_leads / tot * 100) >= 70;
  });
  if (nComp >= 2)          { score += 25; reasons.push(nComp + ' acompanhantes identificados'); }
  else if (nComp === 1)    { score += 15; reasons.push('1 acompanhante identificado'); }
  if (hasBatedor)          { score += 15; reasons.push('padrão de batedor detectado'); }

  // Classificação
  var level, label, bg, border, icon;
  if (score <= 0) {
    level = 0; label = 'SEM CLASSIFICAÇÃO';
    bg = 'rgba(107,114,128,.15)'; border = 'rgba(107,114,128,.4)'; icon = '&#9898;';
  } else if (score <= 20) {
    level = 1; label = 'BAIXO';
    bg = 'rgba(34,197,94,.12)';  border = 'rgba(34,197,94,.45)';  icon = '&#128994;'; // green dot
  } else if (score <= 50) {
    level = 2; label = 'MÉDIO';
    bg = 'rgba(245,158,11,.12)'; border = 'rgba(245,158,11,.45)'; icon = '&#128993;'; // yellow dot
  } else if (score <= 80) {
    level = 3; label = 'ALTO';
    bg = 'rgba(249,115,22,.14)'; border = 'rgba(249,115,22,.5)';  icon = '&#128992;'; // orange dot
  } else {
    level = 4; label = 'CRÍTICO';
    bg = 'rgba(239,68,68,.15)';  border = 'rgba(239,68,68,.5)';   icon = '&#128308;'; // red dot
  }

  var textColor = ['#9ca3af','#4ade80','#fbbf24','#fb923c','#f87171'][level];
  var reasonText = reasons.length
    ? reasons.slice(0,3).join(' · ')
    : 'dados insuficientes';

  el.innerHTML =
    '<div style="display:inline-flex;flex-direction:column;align-items:flex-end;gap:3px">'
    + '<span style="display:inline-flex;align-items:center;gap:6px;background:' + bg + ';border:1px solid ' + border + ';border-radius:99px;padding:4px 14px 4px 10px;font-size:.78rem;font-weight:800;color:' + textColor + ';letter-spacing:.06em;text-transform:uppercase;white-space:nowrap">'
    + icon + ' ' + label
    + '</span>'
    + '<span style="font-size:.68rem;color:var(--muted);max-width:280px;text-align:right;line-height:1.4">' + reasonText + '</span>'
    + '</div>';
}

// ── Alvo: Acompanhantes / Comboio ───────────────────────────────────────────
async function _alvoDvLoadCompanions(id, plate) {
  var el = document.getElementById('alvo-dv-companions');
  if (!el || !plate) return;
  var _compRange = (document.getElementById('alvo-dv-range') || {value:'7d'}).value || '7d';
  var _compWindow = _compRange !== 'custom' ? _compRange : '7d';  // custom usa o intervalo do filtro de histórico via params separados
  el.innerHTML = '<p style="color:var(--muted);font-size:.82rem;padding:4px 0"><span class="spinner"></span> Buscando acompanhantes&hellip; <span style="font-size:.75rem;opacity:.7">(' + _alvoDvFmtWindow(_compWindow) + ')</span></p>';
  try {
    var qs = '?window=' + encodeURIComponent(_compWindow) + '&co_window=300&min_cameras=1&trip_max=7200&limit=20';
    var [compResp, alvosResp] = await Promise.all([
      fetch('/api/batedor/companions/' + encodeURIComponent(plate) + qs),
      fetch('/api/alvos')
    ]);
    if (!compResp.ok) throw new Error('HTTP ' + compResp.status);
    var compData  = await compResp.json();
    var alvosData = alvosResp.ok ? await alvosResp.json() : {alvos:[]};
    var companions = compData.companions || [];
    _alvoDvCompanionsCache = companions;
    _alvoDvUpdatePrioridade();
    // mapa placa -> {id, descricao} somente quando tbm é alvo rastreado
    var alvoMap = {};
    (alvosData.alvos || []).forEach(function(a) { alvoMap[a.plate] = a; });

    // ---- aviso para consultas ampliadas ------------------------------------
    var warnHtml = '';
    if (_compWindow === '90d') {
      warnHtml = '<div style="margin-top:8px;padding:7px 12px;border-radius:7px;background:rgba(234,179,8,.12);border:1px solid rgba(234,179,8,.3);font-size:.78rem;color:#fbbf24">'
        + '&#9719; Consulta ampliada: a an&aacute;lise de acompanhantes pode levar um pouco mais de tempo.</div>';
    } else if (_compWindow === '180d') {
      warnHtml = '<div style="margin-top:8px;padding:7px 12px;border-radius:7px;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);font-size:.78rem;color:#f87171">'
        + '&#9888; Consulta extensa: a an&aacute;lise de acompanhantes em 180 dias pode levar mais tempo.</div>';
    }
    var header = '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:4px">'
      + '<span style="font-size:.82rem;font-weight:700;color:var(--accent2);text-transform:uppercase;letter-spacing:.06em">&#128101; Acompanhantes / Comboio</span>'
      + (companions.length ? '<span style="font-size:.76rem;color:var(--muted)">' + companions.length + ' ve&iacute;culo(s) &bull; ' + _alvoDvFmtWindow(_compWindow) + '</span>' : '')
      + '</div>'
      + warnHtml;

    if (companions.length === 0) {
      el.innerHTML = '<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 20px">'
        + header
        + '<div style="color:var(--muted);font-size:.85rem;padding:10px 0">Nenhum ve&iacute;culo encontrado viajando junto nos &uacute;ltimos ' + _alvoDvFmtWindow(_compWindow) + '.</div>'
        + '</div>';
      return;
    }

    var rows = companions.map(function(c) {
      var alvo    = alvoMap[c.companion];
      var desc    = alvo && alvo.descricao
        ? '<span style="font-size:.75rem;color:var(--text);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block" title="' + alvo.descricao.replace(/"/g,'&quot;') + '">' + alvo.descricao + '</span>'
        : '<span style="color:var(--muted);font-size:.75rem">&mdash;</span>';
      var alvoBadge = alvo
        ? ' <span style="font-size:.68rem;font-weight:700;background:#7c3aed;color:#fff;padding:1px 7px;border-radius:99px;white-space:nowrap;vertical-align:middle">ALVO</span>'
        : '';
      // papel baseado em leads
      var tot = (c.companion_leads + c.target_leads) || 1;
      var clPct = Math.round(c.companion_leads / tot * 100);
      var tgPct = Math.round(c.target_leads   / tot * 100);
      var roleBadge;
      if (clPct >= 70) {
        roleBadge = '<span style="font-size:.68rem;font-weight:700;background:#dc2626;color:#fff;padding:1px 8px;border-radius:99px;white-space:nowrap">BATEDOR</span>';
      } else if (tgPct >= 70) {
        roleBadge = '<span style="font-size:.68rem;font-weight:700;background:#d97706;color:#fff;padding:1px 8px;border-radius:99px;white-space:nowrap">SEGUIDOR</span>';
      } else {
        roleBadge = '<span style="font-size:.68rem;font-weight:700;background:#6366f1;color:#fff;padding:1px 8px;border-radius:99px;white-space:nowrap">COMBOIO</span>';
      }
      // última vez junto
      var lastTog = c.last_seen
        ? new Date(c.last_seen).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'})
        : '<span style="color:var(--muted)">&mdash;</span>';
      // local: primeira câmera da evidência
      var ev0    = (c.evidence || [])[0];
      var localStr = ev0 ? (ev0.camera || ev0.camera_id || '&mdash;') : '&mdash;';
      // ações
      var btnDetalhe = alvo
        ? '<button class="btn btn-outline btn-xs" onclick="alvoVer(' + alvo.id + ',\''+alvo.plate+'\',\''+((alvo.descricao||'').replace(/\'/g,"\'\'"))+'\')">&#128269; Visualizar</button> '
        : '';
      var safeComp = c.companion.replace(/'/g,"\\'");
      var btnBuscar = '<button class="btn btn-outline btn-xs" onclick="_alvoCompSearch(\''+safeComp+'\')" title="Buscar esta placa no Batedor">&#128301; Batedor</button>';
      return '<tr>'
        + '<td style="font-weight:700;font-family:monospace;font-size:.88rem;white-space:nowrap;letter-spacing:.06em">' + c.companion + alvoBadge + '</td>'
        + '<td>' + desc + '</td>'
        + '<td style="text-align:center">' + roleBadge + '<br><span style="font-size:.72rem;color:var(--muted);white-space:nowrap">' + c.cameras_together + ' c&acirc;m.</span></td>'
        + '<td style="white-space:nowrap;font-size:.78rem;color:var(--muted)">' + lastTog + '</td>'
        + '<td style="font-size:.75rem;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + localStr + '">' + localStr + '</td>'
        + '<td class="action-cell"><div class="action-buttons">' + btnDetalhe + btnBuscar + '</div></td>'
        + '</tr>';
    }).join('');

    el.innerHTML = '<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden">'
      + '<div style="padding:12px 16px 8px 16px">' + header + '</div>'
      + '<div class="table-wrap" style="margin:0"><table><thead><tr>'
      + '<th>Placa</th>'
      + '<th>Descri&ccedil;&atilde;o</th>'
      + '<th style="text-align:center">Papel / Cooc.</th>'
      + '<th style="white-space:nowrap">&Uacute;ltima vez junto</th>'
      + '<th>Local / C&acirc;mera</th>'
      + '<th style="white-space:nowrap">A&ccedil;&otilde;es</th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table></div>'
      + '</div>';
  } catch(e) {
    el.innerHTML = '<div style="color:var(--danger);font-size:.82rem;padding:6px 0">Erro ao carregar acompanhantes: ' + e + '</div>';
  }
}

function _alvoCompSearch(plate) {
  plate = String(plate || '').trim().toUpperCase();
  if (!plate) return;
  var nav = document.querySelector('.nav-item[onclick*="batedor"]');
  if (nav && typeof switchTab === 'function') switchTab('batedor', nav);
  var subTab = document.getElementById('bat-subtab-placas');
  if (subTab && typeof switchBatTab === 'function') switchBatTab('placas', subTab);
  var inp = document.getElementById('cen-single-plate');
  if (inp) inp.value = plate;
  if (typeof _cenSingleSearch === 'function') _cenSingleSearch(plate);
}

// ── Alvo: Busca histórico filtrado ───────────────────────────────────────────
async function _alvoDvAplicar() {
  var rangeVal = (document.getElementById('alvo-dv-range')  || {value:'7d'}).value || '7d';
  var janela   = (document.getElementById('alvo-dv-janela') || {value:''}).value    || '';
  var mincam   = (document.getElementById('alvo-dv-mincam') || {value:''}).value    || '';
  var res = document.getElementById('alvo-dv-resultados');
  if (!res) return;
  res.innerHTML = '<p style="color:var(--muted);padding:8px 0"><span class="spinner"></span> Carregando hist&oacute;rico de passagens&hellip;</p>';
  var params = [];
  if (rangeVal !== 'custom') {
    params.push('periodo=' + encodeURIComponent(rangeVal));
  } else {
    var start = (document.getElementById('alvo-dv-start') || {value:''}).value || '';
    var end   = (document.getElementById('alvo-dv-end')   || {value:''}).value || '';
    if (start) params.push('start=' + encodeURIComponent(start));
    if (end)   params.push('end='   + encodeURIComponent(end));
  }
  if (janela) params.push('janela_min=' + encodeURIComponent(janela));
  if (mincam) params.push('min_cameras=' + encodeURIComponent(mincam));
  var url = '/api/alvos/' + _alvoDvId + '/historico?' + params.join('&');
  try {
    var resp = await fetch(url);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var d = await resp.json();
    _alvoDvRenderHistorico(d, rangeVal, janela, mincam);
  } catch(e) {
    res.innerHTML = '<p style="color:var(--danger);padding:8px 0">Erro ao carregar hist&oacute;rico: ' + e + '</p>';
  }
  // Recarrega acompanhantes respeitando os mesmos filtros ativos
  if (_alvoDvId && _alvoDvPlate) _alvoDvLoadCompanions(_alvoDvId, _alvoDvPlate);
}

// ── Alvo: Limpa filtros e re-executa ─────────────────────────────────────────
function _alvoDvLimpar() {
  [['alvo-dv-range','7d'],['alvo-dv-janela',''],['alvo-dv-mincam',''],
   ['alvo-dv-start',''],['alvo-dv-end','']].forEach(function(f) {
    var el = document.getElementById(f[0]); if (el) el.value = f[1];
  });
  _alvoDvPeriodChange();
  _alvoDvAplicar();
}

// ── Alvo: Renderiza tabela de histórico ──────────────────────────────────────
function _alvoDvRenderHistorico(d, rangeVal, janela, mincam) {
  var res = document.getElementById('alvo-dv-resultados');
  if (!res) return;
  var jLabel = {'1':'1 min','5':'5 min','10':'10 min','15':'15 min','30':'30 min','60':'1 hora'};
  var rLabel = {'24h':'24 horas','7d':'7 dias','15d':'15 dias','30d':'30 dias','custom':'per&iacute;odo personalizado'};
  var chips = [];
  chips.push('<span style="background:rgba(250,204,21,.15);color:var(--accent);border:1px solid rgba(250,204,21,.3);border-radius:99px;padding:2px 10px;font-size:.75rem;font-weight:600">&#128197; ' + (rLabel[rangeVal] || rangeVal) + '</span>');
  if (janela) chips.push('<span style="background:rgba(99,102,241,.15);color:#a5b4fc;border:1px solid rgba(99,102,241,.3);border-radius:99px;padding:2px 10px;font-size:.75rem;font-weight:600">&#9201; janela: ' + (jLabel[janela] || janela + ' min') + '</span>');
  if (mincam) chips.push('<span style="background:rgba(16,185,129,.15);color:#6ee7b7;border:1px solid rgba(16,185,129,.3);border-radius:99px;padding:2px 10px;font-size:.75rem;font-weight:600">&#128247; &ge;' + mincam + ' c&acirc;m.</span>');
  if (!d.events || d.events.length === 0) {
    res.innerHTML = '<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:32px 24px">'
      + '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">' + chips.join('') + '</div>'
      + '<div style="color:var(--muted);font-size:.95rem;text-align:center">Nenhuma passagem encontrada com os filtros selecionados.</div>'
      + '<div style="color:var(--muted);font-size:.8rem;text-align:center;margin-top:6px">Tente ampliar o per&iacute;odo ou modificar os filtros.</div>'
      + '</div>';
    return;
  }
  var html = '<div style="display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px">'
    + '<span style="font-size:.95rem;font-weight:700">&#128336; ' + d.total + ' passagem(ns)</span>'
    + '<span style="font-size:.82rem;color:var(--muted)">&middot; ' + d.cameras_count + ' c&acirc;mera(s) no per&iacute;odo</span>'
    + '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-left:4px">' + chips.join('') + '</div>'
    + '</div>'
    + '<div class="table-wrap"><table><thead><tr>'
    + '<th style="white-space:nowrap">Data / Hora</th>'
    + '<th>C&acirc;mera</th>'
    + '<th>Dire&ccedil;&atilde;o</th>'
    + '<th style="text-align:center">Confian&ccedil;a</th>'
    + '<th style="text-align:center">Imagem</th>'
    + '</tr></thead><tbody>';
  d.events.forEach(function(ev) {
    var ts   = ev.occurred_at ? new Date(ev.occurred_at).toLocaleString('pt-BR') : '&mdash;';
    var cam  = ev.camera || ev.channel_name || ev.camera_id || '&mdash;';
    var dir  = ev.direcao ? ev.direcao : '<span style="color:var(--muted)">&mdash;</span>';
    var pct  = ev.confidence ? Math.round(ev.confidence * 100) : 0;
    var cc   = pct >= 80 ? '#4ade80' : pct >= 60 ? '#facc15' : 'var(--muted)';
    var conf = ev.confidence
      ? '<span style="color:' + cc + ';font-weight:700">' + pct + '%</span>'
      : '<span style="color:var(--muted)">&mdash;</span>';
    var imgUrl = normalizeImageUrl(ev.image_path);
    var img  = imgUrl
      ? '<img src="' + imgUrl + '" style="height:44px;border-radius:5px;cursor:pointer;border:1px solid var(--border)" onclick="window.open(this.src,\'_blank\')" onerror="this.style.display=\'none\'" loading="lazy">'
      : '<span style="color:var(--muted);font-size:.75rem">sem imagem</span>';
    html += '<tr>'
      + '<td style="white-space:nowrap;font-size:.82rem">' + ts + '</td>'
      + '<td style="font-size:.82rem">' + cam + '</td>'
      + '<td style="font-size:.82rem">' + dir + '</td>'
      + '<td style="text-align:center">' + conf + '</td>'
      + '<td style="text-align:center">' + img + '</td>'
      + '</tr>';
  });
  html += '</tbody></table></div>';
  res.innerHTML = html;
}

// ── Alvo: Ver (abre tela full-screen) ────────────────────────────────────────
async function alvoVer(id, plate, descricao, desde) {
  _alvoDvId    = id;
  _alvoDvPlate = (plate || '').replace(/&#39;/g, "'");
  var descReal = (descricao || '').replace(/&#39;/g, "'");
  // esconde todos os sub-panes do batedor e desmarca abas
  ['central', 'grupos', 'alvos'].forEach(function(n){
    var el2 = document.getElementById('bat-sub-'+n);
    if (el2) el2.classList.remove('active');
  });
  document.querySelectorAll('#bat-sub-tabs .sub-tab').forEach(function(t){ t.classList.remove('active'); });
  var view = document.getElementById('alvo-detalhe-view');
  if (!view) return;
  view.classList.add('active');
  document.getElementById('alvo-dv-titulo').innerHTML =
    '&#127919; Alvo: <span style="color:#f87171;font-weight:800;font-family:monospace;letter-spacing:.1em">' + _alvoDvPlate + '</span>';
  // reseta caches de prioridade
  _alvoDvDetalhesCache  = null;
  _alvoDvCompanionsCache = [];
  _alvoDvPassagensCache  = [];
  var _prioEl = document.getElementById('alvo-dv-prioridade');
  if (_prioEl) _prioEl.innerHTML = '<span style="font-size:.72rem;color:var(--muted);font-style:italic">Classificando&hellip;</span>';
  // reseta filtros
  var rEl = document.getElementById('alvo-dv-range');  if (rEl) rEl.value = '7d';
  var jEl = document.getElementById('alvo-dv-janela'); if (jEl) jEl.value = '';
  var mEl = document.getElementById('alvo-dv-mincam'); if (mEl) mEl.value = '';
  var ds  = document.getElementById('alvo-dv-start');  if (ds)  ds.value  = '';
  var de  = document.getElementById('alvo-dv-end');    if (de)  de.value  = '';
  _alvoDvPeriodChange();
  _alvoDvLoadDetalhes(id, descReal, desde);
  _alvoDvLoadPassagens(id);
  _alvoDvLoadCompanions(id, _alvoDvPlate);
  _alvoDvAplicar();
}

// ── Alvo: Editar (admin + operador) ──────────────────────────────────────────
function alvoEditar(id, plate, descricao) {
  editAlvo(id, plate, descricao); // delega à função existente
}

// ── Alvo: Apagar (somente admin) ─────────────────────────────────────────────
async function alvoApagar(id, plate) {
  if (window._authRole !== 'admin') {
    alert('Apenas administradores podem apagar alvos rastreados.');
    return;
  }
  if (!confirm('Apagar alvo ' + plate + '? Esta ação é irreversível.')) return;
  await fetch('/api/alvos/' + id, {method: 'DELETE'});
  var card = document.getElementById('alvo-card-' + id);
  if (card) card.remove();
  var st = document.getElementById('alvos-status');
  if (st) { var t = parseInt(st.textContent); if (!isNaN(t)) st.textContent = (t - 1) + ' alvo(s)'; }
}

function editAlvo(id, plate, descricao) {
  _editAlvoId = id;
  var _pi = document.getElementById('alvo-plate-input');
  var _di = document.getElementById('alvo-desc-input');
  if (_pi) _pi.value = plate;
  if (_di) _di.value = descricao.replace(/&#39;/g, "'");
  var btn = document.querySelector('[onclick="addAlvo()"]');
  if (btn) {
    btn.textContent = '&#9998; Salvar';
    btn.innerHTML   = '&#9998; Salvar';
    btn.setAttribute('onclick', 'saveEditAlvo()');
    btn.style.background = 'var(--warning)';
  }
  if (_pi) _pi.focus();
}

function _resetAlvoForm() {
  _editAlvoId = null;
  var _pi = document.getElementById('alvo-plate-input');
  var _di = document.getElementById('alvo-desc-input');
  if (_pi) _pi.value = '';
  if (_di) _di.value = '';
  var btn = document.querySelector('[onclick="saveEditAlvo()"]');
  if (btn) {
    btn.innerHTML = '&#43; Adicionar';
    btn.setAttribute('onclick', 'addAlvo()');
    btn.style.background = '';
  }
}

async function saveEditAlvo() {
  var plate = (document.getElementById('alvo-plate-input').value || '').trim().toUpperCase();
  var desc  = (document.getElementById('alvo-desc-input').value || '').trim();
  if (!plate) { alert('Informe a placa.'); return; }
  var resp = await fetch('/api/alvos/' + _editAlvoId, {
    method: 'PUT',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({plate: plate, descricao: desc})
  });
  if (!resp.ok) { alert('Erro ao salvar: ' + await resp.text()); return; }
  _resetAlvoForm();
  loadAlvos();
}

async function addAlvo() {
  var plate = (document.getElementById('alvo-plate-input').value || '').trim().toUpperCase();
  var desc  = (document.getElementById('alvo-desc-input').value || '').trim();
  if (!plate) { alert('Informe a placa do suspeito.'); return; }
  var resp = await fetch('/api/alvos', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({plate: plate, descricao: desc})
  });
  if (!resp.ok) { alert('Erro ao adicionar: ' + await resp.text()); return; }
  _resetAlvoForm();
  loadAlvos();
}

async function removeAlvo(id, plate) {
  if (!confirm('Remover alvo ' + plate + '?')) return;
  await fetch('/api/alvos/' + id, {method:'DELETE'});
  var card = document.getElementById('alvo-card-' + id);
  if (card) card.remove();
}

// ===== MONITORAMENTO BATEDOR EM TEMPO REAL =====
var _batedorSeen = {}; // chave: 'plateA|plateB', valor: timestamp último alerta
var _batedorAtivos = 0;
var _realtimeEnabled = true;
var _realtimeInterval = null;
var _batNotifEnabled = false;

function toggleBatNotif() {
  _batNotifEnabled = !_batNotifEnabled;
  var btn   = document.getElementById('btn-bat-notif');
  var label = document.getElementById('bat-notif-label');
  if (_batNotifEnabled) {
    btn.classList.remove('btn-outline'); btn.classList.add('btn-success');
    label.innerHTML = 'Notif. ON <span class="dot" style="display:inline-block;margin-left:3px"></span>';
  } else {
    btn.classList.remove('btn-success'); btn.classList.add('btn-outline');
    label.textContent = 'Notif. OFF';
  }
}

function toggleRealtime() {
  _realtimeEnabled = !_realtimeEnabled;
  var btn   = document.getElementById('btn-monitor-toggle');
  var label = document.getElementById('monitor-toggle-label');
  if (!btn || !label) {
    if (_realtimeEnabled && !_realtimeInterval) {
      checkBatedorRealtime();
      _realtimeInterval = setInterval(checkBatedorRealtime, 60000);
    }
    if (!_realtimeEnabled && _realtimeInterval) {
      clearInterval(_realtimeInterval);
      _realtimeInterval = null;
    }
    return;
  }
  if (_realtimeEnabled) {
    btn.classList.remove('btn-outline');
    btn.classList.add('btn-success');
    label.innerHTML = 'ATIVO <span class="dot" style="display:inline-block;margin-left:4px"></span>';
    if (_realtimeInterval) {
      clearInterval(_realtimeInterval);
      _realtimeInterval = null;
    }
    checkBatedorRealtime(); // roda imediatamente
    _realtimeInterval = setInterval(checkBatedorRealtime, 60000);
  } else {
    btn.classList.remove('btn-success');
    btn.classList.add('btn-outline');
    label.textContent = 'OFF';
    if (_realtimeInterval) { clearInterval(_realtimeInterval); _realtimeInterval = null; }
    // limpa badge
    var badge = document.getElementById('bat-live-badge');
    if (badge) badge.style.display = 'none';
  }
}

async function checkBatedorRealtime() {
  if (!_realtimeEnabled) return;
  try {
    var resp = await fetch('/api/batedor/central?window=2h&limit=100');
    if (!resp.ok) return;
    var data = await resp.json();
    var items = data.items || [];

    // Placas com badge COMBOIO ou MULTI-CÂMERA e score alto
    var ameacas = items.filter(function(it) {
      return it.score_total >= 40 || (it.badges && (it.badges.indexOf('COMBOIO') >= 0 || it.badges.indexOf('MULTI-CÂMERA') >= 0));
    });

    var totalAtivos = ameacas.length;

    ameacas.forEach(function(it) {
      var chave = it.plate + '|' + (it.last_seen || '');
      var ultimoLs = _batedorSeen[chave];
      if (ultimoLs === it.last_seen) return; // sem mudança
      _batedorSeen[chave] = it.last_seen;

      if (_batNotifEnabled) {
        triggerComboio(it.plate, '?', null, it.cameras_count || 1, 0);
      }
    });

    _batedorAtivos = totalAtivos;
    var badge = document.getElementById('bat-live-badge');
    var count = document.getElementById('bat-live-count');
    if (badge && count) {
      count.textContent = totalAtivos;
      badge.style.display = totalAtivos > 0 ? '' : 'none';
    }
    checkAlvosRealtime();
  } catch(e) { /* silencioso */ }
}

// Monitoramento inicia apenas quando o usuário clicar em "Monitor OFF"

var _alvoCompanionSeen = {}; // chave: 'alvoPlate|companionPlate'
var _alvoCoWindow = 300; // janela co-detecção padrão (1..1000s)
async function checkAlvosRealtime() {
  try {
    var agora = Date.now();

    // 1. Avistamentos diretos: alvo com 2+ câmeras na última meia hora
    var sr = await fetch('/api/alvos/recentes?window=30m');
    if (sr.ok) {
      var sd = await sr.json();
      (sd.sightings || []).forEach(function(s) {
        var cameras = s.cameras || [];
        // alerta para cada câmera nova individualmente
        cameras.forEach(function(c) {
          var chave    = s.plate + '|' + c.camera_id;
          var ultimoLs = _alvoAvistadoSeen[chave];
          var novoLs   = c.last_seen || null;
          // só re-alerta se houver nova passagem (last_seen mudou)
          if (ultimoLs && novoLs && new Date(novoLs) <= new Date(ultimoLs)) return;
          _alvoAvistadoSeen[chave] = novoLs;
          var detalhe = 'C\u00e2mera: <strong>' + c.camera_id + '</strong>'
            + ' &mdash; ' + s.total_cameras + ' c\u00e2mera(s) no total'
            + (s.descricao ? '<br><span style="opacity:.85">' + s.descricao + '</span>' : '');
          // dispara toast e registra no painel
          _toastPlates['avistado'] = s.plate;
          addAlert('avistado', '&#127919;', s.plate, detalhe, {type:'avistado', plate:s.plate});
          var toast = document.getElementById('alvo-avistado-toast');
          document.getElementById('alvo-avistado-plate').textContent = s.plate;
          document.getElementById('alvo-avistado-desc').innerHTML =
            'C\u00e2mera: <strong>' + c.camera_id + '</strong>'
            + ' <span style="opacity:.7;font-size:.78rem">(' + s.total_cameras + ' c\u00e2meras no per\u00edodo)</span>'
            + (s.descricao ? '<br><span style="opacity:.85">' + s.descricao + '</span>' : '');
          toast.style.display = 'block';
          if (_alvoAvistadoTimer) clearTimeout(_alvoAvistadoTimer);
          _alvoAvistadoTimer = setTimeout(function(){ toast.style.display = 'none'; }, 12000);
          try {
            var ctx = _getAudioCtx(); var t = ctx.currentTime;
            [440, 660].forEach(function(freq, i) {
              var osc = ctx.createOscillator(); var g = ctx.createGain();
              osc.connect(g); g.connect(ctx.destination);
              osc.type = 'sine'; osc.frequency.value = freq;
              g.gain.setValueAtTime(0.35, t + i*0.22);
              g.gain.exponentialRampToValueAtTime(0.001, t + i*0.22 + 0.25);
              osc.start(t + i*0.22); osc.stop(t + i*0.22 + 0.28);
            });
          } catch(e2) {}
          console.warn('[ALVO AVISTADO]', s.plate, 'na câmera', c.camera_id,
            '— total câmeras:', s.total_cameras);
        });
      });
    }

    // 2. Companheiros: alguém está acompanhando o alvo?
    var resp = await fetch('/api/alvos');
    var data = await resp.json();
    var alvos = data.alvos || [];
    if (alvos.length === 0) return;
    for (var i = 0; i < alvos.length; i++) {
      var a = alvos[i];
      var cr = await fetch('/api/batedor/companions/' + encodeURIComponent(a.plate) + '?window=2h&co_window=' + _alvoCoWindow + '&min_cameras=2&trip_max=3600&limit=10');
      if (!cr.ok) continue;
      var cd = await cr.json();
      (cd.companions || []).forEach(function(c) {
        if (c.cameras_together < 2) return; // exige 2+ câmeras
        var chave    = a.plate + '|' + c.companion;
        var ultimoLs = _alvoCompanionSeen[chave];
        var novoLs   = c.last_seen || null;
        // só re-alerta se houver nova passagem (last_seen mudou)
        if (ultimoLs && novoLs && new Date(novoLs) <= new Date(ultimoLs)) return;
        _alvoCompanionSeen[chave] = novoLs;
        // determina quem é o batedor pelo lead %
        var tot = (c.companion_leads + c.target_leads) || 1;
        var compLeadPct = Math.round(c.companion_leads / tot * 100);
        var batedor, alvo;
        if (compLeadPct >= 55) { batedor = c.companion; alvo = a.plate; }
        else if ((100 - compLeadPct) >= 55) { batedor = a.plate; alvo = c.companion; }
        else return; // papéis ambíguos, não alarmar
        triggerComboio(batedor, alvo, null, c.cameras_together, c.avg_co_delta_sec);
        console.warn('[ALVO RASTREADO]', a.plate, '(', a.descricao, ') — batedor:', batedor, 'clareza:', compLeadPct + '%');
      });
    }
  } catch(e) { /* silencioso */ }
}

// ===== C\u00c2MERAS =====
var _cameraEditId = null;

var _cameraRows = [];
var _cameraStatusMap = {};
var _camSortField = 'id';
var _camSortDir   = 'asc';

function _setCamSort(field) {
  if (_camSortField === field) {
    _camSortDir = _camSortDir === 'asc' ? 'desc' : 'asc';
  } else {
    _camSortField = field;
    _camSortDir   = 'asc';
  }
  var labels = { id: 'ID', nome: 'Nome', ip: 'IP', status: 'Status' };
  ['id','nome','ip','status'].forEach(function(f) {
    var btn = document.getElementById('cam-sort-' + f);
    if (!btn) return;
    btn.classList.toggle('cam-sort-active', f === _camSortField);
    btn.innerHTML = labels[f] + (f === _camSortField ? ' ' + (_camSortDir === 'asc' ? '&#9650;' : '&#9660;') : '');
  });
  _renderCameras();
}

function _renderCameras() {
  var tbody = document.getElementById('cameras-tbody');
  if (!tbody) return;
  if (!_cameraRows.length) {
    tbody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--muted);padding:32px">Nenhuma c\u00e2mera cadastrada.</td></tr>';
    return;
  }
  var sorted = _cameraRows.slice().sort(function(a, b) {
    var va, vb;
    if (_camSortField === 'status') {
      va = _cameraStatusPriority(a.last_seen);
      vb = _cameraStatusPriority(b.last_seen);
      return _camSortDir === 'asc' ? va - vb : vb - va;
    }
    if (_camSortField === 'id') {
      return _camSortDir === 'asc' ? a.id - b.id : b.id - a.id;
    }
    if (_camSortField === 'ip') {
      // Comparação numérica por octeto para ordenar IPs corretamente
      function _ipToNum(ip) {
        if (!ip) return -1;
        return ip.split('.').reduce(function(acc, o){ return acc * 256 + parseInt(o, 10); }, 0);
      }
      var na = _ipToNum(a.ip), nb = _ipToNum(b.ip);
      return _camSortDir === 'asc' ? na - nb : nb - na;
    }
    va = (a[_camSortField] || '').toString().toLowerCase();
    vb = (b[_camSortField] || '').toString().toLowerCase();
    if (va < vb) return _camSortDir === 'asc' ? -1 :  1;
    if (va > vb) return _camSortDir === 'asc' ?  1 : -1;
    return 0;
  });
  tbody.innerHTML = sorted.map(function(c) {
    var critBadge  = c.criticidade === 'CRITICA' ? 'badge-red' : 'badge-green';
    var encoded    = encodeURIComponent(JSON.stringify(c));
    var statusDot  = _cameraStatusDot(c.last_seen);
    var modo       = 'push';
    var modoBadge  = '<span class="badge" style="background:rgba(34,197,94,.14);color:#bbf7d0;border:1px solid rgba(34,197,94,.28)">Push</span>';
    var lastSeenFmt = c.last_seen
      ? new Date(c.last_seen).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'})
      : '<span style="color:var(--muted)">Nunca</span>';
    var lastPostFmt = c.last_event_at
      ? new Date(c.last_event_at).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'})
      : null;
    var todayBadge = c.events_today > 0
      ? '<span class="badge badge-green">' + c.events_today + '</span>'
      : '<span style="color:var(--muted)">0</span>';
    var totalFmt = c.total_events > 0 ? c.total_events.toLocaleString('pt-BR') : '<span style="color:var(--muted)">0</span>';
    var pushDiag = '';
    if (modo === 'push') {
      if (!c.last_event_at) {
        pushDiag = '<div style="font-size:.72rem;color:#fca5a5;margin-top:3px">sem POST observado</div>';
      } else {
        var sameIp = !!(c.ip && c.last_event_camera_ip && c.ip === c.last_event_camera_ip);
        var sameId = !!(c.camera_id && c.last_event_camera_id && c.camera_id === c.last_event_camera_id);
        var pushColor = (sameIp || sameId) ? 'var(--muted)' : '#fca5a5';
        pushDiag = '<div style="font-size:.72rem;color:' + pushColor + ';margin-top:3px">últ. POST: '
          + _camEsc(c.last_event_camera_ip || c.last_event_camera_id || '?') + '</div>';
      }
    }
    return '<tr>'
      + '<td style="color:var(--muted)">'  + c.id + '</td>'
      + '<td style="color:var(--muted);font-size:.82rem">'  + _camEsc(c.camera_id || '\u2014') + '</td>'
      + '<td style="font-weight:600">'     + statusDot + _camEsc(c.nome) + pushDiag + '</td>'
      + '<td style="font-family:monospace;font-size:.82rem">' + _camEsc(c.ip || '\u2014') + '</td>'
      + '<td style="text-align:center">' + modoBadge + '</td>'
      + '<td><span class="badge ' + critBadge + '">' + _camEsc(c.criticidade || 'NORMAL') + '</span></td>'
      + '<td>' + parseFloat(c.peso_score != null ? c.peso_score : 1.0).toFixed(1) + '</td>'
      + '<td>' + (c.ativa ? '<span class="badge badge-green">Sim</span>' : '<span class="badge badge-red">N\u00e3o</span>') + '</td>'
      + '<td style="font-size:.8rem;white-space:nowrap">' + lastSeenFmt
      + (modo === 'push' && lastPostFmt ? '<div style="font-size:.71rem;color:var(--muted);margin-top:3px">push: ' + lastPostFmt + '</div>' : '')
      + '</td>'
      + '<td style="text-align:center">' + todayBadge + '</td>'
      + '<td style="text-align:center;font-size:.82rem">' + totalFmt + '</td>'
      + '<td style="text-align:center;font-size:.82rem">' + (c.direcao === 'CRESCENTE' ? '<span style="color:var(--accent);font-weight:700">&#8593; CRESCENTE</span>' : c.direcao === 'DECRESCENTE' ? '<span style="color:var(--accent);font-weight:700">&#8595; DECRESCENTE</span>' : '<span style="color:var(--muted)">&#8212;</span>') + '</td>'
      + '<td class="action-cell"><div class="action-buttons">'
      +   '<button class="btn btn-outline btn-xs" onclick="editCamera(decodeURIComponent(\'' + encoded + '\'))">&#9998; Editar</button>'
      +   '<button class="btn btn-danger btn-xs" onclick="deleteCamera(' + c.id + ',\'' + _camEsc(c.nome).replace(/'/g,'\x27') + '\')">&#128465; Excluir</button>'
      + '</div></td>'
      + '</tr>';
  }).join('');
}

async function loadCameras() {
  var tbody = document.getElementById('cameras-tbody');
  var err   = document.getElementById('cameras-error');
  var btn   = document.getElementById('btn-refresh-cameras');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--muted);padding:28px"><span class="spinner"></span> Carregando...</td></tr>';
  if (err) err.textContent = '';
  if (btn) { btn.disabled = true; btn.textContent = '\u29D7 Atualizando...'; }
  try {
    var r = await fetch('/api/cameras?include_inactive=true');
    if (!r.ok) {
      var ed = await r.json().catch(function(){ return {}; });
      throw new Error('HTTP ' + r.status + (ed.detail ? ' \u2014 ' + ed.detail : ''));
    }
    var d = await r.json();
    _cameraRows      = d.items || [];
    window._camsData = _cameraRows;
    _cameraStatusMap = {};
    _cameraRows.forEach(function(c){ if (c.last_seen) _cameraStatusMap[c.camera_id] = c.last_seen; });
    _renderCameras();
    populateEvCameraFilter(); // atualiza filtro de eventos com todas as câmeras
    _markTabLoaded('cameras');
  } catch(e) {
    if (err) err.textContent = 'Erro ao carregar c\u00e2meras: ' + e.message;
    tbody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--danger);padding:32px">Falha ao carregar.</td></tr>';
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '\u21bb Atualizar'; }
  }
}

function _camEsc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function _cameraStatusDot(lastSeenIso) {
  if (!lastSeenIso) return '<span title="Nunca detectado" style="color:#6b7280;font-size:.9em;margin-right:5px">&#9679;</span>';
  var mins = (Date.now() - new Date(lastSeenIso).getTime()) / 60000;
  if (mins < 15)  return '<span title="ONLINE \u2014 \u00faltimo evento h\u00e1 ' + Math.round(mins) + 'min" style="color:#22c55e;font-size:.9em;margin-right:5px">&#9679;</span>';
  if (mins < 60)  return '<span title="AGUARDANDO \u2014 ' + Math.round(mins) + 'min sem evento" style="color:#f59e0b;font-size:.9em;margin-right:5px">&#9679;</span>';
  var h = (mins/60);
  return '<span title="OFFLINE \u2014 \u00faltimo evento h\u00e1 ' + (h < 24 ? Math.round(h) + 'h' : Math.round(h/24) + 'd') + '" style="color:#ef4444;font-size:.9em;margin-right:5px">&#9679;</span>';
}

// 0=online, 1=aguardando, 2=offline, 3=nunca
function _cameraStatusPriority(lastSeenIso) {
  if (!lastSeenIso) return 3;
  var mins = (Date.now() - new Date(lastSeenIso).getTime()) / 60000;
  if (mins < 15) return 0;
  if (mins < 60) return 1;
  return 2;
}

function _camModoChange() {
  var field = document.getElementById('cam-modo-integracao');
  if (field) field.value = 'push';
}

function toggleCameraPasswordVisibility() {
  var input = document.getElementById('cam-senha');
  var btn = document.getElementById('cam-senha-toggle');
  if (!input || !btn) return;
  var show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.innerHTML = show ? '&#128584;' : '&#128065;';
  btn.setAttribute('aria-label', show ? 'Ocultar senha' : 'Mostrar senha');
  btn.setAttribute('title', show ? 'Ocultar senha' : 'Mostrar senha');
}

function openCameraModal(cam) {
  _cameraEditId = cam ? cam.id : null;
  document.getElementById('camera-modal-title').textContent = cam ? 'Editar Câmera' : 'Adicionar Câmera';
  var camIdField = document.getElementById('cam-camera-id');
  camIdField.value = cam ? (cam.camera_id || '') : '';
  camIdField.removeAttribute('readonly');
  camIdField.removeAttribute('tabindex');
  camIdField.style.opacity       = '1';
  camIdField.style.cursor        = '';
  camIdField.style.pointerEvents = '';
  document.getElementById('cam-id-hint').style.display = 'none';
  document.getElementById('cam-ip').value          = cam ? (cam.ip          || '') : '';
  document.getElementById('cam-usuario').value     = cam ? (cam.usuario     || '') : '';
  document.getElementById('cam-senha').value       = '';
  document.getElementById('cam-senha').type        = 'password';
  document.getElementById('cam-senha-toggle').innerHTML = '&#128065;';
  document.getElementById('cam-senha-toggle').setAttribute('aria-label', 'Mostrar senha');
  document.getElementById('cam-senha-toggle').setAttribute('title', 'Mostrar senha');
  document.getElementById('cam-direcao').value     = cam ? (cam.direcao     || '') : '';
  document.getElementById('cam-criticidade').value = cam ? (cam.criticidade || 'NORMAL') : 'NORMAL';
  document.getElementById('cam-peso-score').value  = cam ? (cam.peso_score  != null ? cam.peso_score : 1.0) : 1.0;
  document.getElementById('cam-latitude').value    = cam ? (cam.latitude  != null ? cam.latitude  : '') : '';
  document.getElementById('cam-longitude').value   = cam ? (cam.longitude != null ? cam.longitude : '') : '';
  document.getElementById('cam-ativa').checked     = cam ? !!cam.ativa : true;
  document.getElementById('cam-modo-integracao').value = cam ? (cam.modo_integracao || 'push') : 'push';
  var pwHint = document.getElementById('cam-senha-hint');
  pwHint.style.display = cam ? 'block' : 'none';
  pwHint.textContent = cam ? 'Deixe em branco para manter a senha atual.' : '';
  _camModoChange();
  document.getElementById('camera-form-error').textContent = '';

  // Barra de status — só exibe ao editar
  var bar = document.getElementById('cam-status-bar');
  if (cam) {
    var mins     = cam.last_seen ? (Date.now() - new Date(cam.last_seen).getTime()) / 60000 : null;
    var dot, label, bg;
    if (mins === null) {
      dot = '&#9679;'; label = 'Nunca detectado'; bg = 'rgba(107,114,128,.13)';
      bar.style.color = '#9ca3af';
    } else if (mins < 15) {
      dot = '&#9679;'; label = 'ONLINE — último evento há ' + Math.round(mins) + ' min'; bg = 'rgba(34,197,94,.13)';
      bar.style.color = '#22c55e';
    } else if (mins < 60) {
      dot = '&#9679;'; label = 'AGUARDANDO — ' + Math.round(mins) + ' min sem evento'; bg = 'rgba(245,158,11,.13)';
      bar.style.color = '#f59e0b';
    } else {
      var h = mins / 60;
      dot = '&#9679;'; label = 'OFFLINE — último evento há ' + (h < 24 ? Math.round(h) + 'h' : Math.round(h/24) + 'd'); bg = 'rgba(239,68,68,.13)';
      bar.style.color = '#ef4444';
    }
    var evHoje  = cam.events_today  > 0 ? cam.events_today  + ' hoje'  : '0 hoje';
    var evTotal = cam.total_events  > 0 ? cam.total_events.toLocaleString('pt-BR') + ' total' : '0 total';
    var lastFmt = cam.last_seen
      ? new Date(cam.last_seen).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'})
      : null;
    var modo = cam.modo_integracao || 'push';
    var diagParts = [];
    if (modo === 'push') {
      if (!cam.last_event_at) {
        diagParts.push('Push sem POST observado ainda');
      } else {
        var pushFmt = new Date(cam.last_event_at).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'});
        var origem  = cam.last_event_camera_ip || cam.last_event_camera_id || '?';
        var sameIp  = !!(cam.ip && cam.last_event_camera_ip && cam.ip === cam.last_event_camera_ip);
        var sameId  = !!(cam.camera_id && cam.last_event_camera_id && cam.camera_id === cam.last_event_camera_id);
        diagParts.push('Último POST: ' + pushFmt);
        diagParts.push('Origem vista: ' + origem + ((sameIp || sameId) ? '' : ' (verificar casamento)'));
      }
    }
    bar.style.background = bg;
    bar.style.display    = 'flex';
    bar.innerHTML =
      '<span style="font-size:1rem">' + dot + '</span>' +
      '<strong>' + label + '</strong>' +
      (lastFmt ? '<span style="color:var(--muted);font-size:.79rem">| último: ' + lastFmt + '</span>' : '') +
      '<span style="margin-left:auto;font-size:.79rem;color:var(--muted)">' + evHoje + ' &nbsp;·&nbsp; ' + evTotal + '</span>' +
      (diagParts.length
        ? '<div style="flex-basis:100%;font-size:.76rem;color:var(--muted);padding-top:4px;border-top:1px dashed rgba(255,255,255,.12)">' + diagParts.join(' &nbsp;·&nbsp; ') + '</div>'
        : '');
  } else {
    bar.style.display = 'none';
    bar.innerHTML = '';
  }

  openModal('camera-modal');
  setTimeout(function(){ document.getElementById('cam-camera-id').focus(); }, 80);
}

(function initCameraModalBindings(){
  function _bindCameraSave() {
    var btn = document.getElementById('camera-save-btn');
    var modal = document.getElementById('camera-modal');
    if (btn && !btn.dataset.bound) {
      btn.dataset.bound = '1';
      btn.addEventListener('click', function(event){
        event.preventDefault();
        saveCamera();
      });
    }
    if (modal && !modal.dataset.bound) {
      modal.dataset.bound = '1';
      modal.addEventListener('keydown', function(event){
        if (event.key === 'Enter' && !event.shiftKey) {
          var tag = (event.target && event.target.tagName || '').toUpperCase();
          if (tag !== 'TEXTAREA') {
            event.preventDefault();
            saveCamera();
          }
        }
      });
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _bindCameraSave);
  } else {
    _bindCameraSave();
  }
})();

function editCamera(encodedOrObj) {
  var cam = (typeof encodedOrObj === 'string') ? JSON.parse(decodeURIComponent(encodedOrObj)) : encodedOrObj;
  openCameraModal(cam);
}

async function saveCamera() {
  var cameraId    = document.getElementById('cam-camera-id').value.trim();
  var ip          = document.getElementById('cam-ip').value.trim();
  var usuario     = document.getElementById('cam-usuario').value.trim();
  var senha       = document.getElementById('cam-senha').value;
  var direcao     = document.getElementById('cam-direcao').value || null;
  var criticidade = document.getElementById('cam-criticidade').value;
  var peso_score  = parseFloat(document.getElementById('cam-peso-score').value) || 1.0;
  var ativa       = document.getElementById('cam-ativa').checked;
  var latRaw      = document.getElementById('cam-latitude').value.trim();
  var lngRaw      = document.getElementById('cam-longitude').value.trim();
  var latitude    = latRaw  !== '' ? parseFloat(latRaw)  : null;
  var longitude   = lngRaw  !== '' ? parseFloat(lngRaw) : null;
  var errEl       = document.getElementById('camera-form-error');
  errEl.textContent = '';
  if (!cameraId) { errEl.textContent = 'ID / Nome da câmera é obrigatório.'; return; }
  if (!ip) { errEl.textContent = 'IP da câmera é obrigatório.'; return; }
  if (!usuario) { errEl.textContent = 'Usuário da câmera é obrigatório.'; return; }
  if (!_cameraEditId && !senha.trim()) { errEl.textContent = 'Senha da câmera é obrigatória.'; return; }
  if (peso_score <= 0) { errEl.textContent = 'Peso Score deve ser maior que 0.'; return; }
  if (latRaw !== '' && (isNaN(latitude)  || latitude  < -90  || latitude  > 90))  { errEl.textContent = 'Latitude inválida (-90 a 90).';   return; }
  if (lngRaw !== '' && (isNaN(longitude) || longitude < -180 || longitude > 180)) { errEl.textContent = 'Longitude inválida (-180 a 180).'; return; }
  var body = { camera_id: cameraId, nome: cameraId, ip: ip, usuario: usuario, direcao: direcao, criticidade: criticidade, peso_score: peso_score, ativa: ativa, latitude: latitude, longitude: longitude, modo_integracao: 'push' };
  if (senha.trim()) body.senha = senha.trim();
  try {
    var url    = _cameraEditId ? '/api/cameras/' + _cameraEditId : '/api/cameras';
    var method = _cameraEditId ? 'PUT' : 'POST';
    var r = await fetch(url, { method: method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!r.ok) {
      var ed = await r.json().catch(function(){ return {}; });
      throw new Error('HTTP ' + r.status + (ed.detail ? ' — ' + ed.detail : ''));
    }
    closeModal('camera-modal');
    await loadCameras();
    alert(_cameraEditId ? 'Câmera atualizada com sucesso.' : 'Câmera adicionada com sucesso.');
  } catch(e) {
    errEl.textContent = 'Erro: ' + e.message;
  }
}

async function deleteCamera(id, nome) {
  if (!confirm('Excluir a câmera "' + nome + '"?\nEsta ação não pode ser desfeita.')) return;
  var err = document.getElementById('cameras-error');
  if (err) err.textContent = '';
  try {
    var r = await fetch('/api/cameras/' + id, { method: 'DELETE' });
    if (!r.ok) {
      var ed = await r.json().catch(function(){ return {}; });
      throw new Error('HTTP ' + r.status + (ed.detail ? ' — ' + ed.detail : ''));
    }
    await loadCameras();
  } catch(e) {
    var msg = 'Erro ao excluir câmera: ' + e.message;
    if (err) err.textContent = msg;
    alert(msg);
  }
}

// ===== MAPA DE CÂMERAS (Google Maps) =====
var _googleMap        = null;
var _trajViewerPrevTab = null; // compat: null = janela fechada
var _trajViewerReturn  = null; // { reopen: fn, label: string }
var _trajMapContentHome = null;
var _detailModalReturnFn = null;
var _relModalReturnFn    = null;
var _relModalCloseRestoreFn = null;
var _mapaMarkers      = [];
var _mapaInfoWindows  = [];
var _mapaTrajetoria   = null;  // {plates:[], points:[{camera_id,ts,plate,cam_nome}]}
var _trajetoriaLayers = [];
var _mapaTrajMode     = false; // true = chamado direto do mapa (exige input de placa)
var _mapaHeatLayer    = null;
var _mapaHeatActive   = false;
var _mapaAutoTimer    = null;
var _mapaCacheItems   = [];   // cache da última lista de câmeras com GPS
var _TRAJ_COLOR       = '#ff0000';
var _TRAJ_GAP_COLOR   = '#ff0000';
var _TRAJ_SHADOW      = '#000000';

function _clearTrajectoryLayers() {
  _trajetoriaLayers.forEach(function(l) {
    if (l && l.setMap) l.setMap(null);
    if (l && l.remove) l.remove();
  });
  _trajetoriaLayers = [];
}

// --- Filtrar eventos por câmera a partir do mapa ---
function _filtrarEventosPorCamera(cameraId) {
  // Fecha todos os InfoWindows abertos
  _mapaInfoWindows.forEach(function(iw) { iw.close(); });
  curCamera = cameraId;
  var sel = document.getElementById('ev-camera');
  if (sel) sel.value = cameraId;
  var evNav = document.querySelector('.nav-item[onclick*="eventos"]');
  if (evNav) evNav.click();
  else { loadEvents(0); }
}

// --- Heat Map ---
function _toggleHeatMap() {
  _mapaHeatActive = !_mapaHeatActive;
  var btn = document.getElementById('btn-mapa-heat');
  if (!_googleMap || !_checkGoogleMapsLoaded()) {
    alert('Aguarde o Google Maps carregar completamente.');
    _mapaHeatActive = false;
    return;
  }
  if (_mapaHeatActive) {
    // Verifica se a biblioteca de visualização está disponível
    if (!google.maps.visualization || !google.maps.visualization.HeatmapLayer) {
      alert('Biblioteca de visualização do Google Maps não disponível.');
      _mapaHeatActive = false;
      return;
    }
    // Constrói pontos com intensidade = total_events (normalizado)
    var maxEvt = Math.max(1, _mapaCacheItems.reduce(function(m, c) { return Math.max(m, c.total_events || 0); }, 0));
    var heatmapData = [];
    _mapaCacheItems.forEach(function(c) {
      if (c.latitude != null && c.longitude != null && (c.total_events || 0) > 0) {
        var weight = (c.total_events || 1) / maxEvt;
        heatmapData.push({
          location: new google.maps.LatLng(c.latitude, c.longitude),
          weight: weight
        });
      }
    });
    if (!heatmapData.length) {
      alert('Nenhuma câmera com GPS e eventos detectados para gerar o heat map.');
      _mapaHeatActive = false;
      return;
    }
    try {
      _mapaHeatLayer = new google.maps.visualization.HeatmapLayer({
        data: heatmapData,
        map: _googleMap,
        radius: 35,
        opacity: 0.7,
        gradient: [
          'rgba(0, 255, 0, 0)',
          'rgba(34, 197, 94, 1)',    // verde
          'rgba(245, 158, 11, 1)',   // amarelo
          'rgba(239, 68, 68, 1)',    // vermelho
          'rgba(255, 255, 255, 1)'   // branco
        ]
      });
      if (btn) { btn.textContent = '\u274c Fechar Heat Map'; btn.classList.add('cam-sort-active'); }
    } catch(e) {
      console.error('[Heat Map]', e);
      alert('Erro ao criar heat map: ' + e.message);
      _mapaHeatActive = false;
    }
  } else {
    if (_mapaHeatLayer) { _mapaHeatLayer.setMap(null); _mapaHeatLayer = null; }
    if (btn) { btn.textContent = '\uD83D\uDD25 Heat Map'; btn.classList.remove('cam-sort-active'); }
  }
}

// --- Auto-refresh de status ---
function _stopMapaAutoRefresh() {
  if (_mapaAutoTimer) { clearInterval(_mapaAutoTimer); _mapaAutoTimer = null; }
  var btn = document.getElementById('btn-mapa-auto');
  if (btn) { btn.textContent = '\u25EF Auto-refresh: OFF'; btn.classList.remove('cam-sort-active'); }
}

async function _mapaRefreshStatus() {
  // Atualiza apenas as cores dos marcadores existentes sem rebuild do mapa
  if (!_googleMap || !_mapaCacheItems.length) return;
  try {
    var r = await fetch('/api/cameras/status');
    if (!r.ok) return;
    var d = await r.json();
    var statusMap = d.status || {};
    _mapaMarkers.forEach(function(m, i) {
      var c = _mapaCacheItems.filter(function(x) { return x.latitude != null && x.longitude != null; })[i];
      if (!c) return;
      var lastSeen = statusMap[c.camera_id] || null;
      var color    = _mapaStatusColor(lastSeen, c.ativa);
      // Atualiza cor do marker no Google Maps
      m.setIcon({
        path: google.maps.SymbolPath.CIRCLE,
        scale: 7,
        fillColor: color,
        fillOpacity: 1,
        strokeColor: 'rgba(255,255,255,0.85)',
        strokeWeight: 2
      });
    });
  } catch(e) { /* silencioso */ }
}

function _toggleMapaAutoRefresh() {
  var btn = document.getElementById('btn-mapa-auto');
  if (_mapaAutoTimer) {
    _stopMapaAutoRefresh();
  } else {
    _mapaAutoTimer = setInterval(_mapaRefreshStatus, 30000);
    if (btn) { btn.textContent = '\u25CF Auto-refresh: 30s'; btn.classList.add('cam-sort-active'); }
  }
}

// ── Viewer temporário de trajetória (overlay sobre aba atual) ────────────
function _setTrajViewerReturn(reopenFn, label) {
  _trajViewerReturn = (typeof reopenFn === 'function')
    ? { reopen: reopenFn, label: label || 'Voltar ao Relatório' }
    : null;
}

function _moverMapaParaModal() {
  var content = document.getElementById('tab-mapa-content');
  var host = document.getElementById('tab-mapa');
  var body = document.getElementById('traj-map-modal-body');
  if (!content || !host || !body) return false;
  _trajMapContentHome = host;
  if (content.parentNode !== body) body.appendChild(content);
  return true;
}

function _restaurarMapaDoModal() {
  var content = document.getElementById('tab-mapa-content');
  var host = _trajMapContentHome || document.getElementById('tab-mapa');
  if (!content || !host) return;
  if (content.parentNode !== host) host.appendChild(content);
}

async function _sincronizarMapaModal() {
  try {
    await loadMapa();
    if (_checkGoogleMapsLoaded() && _googleMap && google.maps && google.maps.event) {
      google.maps.event.trigger(_googleMap, 'resize');
    }
    if (_mapaTrajetoria && _mapaTrajetoria.points && _mapaTrajetoria.points.length) {
      _plotarTrajetoria();
    }
  } catch (e) {
    console.warn('[traj-map-modal]', e);
  }
}

function _abrirMapaOverlay(plate, infoLabel, reopenFn, label) {
  _trajViewerPrevTab = currentTab || '';
  if (typeof reopenFn === 'function') _setTrajViewerReturn(reopenFn, label);
  else _trajViewerReturn = null;
  if (!_moverMapaParaModal()) return;
  var plateEl = document.getElementById('traj-map-modal-plate');
  var infoEl = document.getElementById('traj-map-modal-info');
  if (plateEl) plateEl.textContent = plate || '';
  if (infoEl) infoEl.textContent = infoLabel || '';
  openModal('traj-map-modal');
  setTimeout(_sincronizarMapaModal, 180);
}

function _voltarRelatorioDoMapa() {
  _fecharMapaOverlay(false);
}

function _fecharMapaOverlay(restoreContext) {
  restoreContext = !!restoreContext;
  var returnCtx = _trajViewerReturn;
  _trajViewerPrevTab = null;
  _trajViewerReturn = null;
  closeModal('traj-map-modal');
  _restaurarMapaDoModal();
  _vehicleTrajData = null;
  _mapaTrajetoria = null;
  _clearTrajectoryLayers();
  var noGps = document.getElementById('map-no-gps');
  if (noGps) noGps.innerHTML = '';
  var trajStatus = document.getElementById('traj-map-status');
  if (trajStatus) trajStatus.innerHTML = '';
  var noGpsContainer = document.getElementById('traj-no-gps-container');
  if (noGpsContainer) noGpsContainer.style.display = 'none';
  var noGpsList = document.getElementById('traj-no-gps-list');
  if (noGpsList) noGpsList.textContent = '';
  if (document.getElementById('tab-mapa') && document.getElementById('tab-mapa').classList.contains('active')) {
    setTimeout(loadMapa, 80);
  }
  if (restoreContext && returnCtx && typeof returnCtx.reopen === 'function') {
    setTimeout(function() { returnCtx.reopen(); }, 120);
  }
}

function promptTrajetoria() {
  var plate = _reportCurrentPlate || '';
  if (!plate) return;
  _mapaTrajMode = false;
  document.getElementById('traj-picker-plate').textContent = plate;
  document.getElementById('traj-plate-input-row').style.display  = 'none';
  document.getElementById('traj-plate-display-row').style.display = '';
  document.getElementById('traj-picker-status').textContent = '';
  document.getElementById('traj-custom-row').style.display = 'none';
  // mostra botão definir novamente caso tenha sido escondido
  var defBtn = document.querySelector('#traj-picker-modal .btn-outline[onclick*="traj-custom-row"]');
  if (defBtn) defBtn.style.display = '';
  openModal('traj-picker-modal');
}

// Chamado pelo botão Trajetória direto na aba do mapa
function promptTrajetoriaMapa() {
  _mapaTrajMode = true;
  document.getElementById('traj-plate-input-row').style.display  = 'block';
  document.getElementById('traj-plate-display-row').style.display = 'none';
  document.getElementById('traj-plate-input').value = '';
  document.getElementById('traj-picker-status').textContent = '';
  document.getElementById('traj-custom-row').style.display = 'none';
  var defBtn = document.querySelector('#traj-picker-modal .btn-outline[onclick*="traj-custom-row"]');
  if (defBtn) defBtn.style.display = '';
  openModal('traj-picker-modal');
}

function _setMapaTrajetoriaFromApiData(data, fallbackPlate) {
  var plate = (fallbackPlate || data.plate || '').toUpperCase();
  var rawPoints = (data && data.points) ? data.points : [];
  _mapaTrajetoria = {
    plates: plate ? [plate] : [],
    points: rawPoints.map(function(p) {
      return {
        lat: p.lat,
        lng: p.lng != null ? p.lng : p.lon,
        ts: p.ts,
        plate: plate,
        camera_id: p.camera_id,
        cam_nome: p.camera_name || p.cam_nome || p.camera || p.camera_id,
        direcao: p.direction || p.direcao,
        confidence: p.confidence,
        vehicle_type: p.vehicle_type,
        vehicle_color: p.vehicle_color,
        seq: 0
      };
    }).filter(function(p) {
      return p.lat != null && p.lng != null;
    }),
    stats: {
      total_points: data.total_points || rawPoints.length || 0,
      total_events: data.total_events || rawPoints.length || 0,
      cameras_without_gps: data.cameras_without_gps || []
    }
  };
  return _mapaTrajetoria;
}

async function _loadTrajetoria(windowKey) {
  var plate;
  if (_mapaTrajMode) {
    plate = (document.getElementById('traj-plate-input').value || '').trim().toUpperCase();
  } else {
    plate = _reportCurrentPlate || '';
  }
  if (!plate) {
    document.getElementById('traj-picker-status').textContent = '⚠️ Informe a placa do veículo.';
    if (_mapaTrajMode) document.getElementById('traj-plate-input').focus();
    return;
  }
  var st = document.getElementById('traj-picker-status');
  st.innerHTML = '<span class="spinner"></span> Buscando passagens…';

  var now = Date.now();
  var tsFrom, tsTo = _toLocalDTInput(new Date(now));
  if (windowKey === '12h')   tsFrom = _toLocalDTInput(new Date(now - 12  * 3600000));
  else if (windowKey === '24h')  tsFrom = _toLocalDTInput(new Date(now - 24  * 3600000));
  else if (windowKey === '7d')   tsFrom = _toLocalDTInput(new Date(now -  7  * 86400000));
  else if (windowKey === '30d')  tsFrom = _toLocalDTInput(new Date(now - 30  * 86400000));
  else if (windowKey === 'custom') {
    var f = document.getElementById('traj-custom-from').value;
    var t = document.getElementById('traj-custom-to').value;
    if (!f || !t) { st.textContent = '\u26a0\ufe0f Informe as datas De e At\u00e9.'; return; }
    tsFrom = f;
    tsTo   = t;
  }

  try {
    // ── Novo endpoint dedicado de trajetória (já traz lat/lon) ──
    var url = '/api/vehicles/' + encodeURIComponent(plate) + '/trajectory'
            + '?start=' + encodeURIComponent(tsFrom)
            + '&end=' + encodeURIComponent(tsTo)
            + '&dedupe_seconds=5';
    var r = await fetch(url);
    if (!r.ok) {
      var errData = await r.json().catch(function(){ return {detail:'HTTP '+r.status}; });
      throw new Error(errData.detail || 'HTTP '+r.status);
    }
    var data = await r.json();
    
    if (!data.points || data.points.length === 0) {
      st.textContent = '\u26a0\ufe0f Nenhuma passagem encontrada neste período.';
      if (data.cameras_without_gps && data.cameras_without_gps.length > 0) {
        st.textContent += ' (Câmeras sem GPS: ' + data.cameras_without_gps.join(', ') + ')';
      }
      return;
    }

    _setMapaTrajetoriaFromApiData(data, plate);

    closeModal('traj-picker-modal');
    _abrirMapaOverlay(plate, (data.total_points || data.points.length) + ' passagem(ns)', _mapaTrajMode ? null : _detailModalReturnFn, 'Voltar ao Relatório');
    setTimeout(_plotarTrajetoria, 400);
  } catch(e) {
    st.textContent = 'Erro: ' + e.message;
  }
}

function verTrajetoriaNoMapa() {
  if (!_mapaTrajetoria) return;
  var plate = ((_mapaTrajetoria.plates || [])[0] || '').toUpperCase();
  var infoLabel = ((_mapaTrajetoria.stats && _mapaTrajetoria.stats.total_points) || (_mapaTrajetoria.points || []).length || 0) + ' passagem(ns)';
  _abrirMapaOverlay(plate, infoLabel, _detailModalReturnFn, 'Voltar ao Relatório');
  setTimeout(_plotarTrajetoria, 400);
}

// ── Segmentação inteligente: quebra pontos em trechos ────────────────────
// Retorna array de arrays. Cada sub-array é um trecho contínuo.
// Quebra quando gap de tempo > maxGapMin OU distância > maxGapMeters.
function _haversineMeters(lat1, lng1, lat2, lng2) {
  var R = 6371000;
  var dLat = (lat2 - lat1) * Math.PI / 180;
  var dLng = (lng2 - lng1) * Math.PI / 180;
  var a = Math.sin(dLat/2) * Math.sin(dLat/2)
        + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180)
        * Math.sin(dLng/2) * Math.sin(dLng/2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function splitPointsIntoSegments(pts, maxGapMinutes, maxGapMeters) {
  if (!pts || pts.length === 0) return [];
  maxGapMinutes = maxGapMinutes || 10;
  maxGapMeters  = maxGapMeters  || 2000;
  var segments = [];
  var cur = [pts[0]];
  for (var i = 1; i < pts.length; i++) {
    var prev = cur[cur.length - 1];
    var p    = pts[i];
    // Ponto duplicado (mesma lat/lng e mesma câmera) → ignora
    if (p.lat === prev.lat && p.lng === prev.lng && p.cam_nome === prev.cam_nome) {
      cur.push(p);
      continue;
    }
    var dtPrev = new Date(prev.ts).getTime();
    var dtCur  = new Date(p.ts).getTime();
    var gapMin = Math.abs(dtCur - dtPrev) / 60000;
    var distM  = _haversineMeters(prev.lat, prev.lng, p.lat, p.lng);
    if (gapMin > maxGapMinutes || distM > maxGapMeters) {
      if (cur.length > 0) segments.push(cur);
      cur = [p];
    } else {
      cur.push(p);
    }
  }
  if (cur.length > 0) segments.push(cur);
  return segments;
}

// ── Cores por trecho (alternando para diferenciar visualmente) ───────────
var _SEGMENT_COLORS = ['#ef4444','#f97316','#a855f7','#3b82f6','#06b6d4','#4ade80','#facc15','#ec4899','#14b8a6','#8b5cf6'];

function _plotarTrajetoria() {
  // Limpa camadas anteriores
  _clearTrajectoryLayers();
  if (!_mapaTrajetoria || !_mapaTrajetoria.points.length) return;

  // Ordena cronologicamente antes de desenhar (garante sequência correta mesmo se o backend divergir)
  var points = _mapaTrajetoria.points.slice().sort(function(a, b) {
    return new Date(a.ts) - new Date(b.ts);
  });

  // Calcula bearing entre dois pontos
  function bearing(p1, p2) {
    var dLng = (p2.lng - p1.lng) * Math.PI / 180;
    var lat1  = p1.lat * Math.PI / 180;
    var lat2  = p2.lat * Math.PI / 180;
    var y = Math.sin(dLng) * Math.cos(lat2);
    var x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }

  // ── Agrupa por placa e numera ─────────────────────────────────────────
  var byPlate = {};
  var bounds   = new google.maps.LatLngBounds();
  var seq     = 0;
  
  points.forEach(function(pt) {
    // Pontos já têm lat/lng do backend
    if (!pt.lat || !pt.lng) return;
    seq++;
    pt.seq = seq;
    if (!byPlate[pt.plate]) byPlate[pt.plate] = [];
    byPlate[pt.plate].push(pt);
    bounds.extend(new google.maps.LatLng(pt.lat, pt.lng));
  });

  var totalSegments = 0;
  var totalTrechos  = 0;

  Object.keys(byPlate).forEach(function(plate) {
    var pts       = byPlate[plate];
    if (!pts.length) return;

    // ── Segmentar em trechos ──────────────────────────────────────────
    var segments = splitPointsIntoSegments(pts, 10, 2000);
    totalTrechos += segments.length;

    segments.forEach(function(seg, segIdx) {
      var segColor = _TRAJ_COLOR; // rota sempre vermelha

      // ── Polyline por trecho (segmento-a-segmento) ───────────────
      if (seg.length >= 2) {
        // Sombra discreta
        var shadowPath = seg.map(function(p) { return {lat: p.lat, lng: p.lng}; });
        var shadow = new google.maps.Polyline({
          path: shadowPath,
          strokeColor: _TRAJ_SHADOW,
          strokeOpacity: 0.12,
          strokeWeight: 8,
          map: _googleMap,
          zIndex: 1
        });
        _trajetoriaLayers.push(shadow);

        // Linha principal do trecho — vermelha e bem visível
        var mainPath = seg.map(function(p) { return {lat: p.lat, lng: p.lng}; });
        var line = new google.maps.Polyline({
          path: mainPath,
          strokeColor: segColor,
          strokeOpacity: 0.95,
          strokeWeight: 5,
          map: _googleMap,
          zIndex: 2,
          icons: [{
            icon: {
              path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
              strokeOpacity: 1,
              strokeColor: segColor,
              fillColor: segColor,
              fillOpacity: 1,
              strokeWeight: 2,
              scale: 3
            },
            offset: '50%',
            repeat: '120px'
          }]
        });
        _trajetoriaLayers.push(line);
      }

      // ── Badge do trecho (se há mais de 1 trecho) ───────────────
      if (segments.length > 1) {
        var tFirst = new Date(seg[0].ts);
        var tLast  = new Date(seg[seg.length-1].ts);
        var fmtT = function(d) { return isNaN(d) ? '' : d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'}); };
        var badgeLabel = 'Trecho ' + (segIdx+1) + '/' + segments.length + ' (' + fmtT(tFirst) + ' → ' + fmtT(tLast) + ')';
        
        var badgeHtml = '<div style="background:' + segColor + ';color:#fff;font-weight:800;font-size:.58rem;'
          + 'border-radius:4px;padding:2px 5px;border:1.5px solid #fff;white-space:nowrap;'
          + 'box-shadow:0 1px 4px rgba(0,0,0,.4);opacity:.9">' + badgeLabel + '</div>';
        
        var badgeMk = new google.maps.Marker({
          position: {lat: seg[0].lat, lng: seg[0].lng},
          map: _googleMap,
          icon: {
            url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(
              '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="none"/></svg>'
            ),
            scaledSize: new google.maps.Size(1, 1),
            anchor: new google.maps.Point(0, 0)
          },
          label: {
            text: 'Trecho ' + (segIdx+1) + '/' + segments.length,
            color: '#fff',
            fontSize: '11px',
            fontWeight: 'bold'
          },
          zIndex: 45
        });
        _trajetoriaLayers.push(badgeMk);
      }

      // ── Ícones de carrinho orientados pela rota ────────────────
      seg.forEach(function(p, pIdx) {
        var dt  = new Date(p.ts);
        var fmt = isNaN(dt) ? '-' : dt.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit'})
                + ' ' + dt.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});

        // Rumo: usa próximo ponto; no último usa o anterior
        var ang = 0;
        if (pIdx < seg.length - 1) {
          ang = bearing(p, seg[pIdx + 1]);
        } else if (pIdx > 0) {
          ang = bearing(seg[pIdx - 1], p);
        }

        var pointLabel = String(p.seq);
        var pointSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="34" height="34" viewBox="0 0 34 34">'
          + '<circle cx="17" cy="17" r="12" fill="' + segColor + '" stroke="#ffffff" stroke-width="3"/>'
          + '<text x="17" y="21" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" font-weight="700" fill="#ffffff">' + pointLabel + '</text>'
          + '</svg>';

        var popupContent = '<div style="font-family:system-ui;min-width:220px">'
          + '<div style="font-weight:900;font-size:1rem;color:' + segColor + ';margin-bottom:6px;letter-spacing:.06em">' + plate + '</div>'
          + '<div style="font-size:.82rem;line-height:1.9">'
          + '<b style="color:#64748b">Passagem</b> <b>#' + p.seq + ' de ' + pts.length + '</b>'
          + (segments.length > 1 ? ' <span style="font-size:.72rem;color:' + segColor + '">(trecho ' + (segIdx+1) + ')</span>' : '') + '<br>'
          + '<b style="color:#64748b">C\u00e2mera:</b> ' + (p.cam_nome || p.camera_id || '-') + '<br>'
          + '<b style="color:#64748b">Hor\u00e1rio:</b> ' + fmt
          + '</div></div>';

        var infoWindow = new google.maps.InfoWindow({ content: popupContent });

        var mk = new google.maps.Marker({
          position: {lat: p.lat, lng: p.lng},
          map: _googleMap,
          icon: {
            url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(pointSvg),
            scaledSize: new google.maps.Size(34, 34),
            anchor: new google.maps.Point(17, 17)
          },
          title: 'Passagem #' + p.seq,
          zIndex: 40
        });

        mk.addListener('click', function() {
          _mapaInfoWindows.forEach(function(iw) { iw.close(); });
          infoWindow.open(_googleMap, mk);
        });

        _trajetoriaLayers.push(mk);
        _mapaInfoWindows.push(infoWindow);
      });

      // ── Marca INÍCIO / FIM de cada trecho ──────────────────────
      if (seg.length >= 1) {
        var startLabel = segments.length > 1 ? '▶ INÍCIO T' + (segIdx+1) : '▶ INÍCIO';
        var startHtml = '<div style="background:#16a34a;color:#fff;font-weight:900;font-size:.62rem;'
          + 'border-radius:6px;padding:3px 6px;border:2px solid #fff;white-space:nowrap;'
          + 'box-shadow:0 2px 6px rgba(0,0,0,.45)">' + startLabel + '</div>';
        
        var mStart = new google.maps.Marker({
          position: {lat: seg[0].lat, lng: seg[0].lng},
          map: _googleMap,
          icon: {
            url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(
              '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="none"/></svg>'
            ),
            scaledSize: new google.maps.Size(1, 1),
            anchor: new google.maps.Point(20, 12)
          },
          label: {
            text: startLabel,
            color: '#fff',
            fontSize: '10px',
            fontWeight: 'bold'
          },
          zIndex: 50
        });
        _trajetoriaLayers.push(mStart);
      }
      if (seg.length >= 2) {
        var endLabel = segments.length > 1 ? '■ FIM T' + (segIdx+1) : '■ FIM';
        var mEnd = new google.maps.Marker({
          position: {lat: seg[seg.length-1].lat, lng: seg[seg.length-1].lng},
          map: _googleMap,
          icon: {
            url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(
              '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="none"/></svg>'
            ),
            scaledSize: new google.maps.Size(1, 1),
            anchor: new google.maps.Point(20, 12)
          },
          label: {
            text: endLabel,
            color: '#fff',
            fontSize: '10px',
            fontWeight: 'bold'
          },
          zIndex: 50
        });
        _trajetoriaLayers.push(mEnd);
      }

      // ── Linha tracejada entre fim de um trecho e início do próximo ──
      if (segIdx < segments.length - 1) {
        var nextSeg = segments[segIdx + 1];
        var gapLine = new google.maps.Polyline({
          path: [
            {lat: seg[seg.length-1].lat, lng: seg[seg.length-1].lng},
            {lat: nextSeg[0].lat, lng: nextSeg[0].lng}
          ],
          strokeColor: _TRAJ_GAP_COLOR,
          strokeOpacity: 0.42,
          strokeWeight: 3,
          map: _googleMap,
          zIndex: 1,
          icons: [{
            icon: { path: 'M 0,-1 0,1', strokeOpacity: 1, scale: 2 },
            offset: '0',
            repeat: '10px'
          }]
        });
        _trajetoriaLayers.push(gapLine);
      }
    });
  });

  if (!bounds.isEmpty()) {
    _googleMap.fitBounds(bounds, {top: 70, right: 70, bottom: 70, left: 70});
    if (_googleMap.getZoom() > 14) _googleMap.setZoom(14);
  }

  // ──  Info bar ───────────────────────────────────────────────────────────
  var noGps = document.getElementById('map-no-gps');
  if (noGps) {
    var stats = _mapaTrajetoria.stats || {};
    var camsNoGps = stats.cameras_without_gps || [];
    var missStr = camsNoGps.length 
      ? ' <span style="color:var(--muted);font-size:.74rem">(sem GPS: ' + camsNoGps.join(', ') + ')</span>' 
      : '';
    var trechoStr = totalTrechos > 1
      ? ' &middot; <strong style="color:#f97316">' + totalTrechos + ' trechos</strong> (gap &gt;10min ou &gt;2km)'
      : '';
    var pointsShown = stats.total_points || points.length;
    var pointsTotal = stats.total_events || pointsShown;
    var pointsInfo = pointsShown === pointsTotal 
      ? pointsShown + ' passagem(ns)' 
      : pointsShown + ' de ' + pointsTotal + ' passagem(ns) (filtrado GPS)';
    noGps.innerHTML = '<div style="background:rgba(250,204,21,.1);border:1px solid var(--accent);border-radius:8px;padding:10px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">'
      + '<span style="font-size:1.1rem">&#127760;</span>'
      + '<span style="font-size:.83rem"><strong style="color:var(--accent)">' + _mapaTrajetoria.plates.join(' + ') + '</strong>'
      + ' &mdash; ' + pointsInfo + trechoStr + missStr + '</span>'
      + '<button class="btn btn-outline btn-xs" onclick="_limparTrajetoria()">&#10005; Limpar</button>'
      + '</div>';
  }
}

function _limparTrajetoria() {
  _mapaTrajetoria = null;
  _clearTrajectoryLayers();
  var noGps = document.getElementById('map-no-gps');
  if (noGps) noGps.innerHTML = '';
  loadMapa();
}

function _mapaStatusColor(lastSeenIso, ativa) {
  if (ativa === false) return '#a855f7';
  if (!lastSeenIso) return '#6b7280';
  var mins = (Date.now() - new Date(lastSeenIso).getTime()) / 60000;
  if (mins < 15) return '#22c55e';
  if (mins < 60) return '#f59e0b';
  return '#ef4444';
}

function _mapaStatusLabel(lastSeenIso) {
  if (!lastSeenIso) return 'Nunca detectado';
  var mins = (Date.now() - new Date(lastSeenIso).getTime()) / 60000;
  if (mins < 15) return 'Online (h\u00e1 ' + Math.round(mins) + ' min)';
  if (mins < 60) return 'Aguardando (' + Math.round(mins) + ' min sem evento)';
  var h = mins / 60;
  return 'Offline (h\u00e1 ' + (h < 24 ? Math.round(h) + 'h' : Math.round(h/24) + 'd') + ')';
}

// Verifica se Google Maps está carregado
function _checkGoogleMapsLoaded() {
  return _googleMapsReady && typeof google !== 'undefined' && typeof google.maps !== 'undefined';
}

// Aguarda carregamento do Google Maps
async function _waitForGoogleMaps(timeout) {
  timeout = timeout || 15000;
  var start = Date.now();
  while (!_checkGoogleMapsLoaded()) {
    if (Date.now() - start > timeout) {
      throw new Error('Timeout aguardando Google Maps API. Verifique se a chave está válida.');
    }
    await new Promise(function(resolve) { setTimeout(resolve, 100); });
  }
}

async function loadMapa() {
  var container = document.getElementById('map-container');
  if (!container) return;

  try {
    // Aguarda Google Maps carregar
    if (!_checkGoogleMapsLoaded()) {
      var noGps = document.getElementById('map-no-gps');
      if (noGps) noGps.innerHTML = '<div style="color:var(--warning);font-size:.82rem">⏳ Aguardando Google Maps API...</div>';
      await _waitForGoogleMaps(10000);
    }

    // Inicializa Google Maps na primeira chamada
    if (!_googleMap) {
      _googleMap = new google.maps.Map(container, {
        center: {lat: -15.0, lng: -52.0},
        zoom: 5,
        mapTypeId: google.maps.MapTypeId.ROADMAP,
        zoomControl: true,
        mapTypeControl: true,
        scaleControl: true,
        streetViewControl: false,
        rotateControl: false,
        fullscreenControl: true
      });
    }
  } catch(e) {
    console.error('[Mapa] Erro ao inicializar Google Maps:', e);
    var noGps = document.getElementById('map-no-gps');
    if (noGps) noGps.innerHTML = '<div style="color:var(--danger);font-size:.82rem">❌ Erro ao carregar Google Maps: ' + e.message + '<br><small>Verifique se a chave da API está válida e tem as permissões necessárias.</small></div>';
    return;
  }

  // Remove marcadores anteriores
  _mapaMarkers.forEach(function(m) { m.setMap(null); });
  _mapaMarkers = [];
  _mapaInfoWindows.forEach(function(iw) { iw.close(); });
  _mapaInfoWindows = [];

  try {
    var rCams   = await fetch('/api/cameras?include_inactive=true');
    var rStatus = await fetch('/api/cameras/status');
    var dCams   = await rCams.json();
    var dStatus = rStatus.ok ? await rStatus.json() : {};
    var cameras   = dCams.items || [];
    var statusMap = dStatus.status || {};
    _mapaCacheItems = cameras;   // cache para heat map e auto-refresh

    var withGps = [], withoutGps = [];
    cameras.forEach(function(c) {
      if (c.latitude != null && c.longitude != null) withGps.push(c);
      else withoutGps.push(c);
    });

    var bounds = new google.maps.LatLngBounds();
    withGps.forEach(function(c) {
      var lastSeen = statusMap[c.camera_id] || c.last_seen || null;
      var color    = _mapaStatusColor(lastSeen, c.ativa);
      var label    = c.ativa === false ? 'Inativa' : _mapaStatusLabel(lastSeen);
      var critTag  = c.criticidade === 'CRITICA'
        ? '<span style="color:#ef4444;font-weight:700">CR\u00cdTICA</span>'
        : '<span style="color:#86efac">NORMAL</span>';
      var dirTag   = c.direcao
        ? '<br><b>Dire\u00e7\u00e3o:</b> <span style="color:#facc15">' + c.direcao + '</span>'
        : '';
      var camIdEsc = (c.camera_id || '').replace(/'/g, "\\'");
      var popupContent = '<div style="font-family:system-ui;min-width:210px">'
        + '<div style="font-weight:700;font-size:.95rem;margin-bottom:6px">&#128247; ' + c.nome + '</div>'
        + '<div style="font-size:.8rem;line-height:1.8">'
        + '<b>ID:</b> ' + (c.camera_id || '\u2014') + '<br>'
        + '<b>IP:</b> <span style="font-family:monospace">' + (c.ip || '\u2014') + '</span><br>'
        + '<b>Criticidade:</b> ' + critTag
        + dirTag + '<br>'
        + '<b>Status:</b> <span style="color:' + color + ';font-weight:600">' + label + '</span><br>'
        + '<b>Eventos hoje:</b> ' + (c.events_today || 0) + '&nbsp;&nbsp;'
        + '<b>Total:</b> ' + (c.total_events || 0)
        + '</div>'
        + '<div style="font-size:.72rem;color:#999;margin-top:6px;font-family:monospace">'
        + c.latitude.toFixed(6) + ', ' + c.longitude.toFixed(6)
        + '</div>'
        + '<div style="margin-top:10px">'
        + '<button onclick="_filtrarEventosPorCamera(\''+camIdEsc+'\')" style="background:var(--accent);color:#000;border:none;border-radius:7px;padding:5px 12px;font-size:.78rem;font-weight:700;cursor:pointer;width:100%">&#128467; Ver eventos desta c\u00e2mera</button>'
        + '</div>'
        + '</div>';

      var infoWindow = new google.maps.InfoWindow({
        content: popupContent,
        maxWidth: 260
      });

      var marker = new google.maps.Marker({
        position: {lat: c.latitude, lng: c.longitude},
        map: _googleMap,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 7,
          fillColor: color,
          fillOpacity: 1,
          strokeColor: 'rgba(255,255,255,0.85)',
          strokeWeight: 2
        }
      });
      
      marker.addListener('click', function() {
        _mapaInfoWindows.forEach(function(iw) { iw.close(); });
        infoWindow.open(_googleMap, marker);
      });

      _mapaMarkers.push(marker);
      _mapaInfoWindows.push(infoWindow);
      bounds.extend(marker.getPosition());
    });

    if (withGps.length > 0 && !_mapaTrajetoria) {
      _googleMap.fitBounds(bounds);
      // Limita zoom máximo
      var listener = google.maps.event.addListenerOnce(_googleMap, 'bounds_changed', function() {
        if (_googleMap.getZoom() > 15) {
          _googleMap.setZoom(15);
        }
      });
    }

    // Necessário quando a aba estava oculta
    setTimeout(function() {
      google.maps.event.trigger(_googleMap, 'resize');
      if (_mapaTrajetoria) _plotarTrajetoria();
    }, 80);

    // C\u00e2meras sem GPS
    var noGps = document.getElementById('map-no-gps');
    if (noGps) {
      if (!withoutGps.length) {
        noGps.innerHTML = '<div style="font-size:.79rem;color:var(--muted)">&#10003; Todas as c\u00e2meras possuem coordenadas GPS.</div>';
      } else {
        noGps.innerHTML = '<div style="font-size:.82rem;color:var(--muted);margin-bottom:10px">'
          + '&#9888;&#65039; ' + withoutGps.length + ' c\u00e2mera(s) sem GPS cadastrado:'
          + '</div>'
          + '<div style="display:flex;flex-wrap:wrap;gap:8px">'
          + withoutGps.map(function(c) {
              var clr = _mapaStatusColor(statusMap[c.camera_id] || c.last_seen || null, c.ativa);
              return '<span style="background:rgba(255,255,255,.06);border:1px solid var(--border);border-radius:8px;padding:6px 12px;font-size:.79rem;display:inline-flex;align-items:center;gap:6px">'
                + '<span style="color:' + clr + '">&#9679;</span>'
                + _camEsc(c.nome)
                + ' <button class="btn btn-outline btn-xs" style="padding:1px 6px;font-size:.7rem" onclick="editCamera(decodeURIComponent(\'' + encodeURIComponent(JSON.stringify(c)) + '\'))">+ GPS</button>'
                + '</span>';
            }).join('')
          + '</div>';
      }
    }
    _markTabLoaded('mapa');

  } catch(e) {
    console.error('[Mapa]', e);
    var noGps = document.getElementById('map-no-gps');
    if (noGps) noGps.innerHTML = '<div style="color:var(--danger);font-size:.82rem">Erro ao carregar c\u00e2meras: ' + e.message + '</div>';
  }
}

// ===== TRAJETÓRIA DE VEÍCULO (Painel no Mapa) =====
var _vehicleTrajData = null;

// ---- Filtro rápido de período (Mapa/Trajetória) ----
var _trajActivePeriod = 12; // horas numéricas ou 'custom'

function _toLocalDTInput(d) {
  var pad = function(n) { return String(n).padStart(2,'0'); };
  return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())
         +'T'+pad(d.getHours())+':'+pad(d.getMinutes());
}

function _trajSetPeriod(btn, val) {
  _trajActivePeriod = val;
  document.querySelectorAll('.traj-period-btn').forEach(function(b) { b.classList.remove('active'); });
  btn.classList.add('active');
  var now  = new Date();
  if (val !== 'custom') {
    var from = new Date(now.getTime() - val * 3600 * 1000);
    document.getElementById('traj-start-field').value = _toLocalDTInput(from);
    document.getElementById('traj-end-field').value   = _toLocalDTInput(now);
  }
}

function _trajPlateInput(el) {
  var clean = el.value.replace(/[^A-Z0-9]/gi, '').toUpperCase().slice(0, 7);
  if (el.value !== clean) el.value = clean;
}

async function loadVehicleTrajectory() {
  var plate = (document.getElementById('traj-plate-field').value || '').trim().toUpperCase();
  var status = document.getElementById('traj-map-status');

  // Se período ativo é preset, preenche os campos agora (garante valores frescos)
  if (_trajActivePeriod !== 'custom') {
    var now  = new Date();
    var from = new Date(now.getTime() - _trajActivePeriod * 3600 * 1000);
    document.getElementById('traj-start-field').value = _toLocalDTInput(from);
    document.getElementById('traj-end-field').value   = _toLocalDTInput(now);
  }

  var start = document.getElementById('traj-start-field').value;
  var end   = document.getElementById('traj-end-field').value;

  if (!plate) {
    status.innerHTML = '⚠️ Informe a placa do veículo.';
    return;
  }
  if (!start || !end) {
    status.innerHTML = '⚠️ Selecione um período ou defina datas manuais.';
    return;
  }

  status.innerHTML = '<span class="spinner" style="margin-right:6px;vertical-align:middle"></span>Buscando...';

  try {
    // Envia o valor local diretamente (YYYY-MM-DDTHH:mm).
    // O backend assume fuso -03:00 quando não há tzinfo — não converter para UTC aqui.
    var startIso = start;
    var endIso   = end;

    var url = '/api/vehicles/' + encodeURIComponent(plate) + '/trajectory'
            + '?start=' + encodeURIComponent(startIso)
            + '&end=' + encodeURIComponent(endIso)
            + '&dedupe_seconds=5';
    
    var resp = await fetch(url);
    if (!resp.ok) {
      var errData = await resp.json().catch(function() { return {detail: 'HTTP ' + resp.status}; });
      throw new Error(errData.detail || 'HTTP ' + resp.status);
    }

    var data = await resp.json();
    renderVehicleTrajectory(data);
    status.innerHTML = '';
  } catch(e) {
    status.innerHTML = '❌ Erro: ' + e.message;
    console.error('[loadVehicleTrajectory]', e);
  }
}

function renderVehicleTrajectory(data) {
  if (!data || !data.points || data.points.length === 0) {
    var msg;
    if (!data || !data.total_events) {
      msg = '⚠️ Nenhum registro para esse veículo no período selecionado';
    } else {
      msg = '⚠️ Nenhum ponto com coordenadas GPS encontrado';
      if (data.cameras_without_gps && data.cameras_without_gps.length > 0) {
        msg += ' (câmeras sem GPS: ' + data.cameras_without_gps.join(', ') + ')';
      }
    }
    document.getElementById('traj-map-status').innerHTML = msg;
    return;
  }

  _vehicleTrajData = data;
  if (!_googleMap) return;
  var trajData = _setMapaTrajetoriaFromApiData(data, data.plate);
  if (!trajData.points || !trajData.points.length) {
    document.getElementById('traj-map-status').innerHTML = '⚠️ Nenhum ponto com GPS';
    return;
  }
  _plotarTrajetoria();

  // Mostra câmeras sem GPS se houver
  var noGpsContainer = document.getElementById('traj-no-gps-container');
  var noGpsList = document.getElementById('traj-no-gps-list');
  if (data.cameras_without_gps && data.cameras_without_gps.length > 0) {
    noGpsList.textContent = data.cameras_without_gps.join(', ');
    noGpsContainer.style.display = 'block';
  } else {
    noGpsContainer.style.display = 'none';
  }

  // Status final
  var totalEvents = (trajData.stats && trajData.stats.total_events) || data.total_events || 0;
  var totalPoints = (trajData.stats && trajData.stats.total_points) || data.total_points || 0;
  var statusMsg = '✓ ' + totalPoints + ' ponto(s) com GPS';
  if (totalEvents > totalPoints) {
    statusMsg += ' (+ ' + (totalEvents - totalPoints) + ' sem coordenadas)';
  }
  document.getElementById('traj-map-status').innerHTML = statusMsg;
}

function clearVehicleTrajectory() {
  // Remove camadas de trajetória do mapa
  _clearTrajectoryLayers();
  
  // Limpa dados
  _vehicleTrajData = null;
  
  // Limpa campos de entrada
  document.getElementById('traj-plate-field').value = '';
  document.getElementById('traj-start-field').value = '';
  document.getElementById('traj-end-field').value = '';
  document.getElementById('traj-map-status').innerHTML = '';
  
  // Esconde painel de câmeras sem GPS
  var noGpsContainer = document.getElementById('traj-no-gps-container');
  if (noGpsContainer) noGpsContainer.style.display = 'none';
  
  // Recarrega mapa de câmeras
  loadMapa();
}

// ===== GRUPOS DE COMBOIO =====
var _gruposLiveEnabled = false;
var _gruposLiveTimer   = null;

function toggleGruposLive() {
  _gruposLiveEnabled = !_gruposLiveEnabled;
  var btn = document.getElementById('btn-grupos-live');
  if (_gruposLiveEnabled) {
    btn.classList.remove('btn-outline'); btn.classList.add('btn-success');
    btn.innerHTML = '<span class="dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#22c55e;animation:pulse 1s infinite;margin-right:4px"></span> AO VIVO';
    loadGruposComboio(false);
    _gruposScheduleNext();
  } else {
    _gruposStopTimer();
    btn.classList.remove('btn-success'); btn.classList.add('btn-outline');
    btn.innerHTML = '&#9654; <span id="grupos-live-label">Monitorar</span>';
  }
}

function _gruposStopTimer() {
  if (_gruposLiveTimer) { clearTimeout(_gruposLiveTimer); _gruposLiveTimer = null; }
}

function _gruposScheduleNext() {
  if (!_gruposLiveEnabled) return;
  var sec = parseInt(document.getElementById('grupos-interval').value, 10) || 60;
  _gruposLiveTimer = setTimeout(function() {
    loadGruposComboio(false).then(function() { _gruposScheduleNext(); });
  }, sec * 1000);
}

async function loadGruposComboio(showSpinner) {
  if (showSpinner === undefined) showSpinner = true;
  
  var w = document.getElementById('grupos-window').value || '2h';
  var gs = document.getElementById('grupos-sizes').value || '2,3';
  var mc = document.getElementById('grupos-min-cameras').value || '2';
  var om = document.getElementById('grupos-order-mode').value || 'any';
  
  if (showSpinner) {
    document.getElementById('grupos-status').innerHTML = '<span class="spinner"></span>';
    document.getElementById('grupos-tbody').innerHTML =
      '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:32px"><span class="spinner"></span> Carregando grupos…</td></tr>';
  }
  
  try {
    var url = '/api/batedor/grupos_comboio?window=' + encodeURIComponent(w)
            + '&group_sizes=' + encodeURIComponent(gs)
            + '&min_cameras=' + encodeURIComponent(mc)
            + '&order_mode=' + encodeURIComponent(om)
            + '&co_window=300&leader_ratio=0.7&payload_max_front=0&limit=100';
    
    var r = await fetch(url);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    var data = await r.json();
    var groups = data.groups || [];
    
    // Atualiza cards
    var totalGroups = groups.length;
    var totalVehicles = 0;
    var totalCameras = 0;
    var maxTrip = 0;
    
    groups.forEach(function(g) {
      totalVehicles += (g.plates || []).length;
      totalCameras += g.cameras_count || 0;
      var trip = g.trip_span_sec || 0;
      maxTrip = Math.max(maxTrip, trip);
    });
    
    document.getElementById('grupos-total').textContent = totalGroups;
    document.getElementById('grupos-veiculos').textContent = totalVehicles;
    document.getElementById('grupos-cam-media').textContent = totalGroups > 0 ? Math.round(totalCameras / totalGroups) : '—';
    document.getElementById('grupos-max-trip').textContent = maxTrip > 0 ? _formatDuration(maxTrip) : '—';
    
    // Renderiza tabela
    renderGruposComboio(groups);
    
    var ts = new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
    document.getElementById('grupos-status').textContent = 'Atualizado às ' + ts;
  } catch(e) {
    document.getElementById('grupos-status').textContent = 'Erro: ' + e.message;
    if (showSpinner)
      document.getElementById('grupos-tbody').innerHTML =
        '<tr><td colspan="8" style="text-align:center;color:var(--danger);padding:24px">Erro: ' + e.message + '</td></tr>';
    // para o live se der erro
    _gruposLiveEnabled = false; _gruposStopTimer();
    var btn = document.getElementById('btn-grupos-live');
    if (btn) { btn.classList.remove('btn-success'); btn.classList.add('btn-outline');
               btn.innerHTML = '&#9654; <span id="grupos-live-label">Monitorar</span>'; }
  }
}

function _formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '—';
  if (seconds < 60) return seconds + 's';
  if (seconds < 3600) return Math.round(seconds / 60) + 'm';
  var h = Math.floor(seconds / 3600);
  var m = Math.round((seconds % 3600) / 60);
  return h + 'h' + (m > 0 ? m + 'm' : '');
}

function renderGruposComboio(groups) {
  var tb = document.getElementById('grupos-tbody');
  if (!groups || !groups.length) {
    tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:40px">'
      + 'Nenhum grupo de comboio detectado com os filtros atuais.'
      + '</td></tr>';
    return;
  }
  
  tb.innerHTML = groups.map(function(g, idx) {
    var plates = g.plates || [];
    var placasHtml = plates.map(function(p) { return plateHtml(p); }).join(' + ');
    var cameras = g.cameras || [];
    var camHtml = '<div style="font-size:.75rem;color:var(--muted)">' 
      + (cameras.length ? cameras.slice(0, 3).join(', ') + (cameras.length > 3 ? '...' : '') : 'N/A')
      + '</div>';
    var firstSeen = g.first_seen ? fmtTs(g.first_seen) : '—';
    var lastSeen = g.last_seen ? fmtTs(g.last_seen) : '—';
    var tripSpan = _formatDuration(g.trip_span_sec || 0);
    
    return '<tr>'
      + '<td style="color:var(--muted);font-size:.78rem">#' + (idx + 1) + '</td>'
      + '<td>' + placasHtml + '</td>'
      + '<td><span class="badge badge-yellow">' + plates.length + '</span></td>'
      + '<td><span class="badge badge-green" title="Câmeras onde viram juntos">' + (g.cameras_count || 0) + '</span></td>'
      + '<td style="font-size:.78rem;max-width:180px;overflow-x:auto">' + camHtml + '</td>'
      + '<td style="white-space:nowrap"><span class="badge badge-yellow">' + tripSpan + '</span></td>'
      + '<td style="white-space:nowrap;font-size:.76rem">' 
      + '<div>' + firstSeen + '</div>'
      + '<div style="color:var(--muted)">' + lastSeen + '</div>'
      + '</td>'
      + '<td class="action-cell"><div class="action-buttons">'
      + '<button class="btn btn-outline btn-xs" onclick="openGrupoDetail(' + idx + ',' + JSON.stringify(g).replace(/'/g, "&#39;") + ')">&#128269; Visualizar</button>'
      + '</div></td>'
      + '</tr>';
  }).join('');
}

function openGrupoDetail(idx, grupoJson) {
  var grupo = typeof grupoJson === 'string' ? JSON.parse(grupoJson.replace(/&#39;/g, "'")) : grupoJson;
  var plates = (grupo.plates || []).join(' + ');
  
  document.getElementById('detail-modal-plate').textContent = 'Grupo #' + (idx + 1) + ' — ' + plates;
  
  var html = '<div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:16px">'
    + '<div style="background:var(--bg2);border-radius:8px;padding:12px;min-width:140px">'
    + '<div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px">Placas</div>'
    + '<div style="font-weight:700;font-size:.95rem">' + (grupo.plates || []).length + ' veículos</div>'
    + '</div>'
    + '<div style="background:var(--bg2);border-radius:8px;padding:12px;min-width:140px">'
    + '<div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px">Câmeras juntas</div>'
    + '<div style="font-weight:700;font-size:.95rem;color:#4ade80">' + (grupo.cameras_count || 0) + '</div>'
    + '</div>'
    + '<div style="background:var(--bg2);border-radius:8px;padding:12px;min-width:140px">'
    + '<div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px">Duração</div>'
    + '<div style="font-weight:700;font-size:.95rem">' + _formatDuration(grupo.trip_span_sec || 0) + '</div>'
    + '</div>'
    + '</div>';
  
  // Placas
  if (grupo.plates && grupo.plates.length) {
    html += '<div style="margin-bottom:14px">'
      + '<div style="font-size:.75rem;text-transform:uppercase;color:var(--muted);margin-bottom:6px;font-weight:700">Placas do Grupo</div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:6px">'
      + grupo.plates.map(function(p) { return '<span style="background:rgba(59,130,246,.15);color:var(--accent);border:1px solid rgba(59,130,246,.3);border-radius:6px;padding:4px 12px;font-weight:700;font-size:.82rem;letter-spacing:.04em">' + p + '</span>'; }).join('')
      + '</div>'
      + '</div>';
  }
  
  // Câmeras
  if (grupo.cameras && grupo.cameras.length) {
    html += '<div style="margin-bottom:14px">'
      + '<div style="font-size:.75rem;text-transform:uppercase;color:var(--muted);margin-bottom:6px;font-weight:700">Câmeras (' + grupo.cameras.length + ')</div>'
      + '<div style="background:var(--bg2);border-radius:8px;padding:10px 12px;font-size:.8rem;max-height:120px;overflow-y:auto">'
      + grupo.cameras.join(', ')
      + '</div>'
      + '</div>';
  }
  
  // Timeline
  if (grupo.first_seen || grupo.last_seen) {
    html += '<div>'
      + '<div style="font-size:.75rem;text-transform:uppercase;color:var(--muted);margin-bottom:6px;font-weight:700">Timeline</div>'
      + '<div style="background:var(--bg2);border-radius:8px;padding:10px 12px;font-size:.8rem">'
      + (grupo.first_seen ? '<div><span style="color:var(--muted)">Primeiro visto:</span> ' + fmtTs(grupo.first_seen) + '</div>' : '')
      + (grupo.last_seen ? '<div style="margin-top:3px"><span style="color:var(--muted)">Último visto:</span> ' + fmtTs(grupo.last_seen) + '</div>' : '')
      + '</div>'
      + '</div>';
  }
  
  document.getElementById('detail-modal-body').innerHTML = html;
  openModal('detail-modal');
}

function _resetGruposFilters() {
  var ids = [
    'grupos-window', 'grupos-sizes', 'grupos-min-cameras', 'grupos-order-mode', 'grupos-interval'
  ];
  ids.forEach(function(id) {
    var el = document.getElementById(id);
    if (el) {
      if (id === 'grupos-window') el.value = '2h';
      else if (id === 'grupos-sizes') el.value = '2';
      else if (id === 'grupos-min-cameras') el.value = '2';
      else if (id === 'grupos-order-mode') el.value = 'any';
      else if (id === 'grupos-interval') el.value = '60';
    }
  });
  loadGruposComboio(true);
}

var _AUTH_KEYS = ['bpfron_token', 'bpfron_role', 'bpfron_user', 'bpfron_fullname', 'bpfron_session_id'];

function _authMigrateLegacyStorage() {
  _AUTH_KEYS.forEach(function(key) {
    if (sessionStorage.getItem(key)) return;
    var legacy = localStorage.getItem(key);
    if (legacy) {
      sessionStorage.setItem(key, legacy);
      localStorage.removeItem(key);
    }
  });
}

function _authGet(key) {
  return sessionStorage.getItem(key) || '';
}

function _authClearSession() {
  _AUTH_KEYS.forEach(function(key) {
    sessionStorage.removeItem(key);
    localStorage.removeItem(key);
  });
}

function _authEnsureSessionId() {
  var sid = _authGet('bpfron_session_id');
  if (sid) return sid;
  sid = 'legacy-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  sessionStorage.setItem('bpfron_session_id', sid);
  return sid;
}

var _presenceCurrentPage = { key: 'painel', label: 'Painel', path: '/dashboard#painel' };
var _presenceHeartbeatId = null;
var _presenceLastTrackStamp = '';
var _presenceLastTrackAt = 0;

function _presenceSetCurrentPage(pageKey, pageLabel, pagePath) {
  _presenceCurrentPage = {
    key: String(pageKey || 'painel').trim() || 'painel',
    label: String(pageLabel || 'Painel').trim() || 'Painel',
    path: String(pagePath || '/dashboard#painel').trim() || '/dashboard#painel'
  };
  return _presenceCurrentPage;
}

function _presencePayload(pageKey, pageLabel, pagePath) {
  var page = _presenceSetCurrentPage(pageKey, pageLabel, pagePath);
  return {
    session_id: window._authSessionId || _authEnsureSessionId(),
    page_key: page.key,
    page_label: page.label,
    page_path: page.path
  };
}

async function _presencePost(url, payload, opts) {
  if (!window._authToken) return null;
  opts = opts || {};
  try {
    var resp = await fetch(url, Object.assign({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }, opts));
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    return await resp.json().catch(function(){ return {}; });
  } catch (e) {
    console.warn('[presence]', url, e.message);
    return null;
  }
}

async function trackPageView(pageKey, pageLabel, pagePath, force) {
  var payload = _presencePayload(pageKey, pageLabel, pagePath);
  var stamp = payload.page_key + '|' + payload.page_path;
  var now = Date.now();
  if (!force && stamp === _presenceLastTrackStamp && (now - _presenceLastTrackAt) < 1500) return;
  _presenceLastTrackStamp = stamp;
  _presenceLastTrackAt = now;
  await _presencePost('/api/admin/activity/page-view', payload);
}

async function _presenceHeartbeat(force) {
  if (!window._authToken) return;
  var page = _presenceCurrentPage || { key: 'painel', label: 'Painel', path: '/dashboard#painel' };
  if (!force && document.hidden) return;
  await _presencePost('/api/admin/activity/heartbeat', _presencePayload(page.key, page.label, page.path));
}

function _startPresenceHeartbeat() {
  if (_presenceHeartbeatId) clearInterval(_presenceHeartbeatId);
  _presenceHeartbeat(true);
  _presenceHeartbeatId = setInterval(function(){ _presenceHeartbeat(false); }, 45000);
}

async function _presenceLogout() {
  var page = _presenceCurrentPage || { key: 'painel', label: 'Painel', path: '/dashboard#painel' };
  await _presencePost('/api/admin/activity/logout', _presencePayload(page.key, page.label, page.path), { keepalive: true });
}

document.addEventListener('visibilitychange', function() {
  if (!document.hidden) _presenceHeartbeat(true);
});
window.addEventListener('focus', function() {
  _presenceHeartbeat(true);
});

// ===== AUTH =====
(function(){
  _authMigrateLegacyStorage();
  var token = _authGet('bpfron_token');
  if (!token) { window.location.replace('/login'); return; }
  // Expor token globalmente
  window._authToken = token;
  window._authRole  = _authGet('bpfron_role');
  if (window._authRole === 'operator') window._authRole = 'operador';
  if (window._authRole === 'viewer' || window._authRole === 'visualizacao') window._authRole = 'visualizador';
  window._authUser  = _authGet('bpfron_user');
  window._authName  = _authGet('bpfron_fullname');
  window._authSessionId = _authEnsureSessionId();
  // Mostrar info do usuário
  var sbUser = document.getElementById('sb-username');
  var sbRole = document.getElementById('sb-role');
  var tbUser = document.getElementById('topbar-user');
  var authDisplayName = (window._authName || '').trim() || (window._authUser || '').trim() || 'Usuario';
  var authRoleLabel = window._authRole === 'admin'
    ? 'Administrador'
    : window._authRole === 'operador'
      ? 'Operador'
      : 'Visualizador';
  if (sbUser) sbUser.textContent = authDisplayName;
  if (sbRole) sbRole.textContent = 'Nivel de acesso: ' + authRoleLabel;
  if (tbUser) tbUser.textContent = window._authUser;
  // Mostrar itens de admin
  if (window._authRole === 'admin') {
    document.querySelectorAll('.nav-admin-only').forEach(function(el){
      el.style.display = el.classList.contains('nav-item') ? 'flex' : 'block';
    });
  }
})();

function _applyRoleBasedUI(root) {
  var scope = root || document;
  var role = window._authRole || 'visualizador';
  var isAdmin = role === 'admin';
  var isOperador = role === 'operador';
  var isVisualizador = role === 'visualizador';

  // ── Processar atributo data-perm ──────────────────────────────────────────
  // data-perm="operador-plus" → visível para admin e operador
  // data-perm="admin-only"    → visível apenas para admin
  // data-perm="auth"          → visível para qualquer autenticado
  scope.querySelectorAll('[data-perm="operador-plus"]').forEach(function(el) {
    el.style.display = (isAdmin || isOperador) ? '' : 'none';
  });
  scope.querySelectorAll('[data-perm="admin-only"]').forEach(function(el) {
    el.style.display = isAdmin ? '' : 'none';
  });

  // Ocultar menus que o usuário não tem acesso
  if (!isAdmin) {
    scope.querySelectorAll('.nav-admin-only').forEach(function(el){
      el.style.display = 'none';
    });
  }

  // Operador: pode criar, editar e deletar veículos, listas e câmeras, mas sem acesso a usuários e alarmes
  if (isOperador) {
    // Ocultar gerenciamento de usuários
    scope.querySelectorAll('[data-menu="users"]').forEach(function(el){
      el.style.display = 'none';
    });
    // Ocultar criação/edição de alarmes (apenas admin)
    scope.querySelectorAll('button, a.btn').forEach(function(el){
      var onclick = (el.getAttribute('onclick') || '').toLowerCase();
      if (onclick.includes('openalarmemodal') || onclick.includes('savealarme') || onclick.includes('deletealarme') || onclick.includes('testalarme')) {
        el.style.display = 'none';
      }
    });
  }

  // Visualizador: somente leitura — pode ver Pessoas/Abordagens mas não alterar
  if (isVisualizador) {
    // Abas permitidas: visualizador acessa Pessoas (consulta) além das demais leitura
    var allowedTabs = ['painel', 'eventos', 'batedor', 'mapa', 'config', 'cadastro'];
    scope.querySelectorAll('.nav-item').forEach(function(el){
      var onclick = (el.getAttribute('onclick') || '').toLowerCase();
      var tabMatch = onclick.match(/switchtab\('([^']+)'/i);
      if (tabMatch) {
        var tabName = tabMatch[1].toLowerCase();
        if (!allowedTabs.includes(tabName)) {
          el.style.display = 'none';
        }
      }
    });

    // Ocultar conteúdo de abas não permitidas (mas manter tab-cadastro visível)
    scope.querySelectorAll('[id^="tab-"]').forEach(function(el){
      var tabId = el.id.replace('tab-', '').toLowerCase();
      if (!allowedTabs.includes(tabId)) {
        el.style.display = 'none';
      }
    });

    // Ocultar gerenciamento de usuários
    scope.querySelectorAll('[data-menu="users"]').forEach(function(el){
      el.style.display = 'none';
    });

    // Bloquear botões de escrita — lista explícita de funções JS de modificação
    // (evitar match genérico em texto que quebraria o menu de "Pessoas")
    scope.querySelectorAll('button, a.btn').forEach(function(el){
      var onclick = (el.getAttribute('onclick') || '').toLowerCase();

      var isWriteAction =
        // Alarmes
        onclick.includes('openalarmemodal') || onclick.includes('savealarme') ||
        onclick.includes('deletealarme')    || onclick.includes('testalarme') ||
        // Usuários
        onclick.includes('openusermodal')   || onclick.includes('deleteuser') ||
        // Veículos e listas
        onclick.includes('savevehicle')     || onclick.includes('deletevehicle') ||
        onclick.includes('openlistmodal')   || onclick.includes('deletelist') ||
        onclick.includes('savecamera')      || onclick.includes('deletecamera') ||
        onclick.includes('opencameramodal') ||
        // Comboio / batedor
        onclick.includes('comboio_confirm') || onclick.includes('false_positive') ||
        onclick.includes('savebatedor')     || onclick.includes('openbatedormodal') ||
        // Pessoas / abordagens (ações de escrita — consulta é permitida)
        onclick.includes('cadastronovapessoa')  ||
        onclick.includes('cadastroeditar')      ||
        onclick.includes('cadastroexcluir')     ||
        onclick.includes('absalvar')            ||
        onclick.includes('abexcluir')           ||
        onclick.includes('abusar')              ||
        onclick.includes('cadabordar')          ||
        onclick.includes('cadabordagemsalvar')  ||
        // Importações / decisões
        onclick.includes('import')          || onclick.includes('openvehiculomodal') ||
        onclick.includes('report/decision') || onclick.includes('savealvo');

      if (isWriteAction) {
        el.style.display = 'none';
      }
    });
  }
}

(function initRoleGuards(){
  _applyRoleBasedUI(document);
  var obs = new MutationObserver(function(){ _applyRoleBasedUI(document); });
  obs.observe(document.body, { childList: true, subtree: true });
})();

// Interceptar fetch para adicionar Authorization
(function(){
  var origFetch = window.fetch;
  window.fetch = function(url, opts) {
    opts = opts || {};
    var token = window._authToken;
    if (token && typeof url === 'string' && url.startsWith('/api/')) {
      opts.headers = Object.assign({}, opts.headers || {}, {
        'Authorization': 'Bearer ' + token,
        'X-BPFRON-Session': window._authSessionId || _authEnsureSessionId()
      });
    }
    return origFetch.call(this, url, opts).then(function(resp) {
      if (resp.status === 401) {
        _authClearSession();
        window.location.replace('/login');
      }
      return resp;
    });
  };
})();

async function doLogout() {
  if (!confirm('Deseja sair do sistema?')) return;
  await _presenceLogout();
  _authClearSession();
  window.location.replace('/login');
}

// ===== CONFIGURA\u00c7\u00d5ES =====
var _THEMES = {
  verde: {
    '--bg':'#171d14',
    '--sidebar':'#26301f',
    '--card':'#35422b',
    '--card2':'#2b3623',
    '--border':'#5a6b47',
    '--accent':'#c4a64a',
    '--accent2':'#dbc483',
    '--text':'#f1ecd9',
    '--muted':'#c7c0a4',
    '--success':'#8fa96d',
    '--warning':'#c4a64a',
    '--danger':'#d47460',
    '--sidebar-text':'#f1ecd9',
    '--menu-hover-bg':'rgba(196,166,74,.08)',
    '--menu-hover-text':'#f4eedc',
    '--menu-active-bg':'rgba(196,166,74,.16)',
    '--menu-active-text':'#f4eedc',
    '--table-head-bg':'rgba(18,24,15,.45)',
    '--table-row-hover':'rgba(196,166,74,.08)',
    '--input-bg':'#2b3623',
    '--input-border':'#5a6b47',
    '--input-focus-shadow':'0 0 0 3px rgba(196,166,74,.18)',
    '--btn-secondary-bg':'transparent',
    '--btn-secondary-border':'#788862',
    '--btn-secondary-text':'#f1ecd9',
    '--btn-secondary-hover-bg':'rgba(196,166,74,.08)',
    '--btn-primary-text':'#f1ecd9',
    '--btn-success-text':'#f1ecd9',
    '--btn-danger-text':'#f1ecd9',
    '--btn-warning-text':'#f1ecd9',
    '--pressed-text':'#1c2317',
    '--icon-color':'#dbc483',
    '--icon-bg':'rgba(196,166,74,.12)',
    '--icon-border':'rgba(196,166,74,.28)',
    '--icon-shadow':'0 2px 8px rgba(0,0,0,.24)',
    '--link':'#e4d7a7',
    '--link-hover':'#f1e8c6',
    '--select-option-bg':'#25301e',
    '--select-option-hover':'#556847',
    '--card-label-color':'#d7d0b4',
    '--special-card-label':'#d7d0b4'
  },
  branco: {
    '--bg':'#F8FAFC',
    '--sidebar':'#FFFFFF',
    '--card':'#FFFFFF',
    '--card2':'#F1F5F9',
    '--border':'#E5E7EB',
    '--accent':'#2563EB',
    '--accent2':'#1D4ED8',
    '--text':'#000000',
    '--muted':'#000000',
    '--success':'#16A34A',
    '--warning':'#D97706',
    '--danger':'#DC2626',
    '--sidebar-text':'#111827',
    '--menu-hover-bg':'#EFF6FF',
    '--menu-hover-text':'#1D4ED8',
    '--menu-active-bg':'#DBEAFE',
    '--menu-active-text':'#2563EB',
    '--table-head-bg':'#F1F5F9',
    '--table-row-hover':'#EFF6FF',
    '--input-bg':'#FFFFFF',
    '--input-border':'#CBD5E1',
    '--input-focus-shadow':'0 0 0 3px rgba(37,99,235,.18)',
    '--btn-secondary-bg':'#FFFFFF',
    '--btn-secondary-border':'#CBD5E1',
    '--btn-secondary-text':'#000000',
    '--btn-secondary-hover-bg':'#EFF6FF',
    '--btn-primary-text':'#000000',
    '--btn-success-text':'#000000',
    '--btn-danger-text':'#000000',
    '--btn-warning-text':'#000000',
    '--pressed-text':'#2563EB',
    '--icon-color':'#1D4ED8',
    '--icon-bg':'#DBEAFE',
    '--icon-border':'#93C5FD',
    '--icon-shadow':'0 2px 8px rgba(37,99,235,.18)',
    '--link':'#2563EB',
    '--link-hover':'#1D4ED8',
    '--select-option-bg':'#FFFFFF',
    '--select-option-hover':'#DBEAFE',
    '--card-label-color':'#000000',
    '--special-card-label':'#000000',
    '--fw-system-name':'800',
    '--fw-page-title':'800',
    '--fw-subtitle':'700',
    '--fw-card-title':'700',
    '--fw-menu-item':'700',
    '--fw-table-head':'800',
    '--fw-section-title':'700',
    '--fw-important-label':'600',
    '--fw-body':'400'
  }
};

var _ALLOWED_THEMES = { verde: true, branco: true };
var _DEFAULT_THEME_LOGO = '/static/logo-bpfron.png.png';
var _THEME_LOGOS = {
  verde: _DEFAULT_THEME_LOGO,
  branco: _DEFAULT_THEME_LOGO
};

function normalizeThemeName(name) {
  if (name === 'claro-branco') return 'branco';
  if (name === 'azul' || name === 'cinza' || name === 'claro') return 'verde';
  return _ALLOWED_THEMES[name] ? name : 'verde';
}

function updateThemeLogo(themeName) {
  var logo = document.getElementById('sidebar-theme-logo');
  if (!logo) return;
  var nextSrc = _THEME_LOGOS[themeName] || _THEME_LOGOS.branco;
  logo.onerror = function() {
    if (this.dataset.fallbackApplied === '1') {
      this.style.display = 'none';
      return;
    }
    this.dataset.fallbackApplied = '1';
    this.src = _THEME_LOGOS.branco;
    this.style.display = '';
  };
  logo.dataset.fallbackApplied = '0';
  logo.style.display = '';
  logo.src = nextSrc;
}

function applyTheme(name) {
  var resolved = normalizeThemeName(name);
  var t = _THEMES[resolved] || _THEMES['verde'];
  Object.keys(t).forEach(function(k){ document.documentElement.style.setProperty(k, t[k]); });
  document.documentElement.setAttribute('data-theme', resolved);
  localStorage.setItem('bpfron_theme', resolved);
  updateThemeLogo(resolved);
  document.querySelectorAll('#cfg-theme-list [data-theme]').forEach(function(el){
    var active = el.getAttribute('data-theme') === resolved;
    el.style.borderColor = active ? 'var(--accent)' : 'var(--border)';
    el.style.background  = active ? 'var(--menu-active-bg)' : '';
  });
}
(function(){
  var saved = localStorage.getItem('bpfron_theme');
  applyTheme(normalizeThemeName(saved));
})();

function saveRefreshSetting() {
  var ms = parseInt(document.getElementById('cfg-refresh').value || '15000');
  localStorage.setItem('bpfron_refresh_interval', ms);
  _startAutoRefresh();
}
var _storageDefaults = {
  event_images_dir: '/app/uploads',
  abordagem_images_dir: '/app/abordados',
  metadata_dir: '/app/metadata'
};
var _storageFieldMeta = {
  event_images_dir: {
    inputId: 'storage-event-images-dir',
    label: 'Imagens de eventos',
    presets: ['/app/uploads', 'uploads', '/mnt/dados/uploads', '/srv/fronteira/uploads']
  },
  abordagem_images_dir: {
    inputId: 'storage-abordagem-images-dir',
    label: 'Imagens de abordagens',
    presets: ['/app/abordados', 'abordados', '/mnt/dados/abordados', '/srv/fronteira/abordados']
  },
  metadata_dir: {
    inputId: 'storage-metadata-dir',
    label: 'Metadados (YOLO / JSON)',
    presets: ['/app/metadata', 'metadata', '/mnt/dados/metadata', '/srv/fronteira/metadata']
  }
};
var _storagePickerField = null;
var _storageVolumesCache = [];
function _storageSetMessage(kind, text) {
  var errEl = document.getElementById('storage-error');
  var okEl = document.getElementById('storage-ok');
  if (errEl) errEl.textContent = kind === 'error' ? (text || '') : '';
  if (okEl) okEl.textContent = kind === 'ok' ? (text || '') : '';
}
function _storageFillForm(data) {
  document.getElementById('storage-event-images-dir').value = data.event_images_dir || '';
  document.getElementById('storage-abordagem-images-dir').value = data.abordagem_images_dir || '';
  document.getElementById('storage-metadata-dir').value = data.metadata_dir || '';
}
function _storageSetPickerError(text) {
  var errEl = document.getElementById('storage-path-picker-error');
  if (errEl) errEl.textContent = text || '';
}
function _storageBuildPathFromMount(mountPoint) {
  var meta = _storageFieldMeta[_storagePickerField || 'event_images_dir'];
  if (!meta) return mountPoint;
  var currentValue = (document.getElementById(meta.inputId).value || '').trim();
  var suffix = currentValue.replace(/^\/app\//, '').replace(/^\/+/, '');
  if (!suffix) {
    if (_storagePickerField === 'abordagem_images_dir') suffix = 'abordados';
    else if (_storagePickerField === 'metadata_dir') suffix = 'metadata';
    else suffix = 'uploads';
  }
  return String(mountPoint || '').replace(/\/+$/, '') + '/' + suffix.replace(/^\/+/, '');
}
function _storageUsageColor(percent) {
  if (percent >= 90) return '#ef4444';
  if (percent >= 75) return '#f59e0b';
  return '#22c55e';
}
function _groupStorageVolumesByDisk() {
  var groups = {};
  (_storageVolumesCache || []).forEach(function(item) {
    var diskKey = String(item.device || item.backing_mount || item.mount_point || item.label || 'disco');
    if (!groups[diskKey]) {
      groups[diskKey] = {
        key: diskKey,
        mount_point: item.device || item.backing_mount || item.mount_point || diskKey,
        device: item.device || 'disco',
        fs_type: item.fs_type || 'fs',
        total_gb: item.total_gb,
        used_gb: item.used_gb,
        free_gb: item.free_gb,
        used_percent: item.used_percent,
        items: [],
      };
    }
    groups[diskKey].items.push(item);
  });
  return Object.keys(groups).sort().map(function(key) { return groups[key]; });
}
function _renderStorageVolumeDashboard() {
  var summaryEl = document.getElementById('storage-volume-summary');
  var chartEl = document.getElementById('storage-volume-chart');
  if (!summaryEl || !chartEl) return;
  if (!_storageVolumesCache.length) {
    summaryEl.innerHTML = '<div style="font-size:.8rem;color:var(--muted)">Nenhum disco detectado para resumir.</div>';
    chartEl.innerHTML = '';
    return;
  }
  var diskGroups = _groupStorageVolumesByDisk();
  summaryEl.innerHTML = diskGroups.map(function(group) {
    var percent = Number(group.used_percent || 0);
    var color = _storageUsageColor(percent);
    var title = group.mount_point || 'Disco';
    var subtitle = group.items.map(function(item) { return item.label || item.mount_point || 'caminho'; }).join(' • ');
    return '<div class="card" style="padding:14px 16px;background:rgba(255,255,255,.03);border:1px solid var(--border)">'
      + '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px">'
      + '<div style="font-weight:700">' + title + '</div>'
      + '<span class="badge" style="background:' + color + '22;color:' + color + ';border:1px solid ' + color + '55">' + percent.toLocaleString('pt-BR', {maximumFractionDigits:1}) + '% usado</span>'
      + '</div>'
      + '<div style="font-size:.76rem;color:var(--muted);margin-top:6px">' + subtitle + '</div>'
      + '<div style="font-size:.72rem;color:var(--muted);margin-top:3px">' + (group.device || 'disco') + ' · ' + (group.fs_type || 'fs') + '</div>'
      + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px">'
      + '<div><div style="font-size:.7rem;color:var(--muted)">Total</div><div style="font-weight:700">' + (group.total_gb != null ? group.total_gb.toLocaleString('pt-BR') + ' GB' : '—') + '</div></div>'
      + '<div><div style="font-size:.7rem;color:var(--muted)">Usado</div><div style="font-weight:700">' + (group.used_gb != null ? group.used_gb.toLocaleString('pt-BR') + ' GB' : '—') + '</div></div>'
      + '<div><div style="font-size:.7rem;color:var(--muted)">Livre</div><div style="font-weight:700">' + (group.free_gb != null ? group.free_gb.toLocaleString('pt-BR') + ' GB' : '—') + '</div></div>'
      + '</div>'
      + '</div>';
  }).join('');
  chartEl.innerHTML = '<div class="card" style="padding:16px 18px;background:rgba(255,255,255,.03);border:1px solid var(--border)">'
    + '<div style="font-weight:700;font-size:.92rem;margin-bottom:4px">&#128202; Capacidade dos discos</div>'
    + '<div style="font-size:.76rem;color:var(--muted);margin-bottom:16px">Visual de uso real por disco, com ocupado e livre.</div>'
    + diskGroups.map(function(group) {
    var used = Number(group.used_percent || 0);
    var free = Math.max(0, 100 - used);
    var color = _storageUsageColor(used);
    var ringBackground = 'conic-gradient(' + color + ' 0% ' + used + '%, rgba(255,255,255,.12) ' + used + '% 100%)';
    var title = group.mount_point || 'Disco';
    var subtitle = group.items.map(function(item) {
      var label = item.label || item.mount_point || 'caminho';
      return label + ' (' + (item.mount_point || '—') + ')';
    }).join(' • ');
    var detailLegend = group.items.map(function(item) {
      return '<span style="display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border-radius:999px;background:rgba(255,255,255,.05)"><span style="width:8px;height:8px;border-radius:999px;background:' + color + ';display:inline-block;opacity:.8"></span>' + (item.label || item.mount_point || 'caminho') + '</span>';
    }).join('');
    return '<div style="display:grid;grid-template-columns:minmax(110px,140px) 1fr;gap:18px;align-items:center;padding:14px 0;border-top:1px solid rgba(255,255,255,.06)">'
      + '<div style="display:flex;justify-content:center">'
      + '<div style="width:104px;height:104px;border-radius:50%;background:' + ringBackground + ';display:flex;align-items:center;justify-content:center;box-shadow:inset 0 0 0 1px rgba(255,255,255,.06)">'
      + '<div style="width:70px;height:70px;border-radius:50%;background:var(--card);display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px solid rgba(255,255,255,.06)">'
      + '<div style="font-size:1rem;font-weight:800;color:' + color + '">' + used.toLocaleString('pt-BR', {maximumFractionDigits:1}) + '%</div>'
      + '<div style="font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">usado</div>'
      + '</div>'
      + '</div>'
      + '</div>'
      + '<div>'
      + '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:8px">'
      + '<div style="font-weight:700;font-size:.92rem">' + title + '</div>'
      + '<div style="font-size:.76rem;color:var(--muted)">' + (group.device || 'disco') + ' · ' + (group.fs_type || 'fs') + '</div>'
      + '</div>'
      + '<div style="font-size:.75rem;color:var(--muted);margin-bottom:8px">' + subtitle + '</div>'
      + '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">' + detailLegend + '</div>'
      + '<div style="height:18px;border-radius:999px;overflow:hidden;background:rgba(255,255,255,.08);display:flex;margin-bottom:10px">'
      + '<div style="width:' + used + '%;background:' + color + ';transition:width .25s ease"></div>'
      + '<div style="width:' + free + '%;background:rgba(255,255,255,.16);transition:width .25s ease"></div>'
      + '</div>'
      + '<div style="display:flex;gap:14px;flex-wrap:wrap;font-size:.78rem">'
      + '<span style="display:inline-flex;align-items:center;gap:6px"><span style="width:10px;height:10px;border-radius:999px;background:' + color + ';display:inline-block"></span>Ocupado: ' + (group.used_gb != null ? group.used_gb.toLocaleString('pt-BR') + ' GB' : '—') + '</span>'
      + '<span style="display:inline-flex;align-items:center;gap:6px"><span style="width:10px;height:10px;border-radius:999px;background:rgba(255,255,255,.35);display:inline-block"></span>Livre: ' + (group.free_gb != null ? group.free_gb.toLocaleString('pt-BR') + ' GB' : '—') + '</span>'
      + '<span style="color:var(--muted)">Total: ' + (group.total_gb != null ? group.total_gb.toLocaleString('pt-BR') + ' GB' : '—') + '</span>'
      + '</div>'
      + '</div>'
      + '</div>';
  }).join('')
    + '</div>';
}
function _renderStorageVolumes() {
  var wrap = document.getElementById('storage-path-volumes');
  if (!wrap) return;
  if (!_storageVolumesCache.length) {
    wrap.innerHTML = '<div style="font-size:.76rem;color:var(--muted)">Nenhum disco extra detectado. Voc&#234; ainda pode digitar o caminho manualmente.</div>';
    return;
  }
  wrap.innerHTML = _storageVolumesCache.map(function(item) {
    var safeMount = String(item.mount_point || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    var freeText = item.free_gb != null ? (item.free_gb.toLocaleString('pt-BR') + ' GB livres') : 'Espa\u00e7o indispon\u00edvel';
    var devText = item.device || 'disco';
    return '<button class="btn btn-outline btn-sm" type="button" onclick="selectStorageVolume(\'' + safeMount + '\')">'
      + '&#128452; ' + item.mount_point
      + '<span style="display:block;font-size:.7rem;color:var(--muted);margin-top:3px">' + devText + ' \u00b7 ' + freeText + '</span>'
      + '</button>';
  }).join('');
  _renderStorageVolumeDashboard();
}
async function _loadStorageVolumes(force) {
  if (!force && _storageVolumesCache.length) {
    _renderStorageVolumes();
    return;
  }
  var wrap = document.getElementById('storage-path-volumes');
  if (wrap) wrap.innerHTML = '<div style="font-size:.76rem;color:var(--muted)"><span class="spinner"></span> Detectando discos do servidor...</div>';
  try {
    var response = await fetch('/api/storage/volumes');
    var data = await response.json().catch(function(){ return {}; });
    if (!response.ok) throw new Error(data.detail || 'Falha ao listar discos do servidor.');
    _storageVolumesCache = data.items || [];
    _renderStorageVolumes();
    _renderStorageVolumeDashboard();
  } catch (err) {
    if (wrap) wrap.innerHTML = '<div style="font-size:.76rem;color:var(--danger)">' + (err.message || 'Falha ao listar discos do servidor.') + '</div>';
    var summaryEl = document.getElementById('storage-volume-summary');
    var chartEl = document.getElementById('storage-volume-chart');
    if (summaryEl) summaryEl.innerHTML = '<div style="font-size:.8rem;color:var(--danger)">Falha ao carregar resumo dos discos.</div>';
    if (chartEl) chartEl.innerHTML = '';
  }
}
function openStoragePathPicker(fieldKey) {
  var meta = _storageFieldMeta[fieldKey];
  var modal = document.getElementById('storage-path-modal');
  if (!meta || !modal) return;
  _storagePickerField = fieldKey;
  document.getElementById('storage-path-modal-subtitle').textContent = meta.label;
  var currentValue = (document.getElementById(meta.inputId).value || '').trim();
  document.getElementById('storage-path-manual-input').value = currentValue || (meta.presets[0] || '');
  var presetsWrap = document.getElementById('storage-path-presets');
  presetsWrap.innerHTML = (meta.presets || []).map(function(path) {
    var safePath = String(path).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    return '<button class="btn btn-outline btn-sm" type="button" onclick="selectStoragePreset(\'' + safePath + '\')">&#128193; ' + path + '</button>';
  }).join('');
  _storageSetPickerError('');
  openModal('storage-path-modal');
  _loadStorageVolumes();
  setTimeout(function(){
    var input = document.getElementById('storage-path-manual-input');
    if (input) input.focus();
  }, 80);
}
function closeStoragePathPicker() {
  _storagePickerField = null;
  _storageSetPickerError('');
  closeModal('storage-path-modal');
}
function selectStoragePreset(path) {
  var input = document.getElementById('storage-path-manual-input');
  if (input) input.value = path || '';
  _storageSetPickerError('');
}
function selectStorageVolume(mountPoint) {
  var input = document.getElementById('storage-path-manual-input');
  if (input) input.value = _storageBuildPathFromMount(mountPoint);
  _storageSetPickerError('');
}
function applyStoragePathPicker() {
  if (!_storagePickerField) return;
  var meta = _storageFieldMeta[_storagePickerField];
  if (!meta) return;
  var input = document.getElementById('storage-path-manual-input');
  var target = document.getElementById(meta.inputId);
  var value = (input && input.value || '').trim();
  if (!value) {
    _storageSetPickerError('Informe um caminho antes de aplicar.');
    return;
  }
  if (target) target.value = value;
  closeStoragePathPicker();
}
async function loadStorageSettings() {
  _storageSetMessage('', '');
  _loadStorageVolumes();
  try {
    var response = await fetch('/api/storage/settings');
    var data = await response.json().catch(function(){ return {}; });
    if (!response.ok) throw new Error(data.detail || 'Falha ao carregar caminhos de storage.');
    _storageDefaults = Object.assign({}, _storageDefaults, data || {});
    _storageFillForm(_storageDefaults);
    _markTabLoaded('storage');
  } catch (err) {
    _storageSetMessage('error', err.message || 'Falha ao carregar caminhos de storage.');
  }
}
function restoreStorageDefaults() {
  _storageSetMessage('', '');
  _storageFillForm(_storageDefaults);
}
async function saveStorageSettings() {
  _storageSetMessage('', '');
  var body = {
    event_images_dir: (document.getElementById('storage-event-images-dir').value || '').trim(),
    abordagem_images_dir: (document.getElementById('storage-abordagem-images-dir').value || '').trim(),
    metadata_dir: (document.getElementById('storage-metadata-dir').value || '').trim()
  };
  if (!body.event_images_dir || !body.abordagem_images_dir || !body.metadata_dir) {
    _storageSetMessage('error', 'Preencha todos os caminhos antes de salvar.');
    return;
  }
  try {
    var response = await fetch('/api/storage/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    var data = await response.json().catch(function(){ return {}; });
    if (!response.ok) throw new Error(data.detail || 'Falha ao salvar caminhos de storage.');
    _storageDefaults = Object.assign({}, _storageDefaults, data.settings || body);
    _storageFillForm(_storageDefaults);
    _storageSetMessage('ok', 'Caminhos de storage salvos com sucesso.');
  } catch (err) {
    _storageSetMessage('error', err.message || 'Falha ao salvar caminhos de storage.');
  }
}
function saveCfgAlarmSound() {
  localStorage.setItem('bpfron_alarm_sound', document.getElementById('cfg-alarm-sound').value);
}
function testCfgAlarmSound() {
  var s = document.getElementById('cfg-alarm-sound').value;
  if (s !== 'none') playAlarmSound(s);
}
function initConfigTab() {
  var meEl = document.getElementById('cfg-me-username');
  if (meEl) meEl.textContent = window._authUser || '';
  var sysCard = document.getElementById('cfg-sistema');
  if (sysCard) sysCard.style.display = (window._authRole === 'admin') ? 'block' : 'none';
  var sysUser = document.getElementById('cfg-sys-user');
  if (sysUser) sysUser.textContent = (window._authName || window._authUser) + ' (' + (window._authRole) + ')';
  var curTheme = normalizeThemeName(localStorage.getItem('bpfron_theme'));
  localStorage.setItem('bpfron_theme', curTheme);
  document.querySelectorAll('#cfg-theme-list [data-theme]').forEach(function(el){
    var active = el.getAttribute('data-theme') === curTheme;
    el.style.borderColor = active ? 'var(--accent)' : 'var(--border)';
    el.style.background  = active ? 'var(--menu-active-bg)' : '';
  });
  var cfgRef = document.getElementById('cfg-refresh');
  if (cfgRef) cfgRef.value = localStorage.getItem('bpfron_refresh_interval') || '15000';
  var cfgSound = document.getElementById('cfg-alarm-sound');
  if (cfgSound) cfgSound.value = localStorage.getItem('bpfron_alarm_sound') || 'beep';
  ['cfg-pw-current','cfg-pw-new','cfg-pw-new2'].forEach(function(id){
    var el = document.getElementById(id); if (el) el.value = '';
  });
  var errEl = document.getElementById('cfg-pw-error'); if (errEl) errEl.textContent='';
  var okEl  = document.getElementById('cfg-pw-ok');    if (okEl)  okEl.textContent='';
}
async function changeMyPassword() {
  var errEl = document.getElementById('cfg-pw-error');
  var okEl  = document.getElementById('cfg-pw-ok');
  var btn   = document.getElementById('cfg-pw-btn');
  errEl.textContent = ''; okEl.textContent = '';
  var cur = document.getElementById('cfg-pw-current').value;
  var nw  = document.getElementById('cfg-pw-new').value;
  var nw2 = document.getElementById('cfg-pw-new2').value;
  if (!cur) { errEl.textContent = 'Informe a senha atual.'; return; }
  if (!nw)  { errEl.textContent = 'Informe a nova senha.'; return; }
  if (nw.length < 6) { errEl.textContent = 'Nova senha deve ter pelo menos 6 caracteres.'; return; }
  if (nw !== nw2)    { errEl.textContent = 'As senhas n\u00e3o coincidem.'; return; }
  btn.disabled = true; btn.textContent = 'Salvando...';
  try {
    var r = await fetch('/api/auth/password', { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ current_password: cur, new_password: nw }) });
    if (!r.ok) { var ed = await r.json().catch(function(){ return {}; }); throw new Error(ed.detail || 'HTTP '+r.status); }
    okEl.textContent = '\u2713 Senha alterada com sucesso!';
    ['cfg-pw-current','cfg-pw-new','cfg-pw-new2'].forEach(function(id){ document.getElementById(id).value=''; });
  } catch(e) {
    errEl.textContent = 'Erro: ' + e.message;
  } finally {
    btn.disabled = false; btn.innerHTML = '&#128274; Alterar Senha';
  }
}

// ===== USUARIOS =====
var _usersCache = [];
var _adminActivityOnlineCache = [];
var _adminActivityRecentCache = [];
var _usersActivityVisible = false;
var _usersActivityLoaded = false;

function _fmtAdminTs(value, withSeconds) {
  if (!value) return '\u2014';
  var opts = { day:'2-digit', month:'2-digit', year:'2-digit', hour:'2-digit', minute:'2-digit' };
  if (withSeconds) opts.second = '2-digit';
  return new Date(value).toLocaleString('pt-BR', opts);
}

function _timeAgo(value) {
  if (!value) return '\u2014';
  var diff = Math.max(0, Date.now() - new Date(value).getTime());
  var sec = Math.floor(diff / 1000);
  if (sec < 60) return sec + 's';
  var min = Math.floor(sec / 60);
  if (min < 60) return min + ' min';
  var hours = Math.floor(min / 60);
  if (hours < 24) return hours + ' h';
  return Math.floor(hours / 24) + ' d';
}

function _activityBadge(activityType, activityLabel) {
  var kind = (activityType || '').toLowerCase();
  var cls = kind === 'login'
    ? 'badge-green'
    : (kind === 'logout' || kind === 'produtividade_reset_negado')
      ? 'badge-red'
      : kind === 'produtividade_reset'
        ? 'badge-green'
        : 'badge-yellow';
  return '<span class="badge ' + cls + '">' + (activityLabel || activityType || 'Atividade') + '</span>';
}

function _syncUsersActivityToggleButton() {
  var btn = document.getElementById('users-activity-toggle-btn');
  if (!btn) return;
  btn.innerHTML = _usersActivityVisible ? '&#128203; Ocultar logs' : '&#128203; Ver logs de acesso';
}

async function toggleUsersActivitySection(forceOpen) {
  var panel = document.getElementById('users-activity-panel');
  if (!panel) return;
  var nextVisible = typeof forceOpen === 'boolean' ? forceOpen : !_usersActivityVisible;
  _usersActivityVisible = nextVisible;
  panel.style.display = nextVisible ? 'block' : 'none';
  var header = document.getElementById('users-main-header');
  var cards = document.getElementById('users-cards');
  var searchWrap = document.getElementById('users-search-wrap');
  var usersTableWrap = document.getElementById('users-table-wrap');
  if (header) header.style.display = nextVisible ? 'none' : 'flex';
  if (cards) cards.style.display = nextVisible ? 'none' : 'flex';
  if (searchWrap) searchWrap.style.display = nextVisible ? 'none' : '';
  if (usersTableWrap) usersTableWrap.style.display = nextVisible ? 'none' : '';
  _syncUsersActivityToggleButton();
  if (nextVisible && !_usersActivityLoaded) {
    await loadAdminActivity();
  }
}

function _renderOnlineUsers(items) {
  var tbody = document.getElementById('users-online-tbody');
  if (!tbody) return;
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--muted);padding:24px">Nenhum usuario online agora.</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(function(item){
    var name = item.full_name && item.full_name !== item.username
      ? '<div style="font-weight:700;color:var(--accent)">' + item.full_name + '</div><div style="font-size:.72rem;color:var(--muted)">@' + item.username + '</div>'
      : '<div style="font-weight:700;color:var(--accent)">' + item.username + '</div>';
    var roleBadge = item.role === 'admin'
      ? '<span class="badge badge-red">Admin</span>'
      : item.role === 'operador'
        ? '<span class="badge badge-green">Operador</span>'
        : '<span class="badge">Visualizador</span>';
    var pageText = item.last_page_label || item.last_page_key || '\u2014';
    var sessionInfo = item.active_sessions > 1
      ? '<div style="font-size:.7rem;color:var(--muted);margin-top:3px">' + item.active_sessions + ' sessoes</div>'
      : '<div style="font-size:.7rem;color:var(--muted);margin-top:3px">' + (item.ip_address || 'IP oculto') + '</div>';
    return '<tr>'
      + '<td>' + name + '</td>'
      + '<td>' + roleBadge + '</td>'
      + '<td><div style="font-weight:600">' + pageText + '</div>' + sessionInfo + '</td>'
      + '<td style="white-space:nowrap;color:var(--muted)">' + _timeAgo(item.last_seen_at) + '</td>'
      + '</tr>';
  }).join('');
}

function _renderRecentActivity(items) {
  var tbody = document.getElementById('users-activity-tbody');
  if (!tbody) return;
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:24px">Nenhum log registrado ainda.</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(function(item){
    var userText = item.full_name && item.full_name !== item.username
      ? '<div style="font-weight:700;color:var(--accent)">' + item.full_name + '</div><div style="font-size:.72rem;color:var(--muted)">@' + item.username + '</div>'
      : '<span style="font-weight:700;color:var(--accent)">' + item.username + '</span>';
    var pageText = item.page_label || item.page_key || '\u2014';
    return '<tr>'
      + '<td style="white-space:nowrap;color:var(--muted)">' + _fmtAdminTs(item.created_at, true) + '</td>'
      + '<td>' + userText + '</td>'
      + '<td>' + _activityBadge(item.activity_type, item.activity_label) + '</td>'
      + '<td>' + pageText + '</td>'
      + '<td style="font-size:.78rem;color:var(--muted)">' + (item.ip_address || '\u2014') + '</td>'
      + '</tr>';
  }).join('');
}

async function loadAdminActivity() {
  if ((window._authRole || '') !== 'admin') return;
  var err = document.getElementById('users-activity-error');
  var onlineBody = document.getElementById('users-online-tbody');
  var recentBody = document.getElementById('users-activity-tbody');
  if (err) err.textContent = '';
  if (onlineBody && !onlineBody.children.length) {
    onlineBody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--muted);padding:24px"><span class="spinner"></span> Carregando...</td></tr>';
  }
  if (recentBody && !recentBody.children.length) {
    recentBody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:24px"><span class="spinner"></span> Carregando...</td></tr>';
  }
  try {
    var responses = await Promise.all([
      fetch('/api/admin/activity/overview'),
      fetch('/api/admin/activity/online'),
      fetch('/api/admin/activity/recent?limit=80')
    ]);
    responses.forEach(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
    });
    var overview = await responses[0].json();
    var online = await responses[1].json();
    var recent = await responses[2].json();

    _adminActivityOnlineCache = online.items || [];
    _adminActivityRecentCache = recent.items || [];

    document.getElementById('ua-online-users').textContent = (overview.online_users || 0).toLocaleString('pt-BR');
    document.getElementById('ua-active-sessions').textContent = (overview.active_sessions || 0).toLocaleString('pt-BR');
    document.getElementById('ua-logins-today').textContent = (overview.logins_today || 0).toLocaleString('pt-BR');
    document.getElementById('ua-pageviews-today').textContent = (overview.page_views_today || 0).toLocaleString('pt-BR');
    document.getElementById('ua-last-activity').textContent = overview.last_activity_at
      ? 'Ultima atividade ' + _fmtAdminTs(overview.last_activity_at, true)
      : 'Sem atividade recente';

    _renderOnlineUsers(_adminActivityOnlineCache);
    _renderRecentActivity(_adminActivityRecentCache);
    _usersActivityLoaded = true;
  } catch (e) {
    if (err) err.textContent = 'Erro ao carregar monitoramento de acesso: ' + e.message;
    if (onlineBody) onlineBody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--danger);padding:24px">Falha ao carregar usuarios online.</td></tr>';
    if (recentBody) recentBody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--danger);padding:24px">Falha ao carregar logs recentes.</td></tr>';
  }
}

async function loadUsers() {
  var tbody = document.getElementById('users-tbody');
  var err   = document.getElementById('users-error');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:28px"><span class="spinner"></span> Carregando...</td></tr>';
  if (err) err.textContent = '';
  try {
    var r = await fetch('/api/users');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    var d = await r.json();
    _usersCache = d.items || [];
    _renderUsersTable(_usersCache);
    // Atualizar cards
    document.getElementById('uc-total').textContent     = _usersCache.length;
    document.getElementById('uc-admins').textContent    = _usersCache.filter(function(u){ return u.role==='admin'; }).length;
    document.getElementById('uc-operators').textContent = _usersCache.filter(function(u){ return u.role==='operador' || u.role==='operator'; }).length;
    document.getElementById('uc-inactive').textContent  = _usersCache.filter(function(u){ return !u.ativa; }).length;
    _syncUsersActivityToggleButton();
    if (_usersActivityVisible) await loadAdminActivity();
    _markTabLoaded('usuarios');
  } catch(e) {
    if (err) err.textContent = 'Erro ao carregar usu\u00e1rios: ' + e.message;
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--danger);padding:32px">Falha ao carregar.</td></tr>';
  }
}

function _filterUsersTable() {
  var q = (document.getElementById('users-search').value || '').toLowerCase();
  var filtered = q ? _usersCache.filter(function(u){
    return (u.username||'').toLowerCase().includes(q) || (u.full_name||'').toLowerCase().includes(q);
  }) : _usersCache;
  _renderUsersTable(filtered);
}

function _renderUsersTable(items) {
  var tbody = document.getElementById('users-tbody');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:32px">Nenhum usu\u00e1rio encontrado.</td></tr>';
    return;
  }
  var roleInfo = {
    admin:    { lbl:'Administrador', cls:'badge-red',   icon:'&#128081;' },
    operador: { lbl:'Operador',      cls:'badge-green', icon:'&#128100;' },
    operator: { lbl:'Operador',      cls:'badge-green', icon:'&#128100;' },
    visualizador: { lbl:'Visualizador', cls:'', icon:'&#128065;&#65039;' },
    visualizacao: { lbl:'Visualizador',  cls:'',    icon:'&#128065;&#65039;' },
    viewer:   { lbl:'Visualizador',  cls:'',    icon:'&#128065;&#65039;' }
  };
  tbody.innerHTML = items.map(function(u){
    var ri  = roleInfo[u.role] || { lbl: u.role, cls:'', icon:'' };
    var dt  = u.created_at ? new Date(u.created_at).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'}) : '\u2014';
    var isSelf = (u.username === window._authUser);
    var isMainAdmin = (u.username === 'admin');
    var enc = encodeURIComponent(JSON.stringify(u));
    return '<tr>'
      + '<td style="color:var(--muted);font-size:.8rem">' + u.id + '</td>'
      + '<td><span style="font-weight:700;color:var(--accent)">' + u.username + '</span>'
          + (isSelf ? ' <span style="font-size:.68rem;color:var(--muted);background:rgba(255,255,255,.12);padding:1px 6px;border-radius:4px">voc\u00ea</span>' : '') + '</td>'
      + '<td>' + (u.full_name || '<span style="color:var(--muted)">\u2014</span>') + '</td>'
      + '<td><span class="badge ' + ri.cls + '">' + ri.icon + ' ' + ri.lbl + '</span></td>'
      + '<td>' + (u.ativa
          ? '<span class="badge badge-green">&#9679; Ativo</span>'
          : '<span class="badge badge-red">&#9679; Inativo</span>') + '</td>'
      + '<td style="font-size:.78rem;color:var(--muted)">' + dt + '</td>'
      + '<td class="action-cell">'
      + (isMainAdmin
          ? '<span style="color:var(--muted);font-size:.72rem">admin principal</span>'
          : '<div class="action-buttons">'
            + '<button class="btn btn-outline btn-xs" onclick="openUserModal(decodeURIComponent(\'' + enc + '\'))" title="Editar">&#9998; Editar</button>'
            + '<button class="btn btn-danger btn-xs" onclick="deleteUser(' + u.id + ',\'' + u.username + '\')" title="Excluir">&#128465; Excluir</button>'
            + '</div>')
      + '</td>'
      + '</tr>';
  }).join('');
}

var _userEditId = null;
function openUserModal(encodedOrObj) {
  // encodedOrObj pode ser: objeto direto, string JSON já decodificada (vinda do onclick)
  // NÃO fazer decodeURIComponent aqui — o onclick já decodifica antes de chamar a função
  var u = encodedOrObj
    ? (typeof encodedOrObj === 'string' ? JSON.parse(encodedOrObj) : encodedOrObj)
    : null;
  _userEditId = u ? u.id : null;
  document.getElementById('user-modal-title').textContent = u ? 'Editar Usu\u00e1rio' : 'Novo Usu\u00e1rio';
  document.getElementById('um-username').value  = u ? (u.username||'') : '';
  document.getElementById('um-fullname').value  = u ? (u.full_name||'') : '';
  document.getElementById('um-role').value      = u ? (u.role||'operador') : 'operador';
  document.getElementById('um-ativa').checked   = u ? !!u.ativa : true;
  document.getElementById('um-password').value  = '';
  document.getElementById('um-password2').value = '';
  document.getElementById('um-username').readOnly = !!u;
  document.getElementById('um-username').style.opacity = u ? '.6' : '1';
  document.getElementById('um-pw-label').textContent = u ? 'Nova Senha (opcional)' : 'Senha *';
  document.getElementById('um-password').placeholder  = u ? 'Deixe em branco para manter' : 'M\u00ednimo 6 caracteres';
  document.getElementById('um-password2').placeholder = u ? 'Confirme se alterar' : 'Repita a senha';
  document.getElementById('user-form-error').textContent = '';
  openModal('user-modal');
  setTimeout(function(){ document.getElementById(u ? 'um-fullname' : 'um-username').focus(); }, 80);
}

async function saveUser() {
  var errEl  = document.getElementById('user-form-error');
  var saveBtn = document.getElementById('um-save-btn');
  errEl.textContent = '';
  var username  = document.getElementById('um-username').value.trim().toLowerCase();
  var full_name = document.getElementById('um-fullname').value.trim();
  var roleRaw   = document.getElementById('um-role').value;
  var roleMap = {
    'admin': 'admin',
    'administrador': 'admin',
    'operador': 'operador',
    'operator': 'operador',
    'visualizacao': 'visualizacao',
    'visualização': 'visualizacao',
    'visualizador': 'visualizacao',
    'viewer': 'visualizacao'
  };
  var roleKey = (roleRaw || '').toString().trim().toLowerCase();
  var role    = roleMap[roleKey] || roleKey;
  var ativa     = document.getElementById('um-ativa').checked;
  var pw        = document.getElementById('um-password').value;
  var pw2       = document.getElementById('um-password2').value;
  // Valida\u00e7\u00f5es
  if (!_userEditId && !username) { errEl.textContent = 'Usu\u00e1rio (login) \u00e9 obrigat\u00f3rio.'; return; }
  if (!_userEditId && !pw)       { errEl.textContent = 'Senha \u00e9 obrigat\u00f3ria para novo usu\u00e1rio.'; return; }
  if (['admin','operador','visualizacao'].indexOf(role) < 0) {
    errEl.textContent = 'Perfil inválido. Use apenas: admin, operador ou visualizacao.';
    return;
  }
  if (pw && pw.length < 6)       { errEl.textContent = 'Senha deve ter pelo menos 6 caracteres.'; return; }
  if (pw && pw !== pw2)          { errEl.textContent = 'As senhas n\u00e3o coincidem.'; return; }
  var body = { username: username, full_name: full_name, role: role, ativa: ativa };
  if (pw) body.password = pw;
  saveBtn.disabled = true;
  saveBtn.textContent = 'Salvando...';
  try {
    var url    = _userEditId ? '/api/users/' + _userEditId : '/api/users';
    var method = _userEditId ? 'PUT' : 'POST';
    var r = await fetch(url, { method: method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!r.ok) { var ed = await r.json().catch(function(){ return {}; }); throw new Error(ed.detail || 'HTTP ' + r.status); }
    closeModal('user-modal');
    await loadUsers();
  } catch(e) {
    errEl.textContent = 'Erro: ' + e.message;
  } finally {
    saveBtn.disabled = false;
    saveBtn.innerHTML = '&#128190; Salvar';
  }
}

async function deleteUser(id, username) {
  if (!confirm('Excluir o usu\u00e1rio "' + username + '"?\nEsta a\u00e7\u00e3o n\u00e3o pode ser desfeita.')) return;
  var err = document.getElementById('users-error');
  if (err) err.textContent = '';
  try {
    var r = await fetch('/api/users/' + id, { method: 'DELETE' });
    if (!r.ok) { var ed = await r.json().catch(function(){ return {}; }); throw new Error(ed.detail || 'HTTP ' + r.status); }
    await loadUsers();
  } catch(e) {
    if (err) err.textContent = 'Erro: ' + e.message;
    else alert('Erro: ' + e.message);
  }
}


// ===== ALARMES (CRUD + Histórico) =====
var _almCache = [];
var _almListsCache = [];
var _almUsersCache = [];

function _switchAlarmSub(name, el) {
  document.querySelectorAll('#tab-alarmes .sub-tab').forEach(function(t){ t.classList.remove('active'); t.style.borderBottomColor = 'transparent'; t.style.color = 'var(--muted)'; });
  el.classList.add('active'); el.style.borderBottomColor = 'var(--accent)'; el.style.color = 'var(--accent)';
  document.getElementById('alarm-sub-config').style.display = (name === 'config') ? '' : 'none';
  document.getElementById('alarm-sub-historico').style.display = (name === 'historico') ? '' : 'none';
  if (name === 'historico') _loadHistorico();
  var labels = { config: 'Alarmes / Configuracao', historico: 'Alarmes / Historico' };
  trackPageView('alarmes:' + name, labels[name] || ('Alarmes / ' + name), '/dashboard#alarmes/' + name);
}

async function loadAlarmes() {
  var tbody = document.getElementById('alarmes-tbody');
  var err = document.getElementById('alarmes-error');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:28px"><span class="spinner"></span> Carregando...</td></tr>';
  if (err) err.textContent = '';
  try {
    // Pré-carregar listas e usuários primeiro
    await _preloadAlarmSelects();
    var r = await fetch('/api/alarmes');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    var d = await r.json();
    _almCache = d.items || [];
    _renderAlarmesTable(_almCache);
    document.getElementById('alc-total').textContent = _almCache.length;
    document.getElementById('alc-ativos').textContent = _almCache.filter(function(a){ return a.ativo; }).length;
    document.getElementById('alc-criticos').textContent = _almCache.filter(function(a){ return a.prioridade === 'alta' || a.prioridade === 'critica'; }).length;
    document.getElementById('alc-inativos').textContent = _almCache.filter(function(a){ return !a.ativo; }).length;
    _markTabLoaded('alarmes');
  } catch(e) {
    if (err) err.textContent = 'Erro ao carregar alarmes: ' + e.message;
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:32px">Falha ao carregar.</td></tr>';
  }
}

function _filterAlarmesTable() {
  var q = (document.getElementById('alarmes-search').value || '').toLowerCase();
  var filtered = q ? _almCache.filter(function(a){
    var listName = _almGetListName(a.listas);
    var userStr = _almGetUserNames(a.usuarios);
    return listName.toLowerCase().includes(q) || userStr.toLowerCase().includes(q) || (a.prioridade||'').toLowerCase().includes(q);
  }) : _almCache;
  _renderAlarmesTable(filtered);
}

function _almGetListName(listas) {
  if (!listas || !listas.length) return '\u2014';
  var lid = listas[0];
  var found = _almListsCache.find(function(l){ return l.id === lid; });
  return found ? (found.name||found.nome||'Lista #'+lid) : '#' + lid;
}

function _almGetUserNames(usuarios) {
  if (!usuarios || !usuarios.length) return '\u2014';
  return usuarios.map(function(uid){
    var found = _almUsersCache.find(function(u){ return u.id === uid; });
    return found ? found.username : '#' + uid;
  }).join(', ');
}

function _renderAlarmesTable(items) {
  var tbody = document.getElementById('alarmes-tbody');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:32px">Nenhum alarme cadastrado.</td></tr>';
    return;
  }
  var prioInfo = {
    baixa:  { lbl:'Baixa',         cls:'',            icon:'\u26AA' },
    media:  { lbl:'M\u00e9dia',    cls:'badge-green',  icon:'\u{1F7E0}' },
    alta:   { lbl:'Alta',          cls:'badge-yellow', icon:'\u{1F7E1}' },
    critica:{ lbl:'Cr\u00edtica',  cls:'badge-red',    icon:'\u{1F534}' }
  };
  var isAdmin = (window._authRole === 'admin');
  tbody.innerHTML = items.map(function(a){
    var pi = prioInfo[a.prioridade] || { lbl: a.prioridade, cls:'', icon:'' };
    var enc = encodeURIComponent(JSON.stringify(a));
    var listName = _almGetListName(a.listas);
    var userNames = _almGetUserNames(a.usuarios);
    return '<tr>'
      + '<td style="color:var(--muted);font-size:.8rem">' + a.id + '</td>'
      + '<td><span style="font-weight:700;color:var(--accent)">' + listName + '</span></td>'
      + '<td><span class="badge ' + pi.cls + '">' + pi.icon + ' ' + pi.lbl + '</span></td>'
      + '<td style="font-size:.78rem;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + userNames + '</td>'
      + '<td>' + (a.ativo
        ? '<span class="badge badge-green">\u25CF Ativo</span>'
        : '<span class="badge badge-red">\u25CF Inativo</span>') + '</td>'
      + '<td class="action-cell"><div class="action-buttons">'
        + '<button class="btn btn-outline btn-xs" onclick="testAlarme(' + a.id + ')" title="Testar push">\u{1F514} Testar</button>'
        + (isAdmin
          ? '<button class="btn btn-outline btn-xs" onclick="openAlarmeModal(decodeURIComponent(\'' + enc + '\'))" title="Editar">\u270E Editar</button>'
            + '<button class="btn btn-danger btn-xs" onclick="deleteAlarme(' + a.id + ')" title="Excluir">\u{1F5D1} Excluir</button>'
          : '')
      + '</div></td>'
      + '</tr>';
  }).join('');
}

async function _preloadAlarmSelects() {
  try {
    console.log('[Alarmes] Pré-carregando listas...');
    _almListsCache = await fetchVehicleLists();
    console.log('[Alarmes] Listas pré-carregadas:', _almListsCache.length);
  } catch(e) {
    console.warn('[Alarmes] Erro ao pré-carregar listas:', e.message);
    _almListsCache = []; // Fallback para array vazio
  }
  try {
    console.log('[Alarmes] Pré-carregando usuários...');
    var r2 = await fetch('/api/users');
    if (r2.ok) {
      var d2 = await r2.json();
      _almUsersCache = d2.items || [];
      console.log('[Alarmes] Usuários pré-carregados:', _almUsersCache.length);
    } else {
      throw new Error('HTTP ' + r2.status);
    }
  } catch(e) {
    console.warn('[Alarmes] Erro ao pré-carregar usuários:', e.message);
    _almUsersCache = []; // Fallback para array vazio
  }
}

var _almEditId = null;
function openAlarmeModal(encodedOrObj) {
  // encodedOrObj pode ser: objeto direto, string JSON já decodificada (vinda do onclick)
  // NÃO fazer decodeURIComponent aqui — o onclick já decodifica antes de chamar a função
  var a = encodedOrObj
    ? (typeof encodedOrObj === 'string' ? JSON.parse(encodedOrObj) : encodedOrObj)
    : null;
  _almEditId = a ? a.id : null;
  document.getElementById('alarme-modal-title').textContent = a ? 'Editar Alarme' : 'Novo Alarme';
  document.getElementById('alarme-form-error').textContent = '';
  // Populate lista select
  var sel = document.getElementById('alm-lista');
  var selListaId = (a && a.listas && a.listas.length) ? a.listas[0] : '';
  sel.innerHTML = '<option value="">Selecione uma lista...</option>';
  _almListsCache.forEach(function(l){
    var selected = (l.id === selListaId) ? ' selected' : '';
    sel.innerHTML += '<option value="' + l.id + '"' + selected + '>' + (l.name||l.nome||'Lista #'+l.id) + '</option>';
  });
  document.getElementById('alm-prioridade').value = a ? (a.prioridade||'media') : 'media';
  document.getElementById('alm-ativo').checked = a ? !!a.ativo : true;
  // Render usuários checkboxes
  var uc = document.getElementById('alm-usuarios-container');
  var selUsers = a ? (a.usuarios||[]) : [];
  if (_almUsersCache.length) {
    uc.innerHTML = _almUsersCache.map(function(u){
      var chk = selUsers.indexOf(u.id) >= 0 ? ' checked' : '';
      return '<label style="display:flex;align-items:center;gap:4px;font-size:.8rem;cursor:pointer;padding:3px 8px;background:rgba(255,255,255,.06);border-radius:4px">'
        + '<input type="checkbox" value="' + u.id + '"' + chk + ' style="width:auto"> ' + u.username + (u.full_name ? ' (' + u.full_name + ')' : '') + '</label>';
    }).join('');
  } else {
    uc.innerHTML = '<span style="color:var(--muted);font-size:.78rem">Nenhum usu\u00e1rio cadastrado</span>';
  }
  openModal('alarme-modal');
  setTimeout(function(){ document.getElementById('alm-lista').focus(); }, 80);
}

async function saveAlarme() {
  var errEl = document.getElementById('alarme-form-error');
  var saveBtn = document.getElementById('alm-save-btn');
  errEl.textContent = '';
  var listaId = document.getElementById('alm-lista').value;
  var prioridade = document.getElementById('alm-prioridade').value;
  var ativo = document.getElementById('alm-ativo').checked;
  if (!listaId) { errEl.textContent = 'Selecione uma lista de ve\u00edculos.'; return; }
  var usuarios = [];
  document.querySelectorAll('#alm-usuarios-container input[type=checkbox]:checked').forEach(function(cb){
    usuarios.push(parseInt(cb.value));
  });
  if (!usuarios.length) { errEl.textContent = 'Selecione pelo menos um usu\u00e1rio.'; return; }
  var body = { lista_id: parseInt(listaId), prioridade: prioridade, ativo: ativo, usuarios: usuarios };
  saveBtn.disabled = true;
  saveBtn.textContent = 'Salvando...';
  try {
    var url = _almEditId ? '/api/alarmes/' + _almEditId : '/api/alarmes';
    var method = _almEditId ? 'PUT' : 'POST';
    var r = await fetch(url, { method: method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!r.ok) { var ed = await r.json().catch(function(){ return {}; }); throw new Error(ed.detail || 'HTTP ' + r.status); }
    closeModal('alarme-modal');
    await loadAlarmes();
  } catch(e) {
    errEl.textContent = 'Erro: ' + e.message;
  } finally {
    saveBtn.disabled = false;
    saveBtn.innerHTML = '\u{1F4BE} Salvar';
  }
}

async function deleteAlarme(id) {
  if (!confirm('Excluir este alarme?\nEsta a\u00e7\u00e3o n\u00e3o pode ser desfeita.')) return;
  var err = document.getElementById('alarmes-error');
  if (err) err.textContent = '';
  try {
    var r = await fetch('/api/alarmes/' + id, { method: 'DELETE' });
    if (!r.ok) { var ed = await r.json().catch(function(){ return {}; }); throw new Error(ed.detail || 'HTTP ' + r.status); }
    await loadAlarmes();
  } catch(e) {
    if (err) err.textContent = 'Erro: ' + e.message;
    else alert('Erro: ' + e.message);
  }
}

async function testAlarme(id) {
  if (!confirm('Enviar notificação push de TESTE para este alarme?')) return;
  try {
    console.log('[Alarmes] Testando alarme id=' + id);
    var r = await fetch('/api/alarmes/' + id + '/test', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: '{}'
    });

    if (!r.ok) {
      var ed = await r.json().catch(function() { return {}; });
      console.error('[Alarmes] Erro no teste (HTTP ' + r.status + '):', ed);
      var errMsg = ed.detail || ed.error || ed.message || ('HTTP ' + r.status);
      alert('❌ Erro ao testar alarme (' + r.status + '):\n' + errMsg);
      return;
    }

    var data = await r.json();
    console.log('[Alarmes] Resultado do teste:', data);

    var name   = data.alarm_name  || ('ID ' + id);
    var tokens = data.tokens_encontrados != null ? data.tokens_encontrados : 0;
    var linked = data.linked_users       != null ? data.linked_users       : '?';
    var sent   = data.sent               != null ? data.sent               : 0;
    var failed = data.failed             != null ? data.failed             : 0;

    if (data.ok === true) {
      alert(
        '✅ Notificação de teste enviada!\n\n' +
        'Alarme: ' + name + '\n' +
        'Usuários vinculados: ' + linked + '\n' +
        'Dispositivos encontrados: ' + tokens + '\n' +
        'Enviados: ' + sent + '\n' +
        'Falhas: ' + failed
      );
    } else {
      // ok === false: alarme existe mas sem tokens FCM cadastrados ou todos falharam
      var reason = '';
      if (tokens === 0) {
        reason = 'Nenhum dispositivo FCM cadastrado para os usuários vinculados a este alarme.';
      } else if (sent === 0 && failed > 0) {
        reason = 'Todos os ' + failed + ' envio(s) falharam. Verifique as credenciais FCM no servidor.';
      } else {
        reason = data.detail || data.error || data.message || 'Nenhuma notificação foi entregue.';
      }
      alert(
        '⚠️ Teste concluído sem entregas.\n\n' +
        'Alarme: ' + name + '\n' +
        'Usuários vinculados: ' + linked + '\n' +
        'Dispositivos encontrados: ' + tokens + '\n' +
        'Enviados: ' + sent + ' | Falhas: ' + failed + '\n\n' +
        reason
      );
    }
  } catch (e) {
    console.error('[Alarmes] Erro ao testar alarme:', e);
    alert('❌ Erro de comunicação ao testar alarme:\n' + e.message);
  }
}

// --- Histórico ---
var _histCache = [];
async function _loadHistorico() {
  var tbody = document.getElementById('hist-tbody');
  var err = document.getElementById('hist-error');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:28px"><span class="spinner"></span> Carregando...</td></tr>';
  if (err) err.textContent = '';
  try {
    var r = await fetch('/api/alarmes/historico');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    var d = await r.json();
    _histCache = d.items || [];
    _renderHistTable(_histCache);
  } catch(e) {
    if (err) err.textContent = 'Erro: ' + e.message;
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--danger);padding:32px">Falha ao carregar hist\u00f3rico.</td></tr>';
  }
}

function _filterHistTable() {
  var q = (document.getElementById('hist-search').value || '').toLowerCase();
  var filtered = q ? _histCache.filter(function(h){
    return (h.placa||'').toLowerCase().includes(q) || (h.camera_name||'').toLowerCase().includes(q) || (h.target_name||'').toLowerCase().includes(q);
  }) : _histCache;
  _renderHistTable(filtered);
}

function _renderHistTable(items) {
  var tbody = document.getElementById('hist-tbody');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:32px">Nenhum alerta no hist\u00f3rico.</td></tr>';
    return;
  }
  var riskBadge = { high:'badge-red', critica:'badge-red', alta:'badge-yellow', media:'badge-green', baixa:'' };
  tbody.innerHTML = items.map(function(h){
    var dt = h.criado_em ? new Date(h.criado_em).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '\u2014';
    var cls = riskBadge[h.risk_level] || '';
    return '<tr>'
      + '<td style="color:var(--muted);font-size:.8rem">' + h.id + '</td>'
      + '<td><span style="font-weight:700;color:var(--accent)">' + (h.placa||'\u2014') + '</span></td>'
      + '<td>' + (h.target_name||'\u2014') + '</td>'
      + '<td>' + (h.camera_name||'\u2014') + '</td>'
      + '<td><span class="badge ' + cls + '">' + (h.risk_level||'\u2014') + '</span></td>'
      + '<td style="font-size:.78rem">' + (h.alert_type||'\u2014') + '</td>'
      + '<td style="font-size:.78rem;color:var(--muted)">' + dt + '</td>'
      + '<td>' + (h.lido ? '<span class="badge badge-green">\u2713</span>' : '<span class="badge badge-yellow">\u2022</span>') + '</td>'
      + '</tr>';
  }).join('');
}


// ===== INIT =====
(async function() {
  await loadMonPlates();
  // Carrega câmeras primeiro para o filtro ficar pronto antes dos eventos
  await _queueTabLoad('cameras', function(){ return loadCameras(); }, 0, true);
  await _queueTabLoad('painel', function(){ return loadPainel(); }, 0, true);
  _presenceSetCurrentPage('painel', 'Painel', '/dashboard#painel');
  _startPresenceHeartbeat();
  await trackPageView('painel', 'Painel', '/dashboard#painel', true);
  // Monitoramento automático sem dependência de controles no topo.
  _startBgAlarm();
  if (!_realtimeInterval) {
    checkBatedorRealtime();
    _realtimeInterval = setInterval(checkBatedorRealtime, 60000);
  }
})();
