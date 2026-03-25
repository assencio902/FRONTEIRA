
    // Diagnóstico: captura qualquer erro JS e exibe na tela
    window.onerror = function(msg, src, line, col, err) {
      var d = document.getElementById('_dbg');
      if (!d) {
        d = document.createElement('div');
        d.id = '_dbg';
        d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#dc2626;color:#fff;padding:8px 14px;font-size:.82rem;font-family:monospace;word-break:break-all;white-space:pre-wrap';
        (document.body || document.documentElement).appendChild(d);
      }
      d.textContent += '\nERRO [L' + line + ']: ' + msg;
    };
    window.addEventListener('unhandledrejection', function(e) {
      var d = document.getElementById('_dbg');
      if (!d) {
        d = document.createElement('div');
        d.id = '_dbg';
        d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#dc2626;color:#fff;padding:8px 14px;font-size:.82rem;font-family:monospace;word-break:break-all;white-space:pre-wrap';
        (document.body || document.documentElement).appendChild(d);
      }
      d.textContent += '\nPROMISE REJEITADA: ' + (e.reason && e.reason.message ? e.reason.message : e.reason);
    });
  