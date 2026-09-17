# Roadmap — 12 semanas

Prazo declarado: menos de três meses. O plano abaixo assume início em **15/09/2026** e
entrega por volta de **08/12/2026**, com uma semana inteira de folga antes da defesa.

## Princípio que governa os cortes

> Um núcleo de métricas bem definido, com quatro visualizações excelentes, defende melhor
> que duzentas métricas pela metade.

Uma banca não conta estatísticas. Ela pergunta *como* um número foi calculado, *por que*
aquele critério, e *o que acontece* quando o dado falta. Profundidade e rastreabilidade
valem mais que superfície. Todo corte abaixo segue essa regra.

---

## Fase 0 — Fundação · Semana 1 — **concluída**

- [x] Estrutura do projeto, `pyproject.toml`, ambiente virtual, dependências
- [x] `domain/enums.py` — vocabulário do futebol, tolerante a valores desconhecidos
- [x] `domain/pitch.py` — geometria: zonas, distâncias, ângulos, progressão
- [x] `db/models.py` — schema completo, 19 tabelas
- [x] `db/session.py` — engine, sessão, PRAGMAs de carga
- [x] 33 testes de geometria, aferidos contra medidas oficiais da IFAB
- [x] Lint e formatação configurados e limpos
- [x] `docs/ARQUITETURA.md`

## Fase 1 — Ingestão StatsBomb · Semana 1 — **concluída**

Planejada para as semanas 2 e 3, concluída ainda na semana 1. As duas semanas ganhas vão
para a Fase 1b.

- [x] Cliente StatsBomb com cache em disco e download paralelo
- [x] Tabelas de tradução explícitas do vocabulário, conferidas em 129 mil eventos
- [x] Mapeador de competições, partidas, escalações, eventos e das seis projeções
- [x] Encadeamentos: pré-assistência e consequências do drible
- [x] Minutagem nominal e efetiva, robusta a escalações inconsistentes
- [x] Identidade entre fontes (`external_ids`), pronta para a combinação com outras fontes
- [x] Pipeline idempotente, uma transação por partida, auditoria em `ingestion_runs`
- [x] CLI: `fscout competitions`, `fscout ingest`, `fscout status`
- [x] 89 testes, incluindo ponta a ponta com a final da Copa de 2022

**Validação com a Copa América 2024 completa** — 32 partidas, 100.324 eventos, 20 segundos:

| Verificação | Resultado |
|---|---|
| Placar reconstruído a partir dos eventos | 32 de 32 partidas conferem |
| Valores da fonte fora do vocabulário | nenhum |
| Artilheiro | Lautaro Martínez, 5 gols — confere com o registro oficial |
| Líder de assistências | James Rodríguez, 6 — confere com o registro oficial |
| Soma de minutos por time e partida | 64 de 64 a menos de 3% de 11 jogadores em campo |

A validação contra a partida real encontrou um defeito que os testes sintéticos não
pegariam: a escalação da StatsBomb tem intervalos invertidos e sobrepostos, e Messi somava
207 minutos na final. A correção está documentada em `clock.py` e coberta por testes que
reproduzem os casos reais.

## Fase 1b — Ficha do atleta e clima · Semana 1 — **concluída**

Justificativas e limites de cada fonte em [`FONTES.md`](FONTES.md).

- [x] Adaptador transfermarkt-datasets: nascimento, altura, pé, país de nascimento, valor de
      mercado e fim de contrato
- [x] Ligação de registros em três níveis (escalação, nome e nacionalidade, nome único),
      com fila de revisão manual
- [x] Precisão do método por nome medida contra as ligações por escalação
- [x] Estádio como entidade própria, geocodificado pelo OpenStreetMap, com correção manual
- [x] Open-Meteo: clima de cada partida no horário do jogo
- [x] Carga das competições-alvo: Copa do Mundo 2022, Euro 2024, La Liga 2020/21
- [ ] Histórico de clubes a partir das transferências (adiado: depende de ligar também os
      clubes do Transfermarkt, e não só as seleções)

