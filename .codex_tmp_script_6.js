
// =============================================================================
// SUB-ABAS DA SEÇÃO PESSOAS
// =============================================================================
function switchPessoasSubTab(nome, el) {
  document.querySelectorAll('.pessoas-sub-pane').forEach(function(p) { p.style.display = 'none'; });
  document.querySelectorAll('.pessoas-sub-btn').forEach(function(b) { b.classList.remove('active'); });
  var pane = document.getElementById('pessoas-sub-' + nome);
  if (pane) pane.style.display = '';
  if (el) el.classList.add('active');
  if (nome === 'pesquisar')         _cadMostrarHint();
  if (nome === 'lista-abordagens')  abListaCarregar();
  if (nome === 'abordagem')         abIniciarForm();
  var labels = {
    pesquisar: 'Cadastro / Pessoas',
    abordagem: 'Cadastro / Nova Abordagem',
    'lista-abordagens': 'Cadastro / Historico de Abordagens'
  };
  trackPageView('cadastro:' + nome, labels[nome] || ('Cadastro / ' + nome), '/dashboard#cadastro/' + nome);
}

// =============================================================================
// SUB-ABA: PESQUISAR — estado interno
// =============================================================================
var _cadOffset = 0;
var _cadTotal  = 0;
var _cadLimit  = 50;

async function _cadMostrarHint() {
  var tb  = document.getElementById('cad-tbody');
  var res = document.getElementById('cad-resultado');
  if (res) res.style.display = '';
  if (tb)  tb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:20px"><span class="spinner"></span> Carregando...</td></tr>';
  var st = document.getElementById('cad-status'); if(st) st.textContent = '';
  try {
    var resp = await fetch('/api/pessoas?limit=' + _cadLimit + '&offset=0');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var data = await resp.json();
    _cadTotal = data.total || 0;
    renderCadResultado(data.pessoas || []);
    if (st) st.textContent = _cadTotal + ' pessoa(s) cadastrada(s).' +
      (_cadTotal > _cadLimit ? ' Mostrando primeiras ' + _cadLimit + '.' : '');
  } catch(e) {
    if (tb) tb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--danger);padding:20px">Erro ao carregar lista.</td></tr>';
  }
}

function cadastroCarregar() {
  _cadOffset = 0;
  _cadMostrarHint();
}

function cadastroLimparBusca() {
  var el = document.getElementById('cad-busca'); if(el) el.value = '';
  _cadOffset = 0;
  _cadMostrarHint();
}

async function cadastroBuscar() {
  var q = (document.getElementById('cad-busca').value || '').trim();
  if (!q) { _cadMostrarHint(); return; } // sem filtro → carrega todos
  var url = '/api/pessoas?limit=' + _cadLimit + '&offset=' + _cadOffset;
  url += '&q=' + encodeURIComponent(q);
  var tb  = document.getElementById('cad-tbody');
  var res = document.getElementById('cad-resultado');
  if (tb)  tb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:20px"><span class="spinner"></span> Buscando...</td></tr>';
  if (res) res.style.display = '';
  try {
    var resp = await fetch(url);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var data = await resp.json();
    _cadTotal = data.total || 0;
    renderCadResultado(data.pessoas || []);
    var st = document.getElementById('cad-status');
    if (st) st.textContent = _cadTotal + ' pessoa(s) encontrada(s).' +
      (_cadTotal > _cadLimit ? ' Mostrando primeiras ' + _cadLimit + '.' : '');
  } catch(e) {
    if (tb) tb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--danger);padding:20px">Erro ao buscar.</td></tr>';
    var st = document.getElementById('cad-status'); if(st) st.textContent = '';
  }
}

function renderCadResultado(pessoas) {
  var tb = document.getElementById('cad-tbody');
  if (!tb) return;
  if (!pessoas.length) {
    tb.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:20px">Nenhum resultado.</td></tr>';
    return;
  }
  tb.innerHTML = pessoas.map(function(p) {
    var dc = p.data_cadastro ? p.data_cadastro.substring(0,10) : '\u2014';
    var dn = p.data_nascimento ? p.data_nascimento.substring(0,10) : '\u2014';
    // Botões de ação baseados no perfil do usuário logado
    var role = window._authRole || 'visualizador';
    var botoesAcao = ' <button class="btn btn-outline btn-xs" onclick="cadastroVisualizar(' + p.id + ')" title="Visualizar">&#128269; Visualizar</button>';
    if (role === 'admin' || role === 'operador') {
      botoesAcao += ' <button class="btn btn-outline btn-xs" onclick="cadastroEditar(' + p.id + ')" title="Editar">&#9998; Editar</button>';
    }
    if (role === 'admin') {
      // Botão excluir cadastro: somente admin
      botoesAcao += ' <button class="btn btn-danger btn-xs" onclick="cadastroExcluir(' + p.id + ',this)" title="Excluir" data-nome="' + _esc(p.nome) + '">&#128465; Excluir</button>';
    }
    return '<tr>' +
      '<td style="color:var(--muted);font-size:.8rem">' + p.id + '</td>' +
      '<td style="font-weight:600">' + _esc(p.nome) + '</td>' +
      '<td>' + _esc(p.apelido || '\u2014') + '</td>' +
      '<td style="font-family:monospace">' + _esc(p.cpf ? _fmtCpf(p.cpf) : '\u2014') + '</td>' +
      '<td>' + _esc(p.rg || '\u2014') + '</td>' +
      '<td style="font-size:.78rem">' + dn + '</td>' +
      '<td>' + _esc(p.contato || '\u2014') + '</td>' +
      '<td style="font-size:.78rem;color:var(--muted)">' + dc + '</td>' +
      '<td class="cad-acoes">' + botoesAcao + '</td>' +
      '</tr>';
  }).join('');
}

function _esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function _fmtCpf(cpf) {
  var c = String(cpf).replace(/\D/g,'');
  if (c.length === 11) return c.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4');
  return c;
}

// =============================================================================
// FORMULÁRIO DE PESSOA (edição individual)
// =============================================================================
function cadastroNovaPessoa() {
  cadastroLimparForm();
  var tit = document.getElementById('cad-form-titulo'); if(tit) tit.textContent = '\uD83D\uDCDD Nova Pessoa';
  var fw  = document.getElementById('cad-form-wrap');  if(fw)  fw.style.display = '';
  var nm  = document.getElementById('cad-nome');        if(nm)  nm.focus();
}

function cadastroLimparForm(fechar) {
  ['cad-id','cad-nome','cad-apelido','cad-contato','cad-profissao',
   'cad-cpf','cad-rg','cad-dn','cad-naturalidade','cad-mae','cad-pai','cad-endereco']
    .forEach(function(id){ var el=document.getElementById(id); if(el) el.value=''; });
  var uf = document.getElementById('cad-uf'); if(uf) uf.value = 'RO';
  var er = document.getElementById('cad-form-erro'); if(er) er.textContent = '';
  var ok = document.getElementById('cad-form-ok');   if(ok) ok.style.display = 'none';
  var tit = document.getElementById('cad-form-titulo'); if(tit) tit.textContent = '\uD83D\uDCDD Nova Pessoa';
  if (fechar) { var fw = document.getElementById('cad-form-wrap'); if(fw) fw.style.display = 'none'; }
}

function cadastroPopularForm(p) {
  var set = function(id, val){ var el=document.getElementById(id); if(el) el.value=val||''; };
  set('cad-id', p.id);            set('cad-nome', p.nome);
  set('cad-apelido', p.apelido);  set('cad-contato', p.contato);
  set('cad-profissao', p.profissao); set('cad-cpf', p.cpf); set('cad-rg', p.rg);
  set('cad-dn', p.data_nascimento); set('cad-naturalidade', p.naturalidade);
  var uf = document.getElementById('cad-uf'); if(uf) uf.value = p.estado_naturalidade || 'RO';
  set('cad-mae', p.nome_mae); set('cad-pai', p.nome_pai);
  set('cad-endereco', p.endereco);
  var er = document.getElementById('cad-form-erro'); if(er) er.textContent = '';
  var ok = document.getElementById('cad-form-ok');   if(ok) ok.style.display = 'none';
}

async function cadastroEditar(id) {
  // Fecha modal de visualização se estiver aberto
  closeModal('cad-view-modal');

  var tit  = document.getElementById('cad-edit-titulo');
  var erEl = document.getElementById('cad-edit-erro');
  var okEl = document.getElementById('cad-edit-ok');
  var btn  = document.getElementById('cad-edit-salvar-btn');
  if (erEl) erEl.textContent = '';
  if (okEl) { okEl.textContent = ''; okEl.style.display = 'none'; }
  if (tit)  tit.textContent = '\u270F\uFE0F Carregando...';
  if (btn)  { btn.disabled = false; btn.textContent = '\uD83D\uDCBE Salvar alterações'; }

  openModal('cad-edit-modal');

  try {
    var resp = await fetch('/api/pessoas/' + id);
    if (!resp.ok) {
      if (erEl) erEl.textContent = 'Erro ao carregar pessoa.';
      if (tit)  tit.textContent  = '\u270F\uFE0F Editar cadastro';
      return;
    }
    var p = await resp.json();
    if (tit) tit.textContent = '\u270F\uFE0F Editar: ' + p.nome;

    var set = function(id, val) { var el = document.getElementById(id); if (el) el.value = val || ''; };
    set('cedit-id',          p.id);
    set('cedit-nome',        p.nome);
    set('cedit-apelido',     p.apelido);
    set('cedit-contato',     p.contato);
    set('cedit-profissao',   p.profissao);
    set('cedit-cpf',         p.cpf);
    set('cedit-rg',          p.rg);
    set('cedit-dn',          p.data_nascimento);
    set('cedit-naturalidade',p.naturalidade);
    var uf = document.getElementById('cedit-uf'); if (uf) uf.value = p.estado_naturalidade || 'RO';
    set('cedit-mae',         p.nome_mae);
    set('cedit-pai',         p.nome_pai);
    set('cedit-endereco',    p.endereco);

    // Foca no campo nome
    var nm = document.getElementById('cedit-nome'); if (nm) setTimeout(function(){ nm.focus(); }, 80);
  } catch(e) {
    if (erEl) erEl.textContent = 'Erro: ' + e.message;
    if (tit)  tit.textContent  = '\u270F\uFE0F Editar cadastro';
  }
}

function _cadEditFechar() {
  closeModal('cad-edit-modal');
}

