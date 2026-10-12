# esteleição: seções eleitorais que pedem atenção (Eleições 2026)

Usa os dados abertos do TSE de **todas as seções eleitorais** (comparecimento e
abstenção), os **logs das urnas** (horário de cada voto e se o eleitor foi
identificado pela digital) e o **cadastro de locais de votação** (endereço e
coordenadas da escola) para mostrar, num site leve e estático:

- quantas pessoas votaram **depois das 17h**, sempre em quantidade e porcentagem,
  do Brasil até a seção;
- as seções com abstenção fora do padrão, votação concentrada depois das 17h e
  muitos eleitores liberados pelo mesário sem digital, e principalmente essas
  coisas acontecendo juntas;
- um **mapa por município** com as seções em atenção e os locais de votação;
- um **plano de fiscalização**: a lista de escolas por prioridade, com endereço,
  seções a observar e quantos fiscais alocar.

## Como funciona

```
dados do TSE ──> baixar_*.py ──> dados/*.parquet ──> gerar_site.py ──> web/dados/*.json ──> navegador
                 (no Mac)                            (uma vez, ~12 min)   (Caddy só entrega arquivos)
```

Todo o cálculo (z-scores, cruzamentos, agregações por município, zona e escola)
é feito **uma vez** em `gerar_site.py`. O site em `web/` é HTML + JavaScript
puro e lê arquivos JSON prontos e compactados, divididos para que cada tela
baixe só o necessário. Nada é processado quando alguém abre a página.

## Como usar

Requer Python 3.9+. No macOS o comando é `python3`.