| Etapa | Resultado |
|---|---|
| Partidas ligadas | 182 de 182 |
| Equipes ligadas | 71 |
| Atletas ligados | **1.532 de 1.583 (96,8%)** |
| — por escalação da partida | 703 |
| — por nome e nacionalidade | 827 |
| — por nome único no dataset | 2 |
| Precisão do método por nome | **98,6%** (633 de 642) |
| Cobertura do método por nome | 90,0% |
| Casos para revisão manual | 51 (3,2%) |
| Biografia preenchida | 1.511 datas de nascimento, 1.512 alturas e pés preferenciais |
| Valor de mercado | 41.781 registros de valorização, 1.239 fins de contrato |
| Clima | 182 de 182 partidas, 51 estádios localizados (7 por coordenada manual) |

Três defeitos que só a validação contra dados reais revelaria:

- A regra de folga do método por nome rejeitava **acertos exatos**: "Alessandro Bastoni"
  perdia para "Alessandro Bastrini", que é outra pessoa com letras parecidas. Daí o nível de
  nome idêntico.
- O geocodificador devolveu o **Q2 Stadium na Virgínia** em vez de no Texas, porque a busca
  por nome encontra bairros chamados "Stadium". A coordenada foi corrigida à mão, e a
  correção passou a descartar o clima já gravado.
- O enum de mando de campo se chamava `Venue`, o mesmo nome da nova tabela de estádios, e
  derrubou o mapeamento inteiro. Virou `HomeAway`.

## Fase 2 — Motor de métricas · Semana 1 — **concluída**

- [x] `Slice`: o objeto de recorte, aplicado do mesmo jeito em qualquer consulta
- [x] `MetricSpec` e o catálogo declarativo
- [x] Motor de avaliação, com normalização por 90 minutos
- [x] Piso de amostra em razões e médias
- [x] Percentil dentro do grupo de posição, com a população que o gerou
- [x] Métricas compostas, que cruzam famílias (participação em gols, minutos por gol)
- [x] 108 definições em sete famílias, cobrindo a lista da especificação
- [x] Exportação do catálogo como tabela de definições operacionais (`fscout catalogo --csv`)

**Cache por recorte foi deixado de fora de propósito.** É otimização, as consultas respondem
rápido sobre 662 mil eventos, e otimizar antes de a interface mostrar lentidão gastaria prazo
no lugar errado. O `Slice` é imutável, então continua servindo de chave quando fizer falta.

**Conferência contra fatos conhecidos, na Copa América 2024:** Lautaro Martínez lidera gols
(5, a artilharia oficial), James Rodríguez lidera participação em gols (7, com o recorde de 6
assistências) e Emiliano Martínez lidera gols evitados. Os percentis saem por grupo: James é
comparado entre 43 meias, Lautaro entre 36 atacantes, e um atacante não recebe percentil em
métrica de goleiro.

A meta declarada era de 60 a 80 métricas; o catálogo passou disso porque, com o motor pronto,
cada métrica nova é um registro de cinco linhas. O limite continua valendo como regra de
escopo: nada de métrica que exija coluna nova ou consulta especial.

## Fase 3 — API · Semana 1 — **concluída**

- [x] `GET /catalog` — o catálogo de métricas, que a interface consome para se montar
- [x] `GET /competitions` e `GET /teams` — o que preenche os filtros
- [x] `GET /players` — busca dentro de um recorte, ordenada por minutagem
- [x] `GET /players/{id}` — ficha, com o que veio das fontes fora dos eventos
- [x] `GET /players/{id}/shots` e `/heatmap` — dados brutos dos mapas de campo
- [x] `POST /metrics/evaluate` — o catálogo avaliado sob um recorte
- [x] `POST /compare` — N atletas x M métricas x K recortes
- [x] `fscout api` sobe o serviço; a documentação interativa fica em `/docs`

**Todo endpoint de leitura aceita o mesmo conjunto de filtros de recorte**, de modo que
"gols em junho" e "gols contra determinado adversário" são a mesma chamada com argumentos
diferentes. A comparação aceita recortes diferentes para os mesmos atletas, que é o que
permite "2024 contra 2025".

