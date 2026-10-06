# Marca do Jarvis

O Jarvis é o copiloto de dados da Ease Labs (o nome do produto; o papel,
"Copiloto de Dados", aparece na topbar sob ele).

## Arquivos

- `jarvis-mascote.png` — peça principal gerada pela IA de imagem: corpo,
  viseira, olho e a órbita verde. É a referência de desenho.
- `jarvis-icone.png` — a mesma peça reduzida, sem órbita.

## Ícone do app (favicon)

`app/web/static/web/favicon.svg` é o ícone: a opção **H** de
`jarvis-3.0-favicons.html`, escolhida em 2026-10-06 depois de testar a G (só
a viseira) na prática — um close no rosto do mascote 3.0 (viseira, olho e o
anel atravessando, cortados pelas bordas) sobre um ladrilho lavanda claro
(`#EEF0FF`). O close deixa o Jarvis legível em 16 px; o ladrilho existe
porque a silhueta solta sumia na aba escura do navegador. Do SVG saem,
renderizados:

- `favicon.png` (512 px) e `favicon-32.png` — reserva para navegador que não lê SVG;
- `apple-touch-icon.png` (180 px) — tela inicial do iPhone, sem cantos
  arredondados (o iOS arredonda sozinho).

Mudou o SVG, gere os dois PNGs de novo a partir dele.

## Como o app desenha

A aplicação **não usa esses PNGs em tela**: o mascote é redesenhado em SVG
inline (`jarvis()` em `app/web/static/web/app.js`, e uma cópia estática no
`index.html` para a tela inicial e o login). Assim ele fica nítido em
qualquer tamanho, pesa cerca de 1 KB e cada parte pode ser animada por CSS.

Medidas do SVG (viewBox 64×64), tiradas do PNG original:

| parte   | geometria                                   | cor (3.0)                                   |
|---------|---------------------------------------------|---------------------------------------------|
| corpo   | `rect x=17 y=11.9 w=30 h=40.3 rx=15`        | gradiente `#7C80F7` → `#4A4DC4` (`#jv3Corpo`) |
| viseira | `rect x=18.4 y=21.6 w=27.2 h=9.8 rx=4.9`    | `--primary-950` `#1E1F5C`                   |
| reflexo | `path M 22.5 24.2 H 33`, traço 0,9          | branco a 30%                                |
| olho    | `circle cx=40 cy=26.5 r=2.4`                | `--brand-green` `#6ECC64`, com brilho       |
| órbita  | elipse `cx=32 cy=40 rx=25 ry=8` a -14°, partida em duas metades | trás `#3E8F38` (opacidade 0,7); frente `#4FB34A` → `#A8F09E` (`#jv3Anel`) |
| satélite | sobre a órbita                             | `--brand-satelite` `#9BE88F`, a cor da auréola, com brilho |

### Jarvis 3.0 ("anel energizado", 2026-10-05)

A geometria é a mesma do 2.0. O que muda é luz e cor: o corpo ganha volume,
a viseira ganha um reflexo e o olho brilha. O corpo saiu de
`jarvis-3.0-propostas.html` (opção 5), em que a folha de planilha no satélite
foi descartada por ficar feia. O anel saiu de `jarvis-3.0-escolha.html`
(opção V, "profundidade no verde", escolhida pelo Rubens): verde escuro e firme
atrás do corpo, e a frente clareando até o satélite, que tem a mesma cor. O
primeiro corte, do verde ao ciano, misturava as duas cores no meio do traço e
deixava o anel "lavado"; as alternativas estão em `jarvis-3.0-aneis*.html`. Os gradientes ficam num
SVG só, `.jarvis-defs`, logo no começo do `<body>` do `index.html`, e o CSS os
referencia (`fill: url(#jv3Corpo)`). Esse SVG tem tamanho zero e não pode
receber `display: none`, porque num SVG escondido o navegador não pinta o
gradiente.

No 2.0 o corpo era `--primary-600` chapado, e o anel e o satélite eram
`--brand-green`.

A órbita é desenhada em duas partes: a metade de trás vem **antes** do corpo
no SVG e a da frente **depois**, como anel de planeta. O satélite também é
duplo, uma cópia em cada metade, cada uma visível só na sua vez — é o que faz
a bolinha sumir atrás do Jarvis e reaparecer na frente. Ela fica na altura da
cintura, não do rosto: no meio do corpo, o arco da frente cortava a viseira.

## Estados (classes de CSS em `styles.css`)

- `jarvis--vivo` — respira devagar e o satélite corre pelo anel. Tela inicial e login. O anel **não gira**: girando 360° ele passa pela vertical e parece atravessar o corpo.
- `jarvis--pensando` — o olhar varre a viseira de um lado ao outro.
- `jarvis--consultando` — a varredura acelera e o olho vira um traço; entra
  quando a pergunta passa para `processing`, isto é, quando o SQL vai ao banco.
- `jarvis--chegou` — um pulo curto, uma vez só, quando a resposta aparece.
- `login-jarvis` (só na tela de entrada) — pisca: o olho fecha por ~110 ms,
  abre, e meio segundo depois vem uma piscada dupla. O grupo `j-olho-g`
  continua flutuando com o corpo; quem pisca é o círculo dentro dele, senão
  as duas animações disputariam o mesmo `transform`. Na conversa ele não
  pisca: ao lado de uma tabela, um olho piscando a cada cinco segundos vira
  mosquito na tela.
- Ao passar o mouse no avatar de uma resposta (`jarvisOlhaPraVoce`): o olho
  sai da ponta da viseira, vai ao centro, cresce, pisca uma vez e volta — ele
  vira o olhar para quem apontou. É o único gesto do olho que não é piscada
  nem varredura, para cada estado continuar com um movimento só dele.
- Sem classe — parado. É assim que ele fica no avatar de cada resposta, para
  não ter vinte mascotes se mexendo na mesma tela.

Tudo isso para com `prefers-reduced-motion: reduce`.