Na primeira vez, dentro da pasta do projeto:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python baixar_dados.py
python baixar_logs.py
python baixar_locais.py
python gerar_site.py --servir
```

`gerar_site.py --servir` gera os dados do site e abre em <http://localhost:8000>. Com os dados do Brasil inteiro leva
cerca de 12 minutos e usa até ~6 GB de memória.
Para só gerar (antes de publicar): `python gerar_site.py`.

| Script | O que baixa | Resultado |
|---|---|---|
| `baixar_dados.py` | "Detalhe da apuração por seção eleitoral" | `dados/secoes_<ano>_t<turno>.parquet` |
| `baixar_logs.py` | logs das urnas, um zip por UF | `dados/logs_<ano>_t<turno>_<UF>.parquet` |
| `baixar_locais.py` | "Eleitorado por local de votação" (endereço, bairro, CEP, latitude e longitude) | `dados/locais_<ano>.parquet` |
| `baixar_votacao.py` | "Votação por seção eleitoral" (votos por candidato), um zip por UF | `dados/votacao_<ano>_t<turno>_<UF>.parquet` |
| `baixar_perfil.py` | "Perfil do eleitorado por seção" (idade, biometria) | `dados/perfil_<ano>_<UF>.parquet` |
| `baixar_ibge.py` | população do Censo 2022 por idade (IBGE/SIDRA) | `dados/populacao_2022.parquet` |
| `baixar_transferencia.py` | transferência temporária do eleitorado por seção | `dados/transferencia_<ano>.parquet` |
| `baixar_gastos.py` | prestação de contas: despesas contratadas dos candidatos | `dados/gastos_<ano>.parquet` |
| `gerar_site.py` | nada: lê os `.parquet` | `web/dados/` (JSON + versão `.gz`) |

Os cinco do meio alimentam a aba **Mais análises** e são opcionais: sem eles o site
funciona normalmente, sem aquela parte. Para a repetição entre eleições, baixe também
`python baixar_dados.py --ano 2022` (e, se der, `python baixar_logs.py --ano 2022`).

Os logs e os locais são opcionais: sem logs, o site mostra só a abstenção
daquela UF; sem locais, as seções são localizadas pelo município.

### Logs de urna (horário dos votos e identificação do eleitor)

```bash
python baixar_logs.py --ufs AC
python baixar_logs.py --ufs CE BA
python baixar_logs.py
```

Os arquivos do TSE ("Arquivos transmitidos para totalização") vêm **um zip por
UF**, com boletins, RDV, assinaturas e logs de cada seção: de centenas de MB
(estados pequenos) a vários GB (CE ≈ 4,3 GB, BA ≈ 6,6 GB). Por isso o script,
por padrão, **baixa só os logs** de dentro do zip (cerca de metade do
tamanho), lendo o índice do zip e buscando cada log separadamente
(download parcial / HTTP Range), em 8 conexões simultâneas e com novas
tentativas automáticas. **Se cair ou você interromper (Ctrl+C), rode o mesmo
comando de novo**: ele baixa só o que falta.

Opções: `--conexoes 4` (menos downloads simultâneos), `--completo` (baixa o zip
inteiro, retomando a cada queda) e `--zip arquivo.zip` (processa um zip baixado
por conta própria, por exemplo com
`curl -L -C - --retry 50 --retry-all-errors -O <url>`).

Outras eleições: `python baixar_dados.py --turno 2`, `--ano 2022`, `--zip caminho.zip`
(e o mesmo `--ano`/`--turno` em `gerar_site.py`).

### Testar sem baixar nada

Tudo de uma vez (todas as fontes, inclusive as de "Mais análises", com conferência automática dos casos plantados):

```bash
python testar_sem_internet.py --servir
```

Ou passo a passo, só as fontes principais:

Dados inventados, com anomalias plantadas e municípios reais (para o mapa):

```bash
python gerar_dados_teste.py
python baixar_dados.py --ano 1999 --zip dados/teste_detalhe_votacao_secao.zip
for f in dados/teste_arqurna_*.zip; do python baixar_logs.py --zip $f; done
python baixar_locais.py --ano 1999 --zip dados/teste_eleitorado_local_votacao.zip
python gerar_site.py --ano 1999 --servir
```

## Publicar na internet (servidor Windows)

Veja [deploy/LEIAME_WINDOWS.md](deploy/LEIAME_WINDOWS.md). Resumo: no Mac,
`python gerar_site.py` e `python deploy/empacotar.py`; no servidor, extrair o
`pacote_servidor.zip` e rodar `deploy\publicar_site.ps1`. O Caddy serve a pasta
`web\` direto (`deploy/Caddyfile.est`), sem Python no servidor.

## O site

- **Recorte** (barra abaixo das abas): Brasil → estado → município → zona. Vale para todas as telas e fica no endereço da página, então dá para compartilhar o link.
- **Rigor**: rigoroso, padrão ou amplo (muda os limites dos três critérios).
- **Panorama**: resumo em uma frase, números principais, os três critérios, votos por hora e a tabela do nível abaixo (estados, municípios, zonas ou seções).
- **Simule o 2º turno**: nas disputas que foram ao 2º turno (presidente e governadores), os votos oficiais do 1º turno, os votos de quem ficou de fora, brancos, nulos e abstenção, e um cenário em que a pessoa escolhe como esses votos se dividem. Para presidente, soma os votos válidos a mais do 2º turno de 2022 na proporção do eleitorado atual, com a explicação da escolha. É uma conta, não uma previsão. Dados em `simulador.py` (`web/dados/turno2.json`).
- **Mapa**: municípios pintados por seções em atenção, votos após 17h (quantidade ou %), abstenção baixa ou liberação manual. Num estado, mostra também os locais de votação em atenção (pelas coordenadas do TSE). Clicar num município lista as seções e os endereços.
- **Votos após 17h**: quantidade e % por estado, município e zona; seções por faixa de quantidade; as seções com mais votos depois das 17h, com o horário do último voto e a comparação com as outras seções da mesma escola.
- **Seções em atenção**: lista filtrável (critério, 2+ critérios, busca por escola/bairro/seção), exportável em CSV.
- **Casos extremamente atípicos**: seções com 50+ votos fora do log publicado da urna, urna que só começou depois das 15h ou que terminou sozinha, muito depois das outras do mesmo local. São tags (fora da contagem dos critérios), em cartões, com filtros "tem / não tem" e ordenação à escolha.
- **Sem digital, com foto** (tag) e **tempo de cabine** (sinal no detalhe): a partir de `eleitores_urna.py` e `medidas_eleitores.py`, que leem o log eleitor por eleitor.
- **Plano de fiscalização**: locais de votação por prioridade (alta, média, baixa), com endereço, link para o mapa, seções a observar, eleitores, motivos e fiscais sugeridos; checklist do que observar em cada critério; imprimível e exportável.
- **Detalhe da seção**: cada critério explicado em frases com os números, sinais do log, votos por hora comparados com o município, as outras seções da mesma escola e como verificar.

## Como uma seção é sinalizada

A aba **Seções em atenção** procura só três padrões (abstenção ALTA não é sinalizada). O seletor **Rigor** no alto do site escolhe entre três níveis; a tabela mostra o padrão:

| Critério | Regra padrão (rigor padrão) |
|---|---|
| 🔻 Abstenção baixa | z da abstenção ≤ −3 (abaixo do esperado para o município) e ≥ 50 aptos |
| ⏰ Voto após 17h | ≥ 15% dos votos depois das 17h, com pelo menos 10 votos; por padrão só conta se a hora média da seção for 30+ min mais tarde que a das outras seções da mesma escola (escola inteira tarde = fila) |
| 🖐️ Liberação manual | z da liberação manual pelo mesário (entre eleitores com digital cadastrada) ≥ 3 e pelo menos 5 casos |

Em UFs sem logs baixados, só a abstenção pode ser avaliada. Abaixo, o detalhe
de como o z da abstenção é calculado:

Cada seção é comparada com **o próprio município** (sem contar ela mesma). Se o
município tem menos de 5 seções, a comparação é com a UF.

| Medida | Fórmula | Observação |
|---|---|---|
| z simples | (taxa − média) / desvio padrão | O que se pede intuitivamente, mas seções pequenas variam muito por acaso e dominam a lista. |
| z binomial | (faltaram − esperado) / √(aptos·p·(1−p)) | Considera o tamanho da seção, mas supõe que só o acaso separa as seções — sinaliza milhares. |
| **z ajustado** (padrão) | (taxa − esperada) / √(p(1−p)/aptos + τ²) | τ² é a variação natural entre seções (perfil etário, renda, cadastro desatualizado), estimada por UF de forma robusta. É o modelo de efeitos aleatórios usado em *funnel plots*. Com \|z\| ≥ 3, sinaliza poucas seções de verdade. |

## Horário dos votos: o que é medido

O log (`logd.dat`, dentro do `-log.jez` em 2026, que é um zip, ou do `.logjez` em
2022, que é um 7z) registra cada evento da urna com data e
hora. Cada linha "O voto do eleitor foi computado" é um voto; a linha
"Tipo de habilitação do eleitor [biométrica]" antes dele indica que o eleitor
foi liberado pela digital. Linhas de dias anteriores (testes, carga) são
ignoradas.

**Fuso horário**: a votação é de 8h às 17h no horário de Brasília em todo o
país, mas a urna marca a hora local (no AM/MT/MS/RO/RR abre às 7h locais; no
AC, às 6h). O fuso de cada seção é estimado pela hora em que a urna ficou
pronta para o primeiro eleitor e harmonizado pelo fuso mais comum do
município. Todos os horários do site estão em horário de Brasília.

| Métrica | O que é |
|---|---|
| hora média | média do horário dos votos da seção |
| z horário | (hora média − mediana do município) ÷ dispersão robusta (MAD) do município. Positivo = mais tarde |
| % após 17h | votos computados depois do encerramento |
| sem biometria após 17h | % dos votos depois das 17h sem habilitação por digital |
| urna ociosa antes das 17h | maior intervalo sem votos entre 16h e 17h |
| dif. para a escola | minutos de diferença para a média das outras seções do mesmo local |
| **score cruzado** | min(−z da abstenção, z do horário): só é alto se a seção tiver **ao mesmo tempo** abstenção baixa e votação tardia |

Sinais listados por seção: ≥10% dos votos após 17h · urna ociosa ≥20 min antes
das 17h mas com votos depois · maioria sem biometria após 17h · votos após 17h
em ritmo muito rápido (≤45 s) · 1h+ mais tarde que as outras seções da escola ·
votos no log ≠ comparecimento oficial · urna substituída · abertura atrasada.

## Identificação do eleitor (digital)

Para cada voto, o log mostra como o eleitor foi liberado:

| Tipo | Mensagem no log | O que significa |
|---|---|---|
| Digital | `Tipo de habilitação do eleitor [biométrica]` | digital reconhecida |
| Sem cadastro | `O eleitor não possui biometria` (2022) ou liberação pelo ano de nascimento sem nenhuma tentativa de digital (2026) | o eleitor não tem digital cadastrada na Justiça Eleitoral |
| **Liberação manual** | `Solicitação de dado pessoal do eleitor para habilitação manual` | o eleitor **tem** digital cadastrada, ela não foi reconhecida em 4 tentativas e o **mesário liberou** o voto com a digital dele |

Indicadores por seção:

| Métrica | O que é |
|---|---|
| % sem digital | (sem cadastro + liberação manual) ÷ votos |
| % liberação manual | liberação manual ÷ eleitores que têm digital cadastrada |
| z sem digital / z manual | mesmo método do z ajustado da abstenção: compara com o próprio município, considerando o tamanho da seção e a variação natural entre seções |
| maior sequência manual | maior número de eleitores **seguidos** liberados pelo mesário |
| dif. para a escola | p.p. de diferença no % sem digital para as outras seções do mesmo local |

Sinais: sem digital muito acima do município (z ≥ 3) · liberação manual muito
acima do município (z ≥ 3) · 8+ liberações manuais seguidas · sem digital 25+
p.p. acima das outras seções da escola · maioria sem biometria após 17h.

**Cuidado ao interpretar**: liberar sem digital é previsto em lei e comum
(cerca de 1 em cada 5 eleitores). "Sem cadastro" depende sobretudo do
cadastro biométrico da região (eleitores novos, regiões onde a revisão
biométrica não chegou), e costuma atingir **a escola inteira**. A liberação
manual de quem tem digital também acontece por motivos comuns: idosos,
trabalhadores braçais com digitais gastas, leitor sujo ou com defeito. Um
leitor com defeito, aliás, pode gerar uma longa sequência de liberações
manuais legítimas, e a ata da seção deve registrar isso. O indicador mais
específico é a **liberação manual**, muito acima do município, **em sequência**,
numa seção que destoa das outras da mesma escola, e se possível junto com
abstenção baixa e/ou votos após as 17h.

## Como interpretar (importante)

Uma seção com abstenção atípica **não é indício de fraude por si só**, e a
grande maioria tem explicação comum:

- **Alta**: seção com muitos idosos (voto facultativo após 70 anos), eleitores
  que se mudaram e não transferiram o título, óbitos ainda não baixados,
  zona rural ou ribeirinha distante, presídios/unidades especiais,
  seções que receberam muitos eleitores transferidos (voto em trânsito).
- **Baixa**: seções novas ou recém-agregadas, cadastro biométrico recente
  (revisão eleitoral limpa o cadastro), comunidades pequenas e coesas.

Abstenção é o número de eleitores que **não** foram votar; ela é registrada
pela urna a partir dos eleitores habilitados pelos mesários. Por isso, um caminho
mais informativo para investigar um ponto sinalizado é:

1. Ver as **outras seções do mesmo local de votação** (detalhe da seção) — se a
   escola inteira destoa, é perfil da região; se só uma seção destoa, vale olhar mais.
2. Comparar com **2022** (`--ano 2022`): uma seção que é atípica em todas as
   eleições quase sempre tem causa estrutural.
3. Conferir o **boletim de urna** e o **log da urna** daquela seção no site de
   resultados do TSE e, se for o caso, encaminhar a dúvida ao TRE do estado.

Com cerca de 470 mil seções, mesmo uma regra muito rigorosa vai listar
dezenas a centenas de seções só por acaso estatístico.

**Sobre o horário**: votar depois das 17h é legal: quem está na fila às 17h
vota. No 1º turno de 2022 foram cerca de 4 milhões de votos após as 17h. E
abstenção baixa e votação tardia andam juntas naturalmente: mais eleitores
comparecendo → mais fila. Causas comuns de votação tardia: fila na escola,
problemas de biometria (cada eleitor demora mais), urna substituída, abertura
atrasada, seções agregadas. O que separa fila de algo estranho é o contexto:

- fila de verdade atinge **a escola inteira** e vem precedida de uma última hora
  **cheia** (sem intervalos);
- uma seção que ficou **ociosa antes das 17h** e depois recebeu uma **rajada de
  votos sem biometria**, enquanto as outras seções da escola encerraram
  normalmente, merece um olhar no boletim, no log e na ata da seção.