**Decisão que precisa constar no texto:** o percentil é calculado sobre toda a população do
recorte, e não apenas sobre os atletas consultados. Filtrar antes tornaria o percentil
dependente de quem foi pedido na requisição — dois atletas comparados entre si apareceriam
sempre como percentil 0 e 100.

Conferido contra o banco real: a ficha do Lautaro Martínez traz altura, pé, valor de mercado
e contrato; as 11 finalizações dele na Copa América saem com distância, xG e canto do gol; e
a comparação entre recortes mostra 5 gols na Copa América contra 0 na Copa do Mundo de 2022.

## Fase 4 — Visualização · Semana 2 — **critério de pronto atingido**

Prioridade estrita, de cima para baixo. O critério declarado era "pronto quando o item 6
funciona" — e ele funciona.

1. [x] **Perfil do atleta** — ficha, cartões de resumo, barra de recortes
2. [x] **Mapa de chutes** — sobre o desenho do campo, tamanho por xG, cor por desfecho
3. [x] **Radar comparativo** — percentis dentro do grupo de posição
4. [x] **Mapa de calor** — a partir das células de grade pré-calculadas
5. [x] **Mapa de passes** — origem, destino, cor por desfecho, com recorte por tipo.
       Exigiu rota nova: `GET /players/{id}/passes` e o `PassOut`
6. [x] **Tabela comparativa** — N atletas × M métricas, com segundo recorte independente
7. [x] **Boca do gol** — grade 3×3, nas duas perspectivas, com recorte de pênaltis
8. [x] **Mapa-múndi** — marcador por país do adversário, raio proporcional a G/A

**A Fase 4 saiu inteira, os oito itens.** Os 1–4 e 6 vieram antes do 5 porque o 5 era o
único que pedia rota nova, e o critério de pronto estava no 6.

O mapa-múndi fechou o pedido que originou o trabalho — abrir a ficha de um atleta e ver
num mapa onde a produção dele se concentra. Três decisões dele valem registro:

- **O país é o do adversário**, não o do atleta. "Contra quem ele produz" e "de onde ele
  é" dariam mapas diferentes; a primeira é a que anda junto com a minutagem.
- **Inglaterra, Escócia e País de Gales são três seleções e um Estado soberano.** Sem
  agrupar, sairiam três bolhas empilhadas no mesmo ponto e a de cima esconderia as
  outras. São somadas num marcador rotulado com os três nomes, e a tabela mantém a
  separação. Conferido com Granit Xhaka na Euro: enfrentou Inglaterra e Escócia, e os
  cinco países dele viraram quatro marcadores.
- **Estados extintos de sucessão ambígua ficam sem posição.** Tchecoslováquia, URSS,
  Iugoslávia e Sérvia e Montenegro aparecem como país de nascimento no Transfermarkt e
  não existem num mapa atual. Escolher um sucessor plantaria um marcador onde ninguém
  jogou; eles ficam na tabela, e a tela diz que ficaram de fora. Zaire e Alemanha
  Oriental são exceção: o território é o mesmo de hoje, sem ambiguidade.

A coluna `countries.iso3` já existia no schema, prevista para isto, e estava vazia.
`fscout paises` a preenche a partir de uma tabela ISO 3166-1 explícita — 86 dos 91 países
do banco, com os 5 restantes declarados como sem código.

Conferido contra fatos conhecidos: somando os países, Messi tem **30 gols na La Liga
2020/21** (o Pichichi daquela temporada) e Lautaro Martínez, **5 na Copa América** (a
artilharia do torneio).