async function _cadEditSalvar() {
  var erEl = document.getElementById('cad-edit-erro');
  var okEl = document.getElementById('cad-edit-ok');
  var btn  = document.getElementById('cad-edit-salvar-btn');
  if (erEl) erEl.textContent = '';
  if (okEl) { okEl.textContent = ''; okEl.style.display = 'none'; }

  var g    = function(id) { var el = document.getElementById(id); return el ? el.value.trim() : ''; };
  var nome = g('cedit-nome');
  if (!nome) {
    if (erEl) erEl.textContent = 'Nome é obrigatório.';
    var nm = document.getElementById('cedit-nome'); if (nm) nm.focus();
    return;
  }
  var cpf = g('cedit-cpf').replace(/\D/g, '');
  if (cpf && cpf.length > 11) {
    if (erEl) erEl.textContent = 'CPF deve ter no máximo 11 dígitos.';
    return;
  }

  var id = g('cedit-id');
  if (!id) { if (erEl) erEl.textContent = 'ID da pessoa não encontrado.'; return; }

  var payload = {
    nome:                nome,
    apelido:             g('cedit-apelido'),
    contato:             g('cedit-contato'),
    profissao:           g('cedit-profissao'),
    cpf:                 cpf,
    rg:                  g('cedit-rg'),
    data_nascimento:     g('cedit-dn') || null,
    naturalidade:        g('cedit-naturalidade'),
    estado_naturalidade: g('cedit-uf'),
    nome_mae:            g('cedit-mae'),
    nome_pai:            g('cedit-pai'),
    endereco:            g('cedit-endereco') || null,
  };

  if (btn) { btn.disabled = true; btn.textContent = 'Salvando...'; }

  try {
    var resp = await fetch('/api/pessoas/' + id, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var data = await resp.json();
    if (!resp.ok) {
      if (erEl) erEl.textContent = data.detail || ('Erro ' + resp.status);
      if (btn)  { btn.disabled = false; btn.textContent = '\uD83D\uDCBE Salvar alterações'; }
      return;
    }
    if (okEl) { okEl.textContent = '\u2705 Pessoa atualizada com sucesso!'; okEl.style.display = 'block'; }
    if (btn)  { btn.disabled = false; btn.textContent = '\uD83D\uDCBE Salvar alterações'; }
    _cadMostrarHint();   // atualiza a lista
    // Fecha modal após breve exibição do sucesso
    setTimeout(function() { closeModal('cad-edit-modal'); }, 1000);
  } catch(e) {
    if (erEl) erEl.textContent = 'Erro de rede: ' + e.message;
    if (btn)  { btn.disabled = false; btn.textContent = '\uD83D\uDCBE Salvar alterações'; }
  }
}

async function cadastroSalvar() {
  var erro = document.getElementById('cad-form-erro');
  var ok   = document.getElementById('cad-form-ok');
  if(erro) erro.textContent = ''; if(ok) ok.style.display = 'none';

  var nome = (document.getElementById('cad-nome').value || '').trim();
  if (!nome) { if(erro) erro.textContent = 'Nome \u00e9 obrigat\u00f3rio.'; return; }
  var cpf = (document.getElementById('cad-cpf').value || '').replace(/\D/g,'');
  if (cpf && cpf.length > 11) { if(erro) erro.textContent = 'CPF deve ter no m\u00e1ximo 11 d\u00edgitos.'; return; }

  var g = function(id){ var el=document.getElementById(id); return el ? el.value.trim() : ''; };
  var payload = {
    nome:                nome,
    apelido:             g('cad-apelido'),
    contato:             g('cad-contato'),
    profissao:           g('cad-profissao'),
    cpf:                 cpf,
    rg:                  g('cad-rg'),
    data_nascimento:     g('cad-dn') || null,
    naturalidade:        g('cad-naturalidade'),
    estado_naturalidade: g('cad-uf'),
    nome_mae:            g('cad-mae'),
    nome_pai:            g('cad-pai'),
    endereco:            g('cad-endereco') || null,
  };

  var id     = g('cad-id');
  var url    = id ? '/api/pessoas/' + id : '/api/pessoas';
  var method = id ? 'PUT' : 'POST';

  try {
    var resp = await fetch(url, {method:method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    var data = await resp.json();
    if (!resp.ok) { if(erro) erro.textContent = data.detail || ('Erro ' + resp.status); return; }
    if(ok) { ok.textContent = id ? '\u2705 Pessoa atualizada!' : '\u2705 Pessoa cadastrada!'; ok.style.display = 'block'; }
    var cidEl = document.getElementById('cad-id'); if(!id && data.id && cidEl) cidEl.value = data.id;
    var tit = document.getElementById('cad-form-titulo'); if(tit) tit.textContent = '\u270F\uFE0F Editando: ' + nome;
    cadastroBuscar();
  } catch(e) { if(erro) erro.textContent = 'Erro: ' + e; }
}

// Estado interno do modal de exclusão
var _cadExcluirId   = null;
var _cadExcluirNome = '';

function cadastroExcluir(id, elOrNome) {
  _cadExcluirId   = id;
  _cadExcluirNome = (typeof elOrNome === 'string') ? elOrNome
    : (elOrNome && elOrNome.dataset ? elOrNome.dataset.nome : 'Pessoa #' + id);

  var nomEl = document.getElementById('cad-excluir-nome');
  var erEl  = document.getElementById('cad-excluir-erro');
  var snEl  = document.getElementById('cad-excluir-senha');
  var okBtn = document.getElementById('cad-excluir-ok-btn');

  if (nomEl) nomEl.textContent = _cadExcluirNome;
  if (erEl)  erEl.textContent  = '';
  if (snEl)  { snEl.value = ''; }
  if (okBtn) { okBtn.disabled = false; okBtn.textContent = '\uD83D\uDDD1\uFE0F Confirmar Exclusão'; }

  openModal('cad-excluir-modal');
  setTimeout(function() { var s = document.getElementById('cad-excluir-senha'); if (s) s.focus(); }, 80);
}

function _cadExcluirFechar() {
  var snEl = document.getElementById('cad-excluir-senha');
  if (snEl) snEl.value = '';
  closeModal('cad-excluir-modal');
  _cadExcluirId = null;
}

async function _cadExcluirConfirmar() {
  if (!_cadExcluirId) return;
  var snEl  = document.getElementById('cad-excluir-senha');
  var erEl  = document.getElementById('cad-excluir-erro');
  var okBtn = document.getElementById('cad-excluir-ok-btn');

  var senha = (snEl ? snEl.value : '').trim();
  if (!senha) {
    if (erEl) erEl.textContent = 'Digite sua senha para confirmar.';
    if (snEl) snEl.focus();
    return;
  }
  if (erEl)  erEl.textContent  = '';
  if (okBtn) { okBtn.disabled = true; okBtn.textContent = 'Excluindo...'; }

  try {
    var resp = await fetch('/api/pessoas/' + _cadExcluirId, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ senha_confirmacao: senha }),
    });

    // Limpa o campo de senha imediatamente, independente do resultado
    if (snEl) snEl.value = '';

    if (resp.status === 204 || resp.ok) {
      _cadExcluirFechar();
      _cadMostrarHint();                              // atualiza a lista
      var cidEl = document.getElementById('cad-id');
      if (cidEl && cidEl.value == _cadExcluirId) cadastroLimparForm(true);
    } else {
      var data = await resp.json().catch(function() { return {}; });
      var msg  = data.detail || ('Erro ' + resp.status);
      if (erEl)  erEl.textContent = msg;
      if (okBtn) { okBtn.disabled = false; okBtn.textContent = '\uD83D\uDDD1\uFE0F Confirmar Exclusão'; }
      if (snEl)  snEl.focus();
    }
  } catch(e) {
    if (snEl) snEl.value = '';
    if (erEl) erEl.textContent = 'Erro de rede: ' + e.message;
    if (okBtn) { okBtn.disabled = false; okBtn.textContent = '\uD83D\uDDD1\uFE0F Confirmar Exclusão'; }
  }
}

