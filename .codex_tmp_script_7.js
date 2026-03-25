
// =============================================================================
// RELATÓRIO COMPLETO DA PESSOA
// Endpoint: GET /api/pessoas/{id}/relatorio
// =============================================================================

// Abre a tela de detalhe da pessoa — acionado via botão, sem guia fixa no nav
async function abrirRelatorio(pessoaId, nomePessoa) {
  // 1) Garante que a aba Cadastro está visível
  var tabCadNav = document.querySelector('.nav-item[onclick*="cadastro"]');
  if (document.getElementById('tab-cadastro') &&
      !document.getElementById('tab-cadastro').classList.contains('active')) {
    if (tabCadNav) switchTab('cadastro', tabCadNav);
  }

  // 2) Mostra o pane de detalhe sem ativar nenhum botão de sub-nav
  document.querySelectorAll('.pessoas-sub-pane').forEach(function(p) { p.style.display = 'none'; });
  document.querySelectorAll('.pessoas-sub-btn').forEach(function(b) { b.classList.remove('active'); });
  var pane = document.getElementById('pessoas-sub-relatorio');
  if (pane) pane.style.display = '';

  var container = document.getElementById('relatorio-content');
  if (!container) return;
  container.innerHTML = '<div style="text-align:center;padding:40px">'
    + '<span class="spinner"></span>'
    + '<div style="color:var(--muted);margin-top:10px;font-size:.85rem">Carregando relat\u00f3rio de <strong>'
    + _esc(nomePessoa || 'Pessoa #' + pessoaId) + '</strong>...</div>'
    + '</div>';

  try {
    var resp = await fetch('/api/pessoas/' + pessoaId + '/relatorio');
    if (!resp.ok) {
      var err = await resp.json().catch(function(){return {};});
      container.innerHTML = '<div style="color:var(--danger);padding:30px;text-align:center">'
        + '&#9888; ' + _esc(err.detail || 'Erro ao carregar relat\u00f3rio.') + '</div>';
      return;
    }
    var data = await resp.json();
    container.innerHTML = _renderRelatorio(data);
  } catch(e) {
    container.innerHTML = '<div style="color:var(--danger);padding:30px;text-align:center">'
      + '&#9888; Erro de rede: ' + _esc(e.message) + '</div>';
  }
}

// Chamado a partir do bloco "Cadastro existente" na aba Nova Abordagem
function abAbrirRelatorioExistente() {
  var p = _abPessoaEncontrada || _abCpfDuplicadoPessoa;
  if (!p) return;
  abrirRelatorio(p.id, p.nome);
}

