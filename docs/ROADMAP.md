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

## Fase 1 — Ingestão · Semanas 2 e 3

Sem dado no banco, nada mais pode ser validado. É a fase de maior risco do cronograma.

- Cliente StatsBomb com cache em disco (`data/raw/`), para não rebaixar a cada execução
- Mapeador JSON → domínio: competições, temporadas, partidas, escalações, eventos
- Mapeadores das projeções: `shots`, `passes`, `dribbles`, `defensive_actions`,
  `goalkeeper_actions`, `disciplinary_actions`
- Resolução de cadeia de posse: pré-assistência, consequência do drible, rebote
- Cálculo de minutagem a partir de escalação e substituições
- Pipeline idempotente com registro em `ingestion_runs`
- CLI: `fscout ingest --competition 11 --season 90`

**Pronto quando:** uma competição inteira carrega, recarregar não duplica nada, e os
totais de gols por partida batem com o placar registrado em `matches`.

**Risco principal:** a cadeia de posse é a parte sutil. Se atrasar, entregue a ingestão
sem `led_to_*` e `is_pre_assist` e volte a eles na Semana 5 — o resto não depende disso.

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

- Adaptador CSV para dados de clube, lesões e valor de mercado
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
| Distância percorrida, sprints, velocidade | Exige *tracking data*, inexistente em fonte aberta | Impossível — declarar como limitação |
| Velocidade de chute | Não registrada por nenhuma fonte acessível | Impossível |
| Desempenho por condição climática | Sem fonte confiável e sem massa de dados suficiente | Trabalho futuro |
| Salário e contrato | Tabela existe; alimentação seria manual e de baixa confiabilidade | Trabalho futuro |
| Equipe como entidade analítica | Dobra o escopo do motor de métricas | Fase 2 do projeto, pós-TCC |
| Modelo de xG próprio | Usar o `xg` da fonte; treinar um modelo é um TCC inteiro | Trabalho futuro |
| Scraping de FBref/SofaScore | Entrega dado agregado, que não sustenta a análise granular | Descartado na escolha de fonte |
| Interface em React | Não é a contribuição do trabalho | Substituída por Dash |

Os dois primeiros itens não são corte de prazo: são impossibilidades da fonte. Trate-os
como limitação metodológica declarada, não como funcionalidade faltante — é assim que se
apresenta numa defesa.

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

Fase 1, cliente StatsBomb e mapeador de partidas. O primeiro alvo concreto:

```
fscout ingest --competition 11 --season 90    # La Liga 2020/21
```

e, ao final, uma consulta que responda quantos gols de canhota de fora da área foram
marcados na temporada. É o teste que fecha a Fase 1 e abre a Fase 2.