async function cadastroVisualizar(id) {
  var modal      = document.getElementById('cad-view-modal');
  var body       = document.getElementById('cad-view-body');
  var titulo     = document.getElementById('cad-view-titulo');
  var editBtn    = document.getElementById('cad-view-edit-btn');
  var novaAbBtn  = document.getElementById('cad-view-nova-ab-btn');
  if (!modal) return;
  body.innerHTML = '<div style="text-align:center;padding:20px"><span class="spinner"></span> Carregando...</div>';
  openModal('cad-view-modal');
  try {
    var resp = await fetch('/api/pessoas/' + id);
    if (!resp.ok) { body.innerHTML = '<p style="color:var(--danger)">Erro ao carregar.</p>'; return; }
    var p = await resp.json();
    titulo.textContent = '\uD83D\uDC64 ' + (p.nome || 'Pessoa #' + id);
    editBtn.textContent = '\u270F\uFE0F Editar cadastro';
    editBtn.onclick = function() { closeModal('cad-view-modal'); cadastroEditar(id); };
    if (novaAbBtn) novaAbBtn.onclick = function() { cadastroNovaAbordagem(id, p.nome); };

    var sS = 'font-size:.73rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);margin:16px 0 6px;padding-bottom:4px;border-bottom:1px solid rgba(250,204,21,.2)';
    var rS = 'display:flex;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.06)';
    var lS = 'min-width:155px;color:var(--muted);font-size:.8rem;flex-shrink:0';
    var vS = 'flex:1;word-break:break-word';

    function sec(ic, lbl) { return '<div style="'+sS+'">'+ic+' '+lbl+'</div>'; }
    function row(lbl, val) {
      var v = (val != null && String(val).trim() !== '') ? _esc(String(val)) : '<span style="color:var(--muted)">\u2014</span>';
      return '<div style="'+rS+'"><span style="'+lS+'">'+lbl+'</span><span style="'+vS+'">'+v+'</span></div>';
    }

    var html = '';
    var fotoUrl = normalizeImageUrl(p.foto_path);
    if (fotoUrl) {
      html += '<div style="display:flex;justify-content:flex-end;margin:0 0 10px">'
           +  '<img src="' + fotoUrl.replace(/"/g, '&quot;') + '" alt="Foto do abordado"'
           +  ' style="width:108px;height:108px;border-radius:12px;border:1px solid var(--border);object-fit:cover;cursor:pointer;box-shadow:var(--shadow)"'
           +  ' onclick="openImageUrl(\'' + fotoUrl.replace(/'/g,"\\'") + '\',\'Foto do abordado\')"'
           +  ' title="Clique para ampliar">'
           +  '</div>';
    }

    // 1. Identificação
    html += sec('\uD83D\uDC64', 'Identifica\u00e7\u00e3o');
    html += row('Nome completo', p.nome);
    html += row('Apelido / Vulgo', p.apelido);
    html += row('Contato', p.contato);
    html += row('Profiss\u00e3o', p.profissao);

    // 2. Documentos
    html += sec('\uD83D\uDCCB', 'Documentos');
    html += row('CPF', p.cpf ? _fmtCpf(p.cpf) : null);
    html += row('RG', p.rg);
    html += row('Data de Nascimento', p.data_nascimento);

    // 3. Naturalidade
    html += sec('\uD83D\uDCCD', 'Naturalidade');
    html += row('Munic\u00edpio', p.naturalidade);
    html += row('Estado (UF)', p.estado_naturalidade);

    // 4. Filiação
    html += sec('\uD83D\uDC68\u200D\uD83D\uDC69\u200D\uD83D\uDC67', 'Filia\u00e7\u00e3o');
    html += row('Nome da M\u00e3e', p.nome_mae);
    html += row('Nome do Pai', p.nome_pai);

    // 5. Endereço
    html += sec('\uD83C\uDFE0', 'Endere\u00e7o');
    html += row('Endere\u00e7o completo', p.endereco);

    // 6. Cadastro
    html += sec('\uD83D\uDCC5', 'Cadastro');
    html += row('Cadastrado em', p.data_cadastro ? p.data_cadastro.substring(0,10) : null);

    // 7. Histórico de Abordagens
    html += sec('\uD83D\uDCCB', 'Hist\u00f3rico de Abordagens');
    html += '<button class="btn btn-outline btn-sm" id="_cad-hist-btn" style="font-size:.8rem">&#128202; Ver relat\u00f3rio completo de ' + _esc(p.nome) + '</button>';

    body.innerHTML = html;

    // Handler do botão histórico fora do innerHTML para evitar injeção
    var histBtn = body.querySelector('#_cad-hist-btn');
    if (histBtn) histBtn.onclick = function() {
      closeModal('cad-view-modal');
      abrirRelatorio(id, p.nome);
    };
  } catch(e) {
    body.innerHTML = '<p style="color:var(--danger)">Erro: ' + _esc(e.message) + '</p>';
  }
}

// =============================================================================
// SUB-ABA: ADICIONAR ABORDAGEM
// Endpoints:
//   POST /api/abordagens            → salvar abordagem completa
//   GET  /api/veiculos-abordagem/busca?placa=  → autocompletar veículo
//   GET  /api/pessoas?q=            → buscar pessoas existentes
// =============================================================================
var _abPessoaIdx = 0;

function abIniciarForm() {
  // preenche data/hora com agora se vazio
  var dh = document.getElementById('ab-data-hora');
  if (dh && !dh.value) {
    var n = new Date(); n.setMinutes(n.getMinutes() - n.getTimezoneOffset());
    dh.value = n.toISOString().slice(0, 16);
  }
}

function abPreviewImagem(input) {
  var file = input && input.files ? input.files[0] : null;
  var wrap = document.getElementById('ab-imagem-preview-wrap');
  var img = document.getElementById('ab-imagem-preview');
  if (!wrap || !img) return;
  if (!file) {
    wrap.style.display = 'none';
    img.removeAttribute('src');
    return;
  }
  if (!/^image\//i.test(file.type || '')) {
    alert('Selecione um arquivo de imagem válido.');
    abRemoverImagem();
    return;
  }
  var reader = new FileReader();
  reader.onload = function(e) {
    img.src = e.target.result;
    wrap.style.display = '';
  };
  reader.readAsDataURL(file);
}

function abRemoverImagem() {
  var input = document.getElementById('ab-imagem');
  var wrap = document.getElementById('ab-imagem-preview-wrap');
  var img = document.getElementById('ab-imagem-preview');
  if (input) input.value = '';
  if (img) img.removeAttribute('src');
  if (wrap) wrap.style.display = 'none';
}

function abPreviewVeiculoImagem(input) {
  var file = input && input.files ? input.files[0] : null;
  var wrap = document.getElementById('ab-veiculo-imagem-preview-wrap');
  var img = document.getElementById('ab-veiculo-imagem-preview');
  if (!wrap || !img) return;
  if (!file) {
    wrap.style.display = 'none';
    img.removeAttribute('src');
    return;
  }
  if (!/^image\//i.test(file.type || '')) {
    alert('Selecione um arquivo de imagem válido para o veículo.');
    abRemoverVeiculoImagem();
    return;
  }
  var reader = new FileReader();
  reader.onload = function(e) {
    img.src = e.target.result;
    wrap.style.display = '';
  };
  reader.readAsDataURL(file);
}

function abRemoverVeiculoImagem() {
  var input = document.getElementById('ab-veiculo-imagem');
  var wrap = document.getElementById('ab-veiculo-imagem-preview-wrap');
  var img = document.getElementById('ab-veiculo-imagem-preview');
  if (input) input.value = '';
  if (img) img.removeAttribute('src');
  if (wrap) wrap.style.display = 'none';
}

function cadAbPreviewVeiculoImagem(input) {
  var file = input && input.files ? input.files[0] : null;
  var wrap = document.getElementById('cad-ab-veiculo-foto-wrap');
  var img = document.getElementById('cad-ab-veiculo-foto-preview');
  if (!wrap || !img) return;
  if (!file) {
    wrap.style.display = 'none';
    img.removeAttribute('src');
    return;
  }
  if (!/^image\//i.test(file.type || '')) {
    alert('Selecione um arquivo de imagem válido para o veículo.');
    cadAbRemoverVeiculoImagem();
    return;
  }
  var reader = new FileReader();
  reader.onload = function(e) {
    img.src = e.target.result;
    wrap.style.display = '';
  };
  reader.readAsDataURL(file);
}

function cadAbRemoverVeiculoImagem() {
  var input = document.getElementById('cad-ab-veiculo-foto');
  var wrap = document.getElementById('cad-ab-veiculo-foto-wrap');
  var img = document.getElementById('cad-ab-veiculo-foto-preview');
  if (input) input.value = '';
  if (img) img.removeAttribute('src');
  if (wrap) wrap.style.display = 'none';
}

function cadAbOcPreviewImagem(idx, input) {
  var file = input && input.files ? input.files[0] : null;
  var wrap = document.getElementById('cad-ab-oc-foto-wrap-' + idx);
  var img = document.getElementById('cad-ab-oc-foto-preview-' + idx);
  if (!wrap || !img) return;
  if (!file) {
    wrap.style.display = 'none';
    img.removeAttribute('src');
    return;
  }
  if (!/^image\//i.test(file.type || '')) {
    alert('Selecione um arquivo de imagem válido para o acompanhante.');
    cadAbOcRemoverImagem(idx);
    return;
  }
  var reader = new FileReader();
  reader.onload = function(e) {
    img.src = e.target.result;
    wrap.style.display = '';
  };
  reader.readAsDataURL(file);
}

function cadAbOcRemoverImagem(idx) {
  var input = document.getElementById('cad-ab-oc-foto-' + idx);
  var wrap = document.getElementById('cad-ab-oc-foto-wrap-' + idx);
  var img = document.getElementById('cad-ab-oc-foto-preview-' + idx);
  if (input) input.value = '';
  if (img) img.removeAttribute('src');
  if (wrap) wrap.style.display = 'none';
}

function abLimpar() {
  ['ab-pessoa-id','ab-nome','ab-cpf','ab-rg','ab-contato','ab-profissao',
   'ab-pai','ab-mae','ab-rua','ab-numero','ab-bairro','ab-uf',
   'ab-naturalidade','ab-uf-naturalidade','ab-data-nascimento',
   'ab-data-hora','ab-local','ab-observacoes',
   'ab-placa','ab-modelo','ab-cor']
    .forEach(function(id){ var el=document.getElementById(id); if(el) el.value=''; });
  var pr = document.getElementById('ab-pessoa-resultado'); if(pr) pr.innerHTML = '';
  var vi = document.getElementById('ab-veiculo-info'); if(vi){ vi.style.display='none'; vi.textContent=''; }
  var va = document.getElementById('ab-vincular-alvo'); if(va) va.value = 'nao';
  var tv = document.getElementById('ab-tem-veiculo'); if(tv) tv.value = 'nao';
  var vw = document.getElementById('ab-veiculo-wrap'); if(vw) vw.style.display = 'none';
  abRemoverVeiculoImagem();
  var pl = document.getElementById('ab-pessoas-list');
  if(pl) pl.innerHTML = '<div data-placeholder="1" style="color:var(--muted);font-size:.82rem;font-style:italic;padding:8px 0">Nenhum acompanhante adicionado.</div>';
  _abPessoaIdx = 0;
  var er = document.getElementById('ab-form-erro'); if(er) er.textContent = '';
  var ok = document.getElementById('ab-form-ok');   if(ok) ok.style.display = 'none';
  abRemoverImagem();
  abIniciarForm();
}

async function abBuscarVeiculo() {
  var placa = (document.getElementById('ab-placa').value || '').trim().toUpperCase().replace(/[^A-Z0-9]/g,'');
  if (!placa) { alert('Digite a placa para buscar.'); return; }
  var vi = document.getElementById('ab-veiculo-info');
  try {
    var resp = await fetch('/api/veiculos-abordagem/busca?placa=' + encodeURIComponent(placa));
    if (resp.status === 404) {
      if(vi){ vi.textContent='Placa n\u00e3o encontrada no cadastro. Preencha os dados abaixo.'; vi.style.display=''; vi.style.color='var(--muted)'; }
      return;
    }
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var data = await resp.json();
    if (data.found && data.veiculo) {
      var v = data.veiculo;
      var set = function(id,val){ var el=document.getElementById(id); if(el) el.value=val||''; };
      set('ab-modelo',v.modelo); set('ab-cor',v.cor);
      if(vi){ vi.textContent='\u2705 Ve\u00edculo encontrado (id #'+v.id+').'; vi.style.display=''; vi.style.color='var(--accent)'; }
    } else {
      if(vi){ vi.textContent='Placa n\u00e3o encontrada. Preencha os dados para cadastrar.'; vi.style.display=''; vi.style.color='var(--muted)'; }
    }
  } catch(e) {
    if(vi){ vi.textContent='Erro ao buscar: '+e.message; vi.style.display=''; vi.style.color='var(--danger)'; }
  }
}

function abToggleVeiculo() {
  var sel = document.getElementById('ab-tem-veiculo');
  var wrap = document.getElementById('ab-veiculo-wrap');
  if (!sel || !wrap) return;
  if (sel.value === 'sim') {
    wrap.style.display = '';
  } else {
    wrap.style.display = 'none';
    ['ab-placa','ab-modelo','ab-cor'].forEach(function(id){
      var el = document.getElementById(id); if(el) el.value = '';
    });
    var va = document.getElementById('ab-vincular-alvo'); if(va) va.value = 'nao';
    var vi = document.getElementById('ab-veiculo-info'); if(vi){ vi.style.display='none'; vi.textContent=''; }
    abRemoverVeiculoImagem();
  }
}

var _abCpfDuplicadoPessoa = null;
var _abCpfTimer = null;

function abVerificarCpfDuplicado() {
  clearTimeout(_abCpfTimer);
  var cpf = (document.getElementById('ab-cpf').value||'').replace(/\D/g,'');
  var wrap = document.getElementById('ab-cpf-alerta-wrap');
  if (cpf.length !== 11) {
    _abCpfDuplicadoPessoa = null;
    if(wrap) wrap.style.display = 'none';
    return;
  }
  // se já temos pessoa vinculada pelo id, não revalidar
  var pidEl = document.getElementById('ab-pessoa-id');
  if(pidEl && pidEl.value) return;
  _abCpfTimer = setTimeout(async function() {
    try {
      var resp = await fetch('/api/pessoas/existe-cpf?cpf=' + encodeURIComponent(cpf));
      if (!resp.ok) { if(wrap) wrap.style.display='none'; return; }
      var data = await resp.json();
      if (data.existe) {
        _abCpfDuplicadoPessoa = data.pessoa;
        if(wrap) wrap.style.display = '';
      } else {
        _abCpfDuplicadoPessoa = null;
        if(wrap) wrap.style.display = 'none';
      }
    } catch(e) { if(wrap) wrap.style.display='none'; }
  }, 500);
}

var _abPessoaEncontrada = null; // pessoa pendente de uso (por pesquisa de campo)

function _abMostrarCadastroExistente(p) {
  _abPessoaEncontrada = p;
  var wrap = document.getElementById('ab-cadastro-existente-wrap');
  var info = document.getElementById('ab-cadastro-existente-info');
  if (info) info.innerHTML = '<strong>'+_esc(p.nome)+'</strong>'
    +(p.cpf?' &middot; CPF: '+_fmtCpf(p.cpf):'')
    +(p.rg?' &middot; RG: '+_esc(p.rg):'')
    +' <span style="font-size:.75rem;color:var(--muted)">(#'+p.id+')</span>';
  if (wrap) wrap.style.display = '';
}

function abUsarCadastroExistente() {
  var p = _abPessoaEncontrada || _abCpfDuplicadoPessoa;
  if (!p) return;
  // Esconder alertas e resultado da pesquisa
  var w1 = document.getElementById('ab-cpf-alerta-wrap'); if(w1) w1.style.display='none';
  var w2 = document.getElementById('ab-cadastro-existente-wrap'); if(w2) w2.style.display='none';
  var res = document.getElementById('ab-pessoa-resultado'); if(res) res.innerHTML='';
  _abCpfDuplicadoPessoa = null;
  _abPessoaEncontrada = null;
  // Abrir modal dedicado de nova abordagem para cadastro existente
  cadastroNovaAbordagem(p.id, p.nome);
}

async function _abPesquisarCampo(q) {
  if (!q) return;
  var res = document.getElementById('ab-pessoa-resultado');
  var wrap = document.getElementById('ab-cadastro-existente-wrap');
  if(wrap) wrap.style.display='none';
  if(res) res.innerHTML = '<span style="font-size:.78rem;color:var(--muted)"><span class="spinner" style="width:12px;height:12px;margin-right:4px"></span>Buscando...</span>';
  try {
    var resp = await fetch('/api/pessoas?q='+encodeURIComponent(q)+'&limit=6');
    var data = await resp.json();
    var pessoas = data.pessoas || [];
    if (!pessoas.length) {
      if(res) res.innerHTML='<span style="font-size:.78rem;color:var(--muted)">Nenhum cadastro encontrado para &ldquo;'+_esc(q)+'&rdquo;.</span>';
      return;
    }
    // Se exatamente 1 resultado, vai direto para aviso de cadastro existente
    if (pessoas.length === 1) {
      if(res) res.innerHTML='';
      _abMostrarCadastroExistente(pessoas[0]);
      return;
    }
    // Múltiplos — mostrar lista para o operador escolher
    var html = '<div style="font-size:.78rem;color:var(--muted);margin-bottom:4px">Selecione o cadastro encontrado:</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px;padding:4px 0">';
    pessoas.forEach(function(p){
      html += '<button type="button" class="btn btn-outline btn-sm" style="font-size:.76rem;padding:3px 8px"'
        +' onclick="abSelecionarPrincipal('+JSON.stringify(p).replace(/\\/g,'\\\\').replace(/"/g,'&quot;')+')">'
        +_esc(p.nome)+(p.cpf?' \u00b7 '+_fmtCpf(p.cpf):'')+'</button>';
    });
    html += '</div>';
    if(res) res.innerHTML = html;
  } catch(e) {
    if(res) res.innerHTML = '<span style="font-size:.78rem;color:var(--danger)">Erro: '+_esc(e.message)+'</span>';
  }
}
async function abPesquisarPorNome() {
  var q = (document.getElementById('ab-nome').value||'').trim();
  if (!q) { alert('Preencha o campo Nome antes de pesquisar.'); return; }
  await _abPesquisarCampo(q);
}
async function abPesquisarPorCpf() {
  var q = (document.getElementById('ab-cpf').value||'').replace(/\D/g,'');
  if (!q) { alert('Preencha o campo CPF antes de pesquisar.'); return; }
  await _abPesquisarCampo(q);
}
async function abPesquisarPorRg() {
  var q = (document.getElementById('ab-rg').value||'').trim();
  if (!q) { alert('Preencha o campo RG antes de pesquisar.'); return; }
  await _abPesquisarCampo(q);
}

function abSelecionarPrincipal(p) {
  var res = document.getElementById('ab-pessoa-resultado');
  if(res) res.innerHTML = '';
  _abMostrarCadastroExistente(p);
}

async function abBuscarPrincipal() {
  // mantido para compatibilidade — delega para _abPesquisarCampo
  var q = (document.getElementById('ab-pessoa-busca')||{value:''}).value.trim();
  if (!q) return;
  await _abPesquisarCampo(q);
}

async function abCarregarListasVeiculos() {
  var sel = document.getElementById('ab-alvo-lista-id');
  if (!sel) return;
  sel.innerHTML = '<option value="">Carregando...</option>';
  try {
    var resp = await fetch('/api/vehicles/lists');
    var data = await resp.json();
    var listas = data.items || [];
    if (!listas.length) { sel.innerHTML='<option value="">Nenhuma lista disponível</option>'; return; }
    sel.innerHTML = '<option value="">-- Escolha uma lista --</option>';
    listas.forEach(function(l){
      var opt = document.createElement('option');
      opt.value = l.id;
      opt.textContent = l.name + ' (' + l.vehicle_count + ' veículos)';
      sel.appendChild(opt);
    });
  } catch(e) {
    sel.innerHTML = '<option value="">Erro ao carregar listas</option>';
  }
}

function abToggleVincularAlvo() {
  var sel = document.getElementById('ab-vincular-alvo');
  var wrap = document.getElementById('ab-alvo-lista-wrap');
  if (!sel || !wrap) return;
  if (sel.value === 'sim') {
    wrap.style.display = '';
    abCarregarListasVeiculos();
  } else {
    wrap.style.display = 'none';
    var li = document.getElementById('ab-alvo-lista-id'); if(li) li.value = '';
  }
}

var _papeis = [
  {v:'motorista',l:'Motorista'},{v:'proprietario',l:'Propriet\u00e1rio'},
  {v:'passageiro',l:'Passageiro'},{v:'garupa',l:'Garupa'},{v:'outro',l:'Outro'}
];

function abAdicionarPessoa(dados) {
  var pl = document.getElementById('ab-pessoas-list');
  if (!pl) return;
  var ph = pl.querySelector('[data-placeholder]'); if(ph) ph.remove();
  var idx = _abPessoaIdx++;
  var d   = dados || {};
  var s   = 'padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg2);color:var(--text);font-size:.83rem;width:100%;box-sizing:border-box';
  var opts = _papeis.map(function(p){ return '<option value="'+p.v+'"'+(p.v===(d.papel||'outro')?' selected':'')+'>'+p.l+'</option>'; }).join('');

  function fi(f,lbl,ph2,val,extra) {
    return '<label style="display:flex;flex-direction:column;gap:3px;font-size:.82rem">'+lbl
      +'<input type="text" id="ab-pb-'+idx+'-'+f+'" maxlength="120" placeholder="'+(ph2||'')+'"'+(extra||'')
      +' value="'+_esc(String(val||''))+'" style="'+s+'"></label>';
  }

  var html = '<div class="ab-pessoa-bloco" id="ab-pb-'+idx+'" style="border:1px solid var(--border);border-radius:var(--radius);padding:14px;margin-bottom:12px;background:var(--bg2)">'
    // cabeçalho: label + remover
    +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border)">'
    +'<span style="font-size:.76rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)">Acompanhante '+(idx+1)+'</span>'
    +'<button type="button" class="btn btn-outline btn-sm" style="padding:2px 8px;font-size:.78rem" onclick="document.getElementById(\'ab-pb-'+idx+'\').remove()">&#10005; Remover</button>'
    +'</div>'
    +'<div id="ab-pb-'+idx+'-resultado" style="margin-bottom:8px"></div>'
    +'<input type="hidden" id="ab-pb-'+idx+'-id" value="'+(d.id||'')+'">'
    // Linha 1: Nome / CPF / RG (com botões de pesquisa)
    +'<div style="display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px;margin-bottom:8px">'
    +'<label style="display:flex;flex-direction:column;gap:3px;font-size:.82rem">Nome *'
    +'<div style="display:flex;gap:4px">'
    +'<input type="text" id="ab-pb-'+idx+'-nome" maxlength="120" placeholder="Nome completo"'
    +' value="'+_esc(String(d.nome||''))+'" style="flex:1;'+s+'"'
    +' onkeydown="if(event.key===\'Enter\'){event.preventDefault();abPessoaPesquisarNome('+idx+')}">'
    +'<button type="button" class="btn btn-search btn-sm" onclick="abPessoaPesquisarNome('+idx+')" title="Buscar por nome">&#128269;</button>'
    +'</div></label>'
    +'<label style="display:flex;flex-direction:column;gap:3px;font-size:.82rem">CPF'
    +'<div style="display:flex;gap:4px">'
    +'<input type="text" id="ab-pb-'+idx+'-cpf" maxlength="14" placeholder="000.000.000-00"'
    +' inputmode="numeric" oninput="this.value=this.value.replace(/\\D/g,\'\')"'
    +' value="'+_esc(String(d.cpf||''))+'" style="flex:1;'+s+'"'
    +' onkeydown="if(event.key===\'Enter\'){event.preventDefault();abPessoaPesquisarCpf('+idx+')}">'
    +'<button type="button" class="btn btn-search btn-sm" onclick="abPessoaPesquisarCpf('+idx+')" title="Buscar por CPF">&#128269;</button>'
    +'</div></label>'
    +'<label style="display:flex;flex-direction:column;gap:3px;font-size:.82rem">RG'
    +'<div style="display:flex;gap:4px">'
    +'<input type="text" id="ab-pb-'+idx+'-rg" maxlength="20" placeholder="0000000"'
    +' value="'+_esc(String(d.rg||''))+'" style="flex:1;'+s+'"'
    +' onkeydown="if(event.key===\'Enter\'){event.preventDefault();abPessoaPesquisarRg('+idx+')}">'
    +'<button type="button" class="btn btn-search btn-sm" onclick="abPessoaPesquisarRg('+idx+')" title="Buscar por RG">&#128269;</button>'
    +'</div></label>'
    +'</div>'
    // Linha 2: Contato / Profissão
    +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">'
    +fi('contato','Contato','(69) 9 9999-9999',d.contato)
    +fi('profissao','Profiss\u00e3o','Ex: Aut\u00f4nomo',d.profissao)
    +'</div>'
    // Linha 3: Pai / Mãe
    +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">'
    +fi('pai','Nome do Pai','Nome completo do pai',d.nome_pai)
    +fi('mae','Nome da M\u00e3e','Nome completo da m\u00e3e',d.nome_mae)
    +'</div>'
    // Linha 4: Rua / Número / Bairro / Cidade / Estado
    +'<div style="display:grid;grid-template-columns:2.2fr 0.6fr 1.1fr 1.1fr 0.5fr;gap:8px;margin-bottom:8px">'
    +fi('rua','Rua / Avenida','Ex: Rua das Flores',d.rua||(d.endereco||''))
    +fi('numero','N\u00famero','123',d.numero)
    +fi('bairro','Bairro','Ex: Centro',d.bairro)
    +fi('cidade','Cidade','Ex: Colorado do Oeste',d.cidade)
    +'<label style="display:flex;flex-direction:column;gap:3px;font-size:.82rem">Estado'
    +'<input type="text" id="ab-pb-'+idx+'-estado" maxlength="2" placeholder="RO"'
    +' oninput="this.value=this.value.toUpperCase()"'
    +' value="'+_esc(String(d.estado||''))+'" style="'+s+';text-transform:uppercase"></label>'
    +'</div>'
    // Linha 5: Papel na abordagem
    +'<label style="display:flex;flex-direction:column;gap:3px;font-size:.82rem;margin-bottom:8px">Papel na abordagem'
    +'<select id="ab-pb-'+idx+'-papel" style="'+s+'">'+opts+'</select></label>'
    // Linha 6: Histórico
    +'<label style="display:flex;flex-direction:column;gap:3px;font-size:.82rem">Hist\u00f3rico'
    +'<textarea id="ab-pb-'+idx+'-obs" rows="3" maxlength="2000" placeholder="Observa\u00e7\u00f5es sobre esta pessoa..." style="'+s+';resize:vertical;min-height:60px">'+_esc(String(d.observacao_pessoal||''))+'</textarea>'
    +'</label>'
    +'</div>';

  var tmp = document.createElement('div');
  tmp.innerHTML = html;
  pl.appendChild(tmp.firstChild);
}

async function _abPessoaBuscarCampo(idx, q) {
  if (!q) return;
  var res = document.getElementById('ab-pb-'+idx+'-resultado');
  if(res) res.innerHTML = '<span style="font-size:.78rem;color:var(--muted)"><span class="spinner" style="width:12px;height:12px;margin-right:4px"></span>Buscando...</span>';
  try {
    var resp = await fetch('/api/pessoas?q='+encodeURIComponent(q)+'&limit=5');
    var data = await resp.json();
    var pessoas = data.pessoas || [];
    if (!pessoas.length) { if(res) res.innerHTML='<span style="font-size:.78rem;color:var(--muted)">Nenhuma pessoa encontrada.</span>'; return; }
    var html = '<div style="display:flex;flex-wrap:wrap;gap:6px">';
    pessoas.forEach(function(p){
      html += '<button type="button" class="btn btn-outline btn-sm" style="font-size:.76rem;padding:3px 8px"'
        +' onclick="abPessoaSelecionar('+idx+','+JSON.stringify(p).replace(/\\/g,'\\\\').replace(/"/g,'&quot;')+')">'
        +_esc(p.nome)+(p.apelido?' ('+_esc(p.apelido)+')':'')+(p.cpf?' \u00b7 '+_fmtCpf(p.cpf):'')+'</button>';
    });
    html += '</div>';
    if(res) res.innerHTML = html;
  } catch(e) {
    if(res) res.innerHTML = '<span style="font-size:.78rem;color:var(--danger)">Erro: '+_esc(e.message)+'</span>';
  }
}
async function abPessoaPesquisarNome(idx) {
  await _abPessoaBuscarCampo(idx, (document.getElementById('ab-pb-'+idx+'-nome')||{value:''}).value.trim());
}
async function abPessoaPesquisarCpf(idx) {
  await _abPessoaBuscarCampo(idx, (document.getElementById('ab-pb-'+idx+'-cpf')||{value:''}).value.replace(/\D/g,''));
}
async function abPessoaPesquisarRg(idx) {
  await _abPessoaBuscarCampo(idx, (document.getElementById('ab-pb-'+idx+'-rg')||{value:''}).value.trim());
}
// mantido para compatibilidade (pode ser chamado de código legado)
async function abPessoaBuscar(idx) {
  var q = ((document.getElementById('ab-pb-'+idx+'-nome')||{value:''}).value||'').trim();
  await _abPessoaBuscarCampo(idx, q);
}

function abPessoaSelecionar(idx, p) {
  var set = function(f,v){ var el=document.getElementById('ab-pb-'+idx+'-'+f); if(el) el.value=v||''; };
  set('id',p.id); set('nome',p.nome); set('cpf',p.cpf||''); set('rg',p.rg||'');
  set('contato',p.contato||''); set('profissao',p.profissao||'');
  set('pai',p.nome_pai||''); set('mae',p.nome_mae||'');
  // Endereço: usa campos separados se disponíveis; fallback coloca endereco único em Rua
  set('rua',    p.rua    || p.endereco || '');
  set('numero', p.numero || '');
  set('bairro', p.bairro || '');
  set('cidade', p.cidade || '');
  set('estado', p.estado || '');
  var res=document.getElementById('ab-pb-'+idx+'-resultado');
  if(res) res.innerHTML='<span style="font-size:.78rem;color:var(--accent)">\u2705 #'+p.id+' — '+_esc(p.nome)+' selecionado(a)</span>';
}

async function abSalvar() {
  var erro = document.getElementById('ab-form-erro');
  var ok   = document.getElementById('ab-form-ok');
  if(erro) erro.textContent=''; if(ok) ok.style.display='none';

  var g = function(id){ var el=document.getElementById(id); return el?(el.value||'').trim():''; };
  var dataHora = g('ab-data-hora');
  if (!dataHora) { if(erro) erro.textContent='Data e hora s\u00e3o obrigat\u00f3rios.'; return; }

  var temVeiculo = (document.getElementById('ab-tem-veiculo')||{}).value === 'sim';
  var placa = temVeiculo ? g('ab-placa').toUpperCase().replace(/[^A-Z0-9]/g,'') : '';
  var payload = {
    data_hora:   dataHora + ':00',
    local:       g('ab-local') || null,
    observacoes: g('ab-observacoes') || null,
    veiculo: (temVeiculo && placa) ? {
      placa:  placa,
      modelo: g('ab-modelo') || null,
      cor:    g('ab-cor')    || null,
      vincular_como_alvo: (document.getElementById('ab-vincular-alvo')||{}).value === 'sim',
      list_id: (function(){ var el=document.getElementById('ab-alvo-lista-id'); return el&&el.value ? parseInt(el.value,10) : null; })(),
    } : null,
    pessoas: [],
  };

  // abordado principal
  var mainId = g('ab-pessoa-id');
  var mainNome = g('ab-nome');
  if (mainId || mainNome) {
    var mainEntry = { papel: 'abordado', observacao_pessoal: null };
    if (mainId) {
      mainEntry.pessoa_id = parseInt(mainId, 10);
    } else {
      // Verificação de duplicidade antes de criar novo cadastro
      var cpfCheck = g('ab-cpf').replace(/\D/g,'');
      var rgCheck  = g('ab-rg');
      if (cpfCheck && cpfCheck.length === 11) {
        try {
          var chkResp = await fetch('/api/pessoas/existe-cpf?cpf='+encodeURIComponent(cpfCheck));
          if (chkResp.ok) {
            var chkData = await chkResp.json();
            if (chkData.existe) {
              _abMostrarCadastroExistente(chkData.pessoa);
              if(erro) erro.textContent = 'Este CPF j\u00e1 est\u00e1 cadastrado. Use o cadastro existente acima.';
              return;
            }
          }
        } catch(e2) { /* ignora erro de rede nessa checagem */ }
      }
      var rua = g('ab-rua'); var num = g('ab-numero'); var bairro = g('ab-bairro'); var uf = g('ab-uf');
      var endParts = [rua, num ? 'n\u00ba '+num : '', bairro, uf].filter(Boolean);
      mainEntry.nome = mainNome;
      mainEntry.cpf = cpfCheck || null;
      mainEntry.rg = rgCheck || null;
      mainEntry.contato = g('ab-contato') || null;
      mainEntry.profissao = g('ab-profissao') || null;
      mainEntry.endereco = endParts.join(', ') || null;
      mainEntry.nome_pai = g('ab-pai') || null;
      mainEntry.nome_mae = g('ab-mae') || null;
      mainEntry.naturalidade = g('ab-naturalidade') || null;
      mainEntry.estado_naturalidade = g('ab-uf-naturalidade') || null;
      var _dn = g('ab-data-nascimento'); if(_dn) mainEntry.data_nascimento = _dn;
    }
    payload.pessoas.push(mainEntry);
  }

  document.querySelectorAll('#ab-pessoas-list .ab-pessoa-bloco').forEach(function(bloco){
    var bid = bloco.id.replace('ab-pb-','');
    var gf  = function(f){ var el=bloco.querySelector('#ab-pb-'+bid+'-'+f); return el?(el.value||'').trim():''; };
    var pId   = gf('id');
    var pNome = gf('nome');
    if (!pId && !pNome) return;
    var entry = { papel: gf('papel')||'outro', observacao_pessoal: gf('obs')||null };
    if (pId) {
      entry.pessoa_id = parseInt(pId,10);
    } else {
      entry.nome=pNome; entry.cpf=gf('cpf').replace(/\D/g,'')||null;
      entry.rg=gf('rg')||null;
      entry.contato=gf('contato')||null; entry.profissao=gf('profissao')||null;
      entry.nome_pai=gf('pai')||null;
      entry.nome_mae=gf('mae')||null;
      // Monta endereço a partir dos campos separados
      var _rua=gf('rua'), _num=gf('numero'), _bairro=gf('bairro'), _cid=gf('cidade'), _est=gf('estado');
      var _endParts=[_rua, _num?'n\u00ba '+_num:'', _bairro, _cid, _est].filter(Boolean);
      entry.endereco = _endParts.join(', ') || null;
    }
    payload.pessoas.push(entry);
  });

  try {
    var fileInput = document.getElementById('ab-imagem');
    var imageFile = fileInput && fileInput.files ? fileInput.files[0] : null;
    var vehicleFileInput = document.getElementById('ab-veiculo-imagem');
    var vehicleImageFile = vehicleFileInput && vehicleFileInput.files ? vehicleFileInput.files[0] : null;
    var fetchOptions = { method:'POST' };
    if (imageFile || vehicleImageFile) {
      var formData = new FormData();
      formData.append('payload', JSON.stringify(payload));
      if (imageFile) formData.append('abordado_imagem', imageFile);
      if (vehicleImageFile) formData.append('veiculo_imagem', vehicleImageFile);
      fetchOptions.body = formData;
    } else {
      fetchOptions.headers = {'Content-Type':'application/json'};
      fetchOptions.body = JSON.stringify(payload);
    }
    var resp = await fetch('/api/abordagens', fetchOptions);
    var data = await resp.json();
    if (!resp.ok) { if(erro) erro.textContent = data.detail||('Erro '+resp.status); return; }
    if(ok){ ok.textContent='\u2705 Abordagem #'+data.id+' registrada com sucesso!'; ok.style.display='block'; }
    abLimpar();
    _ablLoaded = false; // força recarregar a lista na próxima visita
  } catch(e) { if(erro) erro.textContent='Erro: '+e.message; }
}

// =============================================================================
// SUB-ABA: HISTORICO DE ABORDAGENS
// Endpoints:
//   GET /api/abordagens?q=&dt_from=&dt_to=&limit=&offset=
//   GET /api/abordagens/{id}
// =============================================================================
var _ablOffset = 0, _ablLimit = 30, _ablTotal = 0, _ablLoaded = false;

function abListaCarregar() { _ablOffset = 0; _abListaFetch(); }
function abListaBuscar()   { _ablOffset = 0; _abListaFetch(); }
function abListaLimpar()   {
  ['abl-busca','abl-dt-from','abl-dt-to'].forEach(function(id){ var el=document.getElementById(id); if(el) el.value=''; });
  _ablOffset=0; _abListaFetch();
}

async function _abListaFetch() {
  var tb  = document.getElementById('abl-tbody');
  var st  = document.getElementById('abl-status');
  var pag = document.getElementById('abl-paginacao');
  if(tb) tb.innerHTML='<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:20px"><span class="spinner"></span> Carregando...</td></tr>';
  var g = function(id){ var el=document.getElementById(id); return el?(el.value||'').trim():''; };
  var url = '/api/abordagens?limit='+_ablLimit+'&offset='+_ablOffset;
  var q=g('abl-busca');     if(q)  url+='&q='+encodeURIComponent(q);
  var df=g('abl-dt-from');  if(df) url+='&dt_from='+encodeURIComponent(df);
  var dt=g('abl-dt-to');    if(dt) url+='&dt_to='+encodeURIComponent(dt);
  try {
    var resp = await fetch(url);
    if (!resp.ok) throw new Error('HTTP '+resp.status);
    var data = await resp.json();
    _ablTotal = data.total || 0;
    _ablLoaded = true;
    var rows = data.abordagens || [];
    if (!rows.length) {
      if(tb) tb.innerHTML='<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:20px">Nenhuma abordagem encontrada.</td></tr>';
    } else {
      if(tb) tb.innerHTML = rows.map(function(ab){
        var dh  = ab.data_hora ? ab.data_hora.replace('T',' ').substring(0,16) : '\u2014';
        var vei = ab.veiculo   ? _esc(ab.veiculo.placa||'')+(ab.veiculo.modelo?' \u00b7 '+_esc(ab.veiculo.modelo):'') : '\u2014';
        var nomes = Array.isArray(ab.pessoas) && ab.pessoas.length
          ? ab.pessoas.slice(0,2).map(function(p){return _esc(p.nome||'');}).join(', ')+(ab.pessoas.length>2?' +\u2026':'')
          : '\u2014';
        // Botão excluir abordagem: somente admin
        var btnExcluirAb = (window._authRole === 'admin')
          ? ' <button class="btn btn-danger btn-xs" onclick="abExcluir('+ab.id+')" title="Excluir abordagem">&#128465; Excluir</button>'
          : '';
        return '<tr>'
          +'<td style="color:var(--muted);font-size:.8rem">'+ab.id+'</td>'
          +'<td style="font-size:.8rem;white-space:nowrap">'+dh+'</td>'
          +'<td>'+_esc(ab.local||'\u2014')+'</td>'
          +'<td>'+_esc(ab.equipe||'\u2014')+'</td>'
          +'<td>'+_esc(ab.tipo_motivo||'\u2014')+'</td>'
          +'<td style="font-family:monospace;font-size:.8rem">'+vei+'</td>'
          +'<td style="font-size:.8rem">'+nomes+'</td>'
          +'<td class="action-cell"><div class="action-buttons">'
          +'<button class="btn btn-outline btn-xs" onclick="abVerDetalhes('+ab.id+')" title="Visualizar abordagem">&#128269; Visualizar</button>'
          +btnExcluirAb
          +'</div></td></tr>';
      }).join('');
    }
    if(st) st.textContent = _ablTotal + ' abordagem(ns) encontrada(s).';
    if(pag){
      var pA=Math.floor(_ablOffset/_ablLimit)+1, pT=Math.ceil(_ablTotal/_ablLimit)||1;
      pag.innerHTML = (_ablOffset>0
        ? '<button class="btn btn-outline btn-sm" onclick="_ablOffset=Math.max(0,_ablOffset-_ablLimit);_abListaFetch()">\u2190 Anterior</button>' : '')
        +'<span style="font-size:.82rem;color:var(--muted);padding:0 8px">P\u00e1g. '+pA+' / '+pT+'</span>'
        +((_ablOffset+_ablLimit)<_ablTotal
        ? '<button class="btn btn-outline btn-sm" onclick="_ablOffset+=_ablLimit;_abListaFetch()">Pr\u00f3xima \u2192</button>' : '');
    }
  } catch(e) {
    if(tb) tb.innerHTML='<tr><td colspan="8" style="text-align:center;color:var(--danger);padding:20px">Erro ao carregar. Verifique o endpoint /api/abordagens.</td></tr>';
    if(st) st.textContent='';
  }
}

// Exclui abordagem — apenas admin (proteção duplicada no backend)
async function abExcluir(id) {
  if (window._authRole !== 'admin') {
    alert('Apenas administradores podem excluir abordagens.');
    return;
  }
  if (!confirm('Excluir abordagem #' + id + '? Esta ação é irreversível.')) return;
  try {
    var resp = await fetch('/api/abordagens/' + id, { method: 'DELETE' });
    if (resp.ok || resp.status === 204) {
      abListaCarregar();
    } else {
      var data = await resp.json().catch(function(){ return {}; });
      alert('Erro ao excluir: ' + (data.detail || resp.status));
    }
  } catch(e) {
    alert('Erro ao excluir abordagem: ' + e.message);
  }
}

async function abVerDetalhes(id) {
  var modal = document.getElementById('ab-det-modal');
  var body  = document.getElementById('ab-det-body');
  var tit   = document.getElementById('ab-det-titulo');
  if (!modal) return;
  if (tit)  tit.textContent = '\uD83D\uDCCB Abordagem #' + id;
  if (body) body.innerHTML = '<div style="text-align:center;padding:30px"><span class="spinner"></span></div>';
  openModal('ab-det-modal');
  try {
    var resp = await fetch('/api/abordagens/' + id);
    if (!resp.ok) { if (body) body.innerHTML = '<p style="color:var(--danger)">Erro ao carregar abordagem #' + id + '</p>'; return; }
    var ab = await resp.json();
    var dh = ab.data_hora ? ab.data_hora.replace('T',' ').substring(0,16) : '\u2014';

    var sS = 'font-size:.73rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);margin:14px 0 6px;padding-bottom:4px;border-bottom:1px solid rgba(250,204,21,.2)';
    var rS = 'display:flex;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.06)';
    var lS = 'min-width:130px;color:var(--muted);font-size:.8rem;flex-shrink:0';
    var vS = 'flex:1;word-break:break-word';
    function sec(ic, lbl) { return '<div style="'+sS+'">'+ic+' '+lbl+'</div>'; }
    function row(lbl, val) {
      var v = (val != null && String(val).trim()) ? _esc(String(val)) : '<span style="color:var(--muted)">\u2014</span>';
      return '<div style="'+rS+'"><span style="'+lS+'">'+lbl+'</span><span style="'+vS+'">'+v+'</span></div>';
    }

    var html = '';
    html += sec('\uD83D\uDCC5', 'Dados da Abordagem');
    html += row('Data/Hora',   dh);
    html += row('Local',       ab.local);
    html += row('Equipe',      ab.equipe);
    html += row('Tipo/Motivo', ab.tipo_motivo);
    if (ab.observacoes) html += row('Observa\u00e7\u00f5es', ab.observacoes);

    if (ab.veiculo) {
      var v = ab.veiculo;
      html += sec('\uD83D\uDE97', 'Ve\u00edculo');
      var vFotoUrl = normalizeImageUrl(v.foto_path);
      html += '<div style="position:relative;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:10px 12px' + (vFotoUrl ? ';padding-right:96px' : '') + ';margin-bottom:8px">';
      if (vFotoUrl) {
        html += '<img src="' + vFotoUrl.replace(/"/g, '&quot;') + '" alt="Foto do veículo"'
          + ' style="position:absolute;top:10px;right:12px;width:72px;height:72px;border-radius:10px;border:1px solid var(--border);object-fit:cover;cursor:pointer;box-shadow:var(--shadow)"'
          + ' onclick="openImageUrl(\'' + vFotoUrl.replace(/'/g,"\\'") + '\',\'Foto do veículo\')">';
      }
      html += row('Placa',  v.placa);
      html += row('Marca',  v.marca);
      html += row('Modelo', v.modelo);
      html += row('Cor',    v.cor);
      html += row('Ano',    v.ano);
      if (v.observacoes) html += row('Obs.', v.observacoes);
      html += '</div>';
    }

    var pessoasPrincipal = null;
    if (Array.isArray(ab.pessoas) && ab.pessoas.length) {
      html += sec('\uD83D\uDC65', 'Pessoas (' + ab.pessoas.length + ')');
      ab.pessoas.forEach(function(p) {
        var pFotoUrl = normalizeImageUrl(p.foto_path);
        html += '<div style="position:relative;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:8px 12px' + (pFotoUrl ? ';padding-right:92px' : '') + ';margin-bottom:8px">';
        if (pFotoUrl) {
          html += '<img src="' + pFotoUrl.replace(/"/g, '&quot;') + '" alt="Foto da pessoa"'
            + ' style="position:absolute;top:10px;right:12px;width:72px;height:72px;border-radius:10px;border:1px solid var(--border);object-fit:cover;cursor:pointer;box-shadow:var(--shadow)"'
            + ' onclick="openImageUrl(\'' + pFotoUrl.replace(/'/g,"\\'") + '\',\'Foto da pessoa\')">';
        }
        html += '<div style="font-weight:600;font-size:.87rem">' + _esc(p.nome || '\u2014') + '</div>';
        if (p.apelido)  html += '<div style="font-size:.78rem;color:var(--muted)">Vulgo: ' + _esc(p.apelido) + '</div>';
        if (p.papel)    html += '<div style="font-size:.78rem;color:var(--muted)">Papel: ' + _esc(p.papel) + '</div>';
        if (p.cpf)      html += '<div style="font-size:.78rem;color:var(--muted)">CPF: ' + _fmtCpf(p.cpf) + '</div>';
        if (p.observacao_pessoal) html += '<div style="font-size:.78rem;color:var(--muted)">Obs: ' + _esc(p.observacao_pessoal) + '</div>';
        if (p.id) {
          html += '<button class="btn btn-outline btn-sm" style="margin-top:8px;font-size:.76rem" '
            + 'onclick="closeModal(\'ab-det-modal\');abrirRelatorio(' + p.id + ',\'' + _esc(p.nome||'').replace(/'/g,"\\'")
            + '\')">' + '&#128202; Ver relat\u00f3rio completo</button>';
        }
        html += '</div>';
        if (!pessoasPrincipal && p.id) pessoasPrincipal = p;
      });
    }

    if (body) body.innerHTML = html;

    // Atualiza botão do footer
    var footBtn = document.getElementById('ab-det-rel-btn');
    if (footBtn) {
      if (pessoasPrincipal) {
        footBtn.style.display = '';
        footBtn.onclick = function() { closeModal('ab-det-modal'); abrirRelatorio(pessoasPrincipal.id, pessoasPrincipal.nome); };
      } else {
        footBtn.style.display = 'none';
      }
    }
  } catch(e) {
    if (body) body.innerHTML = '<p style="color:var(--danger)">Erro: ' + _esc(e.message) + '</p>';
  }
}

// =============================================================================
// MODAL PESSOAS (card do painel) — preservado intacto
// =============================================================================
var _pmOffset = 0, _pmLimit = 20, _pmTotal = 0, _pmQ = '';

async function openPessoasModal() {
  _pmOffset = 0; _pmQ = ''; _pmTotal = 0;
  document.getElementById('pm-busca').value = '';
  openModal('pm-pessoas-modal');
  await pmCarregar();
}

async function pmBuscar() {
  _pmOffset = 0;
  _pmQ = document.getElementById('pm-busca').value.trim();
  await pmCarregar();
}

function pmPagina(dir) {
  _pmOffset = Math.max(0, _pmOffset + dir * _pmLimit);
  pmCarregar();
}

async function pmCarregar() {
  var tbody = document.getElementById('pm-tbody');
  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:20px"><span class="spinner"></span> Carregando...</td></tr>';
  try {
    var url = '/api/pessoas?limit=' + _pmLimit + '&offset=' + _pmOffset + (_pmQ ? '&q=' + encodeURIComponent(_pmQ) : '');
    var resp = await fetch(url);
    if (!resp.ok) { tbody.innerHTML = '<tr><td colspan="7" style="color:var(--danger);text-align:center">Erro ' + resp.status + '</td></tr>'; return; }
    var data = await resp.json();
    _pmTotal = data.total || 0;
    var pessoas = data.pessoas || [];
    if (!pessoas.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:20px">Nenhum resultado.</td></tr>';
    } else {
      tbody.innerHTML = pessoas.map(function(p) {
        return '<tr>'
          + '<td style="color:var(--muted)">' + p.id + '</td>'
          + '<td style="font-weight:600">' + _esc(p.nome || '') + '</td>'
          + '<td>' + _esc(p.apelido || '\u2014') + '</td>'
          + '<td style="font-family:monospace">' + _esc(p.cpf ? _fmtCpf(p.cpf) : '\u2014') + '</td>'
          + '<td>' + _esc(p.contato || '\u2014') + '</td>'
          + '<td style="font-size:.78rem">' + _esc(p.endereco || '\u2014') + '</td>'
          + '<td class="action-cell"><div class="action-buttons">'
          + '<button class="btn btn-outline btn-sm" style="padding:2px 8px;font-size:.76rem" onclick="pmVerDetalhes(' + p.id + ')">&#128269; Visualizar</button>'
          + '</div></td></tr>';
      }).join('');
    }
    var pagAtual = Math.floor(_pmOffset / _pmLimit) + 1;
    var pagTotal = Math.ceil(_pmTotal / _pmLimit) || 1;
    document.getElementById('pm-total-txt').textContent = _pmTotal.toLocaleString('pt-BR') + ' pessoa(s)';
    document.getElementById('pm-pagina-txt').textContent = 'P\u00e1g. ' + pagAtual + ' / ' + pagTotal;
    document.getElementById('pm-prev-btn').style.display = _pmOffset > 0 ? '' : 'none';
    document.getElementById('pm-next-btn').style.display = (_pmOffset + _pmLimit) < _pmTotal ? '' : 'none';
  } catch(e) {
    tbody.innerHTML = '<tr><td colspan="7" style="color:var(--danger);text-align:center">Erro: ' + _esc(e.message) + '</td></tr>';
  }
}

async function pmVerDetalhes(id) {
  closeModal('pm-pessoas-modal');
  await cadastroVisualizar(id);
  // ao fechar o view, reabrir o modal de listagem
  var closeBtn = document.querySelector('#cad-view-modal .modal-close');
  if (closeBtn) {
    var origClose = closeBtn.onclick;
    closeBtn.onclick = function() {
      closeModal('cad-view-modal');
      openPessoasModal();
      closeBtn.onclick = origClose;
    };
  }
  var modalOverlay = document.getElementById('cad-view-modal');
  if (modalOverlay) {
    var origOverlay = modalOverlay.onclick;
    modalOverlay.onclick = function(ev) {
      if (ev.target === this) {
        closeModal('cad-view-modal');
        openPessoasModal();
        modalOverlay.onclick = origOverlay;
      }
    };
  }
}

(function() {
  var _origSwitchTab = window.switchTab;
  window.switchTab = function(name, el) {
    _origSwitchTab(name, el);
    if (name === 'cadastro') cadastroCarregar();
  };
})();

// =============================================================================
// NOVA ABORDAGEM RÁPIDA (a partir da ficha da pessoa)
// Endpoint: POST /api/abordagens (reutiliza o endpoint existente)
// =============================================================================
var _cadAbOcupanteIdx = 0;

async function cadastroNovaAbordagem(pessoaId, nomePessoa) {
  var pid = parseInt(pessoaId, 10);
  if (!pid) { alert('Pessoa não identificada.'); return; }
  document.getElementById('cad-ab-pessoa-id').value = pid;
  document.getElementById('cad-ab-pessoa-nome').textContent = nomePessoa || ('Pessoa #' + pid);

  // Defaults: hoje + hora atual
  var agora = new Date();
  var dataStr = agora.toISOString().substring(0, 10);
  var horaStr = agora.toTimeString().substring(0, 5);
  document.getElementById('cad-ab-data').value = dataStr;
  document.getElementById('cad-ab-hora').value = horaStr;

  // Limpa campos de abordagem
  document.getElementById('cad-ab-local').value = '';
  document.getElementById('cad-ab-historico').value = '';
  document.getElementById('cad-ab-usa-veiculo').value = 'nao';
  document.getElementById('cad-ab-placa').value = '';
  document.getElementById('cad-ab-modelo').value = '';
  document.getElementById('cad-ab-cor').value = '';
  document.getElementById('cad-ab-veiculo-campos').style.display = 'none';
  cadAbRemoverVeiculoImagem();
  document.getElementById('cad-ab-ocupantes-list').innerHTML = '';
  _cadAbOcupanteIdx = 0;
  _cadAbOcResultados = {};
  var _vaEl = document.getElementById('cad-ab-vincular-alvo'); if(_vaEl) _vaEl.value='nao';
  var _vlW  = document.getElementById('cad-ab-alvo-lista-wrap'); if(_vlW) _vlW.style.display='none';
  var _vlS  = document.getElementById('cad-ab-alvo-lista-id'); if(_vlS) _vlS.value='';

  // Limpa campos pessoais
  ['cad-ab-cpf','cad-ab-rg','cad-ab-contato','cad-ab-profissao',
   'cad-ab-rua','cad-ab-numero','cad-ab-bairro','cad-ab-cidade',
   'cad-ab-pai','cad-ab-mae',
   'cad-ab-naturalidade','cad-ab-uf-naturalidade','cad-ab-data-nascimento'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.value = '';
  });
  var _estEl = document.getElementById('cad-ab-estado'); if(_estEl) _estEl.value = '';

  var erroEl = document.getElementById('cad-ab-erro');
  var okEl   = document.getElementById('cad-ab-ok');
  if (erroEl) { erroEl.style.display = 'none'; erroEl.textContent = ''; }
  if (okEl)   { okEl.style.display   = 'none'; okEl.textContent   = ''; }

  var salvarBtn = document.getElementById('cad-ab-salvar-btn');
  if (salvarBtn) salvarBtn.disabled = false;

  openModal('cad-nova-ab-modal');

  // Pré-preenche campos pessoais com dados já cadastrados
  try {
    var resp = await fetch('/api/pessoas/' + pid);
    if (resp.ok) {
      var p = await resp.json();
      var _set = function(id, val) {
        var el = document.getElementById(id);
        if (el && val) el.value = val;
      };
      _set('cad-ab-cpf',      p.cpf ? _fmtCpf(p.cpf) : null);
      _set('cad-ab-rg',       p.rg);
      _set('cad-ab-contato',  p.contato);
      _set('cad-ab-profissao',p.profissao);
      _set('cad-ab-endereco', p.endereco);
      _set('cad-ab-pai',               p.nome_pai);
      _set('cad-ab-mae',               p.nome_mae);
      // Endereço separado — fallback: endereco único em rua
      _set('cad-ab-rua',    p.rua    || p.endereco || null);
      _set('cad-ab-numero', p.numero || null);
      _set('cad-ab-bairro', p.bairro || null);
      _set('cad-ab-cidade', p.cidade || null);
      var _estEl2 = document.getElementById('cad-ab-estado');
      if (_estEl2 && p.estado) _estEl2.value = p.estado;
      _set('cad-ab-naturalidade',      p.naturalidade);
      _set('cad-ab-uf-naturalidade',   p.estado_naturalidade);
      _set('cad-ab-data-nascimento',   p.data_nascimento);
    }
  } catch(e) { /* silencioso — campos ficam em branco */ }
}

function cadAbordagemToggleVeiculo() {
  var usaSim = document.getElementById('cad-ab-usa-veiculo').value === 'sim';
  var campos = document.getElementById('cad-ab-veiculo-campos');
  campos.style.display = usaSim ? '' : 'none';
  if (!usaSim) {
    document.getElementById('cad-ab-placa').value  = '';
    document.getElementById('cad-ab-modelo').value = '';
    document.getElementById('cad-ab-cor').value    = '';
    cadAbRemoverVeiculoImagem();
    var va = document.getElementById('cad-ab-vincular-alvo'); if(va) va.value='nao';
    var lw = document.getElementById('cad-ab-alvo-lista-wrap'); if(lw) lw.style.display='none';
    var li = document.getElementById('cad-ab-alvo-lista-id'); if(li) li.value='';
  }
}

function cadAbordagemAdicionarOcupante() {
  _cadAbOcupanteIdx++;
  var idx  = _cadAbOcupanteIdx;
  var list = document.getElementById('cad-ab-ocupantes-list');
  var div  = document.createElement('div');
  div.id = 'cad-ab-oc-' + idx;
  div.style.cssText = 'border:1px solid var(--border);border-radius:6px;padding:12px 14px;margin-bottom:10px;background:rgba(255,255,255,.03)';
  var iS = 'width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg2);color:var(--text);font-size:.84rem;box-sizing:border-box';
  var lS = 'display:flex;flex-direction:column;gap:3px;font-size:.8rem;color:var(--muted)';
  var tS = 'width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg2);color:var(--text);font-size:.84rem;resize:vertical;min-height:60px;box-sizing:border-box';
  var fR = 'display:flex;gap:4px;align-items:stretch';
  var bS = 'padding:5px 9px;white-space:nowrap;flex-shrink:0';
  div.innerHTML =
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'+
      '<span style="font-size:.8rem;font-weight:700;color:var(--accent)">Acompanhante ' + idx + '</span>'+
      '<button type="button" class="btn btn-outline btn-sm" style="color:#f87171;font-size:.79rem;padding:3px 10px" onclick="cadAbordagemRemoverOcupante(' + idx + ')">Remover</button>'+
    '</div>'+
    '<input type="hidden" id="cad-ab-oc-id-' + idx + '">'+
    '<div id="cad-ab-oc-resultado-' + idx + '" style="margin-bottom:8px"></div>'+
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">'+
      '<label style="'+lS+';grid-column:1/-1">Nome'+
        '<div style="'+fR+'">'+
          '<input type="text" id="cad-ab-oc-nome-'+idx+'" placeholder="Nome completo" maxlength="120" style="'+iS+'" onkeydown="if(event.key===\'Enter\'){event.preventDefault();cadAbOcPesquisarNome('+idx+')}">'+
          '<button type="button" class="btn btn-search btn-sm" style="'+bS+'" onclick="cadAbOcPesquisarNome('+idx+')" title="Buscar por nome">&#128269;</button>'+
        '</div>'+
      '</label>'+
      '<label style="'+lS+'">CPF'+
        '<div style="'+fR+'">'+
          '<input type="text" id="cad-ab-oc-cpf-'+idx+'" placeholder="000.000.000-00" maxlength="14" inputmode="numeric" oninput="this.value=this.value.replace(/\\D/g,\'\')" onkeydown="if(event.key===\'Enter\'){event.preventDefault();cadAbOcPesquisarCpf('+idx+')}" style="'+iS+'">'+
          '<button type="button" class="btn btn-search btn-sm" style="'+bS+'" onclick="cadAbOcPesquisarCpf('+idx+')" title="Buscar por CPF">&#128269;</button>'+
        '</div>'+
      '</label>'+
      '<label style="'+lS+'">RG'+
        '<div style="'+fR+'">'+
          '<input type="text" id="cad-ab-oc-rg-'+idx+'" placeholder="RG" maxlength="20" onkeydown="if(event.key===\'Enter\'){event.preventDefault();cadAbOcPesquisarRg('+idx+')}" style="'+iS+'">'+
          '<button type="button" class="btn btn-search btn-sm" style="'+bS+'" onclick="cadAbOcPesquisarRg('+idx+')" title="Buscar por RG">&#128269;</button>'+
        '</div>'+
      '</label>'+
      '<label style="'+lS+'">Contato'+
        '<input type="text" id="cad-ab-oc-contato-'+idx+'" placeholder="Telefone ou WhatsApp" maxlength="40" style="'+iS+'">'+
      '</label>'+
      '<label style="'+lS+'">Profiss\u00e3o'+
        '<input type="text" id="cad-ab-oc-profissao-'+idx+'" placeholder="Profiss\u00e3o" maxlength="80" style="'+iS+'">'+
      '</label>'+
      '<label style="'+lS+'">Nome do Pai'+
        '<input type="text" id="cad-ab-oc-pai-'+idx+'" placeholder="Nome do pai" maxlength="120" style="'+iS+'">'+
      '</label>'+
      '<label style="'+lS+'">Nome da M\u00e3e'+
        '<input type="text" id="cad-ab-oc-mae-'+idx+'" placeholder="Nome da m\u00e3e" maxlength="120" style="'+iS+'">'+
      '</label>'+
      '<label style="'+lS+';grid-column:1/-1">Foto do acompanhante'+
        '<input type="file" id="cad-ab-oc-foto-'+idx+'" accept="image/*" style="'+iS+'" onchange="cadAbOcPreviewImagem('+idx+', this)">'+
        '<div id="cad-ab-oc-foto-wrap-'+idx+'" style="display:none;margin-top:8px">'+
          '<img id="cad-ab-oc-foto-preview-'+idx+'" src="" alt="Prévia do acompanhante" style="width:92px;height:92px;border-radius:10px;border:1px solid var(--border);object-fit:cover;cursor:pointer;box-shadow:var(--shadow)" onclick="if(this.src){openImageUrl(this.src,\'Foto do acompanhante\')}">'+
          '<div style="margin-top:6px"><button type="button" class="btn btn-outline btn-sm" onclick="cadAbOcRemoverImagem('+idx+')">Remover imagem</button></div>'+
        '</div>'+
      '</label>'+
      '<label style="'+lS+';grid-column:1/-1">Endere\u00e7o'+
        '<input type="text" id="cad-ab-oc-endereco-'+idx+'" placeholder="Endere\u00e7o completo" maxlength="200" style="'+iS+'">'+
      '</label>'+
      '<label style="'+lS+';grid-column:1/-1">Hist\u00f3rico'+
        '<textarea id="cad-ab-oc-historico-'+idx+'" rows="3" maxlength="2000" placeholder="Observa\u00e7\u00f5es sobre este acompanhante..." style="'+tS+'"></textarea>'+
      '</label>'+
    '</div>';
  list.appendChild(div);
  var inp = document.getElementById('cad-ab-oc-nome-' + idx);
  if (inp) inp.focus();
}

function cadAbordagemRemoverOcupante(idx) {
  var el = document.getElementById('cad-ab-oc-' + idx);
  if (el) el.parentNode.removeChild(el);
}

// ---- Busca de cadastro existente para acompanhantes (modal cad-nova-ab) ----
var _cadAbOcResultados = {};

async function _cadAbOcPesquisar(idx, q) {
  if (!q) return;
  var res = document.getElementById('cad-ab-oc-resultado-' + idx);
  if(res) res.innerHTML = '<span style="font-size:.78rem;color:var(--muted)"><span class="spinner" style="width:12px;height:12px;margin-right:4px"></span>Buscando...</span>';
  try {
    var resp = await fetch('/api/pessoas?q=' + encodeURIComponent(q) + '&limit=6');
    var data = await resp.json();
    var pessoas = data.pessoas || [];
    if (!pessoas.length) {
      if(res) res.innerHTML = '<span style="font-size:.78rem;color:var(--muted)">Nenhum cadastro encontrado.</span>';
      return;
    }
    _cadAbOcResultados[idx] = pessoas;
    if (pessoas.length === 1) {
      _cadAbOcPreencher(idx, pessoas[0]);
      if(res) res.innerHTML = '<span style="font-size:.78rem;color:var(--accent)">&#10003; Cadastro vinculado: <strong>' + _esc(pessoas[0].nome) + '</strong> <span style="font-size:.75rem;color:var(--muted)">(#' + pessoas[0].id + ')</span></span>';
      return;
    }
    var html = '<div style="font-size:.78rem;color:var(--muted);margin-bottom:4px">Selecione o cadastro:</div><div style="display:flex;flex-wrap:wrap;gap:5px">';
    pessoas.forEach(function(p, i) {
      html += '<button type="button" class="btn btn-outline btn-sm" style="font-size:.76rem;padding:3px 8px" onclick="cadAbOcSelecionarIdx(' + idx + ',' + i + ')">' + _esc(p.nome) + (p.cpf ? ' \u00b7 ' + _fmtCpf(p.cpf) : '') + '</button>';
    });
    html += '</div>';
    if(res) res.innerHTML = html;
  } catch(e) {
    if(res) res.innerHTML = '<span style="font-size:.78rem;color:var(--danger)">Erro: ' + _esc(e.message) + '</span>';
  }
}

async function cadAbOcPesquisarNome(idx) {
  var q = ((document.getElementById('cad-ab-oc-nome-' + idx) || {}).value || '').trim();
  if(!q) { alert('Preencha o Nome antes de pesquisar.'); return; }
  await _cadAbOcPesquisar(idx, q);
}
async function cadAbOcPesquisarCpf(idx) {
  var q = ((document.getElementById('cad-ab-oc-cpf-' + idx) || {}).value || '').replace(/\D/g,'');
  if(!q) { alert('Preencha o CPF antes de pesquisar.'); return; }
  await _cadAbOcPesquisar(idx, q);
}
async function cadAbOcPesquisarRg(idx) {
  var q = ((document.getElementById('cad-ab-oc-rg-' + idx) || {}).value || '').trim();
  if(!q) { alert('Preencha o RG antes de pesquisar.'); return; }
  await _cadAbOcPesquisar(idx, q);
}

function cadAbOcSelecionarIdx(idx, i) {
  var p = (_cadAbOcResultados[idx] || [])[i];
  if(!p) return;
  _cadAbOcPreencher(idx, p);
  var res = document.getElementById('cad-ab-oc-resultado-' + idx);
  if(res) res.innerHTML = '<span style="font-size:.78rem;color:var(--accent)">&#10003; Cadastro vinculado: <strong>' + _esc(p.nome) + '</strong> <span style="font-size:.75rem;color:var(--muted)">(#' + p.id + ')</span></span>';
}

function _cadAbOcPreencher(idx, p) {
  var _s = function(id, val){ var el=document.getElementById(id); if(el) el.value=val||''; };
  _s('cad-ab-oc-id-'        + idx, p.id);
  _s('cad-ab-oc-nome-'      + idx, p.nome);
  _s('cad-ab-oc-cpf-'       + idx, p.cpf ? _fmtCpf(p.cpf) : '');
  _s('cad-ab-oc-rg-'        + idx, p.rg);
  _s('cad-ab-oc-contato-'   + idx, p.contato);
  _s('cad-ab-oc-profissao-' + idx, p.profissao);
  _s('cad-ab-oc-pai-'       + idx, p.nome_pai);
  _s('cad-ab-oc-mae-'       + idx, p.nome_mae);
  _s('cad-ab-oc-endereco-'  + idx, p.endereco);
}

// ---- Veículo: vincular como alvo rastreado (modal cad-nova-ab) ----
function cadAbordagemToggleVincularAlvo() {
  var sel  = document.getElementById('cad-ab-vincular-alvo');
  var wrap = document.getElementById('cad-ab-alvo-lista-wrap');
  if(!sel || !wrap) return;
  if(sel.value === 'sim') {
    wrap.style.display = '';
    cadAbordagemCarregarListasVeiculosRastreados();
  } else {
    wrap.style.display = 'none';
    var li = document.getElementById('cad-ab-alvo-lista-id'); if(li) li.value='';
  }
}

async function cadAbordagemCarregarListasVeiculosRastreados() {
  var sel = document.getElementById('cad-ab-alvo-lista-id');
  if(!sel) return;
  sel.innerHTML = '<option value="">Carregando...</option>';
  try {
    var resp = await fetch('/api/vehicles/lists');
    var data = await resp.json();
    var listas = data.items || [];
    if(!listas.length) { sel.innerHTML='<option value="">Nenhuma lista dispon\u00edvel</option>'; return; }
    sel.innerHTML = '<option value="">-- Escolha uma lista --</option>';
    listas.forEach(function(l){
      var opt=document.createElement('option');
      opt.value=l.id;
      opt.textContent=l.name+(l.vehicle_count!=null?' ('+l.vehicle_count+' ve\u00edculos)':'');
      sel.appendChild(opt);
    });
  } catch(e) {
    sel.innerHTML='<option value="">Erro ao carregar listas</option>';
  }
}

async function cadAbordagemSalvar() {
  var pessoaId = parseInt(document.getElementById('cad-ab-pessoa-id').value, 10);
  var local    = document.getElementById('cad-ab-local').value.trim();
  var data     = document.getElementById('cad-ab-data').value;
  var hora     = (document.getElementById('cad-ab-hora').value || '00:00');
  var historico = document.getElementById('cad-ab-historico').value.trim();
  var usaVeiculo = document.getElementById('cad-ab-usa-veiculo').value === 'sim';

  var erroEl  = document.getElementById('cad-ab-erro');
  var okEl    = document.getElementById('cad-ab-ok');
  erroEl.style.display = 'none'; erroEl.textContent = '';
  okEl.style.display   = 'none'; okEl.textContent   = '';

  // Validações obrigatórias
  var erros = [];
  if (!pessoaId)  erros.push('Pessoa vinculada não identificada.');
  if (!local)     erros.push('Local é obrigatório.');
  if (!data)      erros.push('Data é obrigatória.');
  if (!historico) erros.push('Histórico é obrigatório.');
  if (erros.length) {
    erroEl.textContent = erros.join(' ');
    erroEl.style.display = '';
    return;
  }

  // Monta payload — inclui campos pessoais da pessoa vinculada
  var _pEntry = { pessoa_id: pessoaId, papel: 'abordado' };
  var _cpfRaw = (document.getElementById('cad-ab-cpf').value     || '').trim().replace(/\D/g, '');
  var _rg     = (document.getElementById('cad-ab-rg').value      || '').trim();
  var _ct     = (document.getElementById('cad-ab-contato').value || '').trim();
  var _prof   = (document.getElementById('cad-ab-profissao').value || '').trim();
  var _end    = (function(){
    var _r=(document.getElementById('cad-ab-rua')||{value:''}).value.trim();
    var _n=(document.getElementById('cad-ab-numero')||{value:''}).value.trim();
    var _b=(document.getElementById('cad-ab-bairro')||{value:''}).value.trim();
    var _c=(document.getElementById('cad-ab-cidade')||{value:''}).value.trim();
    var _e=(document.getElementById('cad-ab-estado')||{value:''}).value.trim();
    return [_r, _n?'n\u00ba '+_n:'', _b, _c, _e].filter(Boolean).join(', ');
  })();
  var _pai    = (document.getElementById('cad-ab-pai').value     || '').trim();
  var _mae    = (document.getElementById('cad-ab-mae').value     || '').trim();
  if (_cpfRaw) _pEntry.cpf      = _cpfRaw;
  if (_rg)     _pEntry.rg       = _rg;
  if (_ct)     _pEntry.contato  = _ct;
  if (_prof)   _pEntry.profissao = _prof;
  if (_end)    _pEntry.endereco = _end;
  if (_pai)    _pEntry.nome_pai = _pai;
  if (_mae)    _pEntry.nome_mae = _mae;
  var _nat   = (document.getElementById('cad-ab-naturalidade').value      || '').trim();
  var _ufnat = (document.getElementById('cad-ab-uf-naturalidade').value   || '').trim().toUpperCase();
  var _dnab  = (document.getElementById('cad-ab-data-nascimento').value   || '').trim();
  if (_nat)   _pEntry.naturalidade        = _nat;
  if (_ufnat) _pEntry.estado_naturalidade = _ufnat;
  if (_dnab)  _pEntry.data_nascimento     = _dnab;
  var payload = {
    data_hora: data + 'T' + hora + ':00',
    local:     local,
    observacoes: historico,
    pessoas: [_pEntry]
  };

  // Veículo (opcional)
  if (usaVeiculo) {
    var placa  = document.getElementById('cad-ab-placa').value.trim();
    var modelo = document.getElementById('cad-ab-modelo').value.trim();
    var cor    = document.getElementById('cad-ab-cor').value.trim();
    if (placa || modelo || cor) {
      var vincAlvo = (document.getElementById('cad-ab-vincular-alvo')||{value:'nao'}).value === 'sim';
      var listaId  = (function(){ var el=document.getElementById('cad-ab-alvo-lista-id'); return el&&el.value ? parseInt(el.value,10) : null; })();
      payload.veiculo = { placa: placa, modelo: modelo, cor: cor,
                          vincular_como_alvo: vincAlvo, list_id: listaId };
    }
  }

  // Ocupantes adicionais — coleta todos os campos de cada bloco
  var listEl = document.getElementById('cad-ab-ocupantes-list');
  listEl.querySelectorAll('div[id^="cad-ab-oc-"]').forEach(function(bloco) {
    var i    = bloco.id.replace('cad-ab-oc-', '');
    var nome = ((document.getElementById('cad-ab-oc-nome-' + i) || {}).value || '').trim();
    if (!nome) return;
    var pessoaIdOc = ((document.getElementById('cad-ab-oc-id-' + i) || {}).value || '').trim();
    var ocupante = pessoaIdOc
      ? { pessoa_id: parseInt(pessoaIdOc, 10), papel: 'outro' }
      : { nome: nome, papel: 'outro' };
    if (!pessoaIdOc) {
      var cpf     = ((document.getElementById('cad-ab-oc-cpf-'      + i) || {}).value || '').replace(/\D/g,'');
      var rg      = ((document.getElementById('cad-ab-oc-rg-'       + i) || {}).value || '').trim();
      var contato = ((document.getElementById('cad-ab-oc-contato-'  + i) || {}).value || '').trim();
      var prof    = ((document.getElementById('cad-ab-oc-profissao-' + i) || {}).value || '').trim();
      var pai     = ((document.getElementById('cad-ab-oc-pai-'      + i) || {}).value || '').trim();
      var mae     = ((document.getElementById('cad-ab-oc-mae-'      + i) || {}).value || '').trim();
      var end     = ((document.getElementById('cad-ab-oc-endereco-' + i) || {}).value || '').trim();
      if (cpf)     ocupante.cpf      = cpf;
      if (rg)      ocupante.rg       = rg;
      if (contato) ocupante.contato  = contato;
      if (prof)    ocupante.profissao = prof;
      if (pai)     ocupante.nome_pai = pai;
      if (mae)     ocupante.nome_mae = mae;
      if (end)     ocupante.endereco = end;
    }
    var fotoInput = document.getElementById('cad-ab-oc-foto-' + i);
    var fotoFile = fotoInput && fotoInput.files ? fotoInput.files[0] : null;
    if (fotoFile) ocupante.foto_upload_key = 'acompanhante_imagem_' + i;
    var hist = ((document.getElementById('cad-ab-oc-historico-' + i) || {}).value || '').trim();
    if (hist) ocupante.observacao_pessoal = hist;
    payload.pessoas.push(ocupante);
  });

  var salvarBtn = document.getElementById('cad-ab-salvar-btn');
  salvarBtn.disabled = true;

  try {
    var formData = new FormData();
    formData.append('payload', JSON.stringify(payload));
    var veiculoFotoInput = document.getElementById('cad-ab-veiculo-foto');
    var veiculoFotoFile = veiculoFotoInput && veiculoFotoInput.files ? veiculoFotoInput.files[0] : null;
    if (veiculoFotoFile) formData.append('veiculo_imagem', veiculoFotoFile);
    listEl.querySelectorAll('div[id^="cad-ab-oc-"]').forEach(function(bloco) {
      var i = bloco.id.replace('cad-ab-oc-', '');
      var fotoInput = document.getElementById('cad-ab-oc-foto-' + i);
      var fotoFile = fotoInput && fotoInput.files ? fotoInput.files[0] : null;
      if (fotoFile) formData.append('acompanhante_imagem_' + i, fotoFile);
    });
    var resp = await fetch('/api/abordagens', {
      method: 'POST',
      body: formData
    });
    var resData = await resp.json();
    if (resp.ok && resData.ok) {
      okEl.textContent   = '\u2705 Abordagem #' + resData.id + ' salva com sucesso!';
      okEl.style.display = '';
      setTimeout(function() { closeModal('cad-nova-ab-modal'); }, 1600);
    } else {
      erroEl.textContent   = 'Erro ao salvar: ' + (resData.detail || resp.status);
      erroEl.style.display = '';
      salvarBtn.disabled   = false;
    }
  } catch(e) {
    erroEl.textContent   = 'Erro: ' + _esc(e.message);
    erroEl.style.display = '';
    salvarBtn.disabled   = false;
  }
}
