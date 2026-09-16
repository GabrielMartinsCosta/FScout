# Arquitetura do FScout

## 1. O problema, e a decisão que o resolve

A especificação inicial lista aproximadamente duzentas estatísticas: gols de canhota, gols
de fora da área, gols vindos de escanteio, passes que entram na pequena área, defesas de
chutes de fora da área, cartões no campo de ataque, e assim por diante.

A leitura ingênua desse pedido produz uma tabela com duzentas colunas. Essa abordagem
falha por três motivos, e reconhecer isso é o ponto de partida do projeto:

1. **Não fecha.** A lista é combinatória. "Gol" cruza com pé (3) × região (3) × origem da
   jogada (8) × técnica (7). São centenas de combinações só para finalização, e a próxima
   pergunta do usuário nunca está entre as colunas existentes.
2. **Não evolui.** Cada estatística nova exige alterar schema, migrar banco e reprocessar
   a carga inteira. Em um TCC com prazo fechado, isso consome o prazo.
3. **Não se sustenta na defesa.** Uma coluna `gols_canhota_fora_area` é um número sem
   origem rastreável. Não dá para auditar como foi calculado nem reproduzir o resultado.

**Decisão central: estatística derivada não é coluna, é consulta.**

O sistema armazena *o que aconteceu em campo* — uma linha por ação, com seus qualificadores
— e calcula *o que se quer saber* no momento da pergunta. O exemplo do enunciado vira:

```
evento.tipo = chute
  ∧ chute.resultado = gol
  ∧ chute.parte_do_corpo = pé_esquerdo
  ∧ chute.na_grande_area = falso
  ∧ evento.padrao_de_jogada = de_escanteio
```

Quatro filtros sobre colunas indexadas. Nenhuma coluna nova. A mesma tabela responde
igualmente bem a uma pergunta que ainda não foi feita.

Esta é a contribuição defensável do trabalho: não "mais um painel de estatísticas", mas um
**modelo de eventos com um motor declarativo de métricas** sobre ele.

---

## 2. Camadas

```
┌─────────────────────────────────────────────────────────────────┐
│  viz/        Dash + Plotly — perfil, comparação, exploração     │
├─────────────────────────────────────────────────────────────────┤
│  api/        FastAPI — contrato HTTP, JSON                      │
├─────────────────────────────────────────────────────────────────┤
│  metrics/    Catálogo declarativo + motor de avaliação          │
├─────────────────────────────────────────────────────────────────┤
│  db/         Schema SQLAlchemy, sessão                          │
├─────────────────────────────────────────────────────────────────┤
│  ingestion/  Adaptadores por fonte → vocabulário do domínio     │
├─────────────────────────────────────────────────────────────────┤
│  domain/     Enums e geometria. Zero I/O, zero dependências.    │
└─────────────────────────────────────────────────────────────────┘
```

A dependência só aponta para baixo. `domain/` não importa nada do projeto e é testável sem
banco — por isso é onde mora a lógica que não pode estar errada (geometria do campo,
definição de progressão, zonas do gol).

A interface conversa com a API por HTTP, nunca com o banco direto. O custo é pequeno; o
ganho é que trocar Dash por React mais adiante não toca em nada abaixo de `api/`.

---

## 3. Modelo de dados

### Dimensões — o "quem, onde, quando"

| Tabela | Papel |
|---|---|
| `countries` | Nacionalidade e sede. Guarda centroide lat/lon para o mapa-múndi. |
| `competitions` | Competição, com `type` distinguindo nacional / estadual / continental / seleção / amistoso / base. |
| `seasons` | Temporada de uma competição. |
| `teams` | Clube ou seleção. |
| `players` | Só atributos estáveis da pessoa. |
| `player_nationalities` | Tabela própria, porque dupla cidadania é comum. |
| `player_club_spells` | Histórico de clubes, com vigência e marcação de empréstimo. |
| `matches` | Partida. |
| `appearances` | Participação do atleta na partida: minutagem, posição, mando. |
| `venues` | Estádio, com coordenada geocodificada e a proveniência dela. |
| `match_weather` | Clima durante a partida, derivado da coordenada do estádio. |

