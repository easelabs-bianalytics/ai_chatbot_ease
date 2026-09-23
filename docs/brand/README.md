# Marca do Jarvis

O Jarvis é o copiloto de dados da Ease Labs (o nome do produto; o papel,
"Copiloto de Dados", aparece na topbar sob ele).

## Arquivos

- `jarvis-mascote.png` — peça principal gerada pela IA de imagem: corpo,
  viseira, olho e a órbita verde. É a referência de desenho.
- `jarvis-icone.png` — a mesma peça reduzida, sem órbita.

## Ícone do app (favicon)

`app/web/static/web/favicon.svg` é o ícone: o mascote, com a órbita, sobre
um ladrilho índigo profundo (`#2E3190` → `#161747`) com um brilho verde no
canto. O ladrilho existe porque a silhueta solta sumia na aba escura do
navegador e virava uma mancha roxa em 16 px. Dele saem, renderizados do
mesmo SVG:

- `favicon-32.png` — reserva para navegador que não lê SVG;
- `apple-touch-icon.png` (180 px) — tela inicial do iPhone, sem cantos
  arredondados (o iOS arredonda sozinho).

Mudou o SVG, gere os dois PNGs de novo a partir dele.

## Como o app desenha

A aplicação **não usa esses PNGs em tela**: o mascote é redesenhado em SVG
inline (`jarvis()` em `app/web/static/web/app.js`, e uma cópia estática no
`index.html` para a tela inicial e o login). Assim ele fica nítido em
qualquer tamanho, pesa cerca de 1 KB e cada parte pode ser animada por CSS.

Medidas do SVG (viewBox 64×64), tiradas do PNG original:

| parte   | geometria                                   | cor                        |
|---------|---------------------------------------------|----------------------------|
| corpo   | `rect x=17 y=11.9 w=30 h=40.3 rx=15`        | `--primary-600` `#5558D4`  |
| viseira | `rect x=18.4 y=21.6 w=27.2 h=9.8 rx=4.9`    | `--primary-950` `#1E1F5C`  |
| olho    | `circle cx=40 cy=26.5 r=2.4`                | `--brand-green` `#6ECC64`  |
| órbita  | elipse `cx=32 cy=40 rx=25 ry=8` a -14°, partida em duas metades | `--brand-green` |

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