**Uma divergência encontrada ao conferir o mapa de passes contra o catálogo**, e que vale
como método: as contagens do mapa e das métricas foram comparadas para Pedri (2.162
passes). Cinco bateram exatamente e três não — progressivos (192 contra 108), para a área
(94 contra 44) e bolas em profundidade (25 contra 7). Nenhum dos dois lados estava
errado: as marcas `is_progressive`, `into_penalty_area` e `is_through_ball` são
geométricas e valem para a **tentativa**, enquanto as métricas de mesmo nome somam só as
**completas** — e os rótulos delas já diziam isso ("Passes progressivos *certos*"). O
defeito era de texto: o rodapé do mapa dizia "192 passes progressivos" ao lado de um
cartão marcado "108". Num mapa, o passe progressivo que se perdeu é justamente o que se
quer ver, então o gráfico continua mostrando tentativas — o rodapé é que passou a dizer
"tentativas, X certas e Y erradas". A distinção está fixada em teste.

**A paleta não foi escolhida no olho.** A regra do método de visualização é que a
segurança para daltonismo se calcula. O validador original é um script Node, e não há
Node nesta máquina, então ele foi **portado para Python** (`scripts/validate_palette.py`)
mantendo as matrizes de Machado, Oliveira & Fernandes (2009) e a definição de ΔE em
OKLab. O porte reproduz exatamente os números publicados na referência, o que é a prova
de que ele não se desviou:

| Subconjunto | Modo | CVD (pior par) | Visão normal | Veredito |
|---|---|---|---|---|
| 8 séries, pares adjacentes | claro | 9.1 | 19.6 | passa |
| 8 séries, pares adjacentes | escuro | 8.4 | 19.3 | passa |
| 3 séries, todos os pares | claro | 9.2 | 24.0 | passa |
| 3 séries, todos os pares | escuro | 9.4 | 20.9 | passa |
| 4 séries, todos os pares | claro | 9.1 | **13.7** | **reprova** |

A última linha é o que governa o desenho das telas: em formas nas quais qualquer série
pode encostar em qualquer outra — dispersão, bolha, radar — o teto é de **três séries**,
porque a quarta põe amarelo ao lado de laranja e o par fica indistinguível até para quem
enxerga todas as cores. Daí o mapa de chutes ter três classes de desfecho e o radar
aceitar no máximo três séries (três atletas num recorte, ou um atleta em dois recortes).

Três decisões que precisam constar no texto:

- **"No alvo" exclui trave e bloqueio.** Chute defendido pelo goleiro conta, inclusive o
  espalmado na trave; bola na trave sem defesa e bloqueio de jogador de linha não contam.
  É a definição corrente de *shots on target*, e é onde uma comparação com fonte externa
  diverge se o critério não estiver escrito.
- **O tamanho do chute é escala absoluta de xG (0 a 1).** Régua relativa ao melhor chute
  de cada atleta tornaria dois mapas lado a lado incomparáveis.
- **Métrica sem percentil sai do radar; não vira zero.** Amostra abaixo do mínimo, grupo
  de posição com menos de dois atletas ou métrica que não se aplica à posição produzem
  valor nulo. Desenhar isso como zero afirmaria "é péssimo" onde o correto é "não sei";
  as métricas descartadas aparecem nomeadas abaixo do gráfico.

**Toda figura tem tabela equivalente**, saída da mesma resposta da API. É exigência de
acessibilidade (escala contínua de cor não é canal único; duas cores do modo claro ficam
abaixo de 3:1 e só são liberadas com o valor legível em outro lugar) e, de quebra, é o
que permite conferir na banca o número que está no desenho.

**O painel sai só no modo claro.** Os degraus escuros estão definidos e verificados
contra a superfície escura, e toda figura já recebe o modo como parâmetro — mas os
controles do Dash não são tematizados sem CSS próprio, e um botão que escurece os
gráficos deixando os filtros brancos é pior que não ter botão. Fica pronto para ligar.

Conferido contra o banco real: as 11 finalizações de Lautaro Martínez na Copa América
saem no mapa como **5 gols**, 3 no alvo e 3 para fora — e os 5 gols são a artilharia
oficial do torneio. A comparação com segundo recorte isola a janela de 20 a 30 de junho.

## Fase 4b — A camada agregada · Semana 2 — **concluída**

Fase que não estava no plano. Ela nasceu de uma correção de rumo: o objetivo declarado
passou a ser **cobertura real do futebol sul-americano**, e a ferramenta só enxergava
competições europeias e de seleções.