### Fato — `events`

Uma linha por ação registrada em campo. Colunas comuns a qualquer evento (quando, quem,
onde, em que posse) mais um JSON `qualifiers` com tudo que a fonte trouxe e ainda não virou
coluna.

Esse JSON é uma rede de segurança deliberada: uma métrica pensada no mês 3 do projeto pode
precisar de um atributo não previsto no mês 1. Com o bruto preservado, ela é calculável sem
reingerir nada.

### Projeções — visões tipadas por família

`shots`, `passes`, `dribbles`, `defensive_actions`, `goalkeeper_actions`,
`disciplinary_actions`. Cada uma contém os atributos específicos daquela família já tipados
e indexados. Quase todas têm uma linha por evento; `defensive_actions` admite duas, porque
um corte de cabeça que venceu a disputa pelo alto é, ao mesmo tempo, corte e duelo aéreo.

**Por que não consultar o JSON diretamente?** Porque quase toda métrica pedida é um filtro
sobre poucos atributos de uma única família. Em colunas indexadas isso é um `WHERE` que usa
índice; dentro de um blob JSON, em SQLite, é varredura completa da tabela. Com centenas de
milhares de eventos, a diferença é entre um painel que responde e um que trava. O custo é um
mapeamento mecânico na ingestão, pago uma única vez.

### Identidade entre fontes — `external_ids`

Atleta, clube, competição e partida não guardam de qual fonte vieram. Existem uma vez, e a
tabela `external_ids` liga cada um ao identificador que tem em cada fonte, registrando como
a ligação foi estabelecida (`created`, `exact_id`, `name_team_season`, `manual`) e com que
confiança.

Sem isso, o mesmo atleta vindo da StatsBomb e do Transfermarkt viraria dois registros, e
toda estatística dele ficaria dividida. A regra de atualização é simples: a fonte que criou
o registro pode atualizá-lo; uma fonte ligada depois só preenche campos vazios.

Eventos são a exceção e mantêm `(source, source_id)` na própria tabela: duas fontes que
descrevem a mesma partida produzem sequências de ações diferentes, que não se fundem.

A estratégia de ligação entre fontes está em [`FONTES.md`](FONTES.md).

### Desnormalizações deliberadas

Duas, ambas de valores derivados na ingestão e nunca editados depois:

- **`appearances.opponent_team_id` e `appearances.home_away`.** Sem elas, "estatísticas contra o
  time X" e "desempenho fora de casa" exigiriam dois JOINs em `matches` com `CASE` para
  descobrir de que lado o jogador estava — em toda consulta do sistema. Com elas, viram um
  `WHERE` indexado.
- **`events.third`, `events.lane`, `events.grid_col/grid_row`.** Zonas derivadas de `(x, y)`
  por função pura e imutável. Pré-calcular remove o mapa de calor e os recortes por setor do
  caminho crítico.

---

## 4. Do pedido ao modelo: como cada família é calculada

A tabela abaixo é o contrato entre a especificação e a implementação. Vale como anexo do TCC.

### Finalização e gols

