# ADR-0017: interface web em página única, servida pelo Django, com a fonte visível

## Status
Aceito — 2026-09-18.

## Contexto
A Fase 6 entrega a tela do chat (ADR-0007). O usuário pediu que o desenho,
o HTML, o CSS, as animações e as transições fossem análogos aos da
Indicação de PDVs (`indicacao_pdvs_fv/app/public`), que segue o ui-system
oficial da Ease Labs (`ease-labs-ui-system.html`), com o logo da marca.

Três decisões precisavam ser tomadas junto com o desenho: como servir a
página, como autenticar e como levar a fonte de cada número até a tela.

## Decisão
1. **Página única servida pelo próprio Django** (app `web`): um template,
   um `styles.css` e um `app.js`, sem etapa de build e sem framework de
   front. É o mesmo formato da referência, cabe no mesmo contêiner e no
   WhiteNoise que já serve o Admin. As rotas do app (`/conversas/12`)
   devolvem a mesma página, para um F5 não virar 404.
2. **Login por sessão do Django** (ADR-0011), pela API
   (`/api/auth/sessao/`, `/login/`, `/logout/`). Nada de token no
   `localStorage`: o cookie é `HttpOnly`. O CSRF vale **inclusive no
   login** (a autenticação de sessão do DRF só confere quem já está logado;
   o login usa uma classe própria que sempre confere), para outro site não
   conseguir logar a vítima na conta do atacante. Mesma mensagem para
   usuário inexistente e senha errada.
3. **Resposta ligada à pergunta** (`Message.in_reply_to`). A auditoria
   mora no `AIReply` da pergunta; com o vínculo, a API devolve junto de
   cada resposta a `fonte`: decisão, consulta executada, referência usada,
   linhas, se foi cortada, tempo no banco e momento. Custo e tokens só para
   quem é da equipe (`is_staff`). Esclarecimento e "não sei" não trazem
   consulta — mostrar "0 linhas" faria parecer que o banco foi consultado.
4. **Sem dependência de front externa.** O Markdown da resposta (tabelas,
   negrito, listas) é renderizado por um conversor próprio de ~80 linhas
   que **escapa o texto antes de formatar**: nada que o modelo escreva vira
   tag. O mesmo vale para o realce do SQL. Só a fonte Inter vem de fora
   (Google Fonts), como na referência.
5. **Polling** a cada 1,5 s enquanto há pergunta sem resposta, com recuo
   quando a rede falha e limite de 3 minutos. A página retoma a espera se
   for reaberta no meio de uma resposta.

## Consequências
- O desenho reaproveita os tokens e componentes do ui-system (topbar de
  vidro, cartões brancos sobre o gradiente da marca, `fadeInUp`, `popIn`,
  `shimmer`, `prefers-reduced-motion`). Um desvio deliberado: a borda
  esquerda em gradiente do `corp-header` vinha de `border-image`, que
  pinta as quatro bordas e desliga o arredondamento; aqui ela é uma faixa
  própria.
- No celular a lista de conversas vira gaveta, os alvos de toque têm
  44 px e o campo usa 16 px (sem zoom automático no iOS/Android).
- A resposta ao usuário ganha duas regras de redação vindas da primeira
  rodada real na tela: não repetir na frase os números que estão na
  tabela, e destacar o último mês fechado quando o mês corrente é parcial
  (a redação passou a receber a data de hoje).
- Desenvolvimento local precisa de `DEBUG=1` no processo (o `.env` tem
  `DEBUG=0` e, com ele, o WhiteNoise exige `collectstatic`), do worker do
  Celery e do túnel do RDS.
