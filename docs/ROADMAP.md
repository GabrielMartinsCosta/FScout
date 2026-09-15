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

## Fase 1b — Ficha do atleta e fontes complementares · Semanas 2 e 3

Detalhes e justificativas em [`FONTES.md`](FONTES.md).

- Adaptador transfermarkt-datasets: data de nascimento, altura, pé, dupla nacionalidade,
  valor de mercado, fim de contrato, transferências
- Ligação de registros entre StatsBomb e Transfermarkt por nome, nacionalidade e equipe na
  mesma temporada, com fila de revisão manual
- Validação da ligação: precisão numa amostra conferida à mão e cobertura
- Open-Meteo: clima de cada partida a partir da coordenada do estádio
- Carga das competições-alvo: Copa do Mundo 2022, Euro 2024, La Liga 2020/21

**Pronto quando:** os atletas da Copa América 2024 têm idade e altura preenchidas, e a
precisão da ligação está medida e documentada.

## Fase 2 — Motor de métricas · Semanas 4 e 5

- `Slice`: o objeto de recorte, com aplicação uniforme em qualquer consulta
- `MetricSpec` e o registro do catálogo
- Predicados reutilizáveis (`is_goal`, `outside_box`, `from_corner`, `left_foot`, …)
- Definições por família: finalização, passe, drible, defesa, goleiro, disciplina, geral
- Normalização por 90 minutos e cálculo de percentis dentro de grupo de posição
- Cache por `Slice` (que é imutável, portanto hasheável)

**Pronto quando:** `evaluate(spec, slice)` responde qualquer métrica do catálogo, e um
teste confere que "gols de canhota de fora da área" bate com a contagem manual num jogo.

**Meta de escopo:** **60 a 80 métricas** bem definidas. Não duzentas. Cubra as famílias
inteiras com profundidade — é a completude *conceitual* que se defende, e o catálogo
declarativo deixa evidente que acrescentar as demais é trivial.

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
| Desempenho por condição climática | Open-Meteo entrega o clima histórico por coordenada e hora | **Reincluído** na Fase 1b |
| Salário e contrato | O Transfermarkt traz fim de contrato; salário não tem fonte aberta confiável | Contrato reincluído na Fase 1b; salário segue fora |
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

Fase 1b, começando pelo Transfermarkt: é o que preenche a ficha básica do atleta, que a
especificação trata como fundamental, e é onde a ligação entre fontes é construída e
medida.