| Pedido | Como é computado |
|---|---|
| Gols por campeonato | `shots.is_goal` agrupado por `competition` via `match → season` |
| Gol de canhota / destra / cabeça | `shots.body_part` |
| Gol de fora da área | `shots.in_penalty_area = falso` |
| Gol dentro da área / pequena área | `shots.in_penalty_area` / `shots.in_six_yard_box` |
| Direção do chute, canto do gol | `shots.goal_mouth_zone` (grade 3×3 a partir de `end_y`, `end_z`) |
| Aproveitamento de chutes | `shots.is_on_target / count(shots)` |
| Chute na trave | `shots.hit_post` |
| Gol acrobático | `shots.technique ∈ {overhead_kick, diving_header, volley}` |
| Gol de pênalti, aproveitamento, canto batido | `shots.shot_type = penalty` cruzado com `is_goal` e `goal_mouth_zone` |
| Gol de falta, pé usado, direção | `shots.shot_type = free_kick` + `body_part` + `goal_mouth_zone` |
| Lado de onde a falta foi cobrada | `events.lane` na origem do chute |
| Gol vindo de escanteio | `events.play_pattern = from_corner` |
| Gol vindo de cruzamento | passe-chave do chute com `passes.is_cross = verdadeiro` |
| xG | `shots.xg` |

### Passe e assistência

| Pedido | Como é computado |
|---|---|
| Assistências por campeonato | `passes.is_goal_assist` agrupado por competição |
| Pé usado / assistência de cabeça | `passes.body_part` |
| Passe curto / médio / longo | `passes.length_bucket`, derivado de `length_m` |
| Distância máxima e mínima | `MIN/MAX(passes.length_m)` |
| Lado do campo | `events.lane` |
| Passe para dentro da área / pequena área | `passes.into_penalty_area` / `into_six_yard_box` |
| Pré-assistência | `passes.is_pre_assist`, resolvido na cadeia de posse |
| Cruzamento | `passes.is_cross` |
| Passe em escanteio ou falta | `passes.pass_type` |
| Grandes chances criadas | `passes.is_shot_assist` filtrado por `xg` do chute resultante |
| Direção (frente / lado / trás) | `passes.direction` |
| Passe que rompe linhas | `passes.is_progressive` (critério Wyscout) |
| Aproveitamento por faixa de distância | `is_complete` agrupado por `length_bucket` |

### Drible

| Pedido | Como é computado |
|---|---|
| Dribles certos, aproveitamento | `dribbles.is_complete` |
| Drible dentro / fora da área | `dribbles.in_penalty_area` |
| Lado do campo | `events.lane` |
| Falta sofrida após drible | `dribbles.drew_foul` |
| Drible que gerou chute / gol / assistência | `dribbles.led_to_shot` / `led_to_goal` / `led_to_assist` |

Os quatro últimos campos são resolvidos na ingestão, percorrendo os eventos seguintes da
mesma posse. Materializar isso evita consulta recursiva em tempo de leitura — a alternativa
seria uma CTE recursiva por drible, inviável em painel interativo.

### Defesa, duelo e goleiro

| Pedido | Como é computado |
|---|---|
| Desarme, interceptação, corte, bloqueio, roubo de bola | `defensive_actions.action_type` |
| Duelo ganho no chão / pelo alto | `defensive_actions.is_aerial` + `is_successful` |
| Defesas de fora / dentro da área | `goalkeeper_actions.shot_from_outside_box` |
| Direção do chute defendido | `goalkeeper_actions.shot_goal_mouth_zone` |
| Defesa que deu rebote | `goalkeeper_actions.gave_rebound` |
| Defesa de pênalti | `goalkeeper_actions.is_penalty_save` |
| Saída certa | `action_type = keeper_sweeper` + `outcome` |
| Clean sheet | `appearances.goals_against = 0` com minutagem integral |
| Gols evitados | `SUM(shot_xg) − gols sofridos`, sobre `goalkeeper_actions` |

### Disciplina

| Pedido | Como é computado |
|---|---|
| Cartão no campo adversário x no próprio campo | `disciplinary_actions.in_own_half` |
| Faltas por jogo | `is_foul_committed / count(appearances)` |
| Falta perto da própria área | `near_own_penalty_area` |
| Faltas sofridas | `is_foul_won` |

---

## 5. Recortes

Todo recorte pedido — campeonato, agrupamento de campeonatos, janela de datas, adversário,
casa/fora, categoria de base, seleção — é o mesmo objeto de filtro aplicado antes da
agregação. Nenhuma métrica implementa recorte por conta própria:

```python
@dataclass(frozen=True)
class Slice:
    player_ids: tuple[int, ...] = ()
    competition_ids: tuple[int, ...] = ()
    competition_types: tuple[CompetitionType, ...] = ()
    season_ids: tuple[int, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    opponent_team_ids: tuple[int, ...] = ()
    team_ids: tuple[int, ...] = ()
    home_away: HomeAway | None = None
    min_minutes: int | None = None
```

É isso que faz "Messi em junho e julho de 2024" e "Messi na Champions 2021–2023 contra o
Real Madrid" serem a mesma operação com argumentos diferentes. Um `Slice` imutável também é
chave de cache natural.

---

## 6. O catálogo de métricas

Cada métrica é um dado, não uma função solta:

```python
@dataclass(frozen=True)
class MetricSpec:
    key: str                  # "gols_canhota"
    label: str                # "Gols de perna esquerda"
    family: str               # "finalizacao"
    table: type               # a projeção de onde sai (Shot, Pass, ...)
    aggregation: Aggregation  # count | sum | average | ratio
    predicate: tuple          # o filtro que define a métrica
    numerator: tuple          # em razões, o que conta como sucesso
    unit: Unit                # count | percent | meters | xg
    per_90: bool              # admite normalização por 90 minutos
    higher_is_better: bool    # orienta cor e escala na comparação
    positions: tuple          # a quem a métrica se aplica
    min_sample: int           # amostra mínima para razões e médias
```

**Estado atual: 108 definições em sete famílias** — finalização (29), passe (22), defesa (14), goleiro (13), drible (11), gerais (10) e disciplina (9) —, das quais
5 são compostas.

Consequências práticas:

- **Adicionar métrica é adicionar um registro.** Nenhuma delas exigiu coluna nova no banco:
  "gol de canhota de fora da área vindo de escanteio" é um filtro sobre três colunas de
  `shots` e uma de `events`.
- **A interface se monta sozinha**, lendo o catálogo em vez de listas escritas à mão.
- **A comparação fica correta por construção:** `positions` impede comparar clean sheet de
  goleiro com drible de ponta, `per_90` evita confrontar quem jogou 300 minutos com quem
  jogou 3.000, e `min_sample` impede que 100% de aproveitamento em um único duelo apareça no
  topo de um ranking.
- **Métricas compostas cruzam famílias.** Participação em gols soma `shots` com `passes`;
  minutos por gol divide a minutagem por uma contagem. Elas não têm consulta própria:
  combinam métricas já calculadas, e o motor resolve a dependência sozinho.
- **O percentil é calculado dentro do grupo de posição** em que o atleta mais atuou no
  recorte, e vem acompanhado da população que o gerou — sem isso, "percentil 90" tanto
  pode significar "melhor que nove entre dez" quanto "melhor que um entre dois".
- **O catálogo é o anexo de metodologia.** `fscout catalogo --csv` exporta a tabela de
  definições operacionais de todas as métricas.

Três regras valem para todas e por isso vivem no motor, não em cada definição: a disputa de
pênaltis fica de fora, o piso de minutagem é aplicado depois da agregação, e o percentil
respeita o sentido da métrica (em gols sofridos, menos é melhor).

---

## 7. Fontes de dados

A StatsBomb Open Data é a fonte primária e a única integrada até aqui: é a única aberta com
dados evento a evento no nível de detalhe que a especificação exige. As lacunas dela —
biografia, valor de mercado, lesões, clima, Brasileirão — são cobertas por fontes
complementares, avaliadas e priorizadas em [`FONTES.md`](FONTES.md).

Todo adaptador de eventos entrega a partida no mesmo formato (`MatchBundle`), então uma
fonte nova exige um mapeador, não mudanças na gravação.

---

## 8. Limitações — a serem declaradas no texto

