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
    conversaId: null,
    ultimoId: 0,
    aguardando: null,     // { id, inicio, texto } — pergunta sem resposta ainda
    anexo: null,          // etiqueta do anexo já validado no servidor (ADR-0024)
    anexoEnviando: false,
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
    // "cartao-aberto": a resposta que deu certo não usa moldura nem avatar.
    answered:     { classe: 'cartao-aberto',        rotulo: '' },
    conversation: { classe: 'cartao-aberto',        rotulo: '' },
    empty_result: { classe: 'tipo-sem-dado',        rotulo: 'Sem resultado',         icone: 'vazio' },
    clarify:      { classe: 'tipo-esclarecimento',  rotulo: 'Preciso de um detalhe', icone: 'pergunta' },
    unknown:      { classe: 'tipo-sem-dado',        rotulo: 'Dado não disponível',   icone: 'info' },
    out_of_scope: { classe: 'tipo-sem-dado',        rotulo: 'Fora do que eu faço',   icone: 'info' },
    failed:       { classe: 'tipo-falha',           rotulo: 'Não consegui responder', icone: 'alerta' },
    // A única resposta que não passou pelo banco (ADR-0024): o rótulo diz isso.
    image_reading: { classe: 'cartao-aberto',       rotulo: 'Leitura da imagem',     icone: 'imagem' },
  };

  const ICONES = {
    util: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10v12"/><path d="M15 5.88L14 10h5.83a2 2 0 011.92 2.56l-2.33 8A2 2 0 0117.5 22H4a2 2 0 01-2-2v-8a2 2 0 012-2h2.76a2 2 0 001.79-1.11L12 2a3.13 3.13 0 013 3.88z"/></svg>',
    errada: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 14V2"/><path d="M9 18.12L10 14H4.17a2 2 0 01-1.92-2.56l2.33-8A2 2 0 016.5 2H20a2 2 0 012 2v8a2 2 0 01-2 2h-2.76a2 2 0 00-1.79 1.11L12 22a3.13 3.13 0 01-3-3.88z"/></svg>',
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
    imagem: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>',
    tabela: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/></svg>',
    fechar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    lixeira: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>',
    lista: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>',
    relogio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    planilha: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/></svg>',
    // Folha com grade, para o ladrilho verde do anexo de planilha.
    xlsx: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h8M12 13v4"/></svg>',
  };

  // ---------------------------------------------------------- Jarvis
  // O mascote é redesenhado em SVG (as medidas saíram do PNG original em
  // docs/brand/) porque assim ele é nítido em qualquer tamanho, pesa ~1 KB e
  // cada parte pode ser animada pelo CSS: um GIF não faria nada disso.
  // A armadura (último quadro do passeio): o desenho da armadura à Homem de
  // Ferro, nas cores da Ease Labs — casco índigo, prata no lugar do dourado,
  // luzes no verde da marca (pedido do Rubens, 2026-09-25). A viseira e o
  // olho verde continuam os do app. As peças só existem no Jarvis do passeio
  // e só aparecem com a classe `jarvis--armadura`; a faixa de luz
  // (`j-arm-scan`) desce pelo corpo e a armadura surge por onde ela passa.
  const ARMADURA_ATRAS = `
      <defs>
        <linearGradient id="jvArmCasco" x1="0.15" y1="0" x2="0.85" y2="1">
          <stop offset="0" stop-color="#9A9EFB"/><stop offset="0.45" stop-color="#5558D4"/><stop offset="1" stop-color="#2E2F8F"/>
        </linearGradient>
        <linearGradient id="jvArmPrata" x1="0.2" y1="0" x2="0.8" y2="1">
          <stop offset="0" stop-color="#E4E5FF"/><stop offset="0.45" stop-color="#A5A8F3"/><stop offset="1" stop-color="#6F73E6"/>
        </linearGradient>
        <radialGradient id="jvArmNucleo" cx="50%" cy="50%" r="50%">
          <stop offset="0" stop-color="#FFFFFF"/><stop offset="0.5" stop-color="#C8F7C0"/><stop offset="1" stop-color="#5FBF5A"/>
        </radialGradient>
        <linearGradient id="jvArmJato" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#FFFFFF"/><stop offset="0.35" stop-color="#B8F5AE"/><stop offset="1" stop-color="#6ECC64" stop-opacity="0"/>
        </linearGradient>
        <clipPath id="jvArmVarredura" clipPathUnits="userSpaceOnUse">
          <rect class="j-arm-varredura" x="0" y="0" width="64" height="70"/>
        </clipPath>
      </defs>
      <g class="j-armadura j-arm-propulsores">
        <rect class="j-arm-bota" x="23.6" y="48.8" width="5.8" height="3.4" rx="1.6"/>
        <rect class="j-arm-bota" x="34.6" y="48.8" width="5.8" height="3.4" rx="1.6"/>
        <path class="j-arm-chama" d="M 24.2 51.6 Q 26.5 50.9 28.8 51.6 Q 28 58.6 26.5 63.8 Q 25 58.6 24.2 51.6 Z"/>
        <path class="j-arm-chama" d="M 35.2 51.6 Q 37.5 50.9 39.8 51.6 Q 39 58.6 37.5 63.8 Q 36 58.6 35.2 51.6 Z"/>
      </g>
      <g class="j-armadura j-arm-braco j-arm-braco--punho">
        <path class="j-arm-contorno" d="M 21.5 39.6 Q 16 40.2 12.4 44.4"/>
        <path class="j-arm-membro" d="M 21.5 39.6 Q 16 40.2 12.4 44.4"/>
        <path class="j-arm-faixa" d="M 16.2 38.6 L 17.4 42.2"/>
        <circle class="j-arm-casca" cx="11.4" cy="45.6" r="3.9"/>
        <path class="j-arm-faixa-fina" d="M 8.6 44.2 Q 11.4 42.6 14.2 44.2"/>
        <path class="j-arm-junta" d="M 8.6 46.4 Q 11.4 45.2 14.2 46.4"/>
        <path class="j-arm-junta" d="M 11.4 42.2 L 11.4 49"/>
      </g>
      <g class="j-armadura j-arm-braco j-arm-braco--aceno">
        <path class="j-arm-contorno" d="M 42.6 38.4 Q 48.6 37.2 51.2 32"/>
        <path class="j-arm-membro" d="M 42.6 38.4 Q 48.6 37.2 51.2 32"/>
        <path class="j-arm-faixa" d="M 48.8 38 L 47.2 34.4"/>
        <g class="j-arm-mao">
          <rect class="j-arm-casca" x="47.6" y="21.2" width="2" height="5.2" rx="1" transform="rotate(-18 48.6 23.8)"/>
          <rect class="j-arm-casca" x="50.3" y="20" width="2" height="5.8" rx="1" transform="rotate(-4 51.3 22.9)"/>
          <rect class="j-arm-casca" x="53" y="20.6" width="2" height="5.4" rx="1" transform="rotate(10 54 23.3)"/>
          <rect class="j-arm-casca" x="55.2" y="23.4" width="1.9" height="4.4" rx="0.95" transform="rotate(34 56.1 25.6)"/>
          <circle class="j-arm-casca" cx="51.6" cy="28.4" r="3.8"/>
          <circle class="j-arm-repulsor" cx="51.6" cy="28.4" r="2.2"/>
          <circle cx="51.6" cy="28.4" r="1" fill="#FFFFFF"/>
        </g>
      </g>`;
  const ARMADURA_FRENTE = `
      <g class="j-armadura j-arm-casco">
        <rect x="17" y="11.9" width="30" height="40.3" rx="15" fill="url(#jvArmCasco)"/>
        <path class="j-arm-ouro" d="M 19.4 37 C 19.8 42.6 21.8 46.8 25 49.6 L 26.8 47.8 C 24.2 45.2 22.6 41.6 22.3 37 Z"/>
        <path class="j-arm-ouro" d="M 44.6 37 C 44.2 42.6 42.2 46.8 39 49.6 L 37.2 47.8 C 39.8 45.2 41.4 41.6 41.7 37 Z"/>
        <path class="j-arm-ouro" d="M 24.6 42.2 L 28.6 44.8 L 29.2 43.4 L 25.6 41 Z"/>
        <path class="j-arm-ouro" d="M 39.4 42.2 L 35.4 44.8 L 34.8 43.4 L 38.4 41 Z"/>
        <path class="j-arm-ouro" d="M 25.4 50.2 Q 32 52.3 38.6 50.2 L 38 49 Q 32 50.8 26 49 Z"/>
        <path class="j-arm-junta" d="M 22.6 16.4 Q 32 11.6 41.4 16.4"/>
        <ellipse cx="24" cy="17.4" rx="3.4" ry="1.7" fill="#FFFFFF" opacity="0.3" transform="rotate(-32 24 17.4)"/>
      </g>
      <g class="j-armadura j-arm-mascara">
        <path class="j-arm-ouro" d="M 30 15.8 L 31 12.2 L 33 12.2 L 34 15.8 Z"/>
        <path class="j-arm-ouro j-arm-rosto" d="M 19.8 24.2 C 19.8 18.6 24.8 15.6 32 15.6 C 39.2 15.6 44.2 18.6 44.2 24.2 L 44.2 31.8
          C 44.2 36.6 40.6 40 36 40.6 L 28 40.6 C 23.4 40 19.8 36.6 19.8 31.8 Z"/>
        <path class="j-arm-traco" d="M 27.2 18.2 L 32 19.4 L 36.8 18.2"/>
        <path class="j-arm-traco" d="M 22.8 32.2 L 25.8 38.4"/>
        <path class="j-arm-traco" d="M 41.2 32.2 L 38.2 38.4"/>
        <path class="j-arm-traco" d="M 29.2 36.4 L 30.9 36.4 M 33.1 36.4 L 34.8 36.4"/>
        <path class="j-arm-brilho" d="M 25.4 17.4 C 28 16.6 36 16.6 38.6 17.4"/>
        <circle class="j-arm-fone" cx="18.2" cy="27.2" r="3.1"/>
        <circle class="j-arm-fone-luz" cx="18.2" cy="27.2" r="1.6"/>
        <circle class="j-arm-fone" cx="45.8" cy="27.2" r="3.1"/>
        <circle class="j-arm-fone-luz" cx="45.8" cy="27.2" r="1.6"/>
      </g>`;
  const ARMADURA_REATOR = `
      <path class="j-armadura j-arm-piscada" d="M 24.4 27.6 Q 26.7 24.9 29 27.6"/>
      <g class="j-armadura j-arm-reator">
        <circle class="j-arm-halo" cx="32" cy="46" r="5.4"/>
        <circle cx="32" cy="46" r="3.6" fill="#1E1F5C" stroke="#A5A8F3" stroke-width="0.8"/>
        <circle class="j-arm-nucleo" cx="32" cy="46" r="2.6" fill="url(#jvArmNucleo)"/>
        <circle cx="32" cy="46" r="2.6" fill="none" stroke="#FFFFFF" stroke-width="0.35" stroke-dasharray="1.1 0.6"/>
        <circle cx="32" cy="46" r="1.2" fill="#FFFFFF"/>
      </g>
      <rect class="j-armadura j-arm-scan" x="6" y="-2" width="52" height="1.4" rx="0.7"/>`;

  const jarvis = (classe = '', orbita = false, armadura = false) => `
    <svg class="jarvis ${classe}" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      ${armadura ? ARMADURA_ATRAS : ''}
      ${orbita ? `
      <g class="j-orbita-g">
        <path class="j-orbita j-orbita--tras" d="M 7,40 A 25,8 0 0,0 57,40"/>
        <circle class="j-satelite j-satelite--tras" r="2.2"/>
      </g>` : ''}
      <rect class="j-corpo" x="17" y="11.9" width="30" height="40.3" rx="15"/>
      ${armadura ? ARMADURA_FRENTE : ''}
      <rect class="j-viseira" x="18.4" y="21.6" width="27.2" height="9.8" rx="4.9"/>
      <circle class="j-olho" cx="40" cy="26.5" r="2.4"/>
      ${armadura ? ARMADURA_REATOR : ''}
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
    pararPalco();
    state.usuario = usuario;
    $('#panel-login').hidden = true;
    $('#panel-chat').hidden = false;
    $('#headerUserAvatar').textContent = usuario.iniciais;
    $('#headerUserName').textContent = usuario.nome;
    $('#menuUserName').textContent = usuario.nome;
    $('#menuUserSub').textContent = usuario.email || `@${usuario.usuario}`;
    // Quem veio do Admin (/admin/login redireciona para cá com ?proximo=)
    // volta para ele depois de entrar. Só caminho interno do Admin: um
    // `proximo` apontando para fora seria um redirecionamento aberto.
    const proximo = new URLSearchParams(location.search).get('proximo');
    if (proximo && /^\/admin\/[\w\-/]*$/.test(proximo)) { location.href = proximo; return; }
    carregarConversas();
    irParaRota(location.pathname, 'replace');
    // Primeiro login desta pessoa: a apresentação é a primeira coisa que
    // acontece, antes de a conversa entrar em cena. Quem chega sem nunca ter
    // visto o Jarvis precisa saber o que ele faz antes de olhar para um campo
    // de pergunta em branco.
    if (usuario.passeio_pendente) setTimeout(() => abrirPasseio(), 320);
    avisarDaCota();
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
  // A seção "Arquivadas" é uma pasta como as outras, e lembrar se ela está
  // aberta é conforto de quem usa, igual às de projeto. O identificador é
  // texto justamente para nunca colidir com o id de um projeto.
  const ARQUIVO = 'arquivadas';
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
        <span class="conversa-titulo">${c.canal === 'whatsapp' ? '<span class="conversa-canal" title="Conversa do WhatsApp">WhatsApp</span>' : ''}${esc(c.title || 'Nova conversa')}</span>
      </button>
      <button class="item-acoes" type="button" data-menu-conversa="${c.id}" aria-label="Opções da conversa" aria-haspopup="true">${ICONES.mais}</button>
    </div>`;

  let listaEstreou = false;

  const renderLista = () => {
    const lista = $('#listaConversas');
    // Só a primeira pintura anima; as seguintes trocam o conteúdo em silêncio.
    lista.classList.toggle('estreando', !listaEstreou);
    listaEstreou = true;
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
        <div class="lista-secao pasta${pastasAbertas.has(ARQUIVO) ? ' aberta' : ''}" data-arquivo="1">
          <button class="secao-cabeca secao-arquivo" type="button" data-pasta="${ARQUIVO}" aria-expanded="${pastasAbertas.has(ARQUIVO)}">
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

    const pasta = ev.target.closest('[data-pasta]');
    if (pasta) {
      const bruto = pasta.dataset.pasta;
      const id = bruto === ARQUIVO ? ARQUIVO : Number(bruto);
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

    // Tirar do arquivo é arrastar para fora dele — para uma pasta ou para
    // "Recentes", tanto faz. O arquivo é um lugar, e sair dele é o gesto
    // natural de voltar a trabalhar na conversa.
    const voltouDoArquivo = conversa.status === 'archived'
      && !ev.target.closest('[data-arquivo]');

    const ordem = state.conversas.filter((c) => c.id !== id);
    let destino;
    if (sobre !== null) {
      destino = ordem.findIndex((c) => c.id === sobre) + (depois ? 1 : 0);
    } else if (projeto !== projetoAntes || voltouDoArquivo) {
      // Largou no corpo da pasta (ou na lista solta), sem mirar ninguém:
      // entra no topo do grupo de destino. Uma conversa que acabou de sair do
      // arquivo entra aqui mesmo sem trocar de pasta — senão a soltura em
      // "Recentes", onde a pasta continua a mesma (nenhuma), não faria nada.
      const i = ordem.findIndex((c) => (c.project ?? null) === projeto && c.status !== 'archived');
      destino = i === -1 ? ordem.length : i;
    } else {
      return;  // soltou onde já estava
    }

    // Otimista: a lista se mexe na hora e o servidor confirma depois. Se
    // falhar, recarrega — melhor voltar ao que o banco tem do que deixar a
    // tela mentindo.
    conversa.project = projeto;
    if (voltouDoArquivo) conversa.status = 'open';
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
      if (voltouDoArquivo) {
        await api(`/api/conversations/${id}/`, { method: 'PATCH', body: { status: 'open' } });
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

  // O menu é `position: fixed`: ele não anda junto com a lista sozinho.
  const posicionarMenu = () => {
    if (!ancoraDoMenu || menu.hidden) return;
    const r = ancoraDoMenu.getBoundingClientRect();
    const largura = menu.offsetWidth;
    const altura = menu.offsetHeight;
    const abaixo = r.bottom + 6 + altura < window.innerHeight;
    menu.style.top = `${abaixo ? r.bottom + 6 : Math.max(8, r.top - altura - 6)}px`;
    menu.style.left = `${Math.max(8, Math.min(r.right - largura, window.innerWidth - largura - 8))}px`;
  };

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
    posicionarMenu();
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
  // Rolar a lista reposiciona o menu em vez de fechá-lo: fechar era o que
  // impedia o menu dos arquivados de abrir.
  $('#listaConversas').addEventListener('scroll', posicionarMenu, true);

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
    // Cada diálogo nasce na largura padrão; quem precisar de mais pede depois.
    modal.querySelector('.modal').classList.remove('largo');
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
    const voltou = await desarquivarAoMover(c, projetoId);
    if (projetoId) { pastasAbertas.add(projetoId); salvarPastas(); }
    await carregarConversas();
    return voltou;
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
        const voltou = await moverPara(c, alvo);
        if (voltou) toast('Conversa movida para o projeto e tirada do arquivo.');
        else toast(alvo ? 'Conversa movida para o projeto.' : 'Conversa tirada do projeto.');
      } catch (e) { toast(e.message, true); }
    };
  };

  // Mover uma conversa arquivada para um projeto é voltar a trabalhar nela.
  // Sem isto o arquivo engolia a ação: a pasta só mostra conversas ativas, a
  // conversa continuava em "Arquivadas", e parecia que mover não funcionava.
  const desarquivarAoMover = async (c, projeto) => {
    if (!projeto || c.status !== 'archived') return false;
    await api(`/api/conversations/${c.id}/`, { method: 'PATCH', body: { status: 'open' } });
    return true;
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

  // Convite para o passeio: quem ainda não viu encontra o ponto verde no
  // mascote da lateral e uma linha na tela de boas-vindas. Nada abre sozinho
  // — empurrar a apresentação na cara de quem chegou para perguntar é o
  // jeito mais rápido de ela ser fechada sem ler. E o convite tem prazo:
  // quem ignorou seis vezes já decidiu, e a linha vira ruído.
  const CHAVE_PASSEIO = 'jarvis:passeio-visto';
  const CHAVE_CONVITES = 'jarvis:passeio-convites';
  // Quem fecha no meio volta de onde parou; o passeio só conta como visto
  // quando chega ao fim.
  const CHAVE_QUADRO = 'jarvis:passeio-quadro';
  const MAX_CONVITES = 6;
  const lerChave = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
  const gravarChave = (k, v) => { try { localStorage.setItem(k, v); } catch { /* navegação privada */ } };
  const convitesFeitos = () => Number(lerChave(CHAVE_CONVITES) || 0);
  const deveConvidar = () => !lerChave(CHAVE_PASSEIO) && convitesFeitos() < MAX_CONVITES;
  // O ponto verde na lateral saiu em 2026-09-24: parecia "online". O convite
  // fica só no aceno do mascote das boas-vindas.
  const convidarParaPasseio = () => {};

  const renderBoasVindas = () => {
    const convite = CONVITES[Math.floor(Math.random() * CONVITES.length)];
    const convidar = deveConvidar();
    const parouNo = Number(lerChave(CHAVE_QUADRO) || 0);
    if (convidar) gravarChave(CHAVE_CONVITES, String(convitesFeitos() + 1));
    $('#mensagens').innerHTML = `
      <div class="boas-vindas${convidar ? ' boas-vindas--convite' : ''}" id="boasVindas">
        <button class="boas-vindas-marca" type="button" data-passeio title="Conheça o Jarvis" aria-label="Conheça o Jarvis">${jarvis('jarvis--vivo', true)}</button>
        <h1>${esc(saudacao())}</h1>
        <p>${esc(convite)}</p>
        ${convidar ? `
        <button class="convite-passeio" type="button" data-passeio>
          <span class="convite-passeio-ponto" aria-hidden="true"></span>
          <span>${parouNo
            ? `Você parou no quadro ${parouNo + 1}. <strong>Continuar o passeio</strong>`
            : 'Primeira vez por aqui? <strong>Conheça o Jarvis em 1 minuto</strong>'}</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
        </button>` : ''}
        <div class="sugestoes">${SUGESTOES.map((s, i) => `
          <button class="sugestao" type="button" data-texto="${esc(s.texto)}" style="--tema-cor:${s.cor};animation-delay:${80 + i * 45}ms">
            <span class="sugestao-tema">${esc(s.tema)}</span>
            <span class="sugestao-texto">${esc(s.texto)}</span>
          </button>`).join('')}
        </div>
      </div>`;
    convidarParaPasseio();
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
      $('#mensagens').style.paddingBottom = '';
      rolarParaFim(false);

      // pergunta que ficou sem resposta (a página foi fechada no meio).
      // Interrompida não conta: ninguém está mais trabalhando nela.
      const ultima = messages[messages.length - 1];
      if (ultima && ultima.direction === 'in' && !['failed', 'cancelled'].includes(ultima.status)) {
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

  // A pergunta enviada sobe para o alto e a resposta nasce embaixo dela, como
  // no ChatGPT e no Claude. Sem isso, numa conversa curta não há o que rolar:
  // a pergunta simplesmente aparece no meio da tela e nada se move.
  //
  // O que permite a subida é um respiro embaixo — aqui, o `padding-bottom` da
  // própria área, e não um elemento vazio que teria de ser mantido sempre por
  // último entre as mensagens. Ele é recalculado a cada passo: encolhe
  // sozinho quando a resposta é longa e enche a tela.
  const RESPIRO = 12;  // o padding que a área já tinha embaixo
  const FOLGA_DO_TOPO = 6;

  const subirAPergunta = (pergunta) => {
    const area = $('#mensagens');
    if (!pergunta || !area.contains(pergunta)) return rolarParaFim();
    area.style.paddingBottom = `${RESPIRO}px`;  // mede a conversa sem o respiro
    const topo = pergunta.getBoundingClientRect().top
      - area.getBoundingClientRect().top + area.scrollTop;
    const abaixo = area.scrollHeight - RESPIRO - topo;
    area.style.paddingBottom = `${Math.max(RESPIRO, area.clientHeight - abaixo - 24)}px`;
    area.scrollTo({ top: Math.max(0, topo - FOLGA_DO_TOPO), behavior: 'smooth' });
  };

  const ultimaPergunta = () => {
    const perguntas = $$('#mensagens > .msg-usuario');
    return perguntas[perguntas.length - 1];
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
    // A imagem vira um quadradinho, como nas outras IAs: clicar abre no
    // tamanho real. A planilha vira uma ficha com o verde do Excel — o
    // arquivo foi descartado (ADR-0024), fica a lembrança dele.
    // A ficha vem numa linha só dela: ela é `inline-flex` para caber no nome
    // do arquivo, e sem a linha a pergunta colaria ao lado.
    //
    // Tudo numa linha de código também, sem quebra nem recuo: o balão é
    // `white-space: pre-wrap` (a pergunta preserva os parágrafos de quem
    // escreveu), então cada quebra de linha do HTML virava espaço em branco
    // desenhado na tela — era daí o vão em cima e embaixo da ficha.
    const ficha = (icone, nome, tipo, variante = '') =>
      `<div><div class="bolha-anexo"><span class="bolha-anexo-ladrilho ${variante}">${icone}</span>`
      + `<span class="bolha-anexo-texto"><span class="bolha-anexo-nome">${esc(nome)}</span>`
      + `<span class="bolha-anexo-tipo">${esc(tipo)}</span></span></div></div>`;
    let anexo = '';
    if (m.anexo?.tipo === 'imagem') {
      const src = m.anexo.miniatura || m.anexo.previa;
      // No visor entra a melhor cópia que existir: a prévia local, enquanto a
      // aba está aberta, é a imagem inteira; depois resta a miniatura de 480px
      // guardada na conversa — o arquivo não é salvo (ADR-0024).
      const cheia = m.anexo.previa || m.anexo.miniatura;
      anexo = src
        ? `<button class="bolha-imagem" type="button" data-visor="${esc(cheia)}" title="Abrir a imagem"><img src="${esc(src)}" alt="Imagem enviada"></button>`
        : ficha(ICONES.imagem, 'Imagem enviada', 'Imagem', 'ladrilho-imagem');
    } else if (m.anexo) {
      anexo = ficha(ICONES.xlsx, m.anexo.nome, /\.csv$/i.test(m.anexo.nome || '') ? 'CSV' : 'Planilha');
    }
    // A hora sai do balão e vira o título: numa conversa de trabalho ela quase
    // nunca importa, e repetida em toda pergunta vira ruído.
    const hora = fmtHora(m.created_at || new Date().toISOString());
    el.innerHTML = `<div class="bolha-usuario" title="${esc(hora)}">${anexo}${esc(m.text)}</div>`;
    return el;
  };

  const elementoResposta = (m) => {
    const fonte = m.fonte || {};
    // Crédito da IA esgotado ou teto do mês: não é erro de quem perguntou e
    // perguntar de novo não adianta — aviso discreto, sem vermelho.
    const semCredito = ['sem_creditos_na_ia', 'teto_de_custo_do_mes', 'limite_diario_da_pessoa']
      .includes(fonte.regra);
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
          ${fonte.blocos?.length
            ? corpoEmBlocos(fonte, m.id)
            : `<div class="md">${semNarrativa ? tabelaCrua(m.text) : markdown(m.text)}</div>`}
          ${m.planilha_preenchida ? `
            <button class="planilha-preenchida" type="button" data-planilha="${m.planilha_preenchida.pergunta}">${ICONES.planilha}<span>Baixar planilha preenchida</span></button>` : ''}
        </div>
        ${fonte.decisao === 'failed' && !semCredito && m.in_reply_to ? `
          <div class="msg-erro-acao"><button class="btn btn-ghost" type="button" data-refazer="${m.in_reply_to}">Perguntar de novo</button></div>` : ''}
        ${fonte.blocos?.length ? '' : blocoGrafico(fonte, m.id)}
        ${blocoFonte(fonte, m.id, !!m.planilha_preenchida)}
        ${semCredito || !m.in_reply_to || fonte.decisao === 'cancelled' ? '' : blocoAvaliacao(m)}
      </article>
      ${blocoContinuacoes(fonte)}
      </div>`;
    if (fonte.grafico && fonte.dados) GRAFICOS.set(String(m.id), { grafico: fonte.grafico, dados: fonte.dados });
    return el;
  };

  // ---------------------------------------------------------- blocos
  // Resposta em blocos (ADR-0025): texto, tabela, texto, gráfico, na ordem
  // que a redação escolheu. Tabela e gráfico são desenhados aqui, com os
  // números do banco — a redação só apontou a consulta e as colunas.
  const rotuloColuna = (nome) => String(nome || '').replace(/_/g, ' ');

  // Percentual só se reconhece pelo nome da coluna: o banco devolve 9.23 e
  // 9.23 pode ser real, unidade ou por cento. A convenção das consultas de
  // referência (`share_pct`, `retencao_90d_pct`, `share_ease_varejo_ytd`) é
  // o que dá a unidade — sem isso a tabela mostrava "9,23" onde a pessoa lê
  // "9,23%" e o gráfico rotulava a barra sem unidade nenhuma.
  const PERCENTUAL_NO_NOME = /(^|_)(pct|perc|percent|percentual|share|participacao|participação)(?=_|$)/i;
  const ehPercentual = (coluna) => PERCENTUAL_NO_NOME.test(String(coluna || ''));

  const fmtCelula = (v, coluna) => {
    if (v === null || v === undefined) return '';
    if (typeof v === 'number') {
      const texto = v.toLocaleString('pt-BR', { maximumFractionDigits: Number.isInteger(v) ? 0 : 2 });
      return ehPercentual(coluna) ? `${texto}%` : texto;
    }
    return String(v);
  };

  const blocoTabela = (bloco, dados) => {
    if (!dados) return '';
    const indices = (bloco.colunas?.length ? bloco.colunas : dados.columns)
      .map((c) => dados.columns.indexOf(c)).filter((i) => i >= 0);
    const cabecalho = indices.map((i) => rotuloColuna(dados.columns[i]));
    const linhas = dados.rows.slice(0, LINHAS_NA_TABELA_DA_TELA)
      .map((linha) => indices.map((i) => fmtCelula(linha[i], dados.columns[i])));
    const titulo = bloco.titulo ? `<div class="bloco-titulo">${esc(bloco.titulo)}</div>` : '';
    const total = dados.total || dados.rows.length;
    const nota = total > linhas.length
      ? `<div class="grafico-nota">Mostrando ${fmtNum(linhas.length)} de ${fmtNum(total)} linhas; a lista completa está no botão Baixar Excel.</div>`
      : '';
    return `<div class="md bloco bloco-tabela">${titulo}${tabelaHtml(cabecalho, linhas)}${nota}</div>`;
  };

  const corpoEmBlocos = (fonte, id) => fonte.blocos.map((bloco, k) => {
    const dados = fonte.dados_blocos?.[String(bloco.consulta)];
    if (bloco.tipo === 'texto') return `<div class="md bloco">${markdown(bloco.texto)}</div>`;
    if (bloco.tipo === 'tabela') return blocoTabela(bloco, dados);
    if (bloco.tipo === 'grafico' && dados) {
      const chave = `${id}-b${k}`;
      GRAFICOS.set(chave, { grafico: bloco.grafico, dados });
      return `<div class="bloco">${blocoGrafico({ grafico: bloco.grafico, dados }, chave)}</div>`;
    }
    return '';
  }).join('');

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
  const CORES = ['#5558D4', '#3FB868', '#F5A623', '#E5484D', '#0EA5E9', '#A855F7', '#14B8A6', '#F472B6'];
  // "Outras" é sempre cinza: é a soma do que ficou de fora, não uma categoria.
  const COR_OUTRAS = '#9CA1B8';
  // Série por categoria: as maiores ganham cor, o resto soma em "Outras".
  // Mais de seis cores num cartão de conversa ninguém distingue.
  const MAX_GRUPOS = 6;
  // Gráficos separados (um por categoria): até 3×3 cabe na conversa.
  const MAX_MULTIPLOS = 9;
  // Linhas da tabela na conversa. O bloco agora traz o resultado inteiro (o
  // gráfico precisa dele); a lista completa está no botão Baixar Excel.
  const LINHAS_NA_TABELA_DA_TELA = 100;
  const MAX_FATIAS = 8;
  // As cores do gráfico saem dos mesmos tokens da interface: assim ele
  // acompanha o tema sem ter uma paleta paralela para manter.
  const token = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

  // Nome da série de um grupo. Categoria em número (1, 3) sozinha não diz de
  // quê: vira "Categoria 1", "Categoria 3".
  const nomeDoGrupo = (coluna, valor) => {
    if (valor === null || valor === undefined) return 'Sem categoria';
    if (typeof valor !== 'number') return String(valor);
    const rotulo = rotuloSerie(coluna);
    return `${rotulo.charAt(0).toUpperCase()}${rotulo.slice(1)} ${valor.toLocaleString('pt-BR')}`;
  };

  // Pequenos múltiplos: um gráfico por valor do grupo (ou por série), na
  // mesma escala, para comparar a forma sem uma série esconder a outra.
  const separarGrafico = (grafico, dados) => {
    const colunas = dados.columns || [];
    const rows = dados.rows || [];
    const series = (grafico.series || []).filter((s) => colunas.includes(s));
    const base = { ...grafico, separar: false, empilhado: false, grupo: '' };
    const maximo = (nomes) => Math.max(0, ...rows.flatMap((l) => nomes.map((n) => Number(l[colunas.indexOf(n)]) || 0)));
    const ig = grafico.grupo ? colunas.indexOf(grafico.grupo) : -1;
    if (ig >= 0 && series.length) {
      const i = colunas.indexOf(series[0]);
      const totais = new Map();
      rows.forEach((l) => totais.set(l[ig], (totais.get(l[ig]) || 0) + (Number(l[i]) || 0)));
      // As maiores primeiro, até MAX_MULTIPLOS painéis: 30 especialidades em
      // 30 gráficos não se leem (conversa 18, 2026-09-23). O resto é dito.
      const ordem = [...totais.entries()].sort((a, b) => b[1] - a[1]);
      const escolhidas = ordem.slice(0, MAX_MULTIPLOS);
      const escala = maximo([series[0]]);
      const paineis = escolhidas.map(([v, total], n) => ({
        grafico: { ...base, series: [series[0]], titulo: nomeDoGrupo(grafico.grupo, v),
          total: fmtValor(total, series[0]), escalaMax: escala, cor: CORES[n % CORES.length] },
        dados: { columns: colunas, rows: rows.filter((l) => l[ig] === v) },
      }));
      paineis.ocultas = ordem.length - escolhidas.length;
      paineis.rotulo = rotuloSerie(grafico.grupo);
      return paineis;
    }
    if (series.length > 1) {
      const escala = maximo(series);
      return series.map((s, n) => ({
        grafico: { ...base, series: [s], titulo: rotuloSerie(s), escalaMax: escala, cor: CORES[n % CORES.length] }, dados,
      }));
    }
    return [];
  };

  const blocoGrafico = (fonte, id) => {
    if (!fonte.grafico || !fonte.dados) return '';
    const multiplos = fonte.grafico.separar && fonte.grafico.tipo !== 'vega' ? separarGrafico(fonte.grafico, fonte.dados) : [];
    if (multiplos.length > 1) {
      const paineis = multiplos.map((m, n) => {
        const chave = `${id}-s${n}`;
        GRAFICOS.set(chave, m);
        return `
          <div class="grafico-multiplo">
            <div class="grafico-subtitulo">${esc(m.grafico.titulo)}${m.grafico.total ? `<span class="grafico-subtitulo-total">${esc(m.grafico.total)} no período</span>` : ''}</div>
            <div class="grafico-area"><canvas data-grafico="${chave}" role="img"></canvas></div>
          </div>`;
      }).join('');
      return `
        <div class="grafico">
          ${fonte.grafico.titulo ? `<div class="grafico-titulo">${esc(fonte.grafico.titulo)}</div>` : ''}
          <div class="grafico-multiplos${multiplos.length > 4 ? ' grafico-multiplos-muitos' : ''}">${paineis}</div>
          ${multiplos.ocultas > 0 ? `<div class="grafico-nota">Mostrando as ${multiplos.length} maiores de ${multiplos.length + multiplos.ocultas} (${esc(multiplos.rotulo)}); as demais estão na planilha.</div>` : ''}
        </div>`;
    }
    const area = fonte.grafico.tipo === 'vega'
      ? `<div class="grafico-vega" data-vega="${id}" role="img"></div>`
      : `<div class="grafico-area"><canvas data-grafico="${id}" role="img"></canvas></div>`;
    return `
      <div class="grafico">
        ${fonte.grafico.titulo ? `<div class="grafico-titulo">${esc(fonte.grafico.titulo)}</div>` : ''}
        ${area}
      </div>`;
  };

  // ---------------------------------------------------------- Vega-Lite
  // Qualquer gráfico que a gramática descreve (ADR-0026). A especificação
  // chega do servidor já sem fonte de dado nem endereço; os valores entram
  // aqui, vindos do resultado da consulta. As expressões rodam no
  // interpretador do Vega, que não executa JavaScript.
  let vegaCarregado = null;
  const carregarScript = (src) => new Promise((ok, falha) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = ok;
    s.onerror = () => falha(new Error(`não carregou ${src}`));
    document.head.appendChild(s);
  });
  const carregarVega = () => {
    if (!vegaCarregado) {
      const libs = JSON.parse($('#bibliotecasVega')?.textContent || '{}');
      // A ordem importa: o Vega-Lite e o Embed procuram o Vega já carregado.
      vegaCarregado = carregarScript(libs.vega)
        .then(() => carregarScript(libs.vegaLite))
        .then(() => carregarScript(libs.vegaEmbed))
        .then(() => carregarScript(libs.interpretador));
    }
    return vegaCarregado;
  };

  const LOCAL_VEGA = {
    numero: { decimal: ',', thousands: '.', grouping: [3], currency: ['R$ ', ''] },
    tempo: {
      dateTime: '%A, %e de %B de %Y. %X', date: '%d/%m/%Y', time: '%H:%M:%S',
      periods: ['AM', 'PM'],
      days: ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'],
      shortDays: ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'],
      months: ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'],
      shortMonths: ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'],
    },
  };

  // O tema do Vega sai dos mesmos tokens da interface, como o do Chart.js.
  const temaVega = () => ({
    background: token('--bg-card') || '#fff',
    font: 'Inter, sans-serif',
    range: { category: CORES },
    axis: {
      labelColor: token('--gray-600'), titleColor: token('--gray-600'), gridColor: token('--border-light'),
      domainColor: token('--border-light'), tickColor: token('--border-light'), labelFontSize: 11, titleFontSize: 11,
    },
    // Em colunas: numa linha só, nove especialidades saíam da tela.
    legend: { labelColor: token('--gray-600'), titleColor: token('--gray-600'), labelFontSize: 11, orient: 'bottom', columns: 4 },
    // Categoria de nome longo inclinada, não em pé: em pé, "CLINICA GERAL" saía cortado.
    // Só no eixo de baixo: no de lado (mapa de calor) o nome cabe deitado.
    axisXBand: { labelAngle: -35, labelLimit: 130 },
    // Mês como no resto do app ("jan/26"), uma marca por mês: sem o intervalo
    // o Vega marcava de quinze em quinze dias e repetia o mês.
    axisTemporal: { format: '%b/%y', tickCount: 'month', labelOverlap: true },
    title: { color: token('--gray-900'), fontSize: 13, anchor: 'start' },
    view: { stroke: null },
    mark: { color: CORES[0] },
    // Rótulo de pizza e de barra: sem isto saía escuro no tema escuro.
    text: { color: token('--gray-700'), fontSize: 11 },
  });

  const VEGAS = new Map();   // div -> view, para refazer ao trocar de tema
  const desenharVega = async (div) => {
    const dado = GRAFICOS.get(div.dataset.vega);
    if (!dado) return;
    try {
      await carregarVega();
    } catch (e) {
      div.textContent = 'Não consegui carregar o desenho do gráfico. A tabela e a planilha continuam com todos os dados.';
      return;
    }
    const { grafico, dados } = dado;
    const colunas = dados.columns || [];
    // "2026-01" e "2026-01-01" sem hora são lidos como meia-noite em UTC, e
    // no fuso de Brasília viram 31/12 do ano anterior: o mapa de calor
    // começava em "dez 2025". Com a hora escrita, a data é local.
    const COMPETENCIA = /^(\d{4})-(\d{2})(?:-(\d{2}))?$/;
    const local = (v) => {
      const m = typeof v === 'string' && v.match(COMPETENCIA);
      return m ? `${m[1]}-${m[2]}-${m[3] || '01'}T00:00:00` : v;
    };
    const valores = (dados.rows || []).map((l) => Object.fromEntries(colunas.map((c, i) => [c, local(l[i])])));
    const spec = JSON.parse(JSON.stringify(grafico.vega));
    spec.data = { values: valores };
    const composto = ['hconcat', 'vconcat', 'concat', 'facet', 'repeat'].some((k) => k in spec);
    if (!composto && spec.width === undefined) spec.width = 'container';
    if (spec.height === undefined && !composto) spec.height = 280;
    spec.config = { ...temaVega(), ...(spec.config || {}) };
    // Nenhum endereço é buscado: a especificação já vem sem eles, e o
    // carregador recusa o que sobrar.
    const carregador = window.vega.loader();
    carregador.sanitize = () => Promise.reject(new Error('o gráfico não busca dado de fora'));
    try {
      const { view } = await window.vegaEmbed(div, spec, {
        renderer: 'svg',
        ast: true,
        expr: window.vegaExpressionInterpreter,
        loader: carregador,
        formatLocale: LOCAL_VEGA.numero,
        timeFormatLocale: LOCAL_VEGA.tempo,
        actions: { export: true, source: false, compiled: false, editor: false },
        i18n: { PNG_ACTION: 'Baixar como PNG', SVG_ACTION: 'Baixar como SVG' },
      });
      VEGAS.set(div, view);
    } catch (e) {
      div.textContent = 'Não consegui desenhar este gráfico. A tabela e a planilha continuam com todos os dados.';
    }
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

  // A IA escolhe as colunas, não a unidade — quem dá a unidade é o nome da
  // coluna (`ehPercentual`, lá em cima, junto do formato da tabela: o
  // gráfico e a tabela da mesma resposta não podem discordar).
  const fmtValor = (v, coluna) => fmtEixo(v) + (ehPercentual(coluna) ? '%' : '');
  // "retencao_90d_pct" vira "retencao 90d" na legenda: o % já está no número.
  // Só o sufixo técnico sai; "share" é o nome do indicador e fica.
  const SUFIXO_PCT = /(^|_)(pct|perc|percent|percentual)(?=_|$)/i;
  const rotuloSerie = (coluna) => coluna.replace(SUFIXO_PCT, '').replace(/_+/g, ' ').trim();

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
    // Formato longo (mês × especialidade × PX): cada valor de `grupo` vira
    // uma série. Pizza reparte uma medida pelas categorias do eixo.
    const grupo = grafico.grupo && colunas.includes(grafico.grupo) ? grafico.grupo : '';
    const ig = grupo ? colunas.indexOf(grupo) : -1;
    const pizza = grafico.tipo === 'pizza';
    const emArea = grafico.tipo === 'area';
    const empilhado = Boolean(grafico.empilhado) && !pizza;

    let linhas = (dados.rows || []).filter((l) => l[ix] !== null && l[ix] !== undefined);
    const porMes = ehMensal(linhas.map((l) => l[ix]));
    const temporal = ehTemporal(linhas.map((l) => l[ix]));
    // Mês fora de ordem numa linha do tempo desenha um ziguezague que não
    // existe: quando o eixo é temporal, a ordem é a do calendário.
    if (temporal) {
      linhas = [...linhas].sort((a, b) => String(a[ix]).localeCompare(String(b[ix])));
    }

    const linha = grafico.tipo === 'linha' || emArea;
    const horizontal = grafico.tipo === 'barras_horizontais';
    const valorDe = (l, nome) => l[colunas.indexOf(nome)];
    const notas = [];

    // Zeros no começo de uma linha do tempo quase sempre são o programa
    // ainda começando, não um resultado. Medido em 2026-09-21: a retenção de
    // jun/23 era 0 de 3 compradores, e desenhava uma subida de 0 a 30% que
    // não aconteceu. Saem do desenho, com aviso — e continuam na planilha.
    if (linha && temporal && !grupo) {
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
    // Com grupo e na pizza o corte é depois, sobre as categorias: cortar as
    // linhas do formato longo levaria meio mês de uma série e nada da outra.
    const corte = grupo || pizza ? 0 : grafico.limite || (linha ? 0 : MAX_CATEGORIAS);
    if (corte && total > corte) linhas = linhas.slice(0, corte);
    const deFora = total - linhas.length;

    // Rótulos do eixo e séries do desenho, nos três formatos.
    let valoresX;
    let conjuntos;
    const numero = (v) => Number(v) || 0;
    if (grupo) {
      const medida = series[0];
      const porX = new Map();
      const totais = new Map();
      valoresX = [];
      linhas.forEach((l) => {
        const chave = String(l[ix]);
        const nome = nomeDoGrupo(grupo, l[ig]);
        if (!porX.has(chave)) { porX.set(chave, new Map()); valoresX.push(l[ix]); }
        porX.get(chave).set(nome, (porX.get(chave).get(nome) || 0) + numero(valorDe(l, medida)));
        totais.set(nome, (totais.get(nome) || 0) + numero(valorDe(l, medida)));
      });
      if (!temporal) valoresX = valoresX.slice(0, grafico.limite || MAX_CATEGORIAS);
      const ordem = [...totais.entries()].sort((a, b) => b[1] - a[1]).map(([nome]) => nome);
      const principais = ordem.slice(0, MAX_GRUPOS);
      const resto = ordem.slice(MAX_GRUPOS);
      conjuntos = principais.map((nome) => ({
        nome, dados: valoresX.map((v) => porX.get(String(v)).get(nome) ?? null),
      }));
      if (resto.length) {
        conjuntos.push({
          nome: 'Outras', outras: true,
          dados: valoresX.map((v) => resto.reduce((s, nome) => s + (porX.get(String(v)).get(nome) || 0), 0)),
        });
        notas.push(`${resto.length === 1 ? '1 categoria menor está somada' : `${resto.length} categorias menores estão somadas`} em "Outras"; a lista inteira está na planilha.`);
      }
    } else if (pizza) {
      // A mesma categoria em várias linhas (um mês por linha) é uma fatia
      // só: soma antes de fatiar, senão a pizza repete o nome.
      const medida = series[0];
      const totais = new Map();
      linhas.forEach((l) => {
        const chave = String(l[ix] ?? 'Sem categoria');
        totais.set(chave, (totais.get(chave) || 0) + numero(valorDe(l, medida)));
      });
      const ordenadas = [...totais.entries()].sort((a, b) => b[1] - a[1]);
      const fatias = ordenadas.slice(0, MAX_FATIAS);
      const resto = ordenadas.slice(MAX_FATIAS);
      valoresX = fatias.map(([nome]) => nome);
      const dados = fatias.map(([, valor]) => valor);
      if (resto.length) {
        valoresX.push('Outras');
        dados.push(resto.reduce((s, [, valor]) => s + valor, 0));
        notas.push(`${resto.length === 1 ? '1 fatia menor está somada' : `${resto.length} fatias menores estão somadas`} em "Outras".`);
      }
      conjuntos = [{ nome: rotuloSerie(medida), dados }];
    } else {
      valoresX = linhas.map((l) => l[ix]);
      conjuntos = series.map((nome) => ({ nome: rotuloSerie(nome), dados: linhas.map((l) => valorDe(l, nome)) }));
    }
    // A medida de cada série, para formatar o número (grupo e pizza têm uma só).
    const colunaDaSerie = (n) => (grupo || pizza ? series[0] : series[n]);

    const area = canvas.parentElement;
    if (horizontal) area.style.height = `${valoresX.length * ALTURA_POR_BARRA + 24}px`;
    if (deFora > 0) {
      notas.push(`Mostrando ${linhas.length} de ${fmtNum(total)} — a lista inteira está na planilha.`);
    }
    if (notas.length && !area.nextElementSibling?.classList.contains('grafico-nota')) {
      const nota = document.createElement('div');
      nota.className = 'grafico-nota';
      nota.textContent = notas.join(' ');
      area.after(nota);
    }

    const umaSerie = conjuntos.length === 1 && !pizza;
    const emPercentual = series.every(ehPercentual);
    const passo = temporal && porMes && !horizontal && !pizza ? passoDoEixo(valoresX.length, area.clientWidth || 600) : 1;

    // Com uma série só, o número vai na ponta da barra e o eixo de valores
    // some: dois jeitos de ler o mesmo número é um a mais do que o preciso.
    const numeroNaBarra = {
      id: 'numeroNaBarra',
      afterDatasetsDraw(c) {
        if (linha || !umaSerie || pizza || empilhado) return;
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
      const d = partesDeData(valoresX[i]);
      return d ? (Number(d.mes) - 1) % passo === 0 : true;
    };
    const eixoDeCategoria = {
      stacked: empilhado,
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
      stacked: empilhado,
      display: linha || !umaSerie,
      beginAtZero: true,
      grace: '8%',
      // Nos gráficos separados, a mesma escala em todos: senão 300 e 600
      // desenham barras da mesma altura.
      ...(grafico.escalaMax ? { max: grafico.escalaMax * 1.12 } : {}),
      grid: { color: token('--border-light'), drawTicks: false },
      border: { display: false },
      ticks: {
        font: { size: 11 }, color: token('--gray-600'), padding: 6,
        callback: (v) => fmtEixo(v) + (emPercentual ? '%' : ''),
      },
    };

    const semAnimacao = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // Painel de gráficos separados: a cor é a da categoria, não a da posição.
    const corDe = (c, n) => (c.outras ? COR_OUTRAS : (grafico.cor && conjuntos.length === 1 ? grafico.cor : CORES[n % CORES.length]));
    const chart = new Chart(canvas, {
      type: pizza ? 'doughnut' : linha ? 'line' : 'bar',
      data: {
        labels: valoresX.map((v) => (pizza ? encurtar(String(v), 28) : rotuloEixo(v, porMes))),
        datasets: pizza
          ? [{
            label: conjuntos[0].nome,
            data: conjuntos[0].dados,
            backgroundColor: valoresX.map((v, n) => (v === 'Outras' ? COR_OUTRAS : CORES[n % CORES.length])),
            borderColor: token('--bg-card') || '#fff',
            borderWidth: 2,
          }]
          : conjuntos.map((c, n) => ({
            label: c.nome,
            data: c.dados,
            borderColor: corDe(c, n),
            // área: preenchida, e empilhada cada uma sobre a de baixo
            backgroundColor: emArea ? `${corDe(c, n)}55` : linha ? 'transparent' : corDe(c, n),
            fill: emArea ? (empilhado && n > 0 ? '-1' : 'origin') : false,
            borderWidth: linha ? 2.5 : 0,
            borderRadius: linha || empilhado ? 0 : 5,
            pointRadius: emArea ? 0 : 3,
            pointBackgroundColor: corDe(c, n),
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
        interaction: pizza ? { mode: 'nearest', intersect: true } : { mode: 'index', intersect: false },
        plugins: {
          // Uma série só já está dita no título e na resposta.
          legend: {
            display: conjuntos.length > 1 || pizza, position: pizza ? 'right' : 'bottom',
            labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, font: { size: 11 } },
          },
          tooltip: {
            backgroundColor: token('--toast-bg'), bodyColor: token('--toast-fg'),
            titleColor: token('--toast-fg'), padding: 10, cornerRadius: 8,
            displayColors: conjuntos.length > 1 || pizza,
            callbacks: {
              label: (c) => (pizza
                ? ` ${c.label}: ${fmtValor(c.parsed, series[0])}`
                : ` ${c.dataset.label}: ${fmtValor(c.parsed[horizontal ? 'x' : 'y'], colunaDaSerie(c.datasetIndex))}`),
            },
          },
        },
        scales: pizza
          ? {}
          : horizontal
            ? { x: eixoDeValor, y: eixoDeCategoria }
            : { x: eixoDeCategoria, y: eixoDeValor },
      },
      plugins: [fundoDoCartao, numeroNaBarra],
    });
    canvas.setAttribute('aria-label', `${grafico.titulo || 'Gráfico'} — ${valoresX.length} pontos`);
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
    const vegas = [...VEGAS.entries()];
    VEGAS.clear();
    vegas.forEach(([div, view]) => {
      view.finalize();
      div.innerHTML = '';
      desenharVega(div);
    });
  };

  const desenharGraficosNovos = (raiz) => {
    (raiz || document).querySelectorAll('canvas[data-grafico]:not([data-pronto])').forEach((c) => {
      c.dataset.pronto = '1';
      desenharGrafico(c);
    });
    (raiz || document).querySelectorAll('[data-vega]:not([data-pronto])').forEach((d) => {
      d.dataset.pronto = '1';
      desenharVega(d);
    });
  };

  // `temPlanilha`: a resposta já traz o botão verde da planilha preenchida.
  // Dois botões de baixar, um do lado do outro, com arquivos diferentes, é
  // uma escolha que ninguém pediu — some o do resultado cru, que não foi o
  // que a pessoa mandou preencher.
  // 👍/👎 (cada 👎 vira rascunho de caso de validação no time de BI).
  const blocoAvaliacao = (m) => {
    const nota = m.avaliacao?.nota || '';
    const botao = (valor, icone, titulo) => `
      <button class="avaliacao-btn${nota === valor ? ' ativo' : ''}" type="button" data-nota="${valor}"
        aria-pressed="${nota === valor}" title="${titulo}" aria-label="${titulo}">${ICONES[icone]}</button>`;
    return `
      <div class="avaliacao" data-avaliacao="${m.id}">
        <div class="avaliacao-linha">
          <span class="avaliacao-rotulo">Esta resposta ajudou?</span>
          ${botao('up', 'util', 'Útil')}
          ${botao('down', 'errada', 'Errada')}
          <span class="avaliacao-obrigado" ${nota ? '' : 'hidden'}>${nota === 'down' ? 'Obrigado: isso vira um teste para o Jarvis melhorar.' : 'Obrigado!'}</span>
        </div>
        <form class="avaliacao-form" hidden>
          <textarea maxlength="2000" rows="2" placeholder="O que estava errado? Ex.: o período não era esse, faltou o Mercado Público">${esc(m.avaliacao?.comentario || '')}</textarea>
          <div class="avaliacao-acoes">
            <button class="btn btn-ghost" type="button" data-avaliacao-fechar>Agora não</button>
            <button class="btn btn-primary" type="submit">Enviar</button>
          </div>
        </form>
      </div>`;
  };

  const avaliar = async (caixa, nota, comentario = '') => {
    const id = caixa.dataset.avaliacao;
    const url = `/api/conversations/${state.conversaId}/messages/${id}/avaliacao/`;
    const obrigado = caixa.querySelector('.avaliacao-obrigado');
    try {
      if (nota) await api(url, { method: 'PUT', body: { nota, comentario } });
      else await api(url, { method: 'DELETE' });
    } catch (e) {
      toast('Não consegui registrar a avaliação. Tente de novo.', true);
      return false;
    }
    caixa.querySelectorAll('.avaliacao-btn').forEach((b) => {
      const ativo = b.dataset.nota === nota;
      b.classList.toggle('ativo', ativo);
      b.setAttribute('aria-pressed', String(ativo));
    });
    obrigado.hidden = !nota;
    obrigado.textContent = nota === 'down' ? 'Obrigado: isso vira um teste para o Jarvis melhorar.' : 'Obrigado!';
    return true;
  };

  const blocoFonte = (fonte, id, temPlanilha = false) => {
    if (fonte.investigacao?.length) return blocoFonteDaInvestigacao(fonte);
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
          ${fonte.excel && !temPlanilha ? `<button class="fonte-excel${fonte.excel_pedido ? ' destaque' : ''}" type="button" data-excel="${id}">${ICONES.planilha}<span>Baixar Excel</span></button>` : ''}
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

  // Investigação: uma consulta por hipótese, na ordem em que foram testadas.
  // É o que permite ao time de BI conferir o raciocínio, não só o número.
  const blocoFonteDaInvestigacao = (fonte) => {
    const equipe = state.usuario?.equipe;
    const passos = fonte.investigacao;
    const meta = [
      ['Consultas', fmtNum(passos.length)],
      ['Rodadas', fmtNum(Math.max(...passos.map((p) => p.rodada || 1)))],
      ['Respondida', new Date(fonte.respondida_em).toLocaleString('pt-BR')],
    ];
    if (equipe && fonte.custo_usd != null) {
      meta.push(['Custo', `US$ ${fonte.custo_usd.toLocaleString('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`]);
      meta.push(['Tempo total', fonte.tempo_ms ? `${(fonte.tempo_ms / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} s` : '—']);
    }
    const consultas = passos.map((p, i) => `
      <div class="fonte-hipotese">
        <div class="fonte-hipotese-titulo">${i + 1}. ${esc(p.hipotese || 'Consulta')}
          <span class="fonte-hipotese-meta">${p.erro ? 'não rodou' : `${fmtNum(p.linhas ?? 0)} linhas`}</span></div>
        ${p.erro ? `<div class="fonte-hipotese-erro">${esc(p.erro)}</div>` : ''}
        <div class="codigo">
          <button class="btn-copiar" type="button">${ICONES.copiar}Copiar</button>
          <pre><code>${realcarSql(p.sql)}</code></pre>
        </div>
      </div>`).join('');
    return `
      <div class="fonte">
        <div class="fonte-barra">
          <button class="fonte-toggle" type="button" aria-expanded="false">${ICONES.banco}<span class="fonte-toggle-texto">Ver fonte e consulta</span><span class="chevron">${ICONES.chevron}</span></button>
        </div>
        <div class="fonte-detalhe">
          <div class="fonte-detalhe-inner">
            <div class="fonte-meta">${meta.map(([rotulo, valor]) => `
              <div><div class="fonte-meta-label">${esc(rotulo)}</div><div class="fonte-meta-valor">${esc(valor)}</div></div>`).join('')}
            </div>
            ${consultas}
          </div>
        </div>
      </div>`;
  };

  $('#mensagens').addEventListener('submit', async (ev) => {
    const form = ev.target.closest('.avaliacao-form');
    if (!form) return;
    ev.preventDefault();
    const comentario = form.querySelector('textarea').value.trim();
    if (await avaliar(form.closest('.avaliacao'), 'down', comentario)) form.hidden = true;
  });

  // abrir/fechar a fonte, copiar o SQL, refazer pergunta, usar sugestão
  $('#mensagens').addEventListener('click', async (ev) => {
    const botaoNota = ev.target.closest('.avaliacao-btn');
    if (botaoNota) {
      const caixa = botaoNota.closest('.avaliacao');
      const form = caixa.querySelector('.avaliacao-form');
      // Clicar de novo no mesmo botão desfaz.
      const nota = botaoNota.classList.contains('ativo') ? '' : botaoNota.dataset.nota;
      // O 👎 fica gravado na hora; o comentário, se vier, completa depois.
      if (await avaliar(caixa, nota)) {
        form.hidden = nota !== 'down';
        if (nota === 'down') form.querySelector('textarea').focus();
      }
      return;
    }
    if (ev.target.closest('[data-avaliacao-fechar]')) {
      ev.target.closest('.avaliacao-form').hidden = true;
      return;
    }
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
    const preenchida = ev.target.closest('[data-planilha]');
    if (preenchida) { await baixarPreenchida(preenchida); return; }

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

  // A planilha preenchida fica disponível por pouco tempo e depois some — de
  // propósito, o arquivo é da pessoa (ADR-0024). Vencida, o botão vira aviso.
  const baixarPreenchida = async (botao) => {
    if (botao.disabled) return;
    botao.disabled = true;
    try {
      const r = await fetch(`/api/conversations/${state.conversaId}/messages/${botao.dataset.planilha}/planilha/`, {
        credentials: 'same-origin',
      });
      if (!r.ok) {
        const erro = await r.json().catch(() => ({}));
        if (r.status === 404) {
          botao.querySelector('span').textContent = 'Planilha expirada — envie de novo';
          toast(erro.error || 'A planilha preenchida expirou.', true);
          return;
        }
        throw new Error(erro.error || 'não consegui baixar a planilha');
      }
      const nome = (r.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/);
      const url = URL.createObjectURL(await r.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = nome ? nome[1] : 'jarvis_preenchida.xlsx';
      link.click();
      URL.revokeObjectURL(url);
      botao.disabled = false;
    } catch (e) {
      botao.disabled = false;
      toast(`Não consegui baixar a planilha: ${e.message}`, true);
    }
  };

  // ---------------------------------------------------------- "pensando"
  const mostrarPensando = () => {
    $('#pensando')?.remove();
    const el = document.createElement('div');
    el.className = 'msg msg-ia';
    el.id = 'pensando';
    // A espera tem a forma de uma resposta que ainda não chegou: o mascote na
    // coluna do avatar e uma linha de estado no lugar do texto. Sem cartão e
    // sem barra de progresso — a resposta não vem por etapas medidas, e a
    // barra prometia uma precisão que não existe.
    el.innerHTML = `
      <div class="ia-avatar" id="jarvisEspera" aria-hidden="true">${jarvis('jarvis--pensando', true)}</div>
      <div class="msg-corpo">
        <div class="pensando">
          <span class="pensando-texto" id="pensandoTexto"><strong>Pensando…</strong></span>
          <span class="pensando-tempo" id="pensandoTempo">0 s</span>
        </div>
        <div class="pensando-entendimento" id="pensandoEntendimento" hidden></div>
      </div>`;
    $('#mensagens').appendChild(el);
    atualizarContinuacoes();
    subirAPergunta(ultimaPergunta());
  };

  const tickPensando = () => {
    if (!state.aguardando) return;
    const seg = Math.round((Date.now() - state.aguardando.inicio) / 1000);
    const tempo = $('#pensandoTempo');
    if (tempo) tempo.textContent = `${seg} s`;
    const texto = $('#pensandoTexto');
    if (texto && seg === 25 && state.aguardando.consultando && !state.aguardando.etapa) {
      texto.innerHTML = '<strong>Ainda consultando</strong> — perguntas que cruzam áreas levam um pouco mais.';
    }
  };

  // O que o servidor diz da pergunta pendente: a etapa e o que foi entendido.
  // "Entendi: vendas de 1 a 20/09 contra 1 a 20/08, só CDD" aparece enquanto
  // a resposta não chega — é quando corrigir o pedido ainda é barato.
  const ETAPAS = {
    entendi: 'Montando a consulta',
    consultando: 'Consultando o banco',
    escrevendo: 'Escrevendo a resposta',
    investigando: 'Investigando',
    conferindo: 'Conferindo o resultado',
  };
  const mostrarEtapa = (pendente) => {
    const texto = $('#pensandoTexto');
    const rotulo = ETAPAS[pendente.etapa] || 'Investigando';
    const detalhe = pendente.progresso && pendente.progresso !== rotulo && pendente.etapa !== 'entendi'
      ? ` — ${esc(pendente.progresso)}` : '';
    if (texto && pendente.progresso) texto.innerHTML = `<strong>${esc(rotulo)}</strong>${detalhe}`;
    const entendi = $('#pensandoEntendimento');
    if (entendi && pendente.entendimento) {
      entendi.hidden = false;
      entendi.innerHTML = `<span class="pensando-entendimento-rotulo">Entendi:</span> ${esc(pendente.entendimento)}`;
    }
    if (pendente.etapa && pendente.etapa !== 'entendi') {
      $('#jarvisEspera .jarvis')?.classList.replace('jarvis--pensando', 'jarvis--consultando');
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
      // O servidor diz em que etapa está e o que entendeu do pedido.
      const mudou = pendente && (pendente.progresso || pendente.entendimento)
        && (pendente.progresso !== aguardando.progresso || pendente.entendimento !== aguardando.entendimento);
      if (mudou) {
        aguardando.progresso = pendente.progresso;
        aguardando.entendimento = pendente.entendimento;
        aguardando.etapa = pendente.etapa || 'investigando';
        if (aguardando.etapa !== 'entendi') aguardando.consultando = true;
        mostrarEtapa({ ...pendente, etapa: aguardando.etapa });
      }
      if (pendente?.status === 'processing' && !aguardando.consultando && (!aguardando.etapa || aguardando.etapa === 'entendi')) {
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
          subirAPergunta(ultimaPergunta());
          avisarDaCota();
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
        <div class="msg-corpo">
        <article class="cartao-ia tipo-falha">
          <div class="cartao-ia-corpo">
            <div class="cartao-ia-rotulo">${ICONES.alerta}Demorou mais que o normal</div>
            <div class="md"><p>A resposta ainda não chegou. Ela pode aparecer se você abrir esta conversa de novo daqui a pouco.</p></div>
          </div>
        </article>
        </div>`;
      $('#mensagens').appendChild(el);
      rolarParaFim();
      return;
    }
    agendarPoll(POLL_MS * Math.min(1 + state.falhasSeguidas, 4));
  };

  // Anexo sem texto: a pergunta padrão diz o que fazer com ele. Para a
  // planilha ela é genérica de propósito — o modelo pede o detalhe que faltar.
  const PERGUNTA_PADRAO = {
    imagem: 'Analise esta imagem.',
    planilha: 'Preencha esta planilha com os dados que faltam.',
  };

  const enviar = async (textoBruto) => {
    const anexo = state.anexo;
    const texto = String(textoBruto || '').trim() || (anexo ? PERGUNTA_PADRAO[anexo.tipo] : '');
    if (!texto || state.aguardando || state.anexoEnviando) return;
    pararDitado();

    const campo = $('#campoPergunta');
    campo.value = '';
    ajustarCampo();
    limparAnexo();
    atualizarBotao();

    // pergunta aparece na hora; o id real chega com a resposta do POST
    const provisoria = elementoPergunta({
      text: texto,
      created_at: new Date().toISOString(),
      anexo: anexo ? { tipo: anexo.tipo, nome: anexo.nome, previa: anexo.previa } : null,
    });
    $('#boasVindas')?.remove();
    $('#mensagens').appendChild(provisoria);
    subirAPergunta(provisoria);
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
        // Só a etiqueta que o servidor devolveu; a prévia local fica no navegador.
        body: {
          client_message_id: novoId(),
          text: texto,
          ...(anexo ? { anexo: { token: anexo.token, tipo: anexo.tipo, nome: anexo.nome, resumo: anexo.resumo } } : {}),
        },
      });
      provisoria.dataset.id = r.message_id;
      definirCabecalho(state.conversas.find((c) => c.id === state.conversaId)?.title || texto.slice(0, 60), 'Consultando…');
      carregarConversas();
      iniciarAguardo(r.message_id, texto);
    } catch (e) {
      state.aguardando = null;
      provisoria.remove();
      campo.value = texto;
      // O anexo volta para o compositor: o token continua valendo no prazo,
      // e perder o arquivo por falha de rede obrigaria a subir de novo.
      if (anexo) mostrarAnexo(anexo);
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

  // Enquanto a resposta não chega, o mesmo botão para a solicitação — é o
  // lugar onde a mão já está, e é assim nas outras IAs. Ele nunca fica
  // desabilitado nesse estado: esperar sem poder desistir é a situação que
  // o botão existe para resolver.
  const atualizarBotao = () => {
    const vazio = !$('#campoPergunta').value.trim() && !state.anexo;
    const esperando = !!state.aguardando;
    const enviar = $('#btnEnviar');
    enviar.classList.toggle('parar', esperando);
    enviar.setAttribute('aria-label', esperando ? 'Interromper a solicitação' : 'Enviar pergunta');
    enviar.title = esperando ? 'Interromper a solicitação' : '';
    enviar.disabled = esperando ? false : (vazio || state.anexoEnviando);
    $('#btnAnexar').disabled = esperando || state.anexoEnviando;
  };

  // Só escreve o status pela API; quem para de verdade é o worker, que o lê
  // entre as etapas. A tela não espera a confirmação para sair do "pensando":
  // quem apertou parar quer a tela livre agora.
  const interromper = async () => {
    const aguardando = state.aguardando;
    if (!aguardando) return;
    // A tela não anuncia a interrupção: quem apertou parar sabe o que fez, e
    // um aviso ali seria ruído em toda pergunta desistida.
    pararAguardo();
    if (!aguardando.id) return;  // o POST da pergunta ainda nem voltou
    try {
      await api(`/api/conversations/${state.conversaId}/messages/${aguardando.id}/interromper/`, {
        method: 'POST', body: {},
      });
    } catch (e) {
      toast(`Não consegui interromper: ${e.message}`, true);
    }
  };


  // ---------------------------------------------------------- anexo
  // O arquivo sobe assim que é escolhido: validação e resumo acontecem no
  // servidor, e quem mandou algo grande demais descobre na hora, antes de
  // escrever a pergunta. Volta só uma etiqueta; o arquivo não é guardado.
  const LIMITE_DO_ANEXO = 5 * 1024 * 1024;
  const EXTENSOES_ACEITAS = /\.(xlsx|xlsm|csv|png|jpe?g|webp)$/i;

  const fmtBytes = (n) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1).replace('.', ',')} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

  const BOTAO_REMOVER = `<button class="anexo-chip-remover" type="button" aria-label="Remover anexo">${ICONES.fechar}</button>`;

  // Imagem: só a prévia, como nas outras IAs — sem nome de arquivo (um
  // print colado nem tem nome). Planilha: nome, linhas e colunas, que é o
  // que diz se o arquivo certo foi escolhido.
  const desenharChip = ({ nome, tipo, detalhe, enviando, previa }) => {
    const chip = $('#anexoChip');
    chip.hidden = false;
    chip.classList.toggle('enviando', !!enviando);
    chip.classList.toggle('imagem', tipo === 'imagem' && !!previa);
    if (tipo === 'imagem' && previa) {
      chip.innerHTML = `
        <div class="anexo-previa">
          <img src="${esc(previa)}" alt="Prévia da imagem">
          ${enviando ? '<span class="anexo-previa-enviando" aria-label="Enviando"></span>' : BOTAO_REMOVER}
        </div>`;
      return;
    }
    const imagem = tipo === 'imagem';
    chip.innerHTML = `
      <span class="anexo-chip-icone${imagem ? ' ladrilho-imagem' : ''}">${imagem ? ICONES.imagem : ICONES.xlsx}</span>
      <div class="anexo-chip-texto">
        <div class="anexo-chip-nome">${esc(nome)}</div>
        <div class="anexo-chip-detalhe">${esc(detalhe)}</div>
      </div>
      ${enviando ? '' : BOTAO_REMOVER}`;
  };

  const mostrarAnexo = (etiqueta) => {
    state.anexo = etiqueta;
    const d = etiqueta.detalhe || {};
    const detalhe = etiqueta.tipo === 'imagem'
      ? 'Imagem'
      : `${fmtNum(d.linhas || 0)} linhas · ${fmtNum((d.colunas || []).length)} colunas · diga o que preencher`;
    desenharChip({ nome: etiqueta.nome, tipo: etiqueta.tipo, detalhe, previa: etiqueta.previa });
    atualizarBotao();
  };

  const limparAnexo = ({ liberarPrevia = false } = {}) => {
    // A prévia local continua valendo depois do envio: é ela que aparece na
    // bolha até a miniatura do servidor chegar. Só é liberada ao remover.
    if (liberarPrevia && state.anexo?.previa) URL.revokeObjectURL(state.anexo.previa);
    state.anexo = null;
    const chip = $('#anexoChip');
    chip.hidden = true;
    chip.classList.remove('imagem', 'enviando');
    chip.innerHTML = '';
    $('#campoAnexo').value = '';
  };

  const subirAnexo = async (arquivo) => {
    if (!arquivo || state.aguardando || state.anexoEnviando) return;
    if (!EXTENSOES_ACEITAS.test(arquivo.name || '')) {
      toast('Envie uma planilha (.xlsx, .csv) ou uma imagem (.png, .jpg, .webp).', true);
      return;
    }
    // Checagem prévia só para poupar a subida; quem decide é o servidor.
    if (arquivo.size > LIMITE_DO_ANEXO) {
      toast(`O arquivo tem ${fmtBytes(arquivo.size)}; o limite é 5 MB. Envie um recorte menor.`, true);
      return;
    }

    const tipo = arquivo.type.startsWith('image/') ? 'imagem' : 'planilha';
    // Prévia na hora, do próprio arquivo: não depende da subida terminar.
    const previa = tipo === 'imagem' ? URL.createObjectURL(arquivo) : null;
    state.anexoEnviando = true;
    atualizarBotao();
    desenharChip({ nome: arquivo.name, tipo, detalhe: `Enviando ${fmtBytes(arquivo.size)}…`, enviando: true, previa });

    try {
      const corpo = new FormData();
      corpo.append('arquivo', arquivo, arquivo.name);
      const r = await fetch('/api/anexos/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'X-CSRFToken': decodeURIComponent(csrf()) },
        body: corpo,
      });
      const dados = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(dados.error || `Erro ${r.status}`);
      state.anexoEnviando = false;
      mostrarAnexo({ ...dados, previa });
      $('#campoPergunta').focus();
    } catch (e) {
      state.anexoEnviando = false;
      if (previa) URL.revokeObjectURL(previa);
      limparAnexo();
      atualizarBotao();
      toast(e.message, true);
    }
  };

  $('#btnAnexar').addEventListener('click', () => $('#campoAnexo').click());
  $('#campoAnexo').addEventListener('change', (ev) => subirAnexo(ev.target.files[0]));
  $('#anexoChip').addEventListener('click', (ev) => {
    if (ev.target.closest('.anexo-chip-remover')) { limparAnexo({ liberarPrevia: true }); atualizarBotao(); }
  });
  // Print colado com Ctrl+V: é o jeito mais comum de alguém "mandar um print".
  $('#campoPergunta').addEventListener('paste', (ev) => {
    const item = [...(ev.clipboardData?.items || [])].find((i) => i.kind === 'file' && i.type.startsWith('image/'));
    if (!item) return;
    ev.preventDefault();
    const bruto = item.getAsFile();
    const extensao = (bruto.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
    subirAnexo(new File([bruto], `print-colado.${extensao}`, { type: bruto.type }));
  });

  $('#campoPergunta').addEventListener('input', () => { ajustarCampo(); atualizarBotao(); });
  $('#campoPergunta').addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      enviar($('#campoPergunta').value);
    }
  });
  $('#formPergunta').addEventListener('submit', (ev) => {
    ev.preventDefault();
    if (state.aguardando) interromper(); else enviar($('#campoPergunta').value);
  });


  // ---------------------------------------------------------- passeio
  // O mascote abre a apresentação do Jarvis. Sete quadros, um assunto cada,
  // em tela cheia: no cartão pequeno de antes as cenas ficavam do tamanho de
  // um ícone, e elas são o que explica — o texto só legenda.
  //
  // O Jarvis é um personagem só do começo ao fim. Ele sai voando do lugar
  // onde foi clicado, troca de estado a cada quadro (vivo, pensando,
  // consultando) sem ser redesenhado, e no fim volta para o mesmo lugar.
  // O que é remontado a cada quadro são os objetos em volta dele e a
  // legenda: animação de CSS só toca do começo quando o nó é novo.
  const PASSEIO = [
    {
      titulo: 'Oi, eu sou o Jarvis',
      texto: 'Eu respondo perguntas sobre os dados da Ease Labs. É só perguntar: eu consulto os dados e mostro de onde veio cada número.',
      estado: 'jarvis--vivo',
      objetos: `
        <span class="cena-brilho cena-brilho--1"></span>
        <span class="cena-brilho cena-brilho--2"></span>
        <span class="cena-brilho cena-brilho--3"></span>
        <span class="cena-oi">Oi!</span>`,
    },
    {
      titulo: 'Pergunte como você fala',
      texto: 'Nada de filtro nem menu. "Quantas unidades a Pague Menos dispensou por mês em 2026?" já é uma pergunta inteira.',
      estado: 'jarvis--pensando',
      objetos: `
        <span class="cena-balao cena-balao--pergunta">Quantas unidades a Pague Menos<br>dispensou por mês em 2026?</span>
        <span class="cena-balao cena-balao--resposta"><i></i><i></i><i></i></span>
        <span class="cena-balao cena-balao--numero"><b>1,2 mi</b> un. · jan–ago</span>`,
    },
    {
      titulo: 'Todo número tem fonte',
      texto: 'Embaixo de cada resposta, "Ver fonte e consulta" abre a consulta que rodou no banco. E é sempre leitura: eu nunca altero o dado na origem.',
      estado: 'jarvis--consultando',
      objetos: `
        <span class="cena-sql">
          <span><b>SELECT</b> rede, <b>SUM</b>(und)</span>
          <span><b>FROM</b> cddd.vendas</span>
          <span><b>WHERE</b> competencia = 202608</span>
        </span>
        <span class="cena-tabela">
          <i style="--w:70%"></i><i style="--w:44%"></i><i style="--w:58%"></i>
        </span>
        <span class="cena-cadeado">somente leitura</span>`,
    },
    {
      titulo: 'Também respondo "por quê"',
      texto: 'Pergunta de causa vira investigação: eu levanto hipóteses, testo uma por uma no banco e cruzo as áreas antes de concluir.',
      estado: 'jarvis--pensando',
      objetos: `
        <span class="cena-hipotese cena-hipotese--1">rede?</span>
        <span class="cena-hipotese cena-hipotese--2">produto?</span>
        <span class="cena-hipotese cena-hipotese--3">mercado?</span>
        <svg class="cena-fios" viewBox="0 0 220 150" aria-hidden="true">
          <path d="M60 46 L110 88" /><path d="M110 40 L112 84" /><path d="M162 46 L118 88" />
        </svg>`,
    },
    {
      titulo: 'Traga sua planilha ou um print',
      texto: 'Eu preencho a sua planilha com os dados do banco e leio um print para analisar. O arquivo não fica guardado: sai da conversa e é descartado.',
      estado: 'jarvis--consultando',
      objetos: `
        <span class="cena-folha">
          <b></b>
          <i style="--w:62%"></i><i style="--w:40%"></i><i style="--w:52%"></i>
        </span>
        <span class="cena-print"></span>
        <span class="cena-descartado">print descartado</span>`,
    },
    {
      titulo: 'Pode perguntar',
      texto: 'Gráfico e Excel saem prontos, e se algo demorar ou sair torto, o botão de parar interrompe na hora. Estou aqui do lado.',
      estado: 'jarvis--vivo',
      objetos: `
        <span class="cena-grafico">
          <i style="--h:34%"></i><i style="--h:62%"></i><i style="--h:46%"></i><i style="--h:88%"></i>
        </span>`,
    },
    {
      // O fim do passeio (2026-09-25): o Jarvis se transforma. Uma faixa de
      // luz desce pelo corpo e a armadura surge por onde ela passa — é ele
      // mudando, não uma imagem trocada. Depois os jatos acendem e ele sobe.
      titulo: 'Pronto para decolar',
      texto: 'Passeio concluído! O J.A.R.V.I.S. fica com o trabalho pesado nos dados, e você com as decisões. É só perguntar.',
      estado: 'jarvis--vivo jarvis--armadura',
      objetos: `
        <span class="cena-estrela cena-estrela--1"></span>
        <span class="cena-estrela cena-estrela--2"></span>
        <span class="cena-estrela cena-estrela--3"></span>
        <span class="cena-estrela cena-estrela--4"></span>`,
    },
  ];

  const semMovimento = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let quadro = 0;
  let origemDoPasseio = null;   // o mascote clicado: é de lá que o Jarvis sai e para lá que volta
  let passeioFechando = false;

  // O voo: o Jarvis do palco começa em cima do mascote clicado, no tamanho
  // dele, e vai para o centro (ou o contrário, na volta). É o mesmo truque
  // de sempre — medir os dois, desenhar no destino, animar a diferença. O
  // ator mora dentro de um palco escalado, então a distância medida na tela
  // é dividida pela escala antes de virar `translate`.
  // Na tela e com tamanho: a lateral recolhida ainda mostra o mascote, a
  // gaveta fechada do celular o deixa fora da tela.
  const naTela = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.right > 0 && r.left < innerWidth && r.bottom > 0 && r.top < innerHeight;
  };
  const mascoteDaLateral = () => $('#btnLogoHome .marca-jarvis');

  // `desde`: onde o ator está quando o voo começa. No último quadro ele
  // paira mais alto e maior; sem isto, a volta começava do tamanho normal e
  // ele encolhia num tranco antes de sair voando.
  const voar = (de, ator, volta = false, desde = 'none') => {
    if (semMovimento() || !naTela(de)) return Promise.resolve();
    const a = de.getBoundingClientRect();
    // medido sem o transform próprio: as contas são do lugar dele no palco
    const guardado = ator.style.transform;
    ator.style.transform = 'none';
    const b = ator.getBoundingClientRect();
    ator.style.transform = guardado;
    if (!b.width) return Promise.resolve();
    const escala = b.width / ator.offsetWidth;
    const dx = (a.left + a.width / 2 - (b.left + b.width / 2)) / escala;
    const dy = (a.top + a.height / 2 - (b.top + b.height / 2)) / escala;
    const quadros = [
      { transform: `translate(${dx}px, ${dy}px) scale(${a.width / b.width})` },
      { transform: `translate(${dx * 0.45}px, ${dy * 0.45 - 30}px) scale(${(a.width / b.width + 1) / 2})`, offset: 0.55 },
      { transform: desde },
    ];
    const voo = ator.animate(volta ? quadros.reverse() : quadros, {
      duration: volta ? 480 : 680,
      easing: volta ? 'cubic-bezier(0.55, 0, 0.75, 0.3)' : 'cubic-bezier(0.22, 1, 0.36, 1)',
      fill: 'both',
    });
    return voo.finished.then(() => voo.cancel(), () => {});
  };

  const desenharQuadro = (direcao = 'frente') => {
    const q = PASSEIO[quadro];
    const walk = $('#walk');
    walk.dataset.direcao = direcao;
    walk.dataset.quadro = String(quadro);
    $('#walkPalco').innerHTML = q.objetos;
    $('#walkLegenda').innerHTML = `
      <span class="walk-contador">${quadro + 1} de ${PASSEIO.length}</span>
      <h2 class="walk-titulo" id="walkTitulo">${esc(q.titulo)}</h2>
      <p class="walk-texto">${esc(q.texto)}</p>`;
    // O mesmo Jarvis, outro estado: trocar a classe não o redesenha, então
    // a órbita segue de onde estava em vez de recomeçar a cada quadro.
    const svg = $('#walkAtor svg');
    if (svg) svg.setAttribute('class', `jarvis ${q.estado}`);
    $('#walkPontos').innerHTML = PASSEIO.map((_, i) =>
      `<button class="walk-ponto${i < quadro ? ' feito' : ''}${i === quadro ? ' atual' : ''}" type="button" role="tab"
        aria-selected="${i === quadro}" aria-label="Quadro ${i + 1}: ${esc(PASSEIO[i].titulo)}" data-quadro="${i}"><i></i></button>`).join('');
    $('#walkVoltar').hidden = quadro === 0;
    const ultimo = quadro === PASSEIO.length - 1;
    $('#walkProximo').textContent = ultimo ? 'Começar a perguntar' : 'Próximo';
    $('#walkProximo').classList.toggle('walk-proximo--fim', ultimo);
  };

  // O pulinho de quando o quadro muda: o ator reage à troca de assunto.
  const pular = () => {
    const ator = $('#walkAtor');
    ator.classList.remove('pula');
    void ator.offsetWidth;   // reinicia a animação
    ator.classList.add('pula');
  };

  // A marca do primeiro acesso é gravada quando o passeio SOBE, não quando
  // ele termina: fechar no primeiro quadro é uma resposta, e reabrir a cada
  // login seria empurrar. Falhar aqui não atrapalha ninguém — no máximo a
  // apresentação abre de novo no próximo login.
  const marcarPasseioVisto = () => {
    if (!state.usuario?.passeio_pendente) return;
    state.usuario.passeio_pendente = false;
    api('/api/auth/passeio/', { method: 'POST', body: {} }).catch(() => {});
  };

  const abrirPasseio = (origem) => {
    if (!$('#walk').hidden) return;
    marcarPasseioVisto();
    origemDoPasseio = origem instanceof Element ? origem : $('#btnLogoHome .marca-jarvis');
    passeioFechando = false;
    const parouNo = lerChave(CHAVE_PASSEIO) ? 0 : Number(lerChave(CHAVE_QUADRO) || 0);
    quadro = parouNo > 0 && parouNo < PASSEIO.length ? parouNo : 0;
    // Com as peças da armadura: só o último quadro as acende.
    $('#walkAtor').innerHTML = jarvis('jarvis--vivo', true, true);
    $('#walkAtor').classList.remove('pula');
    desenharQuadro();
    const walk = $('#walk');
    walk.classList.remove('saindo');
    walk.hidden = false;
    // Enquanto o Jarvis está no palco, o lugar de onde ele saiu fica vazio.
    origemDoPasseio?.classList.add('jarvis-emprestado');
    voar(origemDoPasseio, $('#walkAtor'));
    $('#walkProximo').focus({ preventScroll: true });
  };

  // A despedida do último quadro: a armadura se recolhe ANTES do voo (a faixa
  // de luz sobe, o inverso da chegada), e o Jarvis pousa na lateral já como o
  // mascote de sempre. Antes ele pousava
  // de armadura e virava o outro de uma vez (2026-09-25). Devolve onde ele
  // estava (pairando, maior), para o voo partir dali sem tranco.
  const desarmar = async (ator) => {
    const svg = ator.querySelector('svg');
    if (!svg?.classList.contains('jarvis--armadura') || semMovimento()) return 'none';
    const desde = getComputedStyle(ator).transform;
    ator.style.transform = desde === 'none' ? '' : desde;
    // Sem o quadro 7, o pulinho da troca de quadro (`pula`) voltava a valer e
    // passava por cima: ele encolhia, pulava e crescia de novo antes do voo.
    ator.classList.remove('pula');
    // solta a animação de pairar sem que ele pule: o transform fica preso
    // no lugar em que estava
    $('#walk').dataset.quadro = 'saindo';
    svg.classList.remove('jarvis--armadura');
    svg.classList.add('jarvis--desarmando');
    // A faixa leva 0,6 s para subir; o voo sai no finzinho dela, sem pausa.
    await new Promise((ok) => setTimeout(ok, 520));
    return desde;
  };

  const fecharPasseio = async ({ perguntar = false } = {}) => {
    const walk = $('#walk');
    if (walk.hidden || passeioFechando) return;
    passeioFechando = true;
    const concluiu = perguntar || quadro === PASSEIO.length - 1;
    if (concluiu) {
      gravarChave(CHAVE_PASSEIO, '1');
      try { localStorage.removeItem(CHAVE_QUADRO); } catch { /* navegação privada */ }
    } else {
      gravarChave(CHAVE_QUADRO, String(quadro));
    }
    // Na volta o Jarvis pousa na lateral, mesmo que tenha saído das
    // boas-vindas: é lá que ele mora, e é lá que se clica para revê-lo.
    const lateral = mascoteDaLateral();
    const destino = naTela(lateral) ? lateral : origemDoPasseio;
    destino?.classList.add('jarvis-emprestado');
    const ator = $('#walkAtor');
    const desde = await desarmar(ator);
    walk.classList.add('saindo');
    await Promise.all([
      voar(destino, ator, true, desde),
      new Promise((ok) => setTimeout(ok, semMovimento() ? 0 : 260)),
    ]);
    ator.style.transform = '';
    walk.hidden = true;
    walk.classList.remove('saindo');
    $('#walkPalco').innerHTML = '';   // para as animações da cena
    $('#walkAtor').innerHTML = '';
    origemDoPasseio?.classList.remove('jarvis-emprestado');
    destino?.classList.remove('jarvis-emprestado');
    origemDoPasseio = null;
    passeioFechando = false;
    convidarParaPasseio();
    // Quem concluiu não precisa mais da linha de convite; quem parou no
    // meio passa a ver "continuar" na próxima conversa nova.
    if (concluiu) {
      $('#boasVindas')?.classList.remove('boas-vindas--convite');
      $('.convite-passeio')?.remove();
    }
    if (destino === lateral) acenarNaLateral();
    if (perguntar) $('#campoPergunta').focus();
  };

  // O pouso: o mascote da lateral acena ao receber o Jarvis de volta — é o
  // gesto que mostra onde ele mora, sem precisar de recado.
  const acenarNaLateral = () => {
    const botao = $('#btnLogoHome');
    botao.classList.remove('acenando');
    void botao.offsetWidth;   // reinicia o aceno
    botao.classList.add('acenando');
  };
  $('#btnLogoHome').addEventListener('animationend', (ev) => {
    if (ev.animationName === 'jarvisAcena') $('#btnLogoHome').classList.remove('acenando');
  });

  const irParaQuadro = (i) => {
    if (passeioFechando || i === quadro) return;
    if (i >= PASSEIO.length) return fecharPasseio({ perguntar: true });
    if (i < 0) return;
    const direcao = i > quadro ? 'frente' : 'tras';
    quadro = i;
    desenharQuadro(direcao);
    pular();
  };

  $('#walkProximo').addEventListener('click', () => irParaQuadro(quadro + 1));
  $('#walkVoltar').addEventListener('click', () => irParaQuadro(quadro - 1));
  $('#walkFechar').addEventListener('click', () => fecharPasseio());
  $('#walkPontos').addEventListener('click', (ev) => {
    const ponto = ev.target.closest('[data-quadro]');
    if (ponto) irParaQuadro(Number(ponto.dataset.quadro));
  });
  // Clicar no próprio Jarvis também avança: é o primeiro lugar em que se
  // clica numa tela cheia, e ele está ali justamente para isso.
  $('#walkAtor').addEventListener('click', () => irParaQuadro(quadro + 1));
  document.addEventListener('keydown', (ev) => {
    if ($('#walk').hidden) return;
    if (ev.key === 'Escape') fecharPasseio();
    if (ev.key === 'ArrowRight') irParaQuadro(quadro + 1);
    if (ev.key === 'ArrowLeft') irParaQuadro(quadro - 1);
  });
  // No celular o passeio se navega arrastando, como qualquer onboarding.
  let toqueX = null;
  $('#walk').addEventListener('touchstart', (ev) => { toqueX = ev.touches[0].clientX; }, { passive: true });
  $('#walk').addEventListener('touchend', (ev) => {
    if (toqueX === null) return;
    const dx = ev.changedTouches[0].clientX - toqueX;
    toqueX = null;
    if (Math.abs(dx) > 50) irParaQuadro(quadro + (dx < 0 ? 1 : -1));
  });
  // O mascote grande das boas-vindas e a linha de convite abrem o passeio,
  // e o Jarvis sai de lá — não da lateral.
  $('#mensagens').addEventListener('click', (ev) => {
    const gatilho = ev.target.closest('[data-passeio]');
    if (!gatilho) return;
    abrirPasseio($('#boasVindas .boas-vindas-marca') || undefined);
  });
  convidarParaPasseio();

  // ---------------------------------------------------------- limites
  // Quanto a pessoa já usou hoje. Existe para a cota não ser uma surpresa:
  // descobrir o limite no instante em que ele bate é a pior hora de saber
  // que ele existe.
  // Em percentual, não "7 de 20": a pessoa quer saber quanto já foi e se
  // está perto do fim, e o número absoluto obriga a fazer a conta. A partir
  // de 80% a barra fica âmbar e avisa — descobrir que acabou só quando acaba
  // é o que esta tela existe para evitar.
  const PERTO_DO_LIMITE = 80;

  // Cada janela é uma linha: rótulo e prazo à esquerda, barra no meio,
  // porcentagem à direita. Empilhar rótulo, barra e nota (como estava) dá
  // três alturas por limite e faz o painel parecer um formulário; em linha,
  // os dois limites se comparam num olhar.
  // Só a porcentagem. A pessoa precisa saber se está perto do fim, não
  // contar quantas sobraram — e a conta nem chega aqui: a API manda a
  // porcentagem já pronta.
  const janelaDaCota = (titulo, j, quando) => {
    const nivel = j.excedeu ? 'cheia' : (j.pct >= PERTO_DO_LIMITE ? 'perto' : 'ok');
    const prazo = j.excedeu ? `Cota usada. Volta ${quando}.` : `Renova ${quando}.`;
    return `
      <div class="cota-item cota-item--${nivel}">
        <div class="cota-rotulo">
          <strong>${esc(titulo)}</strong>
          <span>${esc(prazo)}</span>
        </div>
        <div class="cota-barra"><i style="--p:${Math.min(j.pct, 100)}%"></i></div>
        <div class="cota-pct"><strong>${j.pct}% usado</strong></div>
      </div>`;
  };

  const corpoDosLimites = (d) => {
    const agora = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    const rodape = `
      <div class="cota-rodape">
        <span>Atualizado às ${esc(agora)}</span>
        <button class="cota-atualizar" type="button" id="btnAtualizarCota" aria-label="Atualizar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 11-2.6-6.4M21 4v5h-5"/></svg>
        </button>
      </div>`;

    if (!d.dia) {
      return `
        <div class="cota">
          <div class="cota-item">
            <div class="cota-rotulo">
              <strong>Perguntas por dia</strong>
              <span>Sua conta não tem cota. Pergunte à vontade.</span>
            </div>
            <div class="cota-pct"><strong>Sem limite</strong></div>
          </div>
          ${rodape}
        </div>`;
    }
    const segunda = new Date(`${d.semana_renova_em}T00:00:00`).toLocaleDateString('pt-BR', {
      day: '2-digit', month: '2-digit',
    });
    return `
      <div class="cota">
        ${janelaDaCota('Hoje', d.dia, 'à meia\u2011noite')}
        ${janelaDaCota('Esta semana', d.semana, `na segunda, ${segunda}`)}
        ${rodape}
      </div>`;
  };

  const desenharCota = async () => {
    try {
      $('#modalCorpo').innerHTML = corpoDosLimites(await api('/api/auth/limites/'));
    } catch (e) {
      $('#modalCorpo').innerHTML = `<p class="modal-texto">Não consegui ler a sua cota agora: ${esc(e.message)}</p>`;
    }
  };

  // A partir de 80% da janela mais apertada, uma faixa âmbar acima do campo
  // de pergunta. O aviso mora aqui, e não num canto qualquer, porque é aqui
  // que a pessoa está quando a informação importa: um passo antes de gastar
  // a próxima pergunta. Descobrir o limite só quando ele bate é a pior hora
  // de saber que ele existe.
  const avisarDaCota = async () => {
    const faixa = $('#avisoCota');
    if (!faixa) return;
    try {
      const d = await api('/api/auth/limites/');
      // A mais apertada das duas manda: adiantar o fim da semana quando o
      // dia ainda está folgado é o caso que mais pega gente de surpresa.
      const janelas = [
        { j: d.dia, prazo: 'à meia\u2011noite', qual: 'diário' },
        { j: d.semana, prazo: 'na segunda', qual: 'semanal' },
      ].filter((x) => x.j);
      const pior = janelas.sort((a, b) => b.j.pct - a.j.pct)[0];
      if (!pior || pior.j.pct < PERTO_DO_LIMITE) { faixa.hidden = true; return; }
      faixa.textContent = pior.j.excedeu
        ? `Você atingiu 100% do limite de perguntas ${pior.qual}. A cota volta ${pior.prazo}.`
        : `Você já usou ${pior.j.pct}% do limite de perguntas ${pior.qual}. A cota renova ${pior.prazo}.`;
      faixa.classList.toggle('cheia', pior.j.excedeu);
      faixa.hidden = false;
    } catch {
      faixa.hidden = true;  // a cota não é motivo para atrapalhar quem pergunta
    }
  };

  const verLimites = async () => {
    fecharDropdown();
    abrirModal({
      titulo: 'Seus limites de uso',
      corpo: '<div class="cota cota-carregando"></div>',
      acao: null,
    });
    // Recarrega sem fechar: a cota muda enquanto a pessoa usa o app.
    modal.querySelector('.modal').classList.add('largo');
    $('#modalCorpo').onclick = (ev) => { if (ev.target.closest('#btnAtualizarCota')) desenharCota(); };
    await desenharCota();
  };

  $('#btnLimites').addEventListener('click', verLimites);

  // ---------------------------------------------------------- visor
  // A miniatura abre aqui dentro, em cima da conversa. Antes ela era um link
  // para o blob, que abria uma aba com a imagem solta, fora do Jarvis.
  const abrirVisor = (src) => {
    $('#visorImagem').src = src;
    $('#visor').hidden = false;
  };

  const fecharVisor = () => {
    $('#visor').hidden = true;
    $('#visorImagem').removeAttribute('src');
  };

  $('#mensagens').addEventListener('click', (ev) => {
    const alvo = ev.target.closest('.bolha-imagem');
    if (alvo?.dataset.visor) abrirVisor(alvo.dataset.visor);
  });
  // Clicar no fundo fecha; clicar na própria imagem, não.
  $('#visor').addEventListener('click', (ev) => {
    if (!ev.target.closest('#visorImagem')) fecharVisor();
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !$('#visor').hidden) fecharVisor();
  });

  // ---------------------------------------------------------- ditado
  // O reconhecimento de fala é do próprio navegador: não passa pelo nosso
  // servidor, não chama a IA e não custa nada. Duas regras de desenho:
  //
  //   1. o texto cai no campo para quem falou revisar antes de enviar —
  //      ditado que envia sozinho erra uma vez e ninguém usa de novo;
  //   2. o jargão da casa passa por uma lista nossa, porque o navegador
  //      reconhece português geral e devolve "cell out" para "sell out".
  //      A lista é para crescer: toda palavra que voltar torta entra aqui.
  //
  // Onde o navegador não ouve (Firefox), o botão não aparece: melhor não ter
  // do que ter quebrado.
  const CORRECOES_DO_DITADO = [
    [/\b(?:cell|cel|sel|self)[\s-]?out\b/gi, 'sell out'],
    [/\bs?el+(?:aute|auti)\b/gi, 'sell out'],
    [/\b(?:cell|cel|sel)[\s-]?in\b/gi, 'sell in'],
    [/\b(?:is|iz|ease|eas)[\s-]?labs?\b/gi, 'Ease Labs'],
    [/\bp[eê]\s?b[eê]\s?eme\b/gi, 'PBM'],
    [/\bp[eê]\s?xis\b/gi, 'PX'],
    // Sem \b no fim: a borda de palavra do JavaScript não enxerga o "ê".
    [/\bc[eê]\s?d[eê]\s?d[eê](?![a-z])/gi, 'CDD'],
    [/\bmarket[\s-]?(?:cher|xer|sher|cheer)\b/gi, 'market share'],
    [/\besquiu\b/gi, 'SKU'],
    [/\bfor[eé]cast(?:e)?\b/gi, 'forecast'],
    [/\bdash\s?bor(?:d|de)\b/gi, 'dashboard'],
  ];

  const corrigirJargao = (texto) =>
    CORRECOES_DO_DITADO.reduce((t, [de, para]) => t.replace(de, para), texto);

  // Declarado aqui e usado lá em cima no envio: quem apertou Enter não pode
  // deixar o microfone escrevendo na caixa que acabou de esvaziar.
  let pararDitado = () => {};

  const Reconhecimento = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Reconhecimento) {
    const btnDitar = $('#btnDitar');
    const rec = new Reconhecimento();
    rec.lang = 'pt-BR';
    rec.continuous = true;
    rec.interimResults = true;

    let ditando = false;  // o que a pessoa quer; o navegador para sozinho
    let base = '';        // o que já estava escrito quando o microfone abriu
    let firmado = '';     // o que o navegador deu por certo nesta rodada

    // Trima cada pedaço e junta com um espaço. Não mexe no miolo da base:
    // quem escreveu em duas linhas e resolveu ditar o resto mantém as linhas.
    const juntar = (...partes) => partes
      .map((p) => String(p || '').trim())
      .filter(Boolean)
      .join(' ');

    const escrever = (parcial = '') => {
      const campo = $('#campoPergunta');
      campo.value = juntar(base, firmado, parcial);
      ajustarCampo();
      atualizarBotao();
    };

    const marcar = (ouvindo) => {
      btnDitar.setAttribute('aria-pressed', String(ouvindo));
      btnDitar.setAttribute('aria-label', ouvindo ? 'Parar de ditar' : 'Ditar a pergunta');
      btnDitar.title = ouvindo ? 'Parar de ditar' : 'Ditar a pergunta pelo microfone';
    };

    rec.addEventListener('result', (ev) => {
      let parcial = '';
      for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
        const trecho = ev.results[i][0].transcript;
        // A correção só entra no que já está firme: o provisório ainda muda.
        if (ev.results[i].isFinal) firmado = juntar(firmado, corrigirJargao(trecho));
        else parcial = juntar(parcial, trecho);
      }
      escrever(parcial);
    });

    rec.addEventListener('error', (ev) => {
      ditando = false;
      if (ev.error === 'not-allowed' || ev.error === 'service-not-allowed') {
        toast('Preciso da permissão do microfone: libere no cadeado da barra de endereço.', true);
      } else if (ev.error === 'network') {
        toast('O reconhecimento de fala não respondeu. Tente de novo.', true);
      }
      // 'no-speech' e 'aborted' são silêncio e desistência: não viram aviso.
    });

    // O navegador encerra sozinho depois de alguns segundos calado. Se a
    // pessoa não mandou parar, o que ela ditou vira base e o microfone volta;
    // assim ninguém perde a frase por ter pensado no meio dela.
    rec.addEventListener('end', () => {
      escrever();
      if (!ditando) { marcar(false); return; }
      base = juntar(base, firmado);
      firmado = '';
      try {
        rec.start();
      } catch {
        ditando = false;
        marcar(false);
      }
    });

    pararDitado = () => {
      if (!ditando) return;
      ditando = false;
      marcar(false);
      rec.stop();
    };

    btnDitar.addEventListener('click', () => {
      if (ditando) { pararDitado(); return; }
      base = $('#campoPergunta').value;
      firmado = '';
      ditando = true;
      marcar(true);
      try {
        rec.start();
      } catch {
        // start() com a sessão anterior ainda encerrando: o próximo clique pega.
        ditando = false;
        marcar(false);
      }
      $('#campoPergunta').focus();
    });

    btnDitar.hidden = false;
  }

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

  // O palco do login: uma pergunta de exemplo entra, o Jarvis consulta a
  // tabela de onde a resposta sairia, e a resposta chega com a fonte. Sem
  // número: o que ele mostra é o caminho, que é o que o produto promete.
  // As tabelas são as do catálogo, para ninguém do BI estranhar o nome.
  const DEMOS = [
    { pergunta: 'Quantas adesões ao PBM tivemos por mês em 2026?', onde: 'pbm.fato_pbm_adesoes' },
    { pergunta: 'Como evoluiu a prescrição da Ease mês a mês?', onde: 'audit.vw_fato_prescricao_remota' },
    { pergunta: 'Qual foi o sell-in por rede em agosto?', onde: 'estoque_redes.fato_sell_in' },
    { pergunta: 'Por que a prescrição caiu em maio?', onde: '3 hipóteses, uma por uma', porque: true },
  ];
  const palco = { demo: 0, timers: [] };
  const estadoDoJarvis = (estado) => {
    $('#loginJarvis').setAttribute('class', `jarvis jarvis--${estado} login-jarvis`);
  };
  // Um gesto por cima do estado: `nega` (balança a cabeça) e `chegou` (o pulo).
  const gestoDoJarvis = (gesto) => {
    const j = $('#loginJarvis');
    j.classList.remove('login-nega', 'jarvis--chegou');
    void j.getBoundingClientRect();   // reinicia a animação
    j.classList.add(gesto === 'nega' ? 'login-nega' : 'jarvis--chegou');
  };
  const pararPalco = () => { palco.timers.forEach(clearTimeout); palco.timers = []; };
  const depois = (ms, fn) => palco.timers.push(setTimeout(fn, ms));
  const rodarDemo = () => {
    pararPalco();
    const d = DEMOS[palco.demo % DEMOS.length];
    palco.demo += 1;
    $('#loginDemo').innerHTML = `
      <span class="demo-pergunta">${esc(d.pergunta)}</span>
      <span class="demo-consulta"><i></i><i></i><i></i>${d.porque ? 'testando' : 'consultando'} <b>${esc(d.onde)}</b></span>
      <span class="demo-resposta">Resposta pronta, com a fonte e a consulta</span>`;
    estadoDoJarvis('pensando');
    depois(1300, () => estadoDoJarvis('consultando'));
    depois(3500, () => { estadoDoJarvis('vivo'); gestoDoJarvis('chegou'); });
    depois(6400, rodarDemo);
  };
  // Na etapa do código o palco para de encenar e fala com a pessoa.
  const palcoDoCodigo = () => {
    pararPalco();
    $('#loginDemo').innerHTML = `
      <span class="demo-pergunta demo-pergunta--jarvis">Mandei um código para o seu e-mail. É só digitar aqui.</span>`;
    estadoDoJarvis('vivo');
    gestoDoJarvis('chegou');
  };
  const semMovimentoNoLogin = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ligarPalco = () => {
    if (login.etapa === 'codigo') return palcoDoCodigo();
    if (semMovimentoNoLogin()) {
      // Sem animação, o palco mostra a cena já resolvida e não troca sozinho.
      $('#loginDemo').innerHTML = `<span class="demo-pergunta">${esc(DEMOS[0].pergunta)}</span>
        <span class="demo-resposta">Resposta pronta, com a fonte e a consulta</span>`;
      return estadoDoJarvis('vivo');
    }
    rodarDemo();
  };

  // O domínio escrito dentro do campo, logo depois do que a pessoa digitou:
  // um eco invisível do texto empurra o "@easelabs.com.br" para o lugar
  // certo. Com "@" digitado, ele sai.
  const ecoDoEmail = () => {
    const valor = $('#loginEmail').value;
    $('#loginEmailEco').textContent = valor || $('#loginEmail').placeholder;
    $('#campoEmail').classList.toggle('com-arroba', valor.includes('@'));
    $('#campoEmail').classList.toggle('vazio', !valor);
  };
  $('#loginEmail').addEventListener('input', ecoDoEmail);

  // As seis casas desenham o que está no campo invisível por cima delas.
  const casasDoCodigo = () => {
    const campo = $('#loginCodigo');
    const valor = campo.value.replace(/\D/g, '').slice(0, 6);
    const focado = document.activeElement === campo;
    $$('#codigoCasas span').forEach((casa, i) => {
      casa.textContent = valor[i] || '';
      casa.classList.toggle('cheia', i < valor.length);
      casa.classList.toggle('atual', focado && i === Math.min(valor.length, 5));
    });
  };
  ['input', 'focus', 'blur'].forEach((ev) => $('#loginCodigo').addEventListener(ev, casasDoCodigo));

  const erroDoLogin = (texto) => {
    const erro = $('#loginErro');
    erro.textContent = texto || '';
    erro.hidden = !texto;
    if (texto) {
      gestoDoJarvis('nega');
      const campo = login.etapa === 'codigo' ? $('#campoCodigo') : $('#campoEmail');
      campo.classList.remove('treme');
      void campo.offsetWidth;
      campo.classList.add('treme');
    }
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
    ecoDoEmail();
    casasDoCodigo();
    ligarPalco();
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
      pararPalco();
      estadoDoJarvis('consultando');
      try {
        await pedirCodigo();
      } catch (e) {
        estadoDoJarvis('vivo');
        erroDoLogin(e.message);
        botao.textContent = 'Enviar código';
        depois(1800, ligarPalco);
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
    estadoDoJarvis('consultando');
    try {
      const r = await api('/api/auth/entrar/', { method: 'POST', body: { email: login.email, codigo } });
      clearInterval(login.relogio);
      $('#loginCodigo').value = '';
      entrar(r.usuario);
    } catch (e) {
      estadoDoJarvis('vivo');
      erroDoLogin(e.message);
      $('#loginCodigo').select();
      casasDoCodigo();
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
    casasDoCodigo();
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
  $('#btnLogoHome').addEventListener('click', abrirPasseio);

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