O fato duro que a governou: **não existe dado de evento aberto para o futebol de clubes
sul-americano**. Esse dado é produzido por pessoas assistindo à partida e marcando cada
ação, e é vendido sob contrato — empresas como a Sofascore licenciam de provedores, não
obtêm de graça. A limitação é econômica, não de pesquisa.

- [x] Sondagem que mede o que a fonte cobre **antes** de qualquer adaptador ser escrito
- [x] Camada de dado no schema, com recorte que nomeia uma só granularidade
- [x] Baixador desenhado para a cota diária, retomável pelo próprio cache
- [x] Adaptador, com a projeção `player_match_stats`
- [x] Ligação da quarta fonte ao elenco canônico, com fusão de atletas, equipes e temporadas
- [x] 36 métricas agregadas e a agregação `RATE` que elas exigiram
- [x] Interface com seletor de granularidade

| Medida | Resultado |
|---|---|
| Temporadas acessíveis no plano gratuito | Brasileirão e Libertadores, 2022 a 2024 |
| Estatísticas por jogador e partida | 33 campos, 11 grupos |
| Catálogo | 144 métricas: 108 evento + 36 agregado |
| Ligação pela competição compartilhada | 338 de 338 atletas (100%), zero ambíguos |
| Entidades fundidas | 338 atletas, 16 equipes, 1 temporada |

**A validação mais forte do projeto veio daqui**, e de graça: as duas camadas concordam
na artilharia da Copa América — Lautaro 5, Rondón 3, Julián Álvarez 2 —, vindas de fontes
independentes por caminhos de cálculo completamente diferentes, uma somando finalizações
evento a evento e outra lendo totais já agregados.

**O achado que virou mecanismo.** A Copa América de 2024 existe nas duas fontes. Ligados
os identificadores ali, os mesmos reaparecem no Brasileirão, onde não há âncora nenhuma,
e o carregador reaproveita o atleta canônico sozinho. Sete atletas do Brasileirão já
chegaram unificados com o registro de seleção a partir de quatro partidas carregadas —
James Rodríguez, Sergio Rochet, Jhon Arias, Rafael Borré, Santiago Arias, Nahuel
Ferraresi e José Hurtado. Exatamente a população-alvo.

Cinco defeitos que só a execução contra dado real revelou:

- O filtro de partida encerrada aceitava só `FT` e descartava `AET` e `PEN`, escondendo
  cinco jogos da Copa América — **inclusive a final**. Não aparece em liga nacional, onde
  tudo termina em 90 minutos.
- `passes.accuracy` parece porcentagem pelo nome e é contagem: em 124 amostras nunca
  excedeu o total de passes.
- A fonte atribui o identificador 65657 a duas pessoas na mesma partida.
- A fusão de atletas falhava com violação de chave estrangeira por causa de uma passagem
  por clube *derivada* pelo próprio pipeline.
- A heurística de tipo classificou a Copa América, torneio de seleções, como competição
  de clubes.

## Fase 5 — Consolidação · Semanas 10 e 11

- API-Football: histórico de lesões e totais do Brasileirão, respeitando a cota diária
- Exportação do catálogo como tabela de definições operacionais (anexo do TCC)
- Testes de ponta a ponta e ampliação de cobertura
- Roteiro de reprodução: do clone à primeira tela
- Redação: metodologia, resultados, limitações

## Semana 12 — Folga

Deixada vazia de propósito. Ela vai ser usada.

---

## O que foi cortado, e por quê