// =============================================================================
// RENDERIZAÇÃO DO RELATÓRIO
// =============================================================================
function _renderRelatorio(data) {
  var p  = data.pessoa    || {};
  var abs = data.abordagens || [];
  var r  = data.resumo    || {};
  var html = '';

  // ─── BOTÃO VOLTAR ───
  html += '<div style="margin-bottom:16px">';
  html += '<button class="btn btn-outline btn-sm" style="font-size:.82rem" '
    + 'onclick="switchPessoasSubTab(\'pesquisar\',document.getElementById(\'psub-btn-pesquisar\'))">';
  html += '&#8592; Voltar à pesquisa';
  html += '</button>';
  html += '</div>';

  // ─── CABEÇALHO DA PESSOA ───
  html += '<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;margin-bottom:4px">';
  html += '<div>';
  html += '<div style="font-size:1.05rem;font-weight:800;color:var(--accent);margin-bottom:2px">'
    + '&#128100; ' + _esc(p.nome || '—') + '</div>';
  if (p.apelido) html += '<div style="font-size:.8rem;color:var(--muted)">Vulgo: <strong>' + _esc(p.apelido) + '</strong></div>';
  html += '</div>';
  html += '<div style="display:flex;gap:8px;flex-wrap:wrap">';
  html += '<button class="btn btn-outline btn-sm" '
    + 'onclick="cadastroEditar(' + p.id + ')" style="font-size:.78rem">&#9998; Editar cadastro</button>';
  html += '<button class="btn btn-sm" style="background:var(--accent);color:#000;font-weight:600;font-size:.78rem" '
    + 'onclick="cadastroNovaAbordagem(' + p.id + ',\'' + _esc(p.nome || '').replace(/'/g, "\\'") + '\')">'
    + '&#43; Nova abordagem</button>';
  html += '</div></div>';

  // ─── DADOS DA PESSOA ───
  html += '<div class="rel-header-card">';
  html += '<div class="rel-section-title" style="margin-top:0">&#128203; Dados Cadastrais</div>';
  var relFotoUrl = normalizeImageUrl(p.foto_path);
  if (relFotoUrl) {
    html += '<div style="display:flex;justify-content:flex-end;margin:-4px 0 10px">';
    html += '<img src="' + relFotoUrl.replace(/"/g, '&quot;') + '" alt="Foto do abordado"'
      + ' style="width:108px;height:108px;border-radius:12px;border:1px solid var(--border);object-fit:cover;cursor:pointer;box-shadow:var(--shadow)"'
      + ' onclick="openImageUrl(\'' + relFotoUrl.replace(/'/g,"\\'") + '\',\'Foto do abordado\')"'
      + ' title="Clique para ampliar">';
    html += '</div>';
  }
  html += '<div class="rel-dados-grid">';
  function relDado(lbl, val) {
    var v = (val != null && String(val).trim()) ? _esc(String(val)) : '<span style="color:var(--muted)">—</span>';
    return '<div class="rel-dado-item"><div class="rel-dado-label">' + lbl + '</div>'
      + '<div class="rel-dado-value">' + v + '</div></div>';
  }
  html += relDado('CPF', p.cpf ? _fmtCpf(p.cpf) : null);
  html += relDado('RG', p.rg);
  html += relDado('Data de Nascimento', p.data_nascimento);
  html += relDado('Naturalidade', p.naturalidade ? p.naturalidade + (p.estado_naturalidade ? ' / ' + p.estado_naturalidade : '') : null);
  html += relDado('Filiação (Mãe)', p.nome_mae);
  html += relDado('Filiação (Pai)', p.nome_pai);
  html += relDado('Endereço', p.endereco);
  html += relDado('Contato', p.contato);
  html += relDado('Profissão', p.profissao);
  html += relDado('Cadastrado em', p.data_cadastro ? p.data_cadastro.substring(0, 10) : null);
  html += '</div></div>';

  // ─── ABORDAGENS ───
  html += '<div class="rel-section-title">&#128203; Histórico de Abordagens';
  html += ' <span style="font-size:.75rem;font-weight:500;color:var(--muted);margin-left:6px">('
    + (r.total_abordagens || 0) + ' total)</span></div>';

  if (!abs.length) {
    html += '<div style="background:var(--card2);border:1px solid var(--border);border-radius:var(--radius);'
      + 'padding:24px;text-align:center;color:var(--muted);font-style:italic">'
      + '&#128203; Nenhuma abordagem registrada para esta pessoa.</div>';
  } else {
    abs.forEach(function(ab, idx) {
      var dh = ab.data_hora ? ab.data_hora.replace('T', ' ').substring(0, 16) : '—';
      html += '<div class="rel-ab-card">';
      // Header do card de abordagem
      html += '<div class="rel-ab-header">';
      html += '<div>';
      html += '<span style="font-size:.75rem;color:var(--muted);margin-right:8px">#' + (ab.id || '') + '</span>';
      html += '<strong style="font-size:.88rem;color:var(--text)">' + _esc(dh) + '</strong>';
      if (ab.local) html += ' <span style="color:var(--muted);font-size:.82rem">&mdash; ' + _esc(ab.local) + '</span>';
      html += '</div>';
      html += '<div style="display:flex;gap:5px;flex-wrap:wrap;align-items:center">';
      if (ab.equipe) html += '<span class="rel-badge rel-badge-blue">' + _esc(ab.equipe) + '</span>';
      if (ab.tipo_motivo) html += '<span class="rel-badge rel-badge-yellow">' + _esc(ab.tipo_motivo) + '</span>';
      html += '</div>';
      html += '</div>';

      // Corpo do card
      html += '<div class="rel-ab-body">';

      // Observações / histórico
      if (ab.observacoes) {
        html += '<div style="font-size:.82rem;margin-bottom:12px;padding:10px 12px;'
          + 'background:rgba(0,0,0,.1);border-left:3px solid rgba(250,204,21,.4);border-radius:0 6px 6px 0">'
          + '<div style="font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;'
          + 'color:var(--muted);margin-bottom:4px">Histórico / Observações</div>'
          + '<div style="white-space:pre-wrap;line-height:1.6;color:var(--text)">' + _esc(ab.observacoes) + '</div>'
          + '</div>';
      }

      // Veículo
      var v = ab.veiculo;
      if (v) {
        var placaLabel = v.placa || '—';
        var emLista = Array.isArray(v.listas) && v.listas.length > 0;
        var vFotoUrl = normalizeImageUrl(v.foto_path);
        html += '<div style="margin-bottom:12px">';
        html += '<div style="font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;'
          + 'color:var(--muted);margin-bottom:6px">&#128665; Veículo</div>';
        html += '<div style="position:relative;display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start'
          + (vFotoUrl ? ';padding-right:110px' : '') + '">';
        if (vFotoUrl) {
          html += '<img src="' + vFotoUrl.replace(/"/g, '&quot;') + '" alt="Foto do veículo"'
            + ' style="position:absolute;top:0;right:0;width:92px;height:92px;border-radius:12px;border:1px solid var(--border);object-fit:cover;cursor:pointer;box-shadow:var(--shadow)"'
            + ' onclick="openImageUrl(\'' + vFotoUrl.replace(/'/g,"\\'") + '\',\'Foto do veículo\')">';
        }
        // placa + badges de lista
        html += '<div style="display:flex;flex-direction:column;gap:4px">';
        html += '<span class="plate-tag' + (emLista ? ' plate-alert' : '') + '" style="font-size:.88rem">'
          + _esc(placaLabel) + '</span>';
        if (emLista) {
          v.listas.forEach(function(la) {
            html += '<span class="rel-badge rel-badge-red" style="width:fit-content">'
              + '&#9888; ' + _esc(la.nome || 'Lista') + '</span>';
          });
        }
        html += '</div>';
        // demais dados
        html += '<div style="font-size:.8rem;color:var(--muted)">';
        if (v.marca)   html += '<div>Marca: <strong style="color:var(--text)">' + _esc(v.marca)   + '</strong></div>';
        if (v.modelo)  html += '<div>Modelo: <strong style="color:var(--text)">' + _esc(v.modelo) + '</strong></div>';
        if (v.cor)     html += '<div>Cor: <strong style="color:var(--text)">'    + _esc(v.cor)    + '</strong></div>';
        if (v.ano)     html += '<div>Ano: <strong style="color:var(--text)">'    + v.ano          + '</strong></div>';
        if (v.tipo)    html += '<div>Tipo: <strong style="color:var(--text)">'   + _esc(v.tipo)   + '</strong></div>';
        if (v.observacoes) html += '<div style="margin-top:3px;font-style:italic">'
          + _esc(v.observacoes) + '</div>';
        html += '</div>';
        html += '</div></div>';
      }

      // Pessoas relacionadas na abordagem
      var pr = ab.pessoas_relacionadas || [];
      if (pr.length) {
        html += '<div>';
        html += '<div style="font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;'
          + 'color:var(--muted);margin-bottom:6px">&#128101; Pessoas nesta abordagem</div>';
        html += '<div style="display:flex;flex-direction:column;gap:6px">';
        pr.forEach(function(pes) {
          var pesFotoUrl = normalizeImageUrl(pes.foto_path);
          html += '<div style="position:relative;padding:8px 10px;background:rgba(0,0,0,.08);border-radius:6px;font-size:.82rem;'
            + 'display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center' + (pesFotoUrl ? ';padding-right:72px' : '') + '">';
          if (pesFotoUrl) {
            html += '<img src="' + pesFotoUrl.replace(/"/g, '&quot;') + '" alt="Foto do acompanhante"'
              + ' style="position:absolute;top:8px;right:10px;width:54px;height:54px;border-radius:10px;border:1px solid var(--border);object-fit:cover;cursor:pointer;box-shadow:var(--shadow)"'
              + ' onclick="openImageUrl(\'' + pesFotoUrl.replace(/'/g,"\\'") + '\',\'Foto do acompanhante\')">';
          }
          html += '<span style="font-weight:600">' + _esc(pes.nome || '—') + '</span>';
          if (pes.apelido) html += '<span style="color:var(--muted)">(' + _esc(pes.apelido) + ')</span>';
          if (pes.cpf)     html += '<span style="color:var(--muted);font-size:.78rem">CPF: ' + _fmtCpf(pes.cpf) + '</span>';
          if (pes.rg)      html += '<span style="color:var(--muted);font-size:.78rem">RG: '  + _esc(pes.rg) + '</span>';
          if (pes.papel) {
            var papelColors = { motorista:'rel-badge-blue', proprietario:'rel-badge-purple',
              passageiro:'rel-badge-green', garupa:'rel-badge-orange', abordado:'rel-badge-red', outro:'rel-badge-yellow' };
            html += '<span class="rel-badge ' + (papelColors[pes.papel] || 'rel-badge-yellow') + '">'
              + _esc(pes.papel) + '</span>';
          }
          if (pes.observacao_pessoal) html += '<div style="width:100%;color:var(--muted);font-size:.78rem;font-style:italic">'
            + _esc(pes.observacao_pessoal) + '</div>';
          html += '<button class="btn btn-outline btn-sm" style="font-size:.72rem;padding:2px 7px;margin-left:auto" '
            + 'onclick="abrirRelatorio(' + pes.id + ',\'' + _esc(pes.nome || '').replace(/'/g, "\\'") + '\')">'
            + '&#128202; Ver relat\u00f3rio</button>';
          html += '</div>';
        });
        html += '</div></div>';
      } else {
        html += '<div style="font-size:.78rem;color:var(--muted);font-style:italic">Nenhuma outra pessoa registrada nesta abordagem.</div>';
      }

      html += '</div></div>'; // /rel-ab-body /rel-ab-card
    });
  }

  // ─── RESUMO GERAL ───
  html += '<div class="rel-section-title">&#128202; Resumo Geral</div>';
  html += '<div class="rel-resumo-box">';

  // Estatísticas básicas
  var veicsU = r.veiculos_unicos  || [];
  var pessU  = r.pessoas_unicas   || [];
  var reinc  = r.reincidencias    || {};
  var vReinc = reinc.veiculos_reincidentes || [];
  var pReinc = reinc.pessoas_reincidentes  || [];

  html += '<div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:16px">';
  function statBox(num, lbl, color) {
    return '<div style="text-align:center;min-width:90px">'
      + '<div style="font-size:1.9rem;font-weight:800;color:' + color + '">' + num + '</div>'
      + '<div style="font-size:.77rem;color:var(--muted);margin-top:2px">' + lbl + '</div>'
      + '</div>';
  }
  html += statBox(r.total_abordagens || 0, 'Abordagens', 'var(--accent)');
  html += statBox(veicsU.length, 'Veículos únicos', '#93c5fd');
  html += statBox(pessU.length,  'Pessoas únicas', '#6ee7b7');
  html += statBox(vReinc.length + pReinc.length, 'Reincidências', '#fca5a5');
  html += '</div>';

  // Veículos únicos
  if (veicsU.length) {
    html += '<div style="font-size:.77rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;'
      + 'color:var(--muted);margin-bottom:6px">Todos os veículos envolvidos</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:14px">';
    veicsU.forEach(function(v) {
      var reinc = v.total_abordagens > 1;
      var emLista = Array.isArray(v.listas) && v.listas.length > 0;
      html += '<span class="rel-veiculo-pill' + (emLista ? '" style="border-color:rgba(239,68,68,.5);color:#fca5a5' : '') + '">';
      html += _esc(v.placa || '—');
      if (v.modelo) html += ' · ' + _esc(v.modelo);
      if (v.cor)    html += ' · ' + _esc(v.cor);
      if (reinc)    html += ' <span style="font-size:.66rem;background:rgba(239,68,68,.3);padding:1px 5px;border-radius:99px;margin-left:3px">' + v.total_abordagens + 'x</span>';
      if (emLista)  html += ' &#9888;';
      html += '</span>';
    });
    html += '</div>';
  }

  // Pessoas únicas
  if (pessU.length) {
    html += '<div style="font-size:.77rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;'
      + 'color:var(--muted);margin-bottom:6px">Todas as pessoas envolvidas</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:14px">';
    pessU.forEach(function(p2) {
      var reinc = p2.total_abordagens > 1;
      html += '<span class="rel-pessoa-pill">';
      html += _esc(p2.nome || '—');
      if (p2.cpf) html += ' · ' + _fmtCpf(p2.cpf);
      if (reinc)  html += ' <span style="font-size:.66rem;background:rgba(239,68,68,.3);padding:1px 5px;border-radius:99px;margin-left:3px">' + p2.total_abordagens + 'x</span>';
      html += '</span>';
    });
    html += '</div>';
  }

  // Reincidências em destaque
  if (vReinc.length || pReinc.length) {
    html += '<div style="padding:12px;background:rgba(239,68,68,.07);border:1px solid rgba(239,68,68,.2);'
      + 'border-radius:8px;margin-bottom:8px">';
    html += '<div style="font-size:.77rem;font-weight:700;color:#fca5a5;margin-bottom:8px">&#9888;&#65039; REINCIDÊNCIAS</div>';
    if (vReinc.length) {
      html += '<div style="font-size:.77rem;color:var(--muted);margin-bottom:4px">Veículos reincidentes:</div>';
      html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">';
      vReinc.forEach(function(v) {
        html += '<span class="rel-reincidente-pill">'
          + _esc(v.placa || '—') + ' (' + v.total_abordagens + ' abordagens)'
          + '</span>';
      });
      html += '</div>';
    }
    if (pReinc.length) {
      html += '<div style="font-size:.77rem;color:var(--muted);margin-bottom:4px">Pessoas reincidentes:</div>';
      html += '<div style="display:flex;flex-wrap:wrap;gap:4px">';
      pReinc.forEach(function(p2) {
        html += '<span class="rel-reincidente-pill">'
          + _esc(p2.nome || '—') + ' (' + p2.total_abordagens + ' abordagens)'
          + '</span>';
      });
      html += '</div>';
    }
    html += '</div>';
  } else if (!abs.length) {
    html += '<div style="color:var(--muted);font-size:.83rem;font-style:italic">Sem dados suficientes para análise de reincidências.</div>';
  } else {
    html += '<div style="color:var(--success);font-size:.83rem">&#10003; Nenhuma reincidência de veículo ou pessoa detectada.</div>';
  }

  html += '</div>'; // /rel-resumo-box
  return html;
}
