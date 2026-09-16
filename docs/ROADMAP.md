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

## Fase 3 — API · Semana 6

- `GET /players` — busca e filtro
- `GET /players/{id}` — ficha e histórico
- `POST /metrics/evaluate` — catálogo avaliado sob um `Slice`
- `POST /compare` — N jogadores × M métricas × K recortes
- `GET /players/{id}/shots` e `/passes` — eventos brutos para os mapas
- `GET /catalog` — o catálogo de métricas, que a interface consome para se montar

**Pronto quando:** `/docs` do FastAPI responde tudo que a interface vai precisar.

## Fase 4 — Visualização · Semanas 7 a 9

Prioridade estrita. Se o tempo acabar, acaba de baixo para cima.

1. **Perfil do atleta** — dados básicos, cartões de resumo, barra de recortes
2. **Mapa de chutes** — sobre o desenho do campo, tamanho por xG, cor por desfecho
3. **Radar comparativo** — percentis dentro do grupo de posição, 2 ou mais atletas
4. **Mapa de calor** — a partir das células de grade pré-calculadas
5. **Mapa de passes** — origem, destino, cor por sucesso, filtro por tipo
6. **Tabela comparativa** — N jogadores × M métricas, com recorte independente por coluna
7. **Boca do gol** — grade 3×3, para pênaltis e para a leitura do goleiro
8. **Mapa-múndi** — marcador por país, raio proporcional a G/A

**Pronto quando:** o item 6 funciona. Do 7 em diante é ganho, não requisito.

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

Fase 2, o motor de métricas: o `Slice` de recortes, o catálogo declarativo de `MetricSpec` e
a normalização por 90 minutos. É a contribuição central do trabalho, e agora ela tem sobre o
que rodar: 662 mil eventos de 182 partidas, com ficha, valor de mercado e clima ligados.
