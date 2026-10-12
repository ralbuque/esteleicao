# Abstenção, horário de votação e identificação do eleitor por seção — Eleições 2026

Baixa os dados oficiais do TSE de comparecimento/abstenção de **todas as seções
eleitorais** e os **logs das urnas** (horário de cada voto e se o eleitor foi
identificado pela digital), e abre um painel
interativo (estilo BI) com média e desvio padrão por Brasil → estado →
município → zona → seção. Sinaliza seções com abstenção fora do padrão, votação
concentrada no fim do dia, muitos eleitores liberados sem digital e,
principalmente, essas coisas acontecendo juntas.

## Como usar

Requer Python 3.9+. No macOS o comando é `python3` (se não existir, o sistema
oferece instalar as "Command Line Tools"; aceite).

Na primeira vez, dentro da pasta do projeto:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python baixar_dados.py
streamlit run painel.py
```

Nas próximas vezes, basta `source .venv/bin/activate` e `streamlit run painel.py`.

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
tentativas automáticas. Os logs vão para `dados/logs_brutos_<ano>_<turno>t_<UF>.zip`.
**Se cair ou você interromper (Ctrl+C), rode o mesmo comando de novo**: ele
baixa só o que falta.

Opções:

- `--conexoes 4`: menos downloads simultâneos (use se aparecerem muitos erros).
- `--completo`: baixa o zip inteiro, retomando sozinho a cada queda (plano B).
  Também é usado automaticamente se o servidor não aceitar download parcial.
- `--zip arquivo.zip`: processa um zip que você baixou por conta própria.

Para baixar por conta própria (navegador ou `curl`, que também retoma de onde
parou com `-C -`), mantenha o nome original do arquivo e depois use `--zip`:

```bash
curl -L -C - --retry 50 --retry-all-errors -O https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_1t_CE.zip
python baixar_logs.py --zip bu_imgbu_logjez_rdv_vscmr_2026_1t_CE.zip
```

O processamento lê ~800 logs/s por núcleo de CPU. O painel junta os logs
automaticamente quando o arquivo `dados/logs_2026_t1_<UF>.parquet` existe. Fonte:
<https://dadosabertos.tse.jus.br/dataset/resultados-2026-arquivos-transmitidos-para-totalizacao>

Outras opções:

```bash
python baixar_dados.py --turno 2
python baixar_dados.py --ano 2022
python baixar_dados.py --zip caminho/do/arquivo.zip
```

Se o download falhar, baixe manualmente o arquivo **"Detalhe da apuração por
seção eleitoral"** em <https://dadosabertos.tse.jus.br/dataset/resultados-2026>
e use `--zip`.

Testes do critério "salto sem digital às 16h+" (sem dados, ou com os logs já processados):

```bash
python testar_fim_do_dia.py
python testar_fim_do_dia.py --plantar BA --resumo --bruto 3
```

Para testar sem baixar nada (dados inventados, com anomalias plantadas):

```bash
python gerar_dados_teste.py
python baixar_dados.py --ano 1999 --zip dados/teste_detalhe_votacao_secao.zip
for f in dados/teste_arqurna_*.zip; do python baixar_logs.py --zip $f; done
```

## Publicar na internet (servidor Windows)

Veja [deploy/LEIAME_WINDOWS.md](deploy/LEIAME_WINDOWS.md): `python deploy/empacotar.py` gera
`pacote_servidor.zip` (código + dados processados) e o script
`deploy/instalar_servico_windows.ps1` instala o painel como serviço do Windows via NSSM.

## O painel

- **Barra lateral**: escolhe eleição/turno, desce de nível (UF → município → zona → seção) e ajusta o critério de alerta.
- **Comparar**: média ± desvio padrão de cada subunidade (UFs, municípios, zonas ou locais de votação). Com muitos municípios, vira um gráfico média × desvio padrão onde quem destoa do grupo aparece isolado.
- **Distribuição**: histograma das seções com linhas de média, ±1 e ±2 desvios.
- **Funil**: abstenção × tamanho da seção, com limites de ±2 e ±3 desvios esperados para cada tamanho.
- **Sinalizadas**: seções que cumprem pelo menos 1, 2, 3 ou os 4 critérios abaixo (escolha na barra lateral), ordenadas pelo número de critérios e pela gravidade; exportável em CSV; clicar numa linha abre o detalhe.
- **Horário dos votos**: % dos votos em cada hora, hora média por subunidade (média ± desvio), distribuição por seção e lista das seções com mais votos após 17h.
- **Sem digital**: % de eleitores liberados sem digital hora a hora (separando "sem cadastro" de "liberação manual"), média ± desvio por subunidade, gráfico proporção × tamanho da seção e lista das seções acima do esperado.
- **Cruzamento**: escolha na barra lateral quais critérios precisam valer ao mesmo tempo (abstenção baixa, votação tardia, muitos sem digital, liberação manual alta, salto sem digital às 16h+). Cada seção vira um ponto; as que passam em todos os critérios ficam destacadas e listadas com os sinais encontrados no log.
- **Detalhe da seção**: seção vs zona, município, UF e Brasil; percentis; abstenções esperadas; perfil hora a hora comparado com as outras seções da mesma escola e com o município; e as outras seções do **mesmo local de votação**.

## Como uma seção é sinalizada

A aba **Sinalizadas** procura só quatro padrões (abstenção ALTA não é sinalizada):

| Critério | Regra padrão (ajustável na barra lateral) |
|---|---|
| 🔻 Abstenção baixa | z da abstenção ≤ −3 (abaixo do esperado para o município) e ≥ 50 aptos |
| ⏰ Voto após 17h | ≥ 15% dos votos depois das 17h, com pelo menos 10 votos; por padrão só conta se a hora média da seção for 30+ min mais tarde que a das outras seções da mesma escola (escola inteira tarde = fila) |
| 🖐️ Liberação manual | z da liberação manual pelo mesário (entre eleitores com digital cadastrada) ≥ 3 e pelo menos 5 casos |
| 🌆 Salto sem digital às 16h+ | a seção libera sem digital, a partir das 16h, bem mais eleitores do que ela mesma liberava antes das 16h: z ≥ 3, pelo menos 8 votos a mais que o esperado e o leitor ainda reconhecendo 25%+ de quem tem digital (ver abaixo) |

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
município. Todos os horários do painel estão em horário de Brasília.

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

## Salto sem digital a partir das 16h

É o sinal do voto no lugar de um eleitor que faltou: a pessoa vota normalmente e
volta no fim do dia para votar por um ausente. Com a urna biométrica, quem vota
no lugar de outro não passa na digital dele, então esse voto só sai como "sem
cadastro" (o ausente não tinha digital) ou como liberação manual pelo mesário
(o ausente tinha digital). O esquema muda a **composição** dos votos do fim do
dia.

Cada seção é comparada com ela mesma:

| Medida | O que é |
|---|---|
| % sem digital antes das 16h / a partir das 16h | proporção de eleitores liberados sem digital (sem cadastro + manual) em cada período, em horário de Brasília |
| excesso | votos sem digital a partir das 16h acima do esperado pela taxa da própria seção antes das 16h |
| z do salto | z binomial do excesso, padronizado por UF (mediana e MAD), porque o fim do dia tem perfil próprio |
| leitor ok | entre quem tem digital, pelo menos 25% reconhecidos no fim do dia (descarta leitor com defeito) |
| déficit de abstenção | abstenções esperadas menos observadas (as que "faltaram") |
| votos em jogo | o menor valor entre o déficit de abstenção e o excesso |

Por que comparar com a própria seção: fila às 17h não muda a composição (é o
mesmo público do dia), idosos costumam votar cedo e leitor com defeito falha
para quase todos. Também não depende da média do município, que cairia junto
se um esquema cobrisse o município inteiro.

Testes (`python testar_fim_do_dia.py --plantar BA --resumo --bruto 3`):

- casos construídos: fila às 17h, leitor que quebra às 16h e idosos votando cedo
  não são sinalizados; uma seção com 18 votos trocados é;
- esquema plantado em 1.000 seções reais da BA: detecta 52% das seções com 10
  votos trocados, 83% com 15 e 97% com 30; com 5 ou menos, quase nada;
- conferência voto a voto com o log bruto do TSE das seções com maior excesso.

A abstenção entra só como coerência (déficit cobrindo o excesso): a variação
natural da abstenção entre seções (cerca de 10 votos numa seção de 330) é do
mesmo tamanho de um esquema pequeno. Explicações comuns para o salto: leitor
que falhou por um tempo e eleitores sem digital cadastrada que deixaram para
votar no fim do dia. A ata da seção ajuda a separar esses casos.

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

1. Ver as **outras seções do mesmo local de votação** (aba de detalhe) — se a
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