Um TCC ganha credibilidade ao delimitar o que *não* faz. Estas são as fronteiras reais:

**Não calculáveis a partir de dados de evento:**

- Distância percorrida, número de sprints, velocidade média e máxima. Exigem *tracking data*
  (posição de todos os 22 jogadores a 25 Hz). Há amostras abertas (Metrica Sports,
  SkillCorner) que permitem demonstrar o cálculo, mas não cobrem os atletas das competições
  com eventos, então essas métricas não aparecem no perfil dos mesmos jogadores.
- Velocidade do chute. Não é registrada.

**Limitações da fonte:**

- **Cobertura.** A StatsBomb Open Data não inclui o Campeonato Brasileiro. Jogadores da
  seleção brasileira aparecem com dados evento a evento na Copa América 2024. Para o
  Brasileirão, a fonte avaliada (API-Football) entrega apenas estatística agregada.
- **Ficha básica incompleta na fonte primária.** A StatsBomb não informa data de nascimento,
  altura, peso nem pé preferencial. Idade, altura e pé dependem da ligação com o
  Transfermarkt; peso não tem fonte aberta confiável.
- **Escalações inconsistentes.** Os intervalos de posição da StatsBomb às vezes terminam
  antes de começar ou se sobrepõem (na final de 2022, Messi somaria 207 minutos). A
  minutagem é calculada pela união dos intervalos, cortada na substituição, e foi validada:
  nas 64 combinações time-partida da Copa América 2024, a soma de minutos fica a menos de
  3% de 11 jogadores em campo.
- **Gol de peito.** A taxonomia de `body_part` para finalização tem apenas pé esquerdo, pé
  direito, cabeça e "outro". Gol de peito cai em "outro", indistinguível de joelho ou coxa.
- **Duelo aéreo.** A fonte registra explicitamente o duelo aéreo *perdido*; o vencido é
  inferido de uma marca auxiliar em outros eventos. A contagem de duelos aéreos tem,
  portanto, precisão menor que as demais.
- **Normalização de campo.** Toda partida é normalizada para 120 × 80 jardas, então
  distâncias absolutas carregam erro de escala de cerca de 4% em relação a um gramado de
  105 × 68 m. O erro é sistemático e igual para todos os atletas, de modo que comparações
  não são afetadas — apenas valores absolutos.

- **Ligação entre fontes incompleta por construção.** 51 dos 1.583 atletas (3,2%) ficam
  sem ficha biográfica porque as regras preferem não ligar a errar: sobrenome composto
  espanhol, apelido comum ("Fabinho" tem oito registros no Transfermarkt) e apelido contra
  nome de registro ("Sávio" x "Savinho"). Os casos ficam num CSV de revisão manual.
- **Dataset do Transfermarkt congelado.** A atualização automática está pausada desde julho
  de 2026; valor de mercado e contrato refletem essa data.
- **Horário de início.** É UTC, conferido contra horários oficiais de três competições, mas
  a própria final de 2022 está duas horas adiantada na fonte. O clima daquela partida sai
  deslocado.
- **Resolução do clima.** A reanálise ERA5 tem grade de ~25 km e suaviza chuva convectiva:
  a tempestade que interrompeu Alemanha x Dinamarca na Euro 2024 aparece como 0,4 mm.
- **Geocodificação de estádios.** A busca por nome pode devolver um lugar plausível e
  errado (o Q2 Stadium caiu na Virgínia em vez do Texas). Resultados não marcados como
  estádio são sinalizados no relatório e corrigidos em `data/reference/venues.csv`.

**Convenções adotadas que precisam ser declaradas:**

- **Minutagem nominal** (jogo inteiro vale 90, prorrogação 120) como base da normalização
  por 90 minutos, para comparabilidade com fontes públicas. O tempo efetivo, com acréscimos,
  é guardado à parte.
- **Disputa de pênaltis** fica registrada, mas não conta como gol do atleta nem como minuto
  jogado.