| Cortado | Motivo | Estado |
|---|---|---|
| Distância percorrida, sprints, velocidade | Exige *tracking data*, que não existe para as competições com eventos | Demonstrável só em amostra aberta (Metrica, SkillCorner) — opcional |
| Velocidade de chute | Não registrada por nenhuma fonte acessível | Impossível |
| Desempenho por condição climática | Open-Meteo entrega o clima histórico por coordenada e hora | **Concluído** na Fase 1b |
| Salário e contrato | O Transfermarkt traz fim de contrato; salário não tem fonte aberta confiável | Contrato **concluído** na Fase 1b; salário segue fora |
| Equipe como entidade analítica | Dobra o escopo do motor de métricas | Fase 2 do projeto, pós-TCC |
| Modelo de xG próprio | Usar o `xg` da fonte; treinar um modelo é um TCC inteiro | Trabalho futuro |
| Raspagem de FBref, SofaScore, FotMob | APIs não oficiais, termos de uso restritivos, quebram sem aviso | Descartada; substituída por fontes com licença ou API oficial |
| Interface em React | Não é a contribuição do trabalho | Substituída por Dash |

Os dois primeiros itens não são corte de prazo, e sim limites das fontes: velocidade de chute
não existe em lugar nenhum, e métricas físicas só existem em amostras que não cobrem os
mesmos atletas. Trate-os como limitação metodológica declarada, não como funcionalidade
faltante — é assim que se apresenta numa defesa.

---

## Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Ingestão atrasa e trava tudo | Alto | Semanas 2–3 são as mais protegidas; carregue **uma** competição primeiro e siga para a Fase 2 com ela |
| Cadeia de posse mais difícil que o previsto | Médio | Entregável isolável; adiar não bloqueia nenhuma outra fase |
| Volume de eventos degrada o painel | Médio | Índices já definidos; cache por `Slice`; se necessário, tabela de agregados por atleta-partida |
| Escopo de métricas inflando | Alto | Teto de 80 métricas na Fase 2. O catálogo declarativo é o argumento de extensibilidade — não é preciso demonstrá-lo 200 vezes |
| Evolução de schema com banco carregado | Baixo | Enquanto for recarregável, `create_all` basta. Ao ficar caro recarregar, adote Alembic — não antes |

---

## Próximo passo imediato

Fase 5, a consolidação:

1. [x] **Roteiro de reprodução** — [`REPRODUCAO.md`](REPRODUCAO.md), do clone à primeira
   tela, com o número esperado em cada etapa. É o que permite a alguém de fora verificar o
   trabalho em vez de acreditar nele.
2. [ ] **Carga completa do Brasileirão** — quatro dias de cota gratuita, ou uma tarde no
   plano pago. Hoje há quatro partidas carregadas, o bastante para a ferramenta funcionar
   e pouco para ela demonstrar.
3. [x] **Histórico de lesões** — o último item aberto da especificação, carregado e
   **parcialmente** entregue, porque a fonte não tem o que o nome do endpoint promete.

   Ela dá uma linha por *partida perdida*, não por lesão: sem data de início, fim ou dias
   fora. Das 22 razões observadas, cinco são disciplinares ou administrativas — gravar um
   cartão como lesão seria simplesmente errado, então a classificação é explícita. Das
   1.414 ausências médicas, a maioria diz só "Injury", sem nomear a área.

   | Campo | Confiabilidade |
   |---|---|
   | Partidas perdidas | **exato** — é o que a fonte conta |
   | Datas de início e fim | limites do episódio, não diagnóstico |
   | Dias fora | **piso**: o afastamento começa antes da primeira partida perdida |
   | Área do corpo | ausente em 54 dos 78 episódios |

   O agrupamento de ausências seguidas em episódios (corte de 30 dias) é a **única
   inferência** do módulo, e está declarada como convenção. Resultado no Brasileirão de
   2024: 78 episódios, 62 atletas, com Pablo Maia perdendo 29 jogos por lesão na coxa.

   Isso destrava a análise de **disponibilidade** — histórico de lesão cruzado com
   minutagem —, que nada mais no projeto oferece.
4. [ ] **Testes de ponta a ponta** — a cadeia ingestão → métrica → API → figura tem
   cobertura em cada elo, mas não de uma ponta à outra.
5. [ ] **Redação** — metodologia, resultados e limitações.

O catálogo como anexo de metodologia já sai pronto em `fscout catalogo --csv`: 144
definições operacionais, com a granularidade de cada uma declarada.
