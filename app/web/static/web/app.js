/* ============================================================
   Ease Labs — Jarvis, copiloto de dados (Fase 6)

   Uma página só, falando com a API do chat:
     GET  /api/auth/sessao/                          quem está logado
     POST /api/auth/login/  · /api/auth/logout/
     GET  /api/conversations/                        lista
     POST /api/conversations/                        nova
     GET  /api/conversations/:id/messages/?after=N   polling
     POST /api/conversations/:id/messages/           pergunta (202)

   A resposta é montada fora da requisição (Celery), então a página pergunta
   de tempos em tempos até ela chegar. Todo texto que vem do servidor é
   escapado antes de virar HTML — inclusive o Markdown da resposta da IA.
   ============================================================ */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const POLL_MS = 1500;
  const LIMITE_ESPERA_MS = 180000;

  const state = {
    usuario: null,
    conversas: [],
    projetos: [],
    arquivoAberto: false,
    conversaId: null,
    ultimoId: 0,
    aguardando: null,     // { id, inicio, texto } — pergunta sem resposta ainda
    pollTimer: null,
    relogio: null,
    falhasSeguidas: 0,
    tituloConversa: '',
    subtituloConversa: '',
    busca: '',
    buscaTimer: null,
  };

  // Perguntas de exemplo — variações das consultas de referência do time de BI.
  const SUGESTOES = [
    { tema: 'Sell Out',   cor: 'var(--primary-600)', texto: 'Quantas unidades a Ease vendeu no total, mês a mês, em 2026?' },
    { tema: 'Dispensação', cor: 'var(--primary-600)', texto: 'Quantas unidades a Pague Menos dispensou por mês em 2026?' },
    { tema: 'Mercado',    cor: 'var(--accent-800)',  texto: 'Qual o market share da Ease no varejo, mês a mês, em 2026?' },
    { tema: 'Prescrição', cor: 'var(--green-700)',   texto: 'Como evoluiu a prescrição da Ease mês a mês em 2026?' },
    { tema: 'Estoque',    cor: '#9A6700',            texto: 'Quais CDs estão em ruptura de Extrato hoje?' },
    { tema: 'PBM',        cor: 'var(--accent-800)',  texto: 'Quantas adesões ao PBM tivemos por mês em 2026?' },
  ];

  // Como cada decisão do sistema aparece na conversa.
  const TIPO_RESPOSTA = {
    answered:     { classe: '',                     rotulo: '' },
    conversation: { classe: '',                     rotulo: '' },
    empty_result: { classe: 'tipo-sem-dado',        rotulo: 'Sem resultado',         icone: 'vazio' },
    clarify:      { classe: 'tipo-esclarecimento',  rotulo: 'Preciso de um detalhe', icone: 'pergunta' },
    unknown:      { classe: 'tipo-sem-dado',        rotulo: 'Dado não disponível',   icone: 'info' },
    out_of_scope: { classe: 'tipo-sem-dado',        rotulo: 'Fora do que eu faço',   icone: 'info' },
    failed:       { classe: 'tipo-falha',           rotulo: 'Não consegui responder', icone: 'alerta' },
  };

  const ICONES = {
    grafico: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/></svg>',
    pergunta: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 015.8 1c0 2-3 2.5-3 4.5M12 17.5h.01"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>',
    vazio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 21l-4.35-4.35"/><circle cx="11" cy="11" r="8"/></svg>',
    alerta: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
    chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
    copiar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>',
    banco: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
    livro: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 016.5 17H20V3H6.5A2.5 2.5 0 004 5.5v14z"/></svg>',
    mais: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>',
    somar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>',
    pasta: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>',
    lapis: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z"/></svg>',
    arquivo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 002 2h12a2 2 0 002-2V8M10 12h4"/></svg>',
    lixeira: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>',
    lista: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>',
    relogio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    planilha: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/></svg>',
  };

  // ---------------------------------------------------------- Jarvis
  // O mascote é redesenhado em SVG (as medidas saíram do PNG original em
  // docs/brand/) porque assim ele é nítido em qualquer tamanho, pesa ~1 KB e
  // cada parte pode ser animada pelo CSS: um GIF não faria nada disso.
  const jarvis = (classe = '', orbita = false) => `
    <svg class="jarvis ${classe}" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      ${orbita ? `
      <g class="j-orbita-g">
        <path class="j-orbita j-orbita--tras" d="M 7,40 A 25,8 0 0,0 57,40"/>
        <circle class="j-satelite j-satelite--tras" r="2.2"/>
      </g>` : ''}
      <rect class="j-corpo" x="17" y="11.9" width="30" height="40.3" rx="15"/>
      <rect class="j-viseira" x="18.4" y="21.6" width="27.2" height="9.8" rx="4.9"/>
      <circle class="j-olho" cx="40" cy="26.5" r="2.4"/>
      ${orbita ? `
      <g class="j-orbita-g">
        <path class="j-orbita j-orbita--frente" d="M 7,40 A 25,8 0 0,1 57,40"/>
        <circle class="j-satelite j-satelite--frente" r="2.9"/>
      </g>` : ''}
    </svg>`;

  // ---------------------------------------------------------- utilidades
  const esc = (s) => String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const toast = (msg, isError = false, duracao = 5200) => {
    document.querySelectorAll('.toast').forEach((t) => t.remove());
    const el = document.createElement('div');
    el.className = `toast${isError ? ' toast-error' : ''}`;
    el.setAttribute('role', 'status');
    el.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg><span>${esc(msg)}</span>`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), duracao);
  };

  const novoId = () => (window.crypto?.randomUUID
    ? crypto.randomUUID()
    : `web-${Date.now()}-${Math.random().toString(36).slice(2)}`);

  const fmtHora = (iso) => new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  const fmtNum = (n) => Number(n).toLocaleString('pt-BR');

  // ---------------------------------------------------------- API
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';

  const api = async (url, { method = 'GET', body } = {}) => {
    const opts = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    if (method !== 'GET') opts.headers['X-CSRFToken'] = decodeURIComponent(csrf());
    const res = await fetch(url, opts);
    if (res.status === 204) return {};
    const data = await res.json().catch(() => ({}));
    // Sessão expirou (o DRF responde 403 a quem não está logado).
    if ((res.status === 401 || res.status === 403) && state.usuario && !url.startsWith('/api/auth/login')) {
      sessaoEncerrada();
      throw new Error('Sua sessão terminou. Entre de novo.');
    }
    if (!res.ok) {
      const erro = new Error(data.error || data.detail || `Erro ${res.status}`);
      erro.status = res.status;
      erro.dados = data;
      throw erro;
    }
    return data;
  };

  // ---------------------------------------------------------- Markdown
  // Só o que a IA usa: parágrafos, negrito, itálico, código, listas,
  // títulos, citação e tabela. Escapa ANTES de formatar: nada do texto do
  // modelo vira tag.
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');

  // "1.234", "12,3%", "R$ 302,00", "-4,5": alinhados à direita na tabela.
  const pareceNumero = (s) => /^[−\-+]?\s*(R\$\s*)?[\d.,]*\d[\d.,]*\s*%?$/.test(String(s).trim());

  const celulas = (linha) => linha.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());

  const tabelaHtml = (cabecalho, linhas) => {
    const th = cabecalho.map((c, i) => {
      const num = linhas.length && linhas.every((l) => !l[i] || pareceNumero(l[i]));
      return `<th${num ? ' class="num"' : ''}>${inline(c)}</th>`;
    }).join('');
    const tb = linhas.map((l) => `<tr>${cabecalho.map((_, i) => {
      const v = l[i] ?? '';
      return `<td${pareceNumero(v) ? ' class="num"' : ''}>${inline(v)}</td>`;
    }).join('')}</tr>`).join('');
    return `<div class="md-tabela"><table><thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table></div>`;
  };

  const markdown = (texto) => {
    const linhas = String(texto || '').replace(/\r/g, '').split('\n');
    const html = [];
    let paragrafo = [];
    const fecharParagrafo = () => {
      if (paragrafo.length) html.push(`<p>${paragrafo.map(inline).join('<br>')}</p>`);
      paragrafo = [];
    };

    for (let i = 0; i < linhas.length; i++) {
      const linha = linhas[i];
      const limpa = linha.trim();

      if (!limpa) { fecharParagrafo(); continue; }

      const separador = linhas[i + 1] && /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(linhas[i + 1].trim());
      if (limpa.includes('|') && separador) {
        fecharParagrafo();
        const cab = celulas(limpa);
        const corpo = [];
        i += 2;
        while (i < linhas.length && linhas[i].includes('|') && linhas[i].trim()) {
          corpo.push(celulas(linhas[i]));
          i++;
        }
        i--;
        html.push(tabelaHtml(cab, corpo));
        continue;
      }

      const titulo = limpa.match(/^#{1,4}\s+(.*)$/);
      if (titulo) { fecharParagrafo(); html.push(`<h4>${inline(titulo[1])}</h4>`); continue; }

      if (/^>\s?/.test(limpa)) { fecharParagrafo(); html.push(`<blockquote>${inline(limpa.replace(/^>\s?/, ''))}</blockquote>`); continue; }

      const ehLista = (l) => /^\s*([-*•]|\d+[.)])\s+/.test(l);
      if (ehLista(linha)) {
        fecharParagrafo();
        const ordenada = /^\s*\d+[.)]\s+/.test(linha);
        const itens = [];
        while (i < linhas.length && ehLista(linhas[i])) {
          itens.push(`<li>${inline(linhas[i].replace(/^\s*([-*•]|\d+[.)])\s+/, ''))}</li>`);
          i++;
        }
        i--;
        html.push(`<${ordenada ? 'ol' : 'ul'}>${itens.join('')}</${ordenada ? 'ol' : 'ul'}>`);
        continue;
      }

      paragrafo.push(limpa);
    }
    fecharParagrafo();
    return html.join('');
  };

  // Resposta "sem narrativa" (ADR-0010): o sistema entregou a tabela crua,
  // com colunas separadas por " | " e sem a linha de separação do Markdown.
  const tabelaCrua = (texto) => {
    const linhas = String(texto).split('\n').filter((l) => l.trim());
    if (linhas.length < 1) return esc(texto);
    const partes = linhas.map((l) => l.split(' | '));
    return tabelaHtml(partes[0], partes.slice(1));
  };

  // ---------------------------------------------------------- SQL
  const PALAVRAS_SQL = 'SELECT|FROM|WHERE|LEFT|RIGHT|INNER|CROSS|FULL|JOIN|ON|AND|OR|NOT|IN|IS|NULL|AS|WITH|GROUP|ORDER|BY|HAVING|LIMIT|DISTINCT|CASE|WHEN|THEN|ELSE|END|BETWEEN|ILIKE|LIKE|SIMILAR|TO|FILTER|OVER|UNION|ALL|ASC|DESC|SUM|COUNT|MAX|MIN|AVG|ROUND|COALESCE|NULLIF|FLOOR|CEIL|DATE|INTERVAL|LPAD|LEFT|TRANSLATE|UPPER|DATE_TRUNC|TO_CHAR|TO_DATE';
  const REGEX_SQL = new RegExp(`('(?:[^']|'')*')|\\b(${PALAVRAS_SQL})\\b`, 'gi');

  const realcarSql = (sql) => String(sql || '').split('\n').map((linha) => {
    // comentário: tudo depois de "--" que não está dentro de string
    let emString = false; let corte = -1;
    for (let i = 0; i < linha.length - 1; i++) {
      if (linha[i] === "'") emString = !emString;
      if (!emString && linha[i] === '-' && linha[i + 1] === '-') { corte = i; break; }
    }
    const codigo = corte >= 0 ? linha.slice(0, corte) : linha;
    const comentario = corte >= 0 ? linha.slice(corte) : '';
    // escapa só &, < e >: o apóstrofo precisa continuar reconhecível
    const seguro = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const realcado = seguro(codigo).replace(REGEX_SQL, (m, str, kw) => (
      str ? `<span class="str">${str}</span>` : `<span class="kw">${kw}</span>`
    ));
    return realcado + (comentario ? `<span class="com">${seguro(comentario)}</span>` : '');
  }).join('\n');

  // ---------------------------------------------------------- telas
  const mostrarLogin = () => {
    pararAguardo();
    state.usuario = null;
    $('#panel-chat').hidden = true;
    $('#panel-login').hidden = false;
    document.title = 'Entrar · Jarvis · Ease Labs';
    etapaDoLogin('email');
  };

  const sessaoEncerrada = () => {
    if (!state.usuario) return;
    mostrarLogin();
    toast('Sua sessão terminou. Entre de novo para continuar.', true);
  };

  const entrar = (usuario) => {
    state.usuario = usuario;
    $('#panel-login').hidden = true;
    $('#panel-chat').hidden = false;
    $('#headerUserAvatar').textContent = usuario.iniciais;
    $('#headerUserName').textContent = usuario.nome;
    $('#headerUserRole').textContent = usuario.equipe ? 'Equipe BI & Analytics' : 'BI & Analytics';
    $('#menuUserName').textContent = usuario.nome;
    $('#menuUserSub').textContent = usuario.email || `@${usuario.usuario}`;
    // Quem veio do Admin (/admin/login redireciona para cá com ?proximo=)
    // volta para ele depois de entrar. Só caminho interno do Admin: um
    // `proximo` apontando para fora seria um redirecionamento aberto.
    const proximo = new URLSearchParams(location.search).get('proximo');
    if (proximo && /^\/admin\/[\w\-/]*$/.test(proximo)) { location.href = proximo; return; }
    carregarConversas();
    irParaRota(location.pathname, 'replace');
  };

  // ---------------------------------------------------------- rotas
  const rotaDaConversa = (id) => (id ? `/conversas/${id}` : '/');

  const irParaRota = (path, historico) => {
    const achado = path.match(/^\/conversas\/(\d+)\/?$/);
    if (achado) abrirConversa(Number(achado[1]), historico);
    else novaConversa(historico);
  };

  const mudarRota = (path, historico) => {
    if (!historico || location.pathname === path) return;
    history[historico === 'replace' ? 'replaceState' : 'pushState']({}, '', path);
  };

  window.addEventListener('popstate', () => { if (state.usuario) irParaRota(location.pathname, false); });

  // ---------------------------------------------------------- lista
  // Projetos (pastas) no topo, conversas soltas no meio, arquivadas no fim.
  // Quais pastas estão abertas fica no navegador: é conforto de quem usa,
  // não dado da aplicação.
  const CHAVE_PASTAS = 'bi-chat:pastas-abertas';
  const pastasAbertas = (() => {
    try { return new Set(JSON.parse(localStorage.getItem(CHAVE_PASTAS) || '[]')); } catch { return new Set(); }
  })();
  const salvarPastas = () => {
    try { localStorage.setItem(CHAVE_PASTAS, JSON.stringify([...pastasAbertas])); } catch { /* navegação privada */ }
  };

  // `title`: o nome inteiro no hover. A linha é cortada com reticências para
  // caber na lateral, e quem batizou a conversa de "Ruptura de Extrato no CD
  // de Ribeirão" só via "Ruptura de Extrato no...".
  const itemConversa = (c, i) => `
    <div class="conversa-linha" style="animation-delay:${Math.min(i, 8) * 25}ms" draggable="true" data-arrastar="${c.id}">
      <button class="conversa-item${c.id === state.conversaId ? ' ativa' : ''}" type="button" data-id="${c.id}" title="${esc(c.title || 'Nova conversa')}">
        <span class="conversa-titulo">${esc(c.title || 'Nova conversa')}</span>
      </button>
      <button class="item-acoes" type="button" data-menu-conversa="${c.id}" aria-label="Opções da conversa" aria-haspopup="true">${ICONES.mais}</button>
    </div>`;

  const renderLista = () => {
    const lista = $('#listaConversas');
    const ativas = state.conversas.filter((c) => c.status !== 'archived');
    const arquivadas = state.conversas.filter((c) => c.status === 'archived');
    const soltas = ativas.filter((c) => !c.project);
    let n = 0;

    const pastas = state.projetos.map((p) => {
      const daPasta = ativas.filter((c) => c.project === p.id);
      const aberta = pastasAbertas.has(p.id) || daPasta.some((c) => c.id === state.conversaId);
      return `
        <div class="pasta${aberta ? ' aberta' : ''}" data-pasta-alvo="${p.id}">
          <div class="pasta-linha">
            <button class="pasta-cabeca" type="button" data-pasta="${p.id}" aria-expanded="${aberta}" title="${esc(p.name)}">
              ${ICONES.pasta}<span class="pasta-nome">${esc(p.name)}</span><span class="pasta-contagem">${daPasta.length}</span>
            </button>
            <button class="item-acoes" type="button" data-menu-projeto="${p.id}" aria-label="Opções do projeto" aria-haspopup="true">${ICONES.mais}</button>
          </div>
          <div class="pasta-conversas">${daPasta.length
            ? daPasta.map((c) => itemConversa(c, n++)).join('')
            : '<p class="conversa-vazia">Vazio — arraste conversas para cá.</p>'}</div>
        </div>`;
    }).join('');

    if (state.busca) {
      const achadas = state.conversas;
      lista.innerHTML = `
        <div class="lista-secao">
          <div class="busca-resumo">${achadas.length
            ? `${achadas.length} ${achadas.length === 1 ? 'conversa encontrada' : 'conversas encontradas'}`
            : 'Nada encontrado. Tente outra palavra.'}</div>
          ${achadas.map((c) => itemConversa(c, n++)).join('')}
        </div>`;
      return;
    }

    lista.innerHTML = `
      <div class="lista-secao">
        <div class="secao-cabeca">
          <h2 class="section-label">Projetos</h2>
          <button class="secao-acao" type="button" id="btnNovoProjeto" aria-label="Novo projeto" title="Novo projeto">${ICONES.somar}</button>
        </div>
        ${pastas}
      </div>
      <div class="lista-secao" data-solta="soltas">
        <div class="secao-cabeca"><h2 class="section-label">Recentes</h2></div>
        ${soltas.length
          ? soltas.map((c) => itemConversa(c, n++)).join('')
          : `<p class="conversa-vazia">${ativas.length ? 'Todas as conversas estão em projetos.' : 'Suas conversas aparecem aqui. Comece com uma pergunta.'}</p>`}
      </div>
      ${arquivadas.length ? `
        <div class="lista-secao pasta${state.arquivoAberto ? ' aberta' : ''}">
          <button class="secao-cabeca secao-arquivo" type="button" id="btnArquivadas" aria-expanded="${state.arquivoAberto}">
            <h2 class="section-label">Arquivadas · ${arquivadas.length}</h2>${ICONES.chevron}
          </button>
          <div class="pasta-conversas">${arquivadas.map((c) => itemConversa(c, n++)).join('')}</div>
        </div>` : ''}`;
  };

  const carregarConversas = async () => {
    try {
      const filtro = state.busca ? `?q=${encodeURIComponent(state.busca)}` : '';
      const [{ conversations }, { projects }] = await Promise.all([
        api(`/api/conversations/${filtro}`),
        api('/api/projects/'),
      ]);
      state.conversas = conversations;
      state.projetos = projects;
      renderLista();
      atualizarCabecalhoDoProjeto();
    } catch (e) {
      if (state.usuario) toast(`Não consegui carregar as conversas: ${e.message}`, true);
    }
  };

  $('#listaConversas').addEventListener('click', (ev) => {
    const menuConversa = ev.target.closest('[data-menu-conversa]');
    if (menuConversa) { abrirMenuConversa(Number(menuConversa.dataset.menuConversa), menuConversa); return; }
    const menuProjeto = ev.target.closest('[data-menu-projeto]');
    if (menuProjeto) { abrirMenuProjeto(Number(menuProjeto.dataset.menuProjeto), menuProjeto); return; }
    if (ev.target.closest('#btnNovoProjeto')) { dialogoProjeto(); return; }
    if (ev.target.closest('#btnArquivadas')) { state.arquivoAberto = !state.arquivoAberto; renderLista(); return; }

    const pasta = ev.target.closest('[data-pasta]');
    if (pasta) {
      const id = Number(pasta.dataset.pasta);
      if (pastasAbertas.has(id)) pastasAbertas.delete(id); else pastasAbertas.add(id);
      salvarPastas();
      pasta.closest('.pasta').classList.toggle('aberta');
      pasta.setAttribute('aria-expanded', String(pasta.closest('.pasta').classList.contains('aberta')));
      return;
    }

    const item = ev.target.closest('.conversa-item');
    if (!item) return;
    fecharGaveta();
    const id = Number(item.dataset.id);
    if (id !== state.conversaId) abrirConversa(id, 'push');
  });

  // ---------------------------------------------------------- arrastar
  // Um gesto só resolve as duas organizações: soltar dentro de uma pasta
  // move a conversa para ela (PATCH `project`), e soltar entre duas
  // conversas muda a ordem (PATCH `ordem`). Soltar na seção "Recentes" tira
  // da pasta.
  //
  // Desligado durante a busca: ali a lista é resultado de filtro, e arrastar
  // dentro de um filtro ordenaria uma coisa que some no próximo termo.
  let arrastada = null;
  let pista = { el: null, classe: '' };

  const limparPista = () => {
    pista.el?.classList.remove(pista.classe);
    pista = { el: null, classe: '' };
  };

  const marcarPista = (el, classe) => {
    if (pista.el === el && pista.classe === classe) return;
    limparPista();
    if (el) { el.classList.add(classe); pista = { el, classe }; }
  };

  const listaEl = $('#listaConversas');

  listaEl.addEventListener('dragstart', (ev) => {
    const linha = ev.target.closest('[data-arrastar]');
    if (!linha || state.busca) { ev.preventDefault(); return; }
    arrastada = Number(linha.dataset.arrastar);
    linha.classList.add('arrastando');
    ev.dataTransfer.effectAllowed = 'move';
    // O Firefox só começa o arrasto se algo for escrito no dataTransfer.
    ev.dataTransfer.setData('text/plain', String(arrastada));
  });

  listaEl.addEventListener('dragend', (ev) => {
    ev.target.closest('[data-arrastar]')?.classList.remove('arrastando');
    limparPista();
    arrastada = null;
  });

  listaEl.addEventListener('dragover', (ev) => {
    if (arrastada === null) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = 'move';

    const linha = ev.target.closest('[data-arrastar]');
    if (linha && Number(linha.dataset.arrastar) !== arrastada) {
      const r = linha.getBoundingClientRect();
      marcarPista(linha, ev.clientY < r.top + r.height / 2 ? 'solta-antes' : 'solta-depois');
      return;
    }
    marcarPista(ev.target.closest('[data-pasta-alvo]'), 'alvo-pasta');
  });

  listaEl.addEventListener('drop', async (ev) => {
    if (arrastada === null) return;
    ev.preventDefault();

    const id = arrastada;
    const linha = ev.target.closest('[data-arrastar]');
    const sobre = linha && Number(linha.dataset.arrastar) !== id
      ? Number(linha.dataset.arrastar)
      : null;
    const alvoPasta = ev.target.closest('[data-pasta-alvo]');
    const emSoltas = ev.target.closest('[data-solta="soltas"]');
    const depois = sobre !== null
      && ev.clientY >= linha.getBoundingClientRect().top + linha.getBoundingClientRect().height / 2;

    limparPista();
    arrastada = null;

    const conversa = state.conversas.find((c) => c.id === id);
    if (!conversa) return;
    const projetoAntes = conversa.project ?? null;

    // Soltar em cima de outra conversa herda a pasta dela: é o que o olho
    // espera de quem largou o item no meio daquela lista.
    let projeto = projetoAntes;
    if (sobre !== null) projeto = state.conversas.find((c) => c.id === sobre)?.project ?? null;
    else if (alvoPasta) projeto = Number(alvoPasta.dataset.pastaAlvo);
    else if (emSoltas) projeto = null;

    const ordem = state.conversas.filter((c) => c.id !== id);
    let destino;
    if (sobre !== null) {
      destino = ordem.findIndex((c) => c.id === sobre) + (depois ? 1 : 0);
    } else if (projeto !== projetoAntes) {
      // Largou no corpo da pasta (ou na lista solta), sem mirar ninguém:
      // entra no topo do grupo de destino.
      const i = ordem.findIndex((c) => (c.project ?? null) === projeto && c.status !== 'archived');
      destino = i === -1 ? ordem.length : i;
    } else {
      return;  // soltou onde já estava
    }

    // Otimista: a lista se mexe na hora e o servidor confirma depois. Se
    // falhar, recarrega — melhor voltar ao que o banco tem do que deixar a
    // tela mentindo.
    conversa.project = projeto;
    // Largar numa pasta fechada abre a pasta: sem isto a conversa some de
    // vista no instante em que foi movida, e parece que deu errado.
    if (projeto && projeto !== projetoAntes) { pastasAbertas.add(projeto); salvarPastas(); }
    ordem.splice(destino, 0, conversa);
    state.conversas = ordem;
    renderLista();
    atualizarCabecalhoDoProjeto();

    try {
      if (projeto !== projetoAntes) {
        await api(`/api/conversations/${id}/`, { method: 'PATCH', body: { project: projeto } });
      }
      await api('/api/conversations/ordem/', {
        method: 'PATCH',
        body: { ids: state.conversas.map((c) => c.id) },
      });
    } catch (e) {
      toast(`Não consegui mover a conversa: ${e.message}`, true);
      carregarConversas();
    }
  });

  // ---------------------------------------------------------- largura
  // Arrastar a borda direita da lateral. Sem alça desenhada de propósito: o
  // cursor é a única pista, e nada é gravado — um F5 devolve os 300 px do
  // padrão. É ajuste de momento, para ler um título longo, não preferência.
  const alca = $('#alcaSidebar');
  const shell = $('#panel-chat');

  alca?.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0 || shell.classList.contains('recolhida')) return;
    ev.preventDefault();
    alca.setPointerCapture(ev.pointerId);
    document.body.classList.add('redimensionando');

    const mover = (e) => {
      const esquerda = $('#sidebar').getBoundingClientRect().left;
      const largura = Math.min(560, Math.max(220, e.clientX - esquerda));
      shell.style.setProperty('--sidebar-w', `${Math.round(largura)}px`);
    };
    const soltar = () => {
      document.body.classList.remove('redimensionando');
      alca.removeEventListener('pointermove', mover);
      alca.removeEventListener('pointerup', soltar);
      alca.removeEventListener('pointercancel', soltar);
    };
    alca.addEventListener('pointermove', mover);
    alca.addEventListener('pointerup', soltar);
    alca.addEventListener('pointercancel', soltar);
  });

  // Duplo clique devolve o padrão sem precisar do F5.
  alca?.addEventListener('dblclick', () => shell.style.removeProperty('--sidebar-w'));

  // ---------------------------------------------------------- menu ⋯
  const menu = $('#menuContexto');
  let ancoraDoMenu = null;

  const fecharMenu = () => {
    menu.hidden = true;
    menu.innerHTML = '';
    ancoraDoMenu?.setAttribute('aria-expanded', 'false');
    ancoraDoMenu = null;
  };

  const abrirMenu = (ancora, itens) => {
    if (ancoraDoMenu === ancora) { fecharMenu(); return; }
    fecharMenu();
    menu.innerHTML = itens.map((it, i) => (it === '-'
      ? '<div class="dropdown-sep"></div>'
      : `<button class="dropdown-item${it.perigo ? ' dropdown-item-danger' : ''}" type="button" role="menuitem" data-i="${i}">${ICONES[it.icone] || ''}${esc(it.rotulo)}</button>`)).join('');
    menu.hidden = false;
    ancoraDoMenu = ancora;
    ancora.setAttribute('aria-expanded', 'true');
    const r = ancora.getBoundingClientRect();
    const largura = menu.offsetWidth;
    const altura = menu.offsetHeight;
    const abaixo = r.bottom + 6 + altura < window.innerHeight;
    menu.style.top = `${abaixo ? r.bottom + 6 : Math.max(8, r.top - altura - 6)}px`;
    menu.style.left = `${Math.max(8, Math.min(r.right - largura, window.innerWidth - largura - 8))}px`;
    menu.onclick = (ev) => {
      const b = ev.target.closest('[data-i]');
      if (!b) return;
      const { acao } = itens[Number(b.dataset.i)];
      fecharMenu();
      acao();
    };
  };

  document.addEventListener('click', (ev) => {
    if (!menu.hidden && !ev.target.closest('#menuContexto') && !ev.target.closest('.item-acoes')) fecharMenu();
  });
  window.addEventListener('resize', fecharMenu);
  $('#listaConversas').addEventListener('scroll', fecharMenu, true);

  const conversaPorId = (id) => state.conversas.find((c) => c.id === id);

  const abrirMenuConversa = (id, ancora) => {
    const c = conversaPorId(id);
    if (!c) return;
    const arquivada = c.status === 'archived';
    abrirMenu(ancora, [
      { rotulo: 'Renomear', icone: 'lapis', acao: () => dialogoRenomearConversa(c) },
      { rotulo: 'Mover para projeto', icone: 'pasta', acao: () => dialogoMover(c) },
      { rotulo: arquivada ? 'Desarquivar' : 'Arquivar', icone: 'arquivo', acao: () => arquivar(c, !arquivada) },
      '-',
      { rotulo: 'Excluir', icone: 'lixeira', perigo: true, acao: () => dialogoExcluirConversa(c) },
    ]);
  };

  const abrirMenuProjeto = (id, ancora) => {
    const p = state.projetos.find((x) => x.id === id);
    if (!p) return;
    abrirMenu(ancora, [
      { rotulo: 'Renomear projeto', icone: 'lapis', acao: () => dialogoProjeto(p) },
      '-',
      { rotulo: 'Excluir projeto', icone: 'lixeira', perigo: true, acao: () => dialogoExcluirProjeto(p) },
    ]);
  };

  // ---------------------------------------------------------- janela de diálogo
  // Mesmo desenho do modal da Indicação de PDVs: véu com blur, cartão que
  // sobe 12px ao abrir, rodapé cinza com as ações.
  const modal = $('#modal');
  let aoConfirmar = null;

  const fecharModal = () => {
    modal.classList.remove('aberto');
    aoConfirmar = null;
    setTimeout(() => { if (!modal.classList.contains('aberto')) modal.hidden = true; }, 200);
  };

  const abrirModal = ({ titulo, corpo, confirmar = 'Salvar', perigo = false, acao = null }) => {
    $('#modalTitulo').textContent = titulo;
    const area = $('#modalCorpo');
    area.onclick = null;
    area.innerHTML = corpo;
    const botao = $('#modalConfirmar');
    botao.textContent = confirmar;
    botao.className = `btn ${perigo ? 'btn-perigo' : 'btn-primary'}`;
    botao.hidden = !acao;
    botao.disabled = false;
    $('#modalCancelar').textContent = acao ? 'Cancelar' : 'Fechar';
    aoConfirmar = acao;
    modal.hidden = false;
    requestAnimationFrame(() => modal.classList.add('aberto'));
    setTimeout(() => {
      const campo = modal.querySelector('.modal-corpo input');
      if (campo) { campo.focus(); campo.select(); } else if (acao) botao.focus();
    }, 60);
  };

  $('#modalCancelar').addEventListener('click', fecharModal);
  modal.addEventListener('mousedown', (ev) => { if (ev.target === modal) fecharModal(); });
  $('#modalForm').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!aoConfirmar) return;
    const botao = $('#modalConfirmar');
    botao.disabled = true;
    try {
      await aoConfirmar();
      fecharModal();
    } catch (e) {
      const erro = $('#modalErro');
      if (erro) { erro.textContent = e.message; erro.hidden = false; } else toast(e.message, true);
      botao.disabled = false;
    }
  });

  const campoTexto = (id, rotulo, valor, exemplo, limite) => `
    <div class="input-group">
      <label class="input-label" for="${id}">${esc(rotulo)}</label>
      <input class="input-field" id="${id}" type="text" maxlength="${limite}" value="${esc(valor || '')}" placeholder="${esc(exemplo)}" autocomplete="off">
    </div>
    <div class="input-error-msg" id="modalErro" hidden></div>`;

  const dialogoProjeto = (projeto = null, depois = null) => abrirModal({
    titulo: projeto ? 'Renomear projeto' : 'Novo projeto',
    corpo: campoTexto('campoProjeto', 'Nome do projeto', projeto?.name, 'Ex.: Fechamento de agosto', 80),
    confirmar: projeto ? 'Salvar' : 'Criar projeto',
    acao: async () => {
      const name = $('#campoProjeto').value.trim();
      if (!name) throw new Error('Dê um nome ao projeto.');
      const salvo = projeto
        ? await api(`/api/projects/${projeto.id}/`, { method: 'PATCH', body: { name } })
        : await api('/api/projects/', { method: 'POST', body: { name } });
      pastasAbertas.add(salvo.id);
      salvarPastas();
      if (depois) await depois(salvo);
      await carregarConversas();
      toast(projeto ? 'Projeto renomeado.' : `Projeto "${salvo.name}" criado.`);
    },
  });

  const dialogoExcluirProjeto = (p) => {
    const qtd = state.conversas.filter((c) => c.project === p.id).length;
    const destino = qtd === 1 ? 'A conversa dele volta' : `As ${qtd} conversas dele voltam`;
    abrirModal({
      titulo: 'Excluir projeto',
      corpo: `<p class="modal-texto">O projeto <strong>${esc(p.name)}</strong> será excluído.${qtd ? ` ${destino} para a lista geral — nenhuma conversa é apagada.` : ''}</p>`,
      confirmar: 'Excluir projeto',
      perigo: true,
      acao: async () => {
        await api(`/api/projects/${p.id}/`, { method: 'DELETE' });
        pastasAbertas.delete(p.id);
        salvarPastas();
        await carregarConversas();
        toast('Projeto excluído.');
      },
    });
  };

  const dialogoRenomearConversa = (c) => abrirModal({
    titulo: 'Renomear conversa',
    corpo: campoTexto('campoTitulo', 'Título', c.title, 'Ex.: Vendas de agosto', 200),
    acao: async () => {
      const title = $('#campoTitulo').value.trim();
      if (!title) throw new Error('O título não pode ficar vazio.');
      await api(`/api/conversations/${c.id}/`, { method: 'PATCH', body: { title } });
      if (c.id === state.conversaId) definirCabecalho(title, state.subtituloConversa);
      await carregarConversas();
    },
  });

  const moverPara = async (c, projetoId) => {
    await api(`/api/conversations/${c.id}/`, { method: 'PATCH', body: { project: projetoId } });
    if (projetoId) { pastasAbertas.add(projetoId); salvarPastas(); }
    await carregarConversas();
  };

  const dialogoMover = (c) => {
    const atual = c.project || null;
    const opcoes = [{ id: null, name: 'Sem projeto' }, ...state.projetos];
    abrirModal({
      titulo: 'Mover para projeto',
      corpo: `<div class="opcoes-projeto">${opcoes.map((p) => `
          <button type="button" class="opcao-projeto${atual === p.id ? ' atual' : ''}" data-projeto="${p.id ?? ''}">
            ${p.id ? ICONES.pasta : ICONES.lista}<span>${esc(p.name)}</span>${atual === p.id ? '<span class="badge badge-primary">Atual</span>' : ''}
          </button>`).join('')}
          <button type="button" class="opcao-projeto opcao-nova" data-novo-projeto>${ICONES.somar}<span>Novo projeto…</span></button>
        </div>`,
    });
    $('#modalCorpo').onclick = async (ev) => {
      if (ev.target.closest('[data-novo-projeto]')) {
        fecharModal();
        setTimeout(() => dialogoProjeto(null, (novo) => moverPara(c, novo.id)), 220);
        return;
      }
      const opcao = ev.target.closest('[data-projeto]');
      if (!opcao) return;
      const alvo = opcao.dataset.projeto ? Number(opcao.dataset.projeto) : null;
      fecharModal();
      if (alvo === atual) return;
      try {
        await moverPara(c, alvo);
        toast(alvo ? 'Conversa movida para o projeto.' : 'Conversa tirada do projeto.');
      } catch (e) { toast(e.message, true); }
    };
  };

  const arquivar = async (c, arquivar) => {
    try {
      await api(`/api/conversations/${c.id}/`, { method: 'PATCH', body: { status: arquivar ? 'archived' : 'open' } });
      await carregarConversas();
      toast(arquivar ? 'Conversa arquivada.' : 'Conversa de volta à lista.');
    } catch (e) { toast(e.message, true); }
  };

  const dialogoExcluirConversa = (c) => abrirModal({
    titulo: 'Excluir conversa',
    corpo: `<p class="modal-texto">A conversa <strong>${esc(c.title || 'Nova conversa')}</strong> sai da sua lista e não pode ser reaberta.</p>`,
    confirmar: 'Excluir',
    perigo: true,
    acao: async () => {
      await api(`/api/conversations/${c.id}/`, { method: 'DELETE' });
      if (c.id === state.conversaId) novaConversa('replace');
      await carregarConversas();
      toast('Conversa excluída.');
    },
  });

  const atualizarCabecalhoDoProjeto = () => {
    const c = conversaPorId(state.conversaId);
    const p = c?.project ? state.projetos.find((x) => x.id === c.project) : null;
    const selo = $('#chatProjeto');
    selo.hidden = !p;
    selo.innerHTML = p ? `${ICONES.pasta}${esc(p.name)}` : '';
  };

  // ---------------------------------------------------------- conversa
  // Cumprimentar pelo nome e pela hora é o que faz a tela vazia parecer
  // alguém esperando, e não um formulário. O primeiro nome basta: "Boa
  // tarde, Rubens Guimaraes Filho" soa como carta de cobrança.
  const saudacao = () => {
    const h = new Date().getHours();
    const hora = h < 5 ? 'Boa madrugada' : h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite';
    const primeiro = (state.usuario?.nome || '').trim().split(/\s+/)[0];
    return primeiro ? `${hora}, ${primeiro}!` : `${hora}!`;
  };

  // Uma linha diferente a cada conversa nova: sempre a mesma frase, todo dia,
  // some da vista depois da segunda semana.
  const CONVITES = [
    'Eu consulto o banco da Ease Labs e mostro de onde veio cada número. Diga o período e o recorte que você quer.',
    'Pergunte como você falaria com alguém do time de BI & Analytics. Eu monto a consulta e mostro a fonte junto com a resposta.',
    'Diga o que você quer saber, com o período e o recorte. Eu vou ao banco e volto com o número e a consulta que o gerou.',
    'Posso comparar meses, redes, produtos e representantes. Quanto mais claro o recorte, mais direta a resposta.',
  ];

  const renderBoasVindas = () => {
    const convite = CONVITES[Math.floor(Math.random() * CONVITES.length)];
    $('#mensagens').innerHTML = `
      <div class="boas-vindas" id="boasVindas">
        <div class="boas-vindas-marca">${jarvis('jarvis--vivo', true)}</div>
        <h1>${esc(saudacao())}</h1>
        <p>${esc(convite)}</p>
        <div class="sugestoes">${SUGESTOES.map((s, i) => `
          <button class="sugestao" type="button" data-texto="${esc(s.texto)}" style="--tema-cor:${s.cor};animation-delay:${80 + i * 45}ms">
            <span class="sugestao-tema">${esc(s.tema)}</span>
            <span class="sugestao-texto">${esc(s.texto)}</span>
          </button>`).join('')}
        </div>
      </div>`;
  };

  // O cartão de cabeçalho saiu da tela; o título continua existindo na aba
  // do navegador e na lista de conversas, que é onde ele é útil.
  const definirCabecalho = (titulo, subtitulo) => {
    state.tituloConversa = titulo;
    state.subtituloConversa = subtitulo;
    document.title = `${titulo} · Jarvis · Ease Labs`;
  };

  const novaConversa = (historico = 'push') => {
    pararAguardo();
    state.conversaId = null;
    state.ultimoId = 0;
    renderBoasVindas();
    definirCabecalho('Nova conversa', 'Pergunte sobre prescrição, sell-out, estoque, PBM ou força de vendas.');
    renderLista();
    atualizarCabecalhoDoProjeto();
    mudarRota('/', historico);
    atualizarBotao();
    $('#campoPergunta').focus();
  };

  const abrirConversa = async (id, historico = 'push') => {
    pararAguardo();
    state.conversaId = id;
    state.ultimoId = 0;
    renderLista();
    mudarRota(rotaDaConversa(id), historico);
    const conversa = state.conversas.find((c) => c.id === id);
    definirCabecalho(conversa?.title || 'Conversa', 'Carregando as mensagens…');
    atualizarCabecalhoDoProjeto();
    $('#mensagens').innerHTML = '<div class="skeleton" style="height:64px;width:55%;margin-left:auto"></div><div class="skeleton" style="height:140px;width:80%"></div>';

    try {
      const { messages } = await api(`/api/conversations/${id}/messages/`);
      if (state.conversaId !== id) return;
      $('#mensagens').innerHTML = '';
      if (!messages.length) renderBoasVindas();
      messages.forEach(renderMensagem);
      state.ultimoId = messages.length ? messages[messages.length - 1].id : 0;
      atualizarSubtitulo(messages);
      rolarParaFim(false);

      // pergunta que ficou sem resposta (a página foi fechada no meio)
      const ultima = messages[messages.length - 1];
      if (ultima && ultima.direction === 'in' && ultima.status !== 'failed') {
        iniciarAguardo(ultima.id, ultima.text, new Date(ultima.created_at).getTime());
      }
    } catch (e) {
      if (state.conversaId !== id) return;
      $('#mensagens').innerHTML = '';
      definirCabecalho('Conversa', 'Não foi possível abrir esta conversa.');
      toast(e.message, true);
    }
    atualizarBotao();
  };

  const atualizarSubtitulo = (messages) => {
    const perguntas = messages.filter((m) => m.direction === 'in').length;
    const ultima = messages[messages.length - 1];
    const conversa = state.conversas.find((c) => c.id === state.conversaId);
    definirCabecalho(
      conversa?.title || messages.find((m) => m.direction === 'in')?.text?.slice(0, 60) || 'Conversa',
      perguntas
        ? `${perguntas} ${perguntas === 1 ? 'pergunta' : 'perguntas'}${ultima ? ` · última às ${fmtHora(ultima.created_at)}` : ''}`
        : 'Sem perguntas ainda',
    );
  };

  const rolarParaFim = (suave = true) => {
    const area = $('#mensagens');
    area.scrollTo({ top: area.scrollHeight, behavior: suave ? 'smooth' : 'auto' });
  };

  // ---------------------------------------------------------- mensagens
  const jaNaTela = (id) => !!document.querySelector(`#mensagens [data-id="${id}"]`);

  const renderMensagem = (m) => {
    if (m.id && jaNaTela(m.id)) return;
    $('#boasVindas')?.remove();
    const area = $('#mensagens');
    const el = m.direction === 'in' ? elementoPergunta(m) : elementoResposta(m);
    // a bolha "pensando" fica sempre por último
    const pensando = $('#pensando');
    if (pensando) area.insertBefore(el, pensando); else area.appendChild(el);
    // O Chart.js precisa do canvas já no documento para medir a área.
    desenharGraficosNovos(el);
    atualizarContinuacoes();
  };

  // Continuações só na resposta mais recente, e só enquanto ela é a última
  // coisa da conversa. Deixadas em toda resposta, numa conversa longa viravam
  // uma escada de botões antigos — e clicar numa delas respondia uma
  // pergunta que já não era a do momento. Quando o usuário pergunta de novo
  // (ou o "pensando" aparece), as da última somem também.
  const atualizarContinuacoes = () => {
    const mensagens = $$('#mensagens > .msg');
    const ultima = mensagens[mensagens.length - 1];
    $$('#mensagens .continuacoes').forEach((c) => { c.hidden = !(ultima && ultima.contains(c)); });
  };

  const elementoPergunta = (m) => {
    const el = document.createElement('div');
    el.className = 'msg msg-usuario';
    if (m.id) el.dataset.id = m.id;
    el.innerHTML = `<div class="bolha-usuario">${esc(m.text)}<span class="msg-hora">${esc(fmtHora(m.created_at || new Date().toISOString()))}</span></div>`;
    return el;
  };

  const elementoResposta = (m) => {
    const fonte = m.fonte || {};
    // Crédito da IA esgotado ou teto do mês: não é erro de quem perguntou e
    // perguntar de novo não adianta — aviso discreto, sem vermelho.
    const semCredito = ['sem_creditos_na_ia', 'teto_de_custo_do_mes'].includes(fonte.regra);
    const tipo = semCredito
      ? { classe: 'tipo-sem-dado', rotulo: 'Indisponível no momento', icone: 'info' }
      : (TIPO_RESPOSTA[fonte.decisao] || TIPO_RESPOSTA.answered);
    const semNarrativa = fonte.regra === 'resposta_sem_narrativa';

    const el = document.createElement('div');
    el.className = 'msg msg-ia';
    el.dataset.id = m.id;
    el.innerHTML = `
      <div class="ia-avatar" aria-hidden="true">${jarvis()}</div>
      <div class="msg-corpo">
      <article class="cartao-ia ${tipo.classe}">
        <div class="cartao-ia-corpo">
          ${tipo.rotulo ? `<div class="cartao-ia-rotulo">${ICONES[tipo.icone] || ''}${esc(tipo.rotulo)}</div>` : ''}
          ${semNarrativa ? '<div class="cartao-ia-rotulo" style="color:var(--gray-600)">' + ICONES.info + 'Resultado da consulta</div>' : ''}
          <div class="md">${semNarrativa ? tabelaCrua(m.text) : markdown(m.text)}</div>
        </div>
        ${fonte.decisao === 'failed' && !semCredito && m.in_reply_to ? `
          <div class="msg-erro-acao"><button class="btn btn-ghost" type="button" data-refazer="${m.in_reply_to}">Perguntar de novo</button></div>` : ''}
        ${blocoGrafico(fonte, m.id)}
        ${blocoFonte(fonte, m.id)}
      </article>
      ${blocoContinuacoes(fonte)}
      </div>`;
    if (fonte.grafico && fonte.dados) GRAFICOS.set(String(m.id), { grafico: fonte.grafico, dados: fonte.dados });
    return el;
  };

  // Continuações: a investigação raramente termina na primeira pergunta, e
  // digitar "e por rede?" de novo é atrito à toa.
  const blocoContinuacoes = (fonte) => {
    const itens = fonte.sugestoes || [];
    if (!itens.length) return '';
    return `
      <div class="continuacoes">
        ${itens.map((s) => `
          <button class="continuacao" type="button" data-texto="${esc(s)}">${esc(s)}</button>`).join('')}
      </div>`;
  };

  // ---------------------------------------------------------- gráfico
  // A IA só escolheu o tipo e as colunas (ADR-0020); os números vêm do
  // resultado da consulta, já conferido pelo orquestrador. Aqui é só desenho.
  const GRAFICOS = new Map();
  const DESENHADOS = new Map();   // canvas -> instância, para refazer ao trocar de tema
  const CORES = ['#5558D4', '#3FB868', '#F5A623'];
  // As cores do gráfico saem dos mesmos tokens da interface: assim ele
  // acompanha o tema sem ter uma paleta paralela para manter.
  const token = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

  const blocoGrafico = (fonte, id) => {
    if (!fonte.grafico || !fonte.dados) return '';
    return `
      <div class="grafico">
        ${fonte.grafico.titulo ? `<div class="grafico-titulo">${esc(fonte.grafico.titulo)}</div>` : ''}
        <div class="grafico-area"><canvas data-grafico="${id}" role="img"></canvas></div>
      </div>`;
  };

  const partesDeData = (valor) => {
    const texto = String(valor ?? '');
    const m = texto.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?/) || texto.match(/^(\d{4})(\d{2})$/);
    return m && MESES[Number(m[2]) - 1] ? { ano: m[1], mes: m[2], dia: m[3] } : null;
  };

  // "2026-08", 202608 e "2026-08-15" viram "ago/26" ou "15/ago"; o resto vai
  // como veio. `porMes` decide entre os dois: uma série mensal costuma vir do
  // banco como o primeiro dia de cada mês, e ler "01/jan" em vez de "jan/26"
  // faz parecer que o gráfico é de dias.
  const rotuloEixo = (valor, porMes) => {
    const d = partesDeData(valor);
    if (!d) return String(valor ?? '');
    const mes = MESES[Number(d.mes) - 1];
    return porMes || !d.dia ? `${mes}/${d.ano.slice(2)}` : `${d.dia}/${mes}`;
  };

  const ehTemporal = (valores) => valores.every((v) => partesDeData(v));
  const ehMensal = (valores) => valores.every((v) => {
    const d = partesDeData(v);
    return d && (!d.dia || d.dia === '01');
  });

  const fmtEixo = (v) => Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 2 });

  // A IA escolhe as colunas, não a unidade. O nome da coluna diz: é a
  // convenção das consultas de referência (`retencao_90d_pct`, `share_pct`).
  // Sem isto o eixo de retenção ia de 0 a 60 sem dizer de quê.
  const PERCENTUAL = /(^|_)(pct|perc|percent|percentual)(?=_|$)/i;
  const ehPercentual = (coluna) => PERCENTUAL.test(coluna);
  const fmtValor = (v, coluna) => fmtEixo(v) + (ehPercentual(coluna) ? '%' : '');
  // "retencao_90d_pct" vira "retencao 90d" na legenda: o % já está no número.
  const rotuloSerie = (coluna) => coluna.replace(PERCENTUAL, '').replace(/_+/g, ' ').trim();

  // Quantos meses pular entre um rótulo e outro, para caber na horizontal.
  // O passo acompanha o calendário (3 = jan/abr/jul/out, 6 = jan/jul): um
  // eixo que mostra "fev, mai, ago" parece aleatório.
  const LARGURA_POR_ROTULO = 56;
  const passoDoEixo = (pontos, largura) => {
    const cabem = Math.max(2, Math.floor(largura / LARGURA_POR_ROTULO));
    return [1, 2, 3, 6, 12].find((p) => Math.ceil(pontos / p) <= cabem) || 12;
  };

  // Quantas categorias cabem numa barra antes de virar parede de fiapo, e
  // quanta altura cada uma precisa para a barra ser legível.
  const MAX_CATEGORIAS = 14;
  const ALTURA_POR_BARRA = 28;

  const encurtar = (texto, n = 24) => (texto.length > n ? texto.slice(0, n - 1) + '…' : texto);

  const desenharGrafico = (canvas) => {
    const dado = GRAFICOS.get(canvas.dataset.grafico);
    if (!dado || typeof Chart === 'undefined') return;
    const { grafico, dados } = dado;
    const colunas = dados.columns || [];
    const ix = colunas.indexOf(grafico.x);
    const series = (grafico.series || []).filter((s) => colunas.includes(s));
    if (ix < 0 || !series.length) return;

    let linhas = (dados.rows || []).filter((l) => l[ix] !== null && l[ix] !== undefined);
    const porMes = ehMensal(linhas.map((l) => l[ix]));
    const temporal = ehTemporal(linhas.map((l) => l[ix]));
    // Mês fora de ordem numa linha do tempo desenha um ziguezague que não
    // existe: quando o eixo é temporal, a ordem é a do calendário.
    if (temporal) {
      linhas = [...linhas].sort((a, b) => String(a[ix]).localeCompare(String(b[ix])));
    }

    const linha = grafico.tipo === 'linha';
    const horizontal = grafico.tipo === 'barras_horizontais';
    const valorDe = (l, nome) => l[colunas.indexOf(nome)];
    const notas = [];

    // Zeros no começo de uma linha do tempo quase sempre são o programa
    // ainda começando, não um resultado. Medido em 2026-09-21: a retenção de
    // jun/23 era 0 de 3 compradores, e desenhava uma subida de 0 a 30% que
    // não aconteceu. Saem do desenho, com aviso — e continuam na planilha.
    if (linha && temporal) {
      const zerado = (l) => series.every((s) => {
        const v = valorDe(l, s);
        return v === null || v === undefined || Number(v) === 0;
      });
      let n = 0;
      while (n < linhas.length - 1 && zerado(linhas[n])) n += 1;
      if (n > 0) {
        const de = rotuloEixo(linhas[0][ix], porMes);
        const ate = rotuloEixo(linhas[n - 1][ix], porMes);
        notas.push(n === 1
          ? `${de} estava zerado e ficou fora do gráfico; continua na planilha.`
          : `De ${de} a ${ate} a série estava zerada e ficou fora do gráfico; continua na planilha.`);
        linhas = linhas.slice(n);
      }
    }
    // Trinta barras num cartão de conversa viram fiapos. Corta mantendo a
    // ordem que o SQL pediu — as primeiras são as que importam — e avisa.
    const total = linhas.length;
    // O corte pedido na conversa ("só os cinco primeiros") vence o automático.
    const corte = grafico.limite || (linha ? 0 : MAX_CATEGORIAS);
    if (corte && total > corte) linhas = linhas.slice(0, corte);
    const deFora = total - linhas.length;

    const area = canvas.parentElement;
    if (horizontal) area.style.height = `${linhas.length * ALTURA_POR_BARRA + 24}px`;
    if (deFora > 0) {
      notas.push(`Mostrando ${linhas.length} de ${fmtNum(total)} — a lista inteira está na tabela acima e na planilha.`);
    }
    if (notas.length && !area.nextElementSibling?.classList.contains('grafico-nota')) {
      const nota = document.createElement('div');
      nota.className = 'grafico-nota';
      nota.textContent = notas.join(' ');
      area.after(nota);
    }

    const umaSerie = series.length === 1;
    const emPercentual = series.every(ehPercentual);
    const passo = temporal && porMes && !horizontal ? passoDoEixo(linhas.length, area.clientWidth || 600) : 1;

    // Com uma série só, o número vai na ponta da barra e o eixo de valores
    // some: dois jeitos de ler o mesmo número é um a mais do que o preciso.
    const numeroNaBarra = {
      id: 'numeroNaBarra',
      afterDatasetsDraw(c) {
        if (linha || !umaSerie) return;
        const ctx = c.ctx;
        ctx.save();
        ctx.font = '600 11px Inter, sans-serif';
        ctx.fillStyle = token('--gray-600') || '#5E6484';
        c.getDatasetMeta(0).data.forEach((barra, i) => {
          const v = c.data.datasets[0].data[i];
          if (v === null || v === undefined) return;
          if (horizontal) {
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(fmtValor(v, series[0]), barra.x + 7, barra.y);
          } else {
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillText(fmtValor(v, series[0]), barra.x, barra.y - 6);
          }
        });
        ctx.restore();
      },
    };

    const fundoDoCartao = {
      id: 'fundoDoCartao',
      beforeDraw: (c) => {
        const ctx = c.canvas.getContext('2d');
        ctx.save();
        ctx.globalCompositeOperation = 'destination-over';
        ctx.fillStyle = token('--bg-card') || '#fff';
        ctx.fillRect(0, 0, c.width, c.height);
        ctx.restore();
      },
    };

    // Numa série mensal, só um mês a cada `passo` ganha rótulo, e sempre na
    // horizontal. 36 meses inclinados a 45° não se liam (2026-09-21).
    const mesmoMesDoPasso = (i) => {
      if (passo === 1) return true;
      const d = partesDeData(linhas[i]?.[ix]);
      return d ? (Number(d.mes) - 1) % passo === 0 : true;
    };
    const eixoDeCategoria = {
      grid: { display: false },
      border: { display: false },
      ticks: {
        font: { size: 11 }, color: token('--gray-600'), autoSkip: false,
        ...(temporal && porMes && !horizontal ? { maxRotation: 0, minRotation: 0 } : {}),
        callback(v) {
          return mesmoMesDoPasso(v) ? encurtar(String(this.getLabelForValue(v))) : '';
        },
      },
    };
    // Escondido quando o número já está na barra; na linha ele é necessário.
    const eixoDeValor = {
      display: linha || !umaSerie,
      beginAtZero: true,
      grace: '8%',
      grid: { color: token('--border-light'), drawTicks: false },
      border: { display: false },
      ticks: {
        font: { size: 11 }, color: token('--gray-600'), padding: 6,
        callback: (v) => fmtEixo(v) + (emPercentual ? '%' : ''),
      },
    };

    const semAnimacao = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const chart = new Chart(canvas, {
      type: linha ? 'line' : 'bar',
      data: {
        labels: linhas.map((l) => rotuloEixo(l[ix], porMes)),
        datasets: series.map((nome, n) => ({
          label: rotuloSerie(nome),
          data: linhas.map((l) => valorDe(l, nome)),
          borderColor: CORES[n % CORES.length],
          backgroundColor: linha ? 'transparent' : CORES[n % CORES.length],
          borderWidth: linha ? 2.5 : 0,
          borderRadius: linha ? 0 : 5,
          pointRadius: 3,
          pointBackgroundColor: CORES[n % CORES.length],
          tension: 0.25,
          barPercentage: 0.72,
          categoryPercentage: 0.86,
          maxBarThickness: 34,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: horizontal ? 'y' : 'x',
        animation: semAnimacao ? false : { duration: 500 },
        // espaço para o número na ponta da barra não encostar na borda
        layout: { padding: { right: horizontal && umaSerie ? 40 : 4, top: umaSerie && !linha ? 14 : 2 } },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          // Uma série só já está dita no título e na resposta.
          legend: {
            display: series.length > 1, position: 'bottom',
            labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, font: { size: 11 } },
          },
          tooltip: {
            backgroundColor: token('--toast-bg'), bodyColor: token('--toast-fg'),
            titleColor: token('--toast-fg'), padding: 10, cornerRadius: 8, displayColors: series.length > 1,
            callbacks: {
              label: (c) => ` ${c.dataset.label}: ${fmtValor(c.parsed[horizontal ? 'x' : 'y'], series[c.datasetIndex])}`,
            },
          },
        },
        scales: horizontal
          ? { x: eixoDeValor, y: eixoDeCategoria }
          : { x: eixoDeCategoria, y: eixoDeValor },
      },
      plugins: [fundoDoCartao, numeroNaBarra],
    });
    canvas.setAttribute('aria-label', `${grafico.titulo || 'Gráfico'} — ${linhas.length} pontos`);
    DESENHADOS.set(canvas, chart);
    return chart;
  };

  // Trocar o tema muda fundo, grade e rótulos: o jeito honesto é refazer o
  // desenho, não remendar cor por cor numa instância viva.
  const redesenharGraficos = () => {
    // A lista é copiada antes: `desenharGrafico` volta a registrar o canvas
    // no mesmo Map, e entrada nova durante um forEach é visitada de novo —
    // apagar e reinserir a mesma chave virava laço infinito, que travava a
    // página no clique do tema.
    const pares = [...DESENHADOS.entries()];
    DESENHADOS.clear();
    pares.forEach(([canvas, chart]) => {
      chart.destroy();
      const nota = canvas.parentElement?.nextElementSibling;
      if (nota?.classList.contains('grafico-nota')) nota.remove();
      desenharGrafico(canvas);
    });
  };

  const desenharGraficosNovos = (raiz) => {
    (raiz || document).querySelectorAll('canvas[data-grafico]:not([data-pronto])').forEach((c) => {
      c.dataset.pronto = '1';
      desenharGrafico(c);
    });
  };

  const blocoFonte = (fonte, id) => {
    const consulta = fonte.consulta;
    if (!consulta) return '';
    const equipe = state.usuario?.equipe;

    const meta = [
      ['Referência', consulta.referencia || 'nenhuma'],
      ['Linhas', fmtNum(consulta.linhas ?? 0) + (consulta.cortada ? ' (cortado)' : '')],
      ['Tempo no banco', consulta.duracao_ms != null ? `${fmtNum(consulta.duracao_ms)} ms` : '—'],
      ['Respondida', new Date(fonte.respondida_em).toLocaleString('pt-BR')],
      ['Tentativas', fonte.tentativas],
    ];
    if (equipe && fonte.custo_usd != null) {
      meta.push(['Custo', `US$ ${fonte.custo_usd.toLocaleString('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`]);
      meta.push(['Tokens', fmtNum(fonte.tokens || 0)]);
      meta.push(['Tempo total', fonte.tempo_ms ? `${(fonte.tempo_ms / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} s` : '—']);
    }

    return `
      <div class="fonte">
        <div class="fonte-barra">
          <button class="fonte-toggle" type="button" aria-expanded="false">${ICONES.banco}<span class="fonte-toggle-texto">Ver fonte e consulta</span><span class="chevron">${ICONES.chevron}</span></button>
          ${fonte.excel ? `<button class="fonte-excel${fonte.excel_pedido ? ' destaque' : ''}" type="button" data-excel="${id}">${ICONES.planilha}<span>Baixar Excel</span></button>` : ''}
        </div>
        <div class="fonte-detalhe">
          <div class="fonte-detalhe-inner">
            <div class="fonte-meta">${meta.map(([rotulo, valor]) => `
              <div><div class="fonte-meta-label">${esc(rotulo)}</div><div class="fonte-meta-valor">${esc(valor)}</div></div>`).join('')}
            </div>
            <div class="codigo">
              <button class="btn-copiar" type="button">${ICONES.copiar}Copiar</button>
              <pre><code>${realcarSql(consulta.sql)}</code></pre>
            </div>
          </div>
        </div>
      </div>`;
  };

  // abrir/fechar a fonte, copiar o SQL, refazer pergunta, usar sugestão
  $('#mensagens').addEventListener('click', async (ev) => {
    const toggle = ev.target.closest('.fonte-toggle');
    if (toggle) {
      const fonte = toggle.closest('.fonte');
      const aberta = fonte.classList.toggle('aberta');
      toggle.setAttribute('aria-expanded', String(aberta));
      toggle.querySelector('.fonte-toggle-texto').textContent = aberta ? 'Ocultar fonte e consulta' : 'Ver fonte e consulta';
      return;
    }
    const copiar = ev.target.closest('.btn-copiar');
    if (copiar) {
      const sql = copiar.parentElement.querySelector('pre').innerText;
      try { await navigator.clipboard.writeText(sql); toast('Consulta copiada.'); }
      catch { toast('Não consegui copiar; selecione o texto manualmente.', true); }
      return;
    }
    const refazer = ev.target.closest('[data-refazer]');
    if (refazer) {
      const original = document.querySelector(`#mensagens [data-id="${refazer.dataset.refazer}"] .bolha-usuario`);
      const texto = original ? original.firstChild.textContent : '';
      if (texto) enviar(texto);
      return;
    }
    const excel = ev.target.closest('[data-excel]');
    if (excel) { await baixarExcel(excel); return; }

    const sugestao = ev.target.closest('.sugestao, .continuacao');
    if (sugestao) enviar(sugestao.dataset.texto);
  });

  // A planilha roda a mesma consulta de novo no banco e pode demorar alguns
  // segundos numa lista grande: o botão precisa dizer que está trabalhando.
  const baixarExcel = async (botao) => {
    if (botao.disabled) return;
    const rotulo = botao.querySelector('span');
    const original = rotulo.textContent;
    botao.disabled = true;
    rotulo.textContent = 'Gerando planilha…';
    try {
      const r = await fetch(`/api/conversations/${state.conversaId}/messages/${botao.dataset.excel}/excel/`, {
        credentials: 'same-origin',
      });
      if (!r.ok) {
        const erro = await r.json().catch(() => ({}));
        throw new Error(erro.error || 'não consegui gerar a planilha');
      }
      const nome = (r.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = nome ? nome[1] : 'jarvis.xlsx';
      link.click();
      URL.revokeObjectURL(url);
      toast('Planilha baixada.');
    } catch (e) {
      toast(`Não consegui gerar a planilha: ${e.message}`, true);
    } finally {
      botao.disabled = false;
      rotulo.textContent = original;
    }
  };

  // ---------------------------------------------------------- "pensando"
  const mostrarPensando = () => {
    $('#pensando')?.remove();
    const el = document.createElement('div');
    el.className = 'msg msg-ia';
    el.id = 'pensando';
    el.innerHTML = `
      <article class="cartao-ia cartao-pensando">
        <div class="pensando">
          <span class="jarvis-espera" id="jarvisEspera">${jarvis('jarvis--pensando', true)}</span>
          <span class="pensando-texto" id="pensandoTexto"><strong>Pensando…</strong></span>
          <span class="pensando-tempo" id="pensandoTempo">0 s</span>
        </div>
        <div class="pensando-trilha"></div>
      </article>`;
    $('#mensagens').appendChild(el);
    atualizarContinuacoes();
    rolarParaFim();
  };

  const tickPensando = () => {
    if (!state.aguardando) return;
    const seg = Math.round((Date.now() - state.aguardando.inicio) / 1000);
    const tempo = $('#pensandoTempo');
    if (tempo) tempo.textContent = `${seg} s`;
    const texto = $('#pensandoTexto');
    if (texto && seg === 25 && state.aguardando.consultando) {
      texto.innerHTML = '<strong>Ainda consultando</strong> — perguntas que cruzam áreas levam um pouco mais.';
    }
  };

  // ---------------------------------------------------------- envio e polling
  const iniciarAguardo = (id, texto, inicio = Date.now()) => {
    state.aguardando = { id, texto, inicio, consultando: false };
    state.falhasSeguidas = 0;
    mostrarPensando();
    clearInterval(state.relogio);
    state.relogio = setInterval(tickPensando, 1000);
    tickPensando();
    agendarPoll(POLL_MS);
    atualizarBotao();
  };

  const pararAguardo = () => {
    clearTimeout(state.pollTimer);
    clearInterval(state.relogio);
    state.aguardando = null;
    $('#pensando')?.remove();
    atualizarContinuacoes();
    atualizarBotao();
  };

  const agendarPoll = (ms) => {
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(poll, ms);
  };

  const poll = async () => {
    const conversaId = state.conversaId;
    const aguardando = state.aguardando;
    if (!conversaId || !aguardando) return;

    try {
      // Inclui a própria pergunta pendente: a situação dela diz se a IA já
      // mandou a consulta ao banco (aí sim "consultando os dados").
      const depoisDe = Math.min(state.ultimoId, aguardando.id - 1);
      const { messages } = await api(`/api/conversations/${conversaId}/messages/?after=${depoisDe}`);
      if (state.conversaId !== conversaId || state.aguardando !== aguardando) return;
      state.falhasSeguidas = 0;
      const pendente = messages.find((m) => m.id === aguardando.id);
      if (pendente?.status === 'processing' && !aguardando.consultando) {
        aguardando.consultando = true;
        const texto = $('#pensandoTexto');
        if (texto) texto.innerHTML = '<strong>Consultando os dados</strong> — conferindo a consulta no banco.';
        $('#jarvisEspera .jarvis')?.classList.replace('jarvis--pensando', 'jarvis--consultando');
      }
      messages.forEach(renderMensagem);
      if (messages.length) {
        state.ultimoId = Math.max(state.ultimoId, ...messages.map((m) => m.id));
        const chegou = messages.find((m) => m.direction === 'out' && m.in_reply_to === aguardando.id);
        if (chegou) {
          pararAguardo();
          document.querySelector(`#mensagens [data-id="${chegou.id}"] .jarvis`)?.classList.add('jarvis--chegou');
          rolarParaFim();
          carregarConversas();
          const perguntas = document.querySelectorAll('#mensagens .msg-usuario').length;
          state.subtituloConversa = `${perguntas} ${perguntas === 1 ? 'pergunta' : 'perguntas'}`;
          return;
        }
      }
    } catch (e) {
      // Rede instável não pode derrubar a espera: tenta de novo, mais devagar.
      state.falhasSeguidas += 1;
      if (!state.usuario) return;
      if (state.falhasSeguidas === 3) toast('Conexão instável — ainda aguardando a resposta.', true);
    }

    if (Date.now() - aguardando.inicio > LIMITE_ESPERA_MS) {
      pararAguardo();
      const el = document.createElement('div');
      el.className = 'msg msg-ia';
      el.innerHTML = `
        <div class="ia-avatar" aria-hidden="true">${jarvis()}</div>
        <article class="cartao-ia tipo-falha">
          <div class="cartao-ia-corpo">
            <div class="cartao-ia-rotulo">${ICONES.alerta}Demorou mais que o normal</div>
            <div class="md"><p>A resposta ainda não chegou. Ela pode aparecer se você abrir esta conversa de novo daqui a pouco.</p></div>
          </div>
        </article>`;
      $('#mensagens').appendChild(el);
      rolarParaFim();
      return;
    }
    agendarPoll(POLL_MS * Math.min(1 + state.falhasSeguidas, 4));
  };

  const enviar = async (textoBruto) => {
    const texto = String(textoBruto || '').trim();
    if (!texto || state.aguardando) return;

    const campo = $('#campoPergunta');
    campo.value = '';
    ajustarCampo();
    atualizarBotao();

    // pergunta aparece na hora; o id real chega com a resposta do POST
    const provisoria = elementoPergunta({ text: texto, created_at: new Date().toISOString() });
    $('#boasVindas')?.remove();
    $('#mensagens').appendChild(provisoria);
    rolarParaFim();
    state.aguardando = { id: null, texto, inicio: Date.now() };
    atualizarBotao();

    try {
      if (!state.conversaId) {
        const conversa = await api('/api/conversations/', { method: 'POST', body: {} });
        state.conversaId = conversa.id;
        state.conversas.unshift(conversa);
        mudarRota(rotaDaConversa(conversa.id), 'push');
      }
      const r = await api(`/api/conversations/${state.conversaId}/messages/`, {
        method: 'POST',
        body: { client_message_id: novoId(), text: texto },
      });
      provisoria.dataset.id = r.message_id;
      definirCabecalho(state.conversas.find((c) => c.id === state.conversaId)?.title || texto.slice(0, 60), 'Consultando…');
      carregarConversas();
      iniciarAguardo(r.message_id, texto);
    } catch (e) {
      state.aguardando = null;
      provisoria.remove();
      campo.value = texto;
      ajustarCampo();
      atualizarBotao();
      toast(`Não consegui enviar: ${e.message}`, true);
    }
  };

  // ---------------------------------------------------------- composer
  const ajustarCampo = () => {
    const campo = $('#campoPergunta');
    campo.style.height = 'auto';
    campo.style.height = `${Math.min(campo.scrollHeight, 180)}px`;
  };

  const atualizarBotao = () => {
    const vazio = !$('#campoPergunta').value.trim();
    $('#btnEnviar').disabled = vazio || !!state.aguardando;
  };

  $('#campoPergunta').addEventListener('input', () => { ajustarCampo(); atualizarBotao(); });
  $('#campoPergunta').addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      enviar($('#campoPergunta').value);
    }
  });
  $('#formPergunta').addEventListener('submit', (ev) => { ev.preventDefault(); enviar($('#campoPergunta').value); });

  // ---------------------------------------------------------- login
  document.querySelectorAll('.btn-olho').forEach((btn) => {
    btn.addEventListener('click', () => {
      const campo = document.getElementById(btn.dataset.alvo);
      const mostrar = campo.type === 'password';
      campo.type = mostrar ? 'text' : 'password';
      btn.setAttribute('aria-pressed', String(mostrar));
      btn.setAttribute('aria-label', mostrar ? 'Ocultar senha' : 'Exibir senha');
    });
  });

  // ---------------------------------------------------------- login por código
  // Etapa 1: o e-mail @easelabs.com.br. Etapa 2: o código que chegou nele.
  // As regras de segurança (validade, tentativas, limites) estão no servidor,
  // em web/acesso.py; aqui é só a conversa com quem está entrando.
  const DOMINIO = '@easelabs.com.br';
  const login = { etapa: 'email', email: '', relogio: null };

  const erroDoLogin = (texto) => {
    const erro = $('#loginErro');
    erro.textContent = texto || '';
    erro.hidden = !texto;
  };

  const etapaDoLogin = (etapa) => {
    login.etapa = etapa;
    const noCodigo = etapa === 'codigo';
    $('#etapaEmail').hidden = noCodigo;
    $('#etapaCodigo').hidden = !noCodigo;
    $('#loginAcoes').hidden = !noCodigo;
    $('#btnLogin').textContent = noCodigo ? 'Entrar' : 'Enviar código';
    erroDoLogin('');
    if (noCodigo) {
      $('#loginEmailEnviado').textContent = login.email;
      $('#loginCodigo').value = '';
      setTimeout(() => $('#loginCodigo').focus(), 50);
    } else {
      clearInterval(login.relogio);
      setTimeout(() => $('#loginEmail').focus(), 50);
    }
  };

  // "Reenviar" fica travado pelo mesmo tempo que o servidor exige entre dois
  // pedidos, com a contagem à vista: sem ela, a pessoa clica, nada acontece,
  // e ela acha que quebrou.
  const travarReenvio = (segundos) => {
    const botao = $('#btnReenviar');
    clearInterval(login.relogio);
    let falta = Math.max(0, Math.round(segundos));
    const pintar = () => {
      botao.disabled = falta > 0;
      botao.textContent = falta > 0 ? `Reenviar em ${falta} s` : 'Reenviar código';
    };
    pintar();
    login.relogio = setInterval(() => {
      falta -= 1;
      pintar();
      if (falta <= 0) clearInterval(login.relogio);
    }, 1000);
  };

  const pedirCodigo = async () => {
    const r = await api('/api/auth/codigo/', { method: 'POST', body: { email: login.email } });
    login.email = r.email;
    etapaDoLogin('codigo');
    travarReenvio(r.reenviar_em || 60);
  };

  $('#formLogin').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const botao = $('#btnLogin');
    erroDoLogin('');

    if (login.etapa === 'email') {
      let email = $('#loginEmail').value.trim().toLowerCase();
      // Quem digita só "fernando.franco" quer dizer o e-mail da empresa.
      if (email && !email.includes('@')) email += DOMINIO;
      if (!email.endsWith(DOMINIO)) {
        erroDoLogin(`Use o seu e-mail ${DOMINIO}.`);
        $('#loginEmail').focus();
        return;
      }
      login.email = email;
      botao.disabled = true;
      botao.textContent = 'Enviando…';
      try {
        await pedirCodigo();
      } catch (e) {
        erroDoLogin(e.message);
        botao.textContent = 'Enviar código';
      } finally {
        botao.disabled = false;
      }
      return;
    }

    const codigo = $('#loginCodigo').value.replace(/\D/g, '');
    if (codigo.length !== 6) {
      erroDoLogin('O código tem 6 dígitos.');
      $('#loginCodigo').focus();
      return;
    }
    botao.disabled = true;
    botao.textContent = 'Entrando…';
    try {
      const r = await api('/api/auth/entrar/', { method: 'POST', body: { email: login.email, codigo } });
      clearInterval(login.relogio);
      $('#loginCodigo').value = '';
      entrar(r.usuario);
    } catch (e) {
      erroDoLogin(e.message);
      $('#loginCodigo').select();
    } finally {
      botao.disabled = false;
      botao.textContent = 'Entrar';
    }
  });

  // O código colado com espaço ("123 456") ou digitado com o teclado do
  // celular entra limpo; com 6 dígitos, entra sozinho.
  $('#loginCodigo').addEventListener('input', (ev) => {
    const limpo = ev.target.value.replace(/\D/g, '').slice(0, 6);
    if (ev.target.value !== limpo) ev.target.value = limpo;
    if (limpo.length === 6 && !$('#btnLogin').disabled) $('#formLogin').requestSubmit();
  });

  $('#btnReenviar').addEventListener('click', async () => {
    erroDoLogin('');
    $('#btnReenviar').disabled = true;
    try {
      await pedirCodigo();
      toast('Enviamos um novo código. O anterior deixou de valer.');
    } catch (e) {
      erroDoLogin(e.message);
      travarReenvio(e.dados?.reenviar_em || 30);
    }
  });

  $('#btnOutroEmail').addEventListener('click', () => etapaDoLogin('email'));

  // ---------------------------------------------------------- menu e gaveta
  const fecharDropdown = () => {
    $('#topbarUser').classList.remove('open');
    $('#userTrigger').setAttribute('aria-expanded', 'false');
  };
  $('#userTrigger').addEventListener('click', (ev) => {
    ev.stopPropagation();
    const aberto = $('#topbarUser').classList.toggle('open');
    $('#userTrigger').setAttribute('aria-expanded', String(aberto));
  });
  document.addEventListener('click', (ev) => { if (!ev.target.closest('#topbarUser')) fecharDropdown(); });

  const abrirGaveta = () => {
    $('#sidebar').classList.add('aberta');
    $('#sidebarVeu').hidden = false;
    $('#btnMenu').setAttribute('aria-expanded', 'true');
  };
  const fecharGaveta = () => {
    $('#sidebar').classList.remove('aberta');
    $('#sidebarVeu').hidden = true;
    $('#btnMenu').setAttribute('aria-expanded', 'false');
  };
  $('#btnMenu').addEventListener('click', () => ($('#sidebar').classList.contains('aberta') ? fecharGaveta() : abrirGaveta()));
  $('#sidebarVeu').addEventListener('click', fecharGaveta);
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    if (!$('#modal').hidden) { fecharModal(); return; }
    fecharMenu(); fecharDropdown(); fecharGaveta();
  });

  const irParaNova = () => { fecharDropdown(); fecharGaveta(); novaConversa('push'); };
  $('#btnNovaConversa').addEventListener('click', irParaNova);
  $('#btnNovaConversaMenu').addEventListener('click', irParaNova);
  $('#btnLogoHome').addEventListener('click', irParaNova);

  // ---------------------------------------------------------- busca
  // Espera a pessoa parar de digitar: uma consulta por tecla faria a lista
  // piscar e o servidor trabalhar à toa.
  const buscar = (termo) => {
    state.busca = termo.trim();
    $('#btnLimparBusca').hidden = !state.busca;
    clearTimeout(state.buscaTimer);
    state.buscaTimer = setTimeout(carregarConversas, 250);
  };

  $('#campoBusca').addEventListener('input', (ev) => buscar(ev.target.value));
  $('#campoBusca').addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') { ev.target.value = ''; buscar(''); }
  });
  $('#btnLimparBusca').addEventListener('click', () => {
    $('#campoBusca').value = '';
    buscar('');
    $('#campoBusca').focus();
  });

  // ---------------------------------------------------------- tema
  const TEMA = 'jarvis:tema';
  const preferenciaDoSistema = window.matchMedia('(prefers-color-scheme: dark)');

  const aplicarTema = (tema, guardar = true) => {
    const escuro = tema === 'escuro' || (tema === 'sistema' && preferenciaDoSistema.matches);
    document.documentElement.dataset.tema = tema;
    document.documentElement.dataset.escuro = escuro ? '1' : '0';
    $$('#seletorTema .tema-opcao').forEach((b) => b.classList.toggle('ativa', b.dataset.tema === tema));
    if (guardar) { try { localStorage.setItem(TEMA, tema); } catch { /* navegação privada */ } }
    redesenharGraficos();
  };

  const temaEscolhido = () => document.documentElement.dataset.tema || 'sistema';
  aplicarTema(temaEscolhido(), false);

  $('#seletorTema').addEventListener('click', (ev) => {
    const opcao = ev.target.closest('.tema-opcao');
    if (opcao) aplicarTema(opcao.dataset.tema);
  });
  // Quem escolheu "sistema" acompanha o computador mudando de dia para noite.
  preferenciaDoSistema.addEventListener('change', () => {
    if (temaEscolhido() === 'sistema') aplicarTema('sistema', false);
  });

  // ---------------------------------------------------------- sidebar
  const RECOLHIDA = 'jarvis:sidebar-recolhida';
  const recolher = (sim) => {
    $('#panel-chat').classList.toggle('recolhida', sim);
    $('#btnRecolher').setAttribute('aria-label', sim ? 'Expandir a lista' : 'Recolher a lista');
    try { localStorage.setItem(RECOLHIDA, sim ? '1' : '0'); } catch { /* navegação privada */ }
  };
  try { if (localStorage.getItem(RECOLHIDA) === '1') recolher(true); } catch { /* idem */ }
  $('#btnRecolher').addEventListener('click', () => recolher(!$('#panel-chat').classList.contains('recolhida')));
  document.addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'b') {
      ev.preventDefault();
      recolher(!$('#panel-chat').classList.contains('recolhida'));
    }
  });

  $('#btnSair').addEventListener('click', async () => {
    fecharDropdown();
    try { await api('/api/auth/logout/', { method: 'POST' }); } catch { /* sai mesmo assim */ }
    state.conversas = [];
    state.projetos = [];
    state.conversaId = null;
    history.replaceState({}, '', '/');
    mostrarLogin();
  });

  // No celular o exemplo longo quebra em duas linhas num campo de uma linha.
  const telaEstreita = window.matchMedia('(max-width: 640px)');
  const ajustarExemplo = () => {
    $('#campoPergunta').placeholder = telaEstreita.matches
      ? 'Pergunte sobre os dados…'
      : 'Ex.: Quantas unidades a Pague Menos dispensou por mês em 2026?';
  };
  telaEstreita.addEventListener('change', ajustarExemplo);
  ajustarExemplo();

  // ---------------------------------------------------------- início
  (async () => {
    try {
      const sessao = await api('/api/auth/sessao/');
      if (sessao.autenticado) entrar(sessao.usuario);
      else mostrarLogin();
    } catch {
      mostrarLogin();
      toast('Não consegui falar com o servidor. Tente recarregar a página.', true);
    }
  })();
})();