- **Campo neutro** é inferido quando o estádio fica fora do país do mandante.

**Fora do escopo por prazo:** salário, equipe como entidade analítica de primeira classe,
modelo de xG próprio, segunda fonte de eventos (Wyscout).

---

## 9. Registro de decisões

| # | Decisão | Motivo | Alternativa descartada |
|---|---|---|---|
| 1 | Modelo de eventos, métrica como consulta | Único caminho que suporta a combinatória pedida e admite extensão | Tabela larga de estatísticas agregadas |
| 2 | Projeções tipadas por família | `WHERE` indexado em vez de varredura sobre JSON | Consultar `qualifiers` diretamente |
| 3 | Preservar o JSON bruto além das projeções | Métrica futura sem reingestão | Descartar o que não vira coluna |
| 4 | SQLite com schema portável a Postgres | Zero infraestrutura; volume do TCC cabe | Postgres desde o início |
| 5 | Entidade canônica e `external_ids` | Combinar fontes sem duplicar atletas; ligação auditável | `(source, source_id)` em cada tabela |
| 6 | Enums como texto com CHECK | Banco legível na consulta manual, portável | Inteiros ou ENUM nativo |
| 7 | Conversão isotrópica jarda→metro | Preserva largura oficial do gol e ângulos | Reescalar para 105 × 68 m |
| 8 | Zonas pré-calculadas em `events` | Mapa de calor fora do caminho crítico | Derivar em tempo de consulta |
| 9 | Dash em vez de React | Concentra o esforço no motor analítico, que é a contribuição | SPA em React/TypeScript |
| 10 | Catálogo de métricas declarativo | Interface se monta sozinha; vira anexo de metodologia | Uma função por métrica |
| 11 | Tradução explícita do vocabulário da fonte | A StatsBomb escreve "Off T", "Ground Pass"; normalização automática erraria em silêncio | Normalizar texto automaticamente |
| 12 | Minutagem nominal e efetiva | Nominal é comparável com fontes públicas; efetiva mede exposição real | Guardar só uma |
| 13 | União de intervalos cortada na substituição | A escalação da fonte tem intervalos invertidos e sobrepostos | Somar intervalos |
| 14 | Disputa de pênaltis marcada, não descartada | A cobrança é dado útil; gol de disputa não é gol do atleta | Excluir o período 5 |
| 15 | Chave de temporada `competição-temporada` | O `season_id` da StatsBomb se repete entre competições | Usar o id da fonte |
| 16 | Ligação em três níveis, com recusa explícita | Preferir não ligar a ligar errado; a precisão é medida | Ligar sempre o nome mais parecido |
| 17 | Precisão medida contra as ligações por escalação | Dá um gabarito real, sem anotação manual | Apenas inspeção visual |
| 18 | Estádio como entidade, com coordenada | Uma geocodificação por estádio, não por partida | Latitude e longitude na partida |
| 19 | Correção manual descarta o clima gravado | Sem isso a correção não teria efeito | Corrigir só a coordenada |
| 20 | Clima pedido em UTC | Evita converter fuso e horário de verão no meio da temporada | Pedir no fuso local |
| 21 | O painel fala com a API, nunca com o banco | Uma definição só de cada número; a tela não pode discordar da API | Dash consultando o banco direto |
| 22 | Paleta verificada por cálculo, com o validador portado para Python | Não há Node nesta máquina, e a segurança para daltonismo se mede | Estimar a olho, ou pular a verificação |
| 23 | Teto de três séries em formas de todos os pares | Medido: a quarta reprova com ΔE 13.7, abaixo do piso de 15 | Quatro ou mais séries, ou matizes gerados |
| 24 | Toda figura acompanhada da tabela equivalente | Cor não é canal único, e duas cores do modo claro ficam abaixo de 3:1 | Só o gráfico |
| 25 | Tamanho do chute em escala absoluta de xG | Dois mapas lado a lado ficam comparáveis | Escala relativa ao melhor chute de cada atleta |
| 26 | Métrica sem percentil sai do radar | Nulo não é zero; zero afirmaria "é péssimo" onde não se sabe | Desenhar o nulo como zero |
| 27 | A regra de "qual número exibir" mora num lugar só | O valor na tela tem que ser aquele sobre o qual o percentil foi calculado | Cada tela decidindo por conta própria |
| 28 | As duas telas ficam montadas; a aba troca a visibilidade | Não obriga a silenciar exceções de callback, que esconderiam erro real | `dcc.Tabs` trocando o conteúdo |
| 29 | Painel só no modo claro, com o escuro pronto | Os controles do Dash não são tematizados sem CSS próprio | Botão de tema escurecendo só os gráficos |

---

## 10. Estrutura de diretórios

```
FScout/
├── src/fscout/
│   ├── config.py              Configuração via variáveis de ambiente
│   ├── cli.py                 competitions, ingest, transfermarkt, weather, catalogo, api, ui, status
│   ├── domain/                Vocabulário e geometria. Sem I/O.
│   │   ├── enums.py           Enums do futebol, tolerantes a valor desconhecido
│   │   └── pitch.py           Zonas, distâncias, ângulos, progressão
│   ├── db/
│   │   ├── base.py            Base declarativa e mixins
│   │   ├── models.py          Schema (22 tabelas)
│   │   └── session.py         Engine, sessão, PRAGMAs do SQLite
│   ├── linking/               Decidir quando dois registros são a mesma entidade
│   │   ├── names.py           Normalização e comparação de nomes
│   │   ├── countries.py       Identidade de países entre fontes
│   │   ├── venues.py          Identidade de estádios
│   │   └── matching.py        Regras de ligação: partidas, atletas, votação
│   ├── ingestion/
│   │   ├── bundle.py          Contrato entre adaptadores e carga (MatchBundle)
│   │   ├── download.py        Download com cache e novas tentativas
│   │   ├── loader.py          Gravação idempotente e resolução de identidade
│   │   ├── pipeline.py        Orquestração da ingestão de eventos
│   │   ├── geocoding.py       Nominatim (OpenStreetMap)
│   │   ├── openmeteo.py       Clima histórico por coordenada e hora
│   │   ├── weather.py         Localiza estádios e grava o clima das partidas
│   │   ├── statsbomb/         Cliente, vocabulário, relógio, encadeamentos, mapeador
│   │   └── transfermarkt/     Cliente, ligador, enriquecimento, orquestração
│   ├── metrics/               Catálogo e motor de métricas (Fase 2)
│   ├── api/                   Contrato HTTP
│   │   ├── deps.py            Sessão por requisição e recorte vindo da consulta
│   │   ├── schemas.py         Formatos de entrada e saída
│   │   └── routers/           catalog, reference, players, metrics
│   └── ui/                    Painel Dash. Consome a API, nunca o banco.
│       ├── theme.py           Tokens de cor verificados e template do gráfico
│       ├── api_client.py      Único caminho de dados do painel
│       ├── format.py          Como um número do motor vira texto na tela
│       ├── pitch.py           Desenho do campo, sob as figuras
│       ├── app.py             Montagem, abas e callbacks do recorte
│       ├── figures/           shot_map, heatmap, radar
│       ├── components/        Cartões de resumo e barra de recortes
│       └── pages/             perfil, comparar
├── scripts/
│   └── validate_palette.py    Verificação computável da paleta (porte do original)
├── tests/
├── docs/
│   ├── ARQUITETURA.md
│   ├── FONTES.md
│   └── ROADMAP.md
└── data/
    ├── raw/                   Cache das fontes (fora do git)
    ├── reference/             Coordenadas corrigidas à mão (versionado)
    ├── processed/             Relatórios, como a fila de revisão manual
    └── db/                    Banco SQLite (fora do git)
```
