# CLAUDE.md — contexto do projeto esteleicao

Este arquivo resume tudo o que foi feito e decidido neste projeto, para que
qualquer sessão do Claude Code (no Mac ou no servidor Windows) continue o
trabalho sem precisar do histórico da conversa original.

**Idioma:** o usuário (Ricardo) conversa em português do Brasil. Responda em português.

## 1. Objetivo

Painel web (estilo BI) com dados abertos do TSE das **Eleições Gerais 2026
(1º turno, 04/10/2026)** para encontrar **seções eleitorais com comportamento
atípico** que possam (eventualmente) indicar irregularidade. Navegação
Brasil → UF → município → zona → seção.

O usuário quer focar em três padrões (aba "Seções em atenção"):

1. **Abstenção BAIXA** (abstenção alta não interessa).
2. **Voto após 17h significativo.**
3. **Liberação manual pelo mesário** de eleitores que **têm digital cadastrada**.

Postura combinada com o usuário: sinalização estatística **não é prova de
fraude**; a maioria dos casos tem explicação comum (fila, perfil do eleitorado,
cadastro biométrico, leitor com defeito). O site tem aviso no rodapé, na aba
"Como ler" e em cada tela. Manter esse tom.

## 2. Arquivos

| Arquivo | Função |
|---|---|
| `baixar_dados.py` | Baixa "Detalhe da apuração por seção eleitoral" (CDN do TSE) → `dados/secoes_<ano>_t<turno>.parquet` (aptos, comparecimento, abstenção por seção). |
| `baixar_logs.py` | Baixa os logs das urnas por UF e gera `dados/logs_<ano>_t<turno>_<UF>.parquet` (métricas por seção). |
| `baixar_locais.py` | Baixa "Eleitorado por local de votação" → `dados/locais_<ano>.parquet` (nome da escola, endereço, bairro, CEP, lat/lon por seção). |
| `download_tse.py` | Downloads resilientes: modo padrão baixa **só os logs** de dentro do zip remoto via HTTP Range (lê o diretório central do zip, 8 conexões, retomável, grava em `dados/logs_brutos_<ano>_<turno>t_<UF>.zip`); plano B `--completo` baixa o zip inteiro com retomada. |
| `logs_urna.py` | Parser do log da urna (`logd.dat`) e cálculo de métricas por seção. |
| `analise.py` | Estatística: z da abstenção, z de proporções (sem digital, manual, após 17h), z do horário, sinais, correção de fuso. |
| `gerar_site.py` | Roda toda a análise UMA vez e grava `web/dados/*.json` (+ `.gz`): `brasil.json`, `municipios.json`, `apos17.json`, `plano.json`, `uf/<UF>.json`, `mun/<cd>.json`, `zona/<cd>-<zona>.json`. `--servir` abre em localhost:8000. |
| `web/` | Site estático (HTML + `app.js` + `estilo.css`, sem build). `vendor/` (d3-geo, d3-array, topojson-client), `fontes/` (Archivo), `mapa/brasil.topo.json` (5.564 municípios simplificados, id = código IBGE). |
| `referencia/municipios.csv` | Código TSE ↔ código IBGE, nome, lat/lon do centro de cada município (fontes: betafcc/Municipios-Brasileiros-TSE e kelvins/municipios-brasileiros). |
| `gerar_dados_teste.py` | Dados sintéticos com anomalias plantadas (ano 1999), municípios reais e arquivo de locais de votação. |
| `deploy/Caddyfile.est` | Bloco do Caddy: `esteleicao.com` → `file_server` da pasta `C:/git/esteleicao/web` (precompressed gzip, cache). |
| `deploy/publicar_site.ps1` | Extrai o pacote, remove o serviço NSSM antigo do Streamlit, valida e recarrega o Caddy. |
| `deploy/diagnosticar_caddy.ps1` | Diagnóstico do HTTPS no Caddy. |
| `deploy/empacotar.py` | Gera `pacote_servidor.zip` com `web/` (site + dados) no Mac. |
| `deploy/publicar_pages.ps1` | Roda `gerar_site.py` e publica `web/` (sem .gz, com .nojekyll) na branch órfã `gh-pages` (GitHub Pages). |
| `docs/ideias-de-relatorios.md` | Próximos relatórios e dados sugeridos para fiscalização. |
| `extras.py` | Análises da aba "Mais análises" (a–i de docs/ideias-de-relatorios.md). Só ACRESCENTA colunas; não muda os 3 critérios. Cada fonte é opcional. |
| `leitura_tse.py` | Leitura de CSV do TSE com detecção flexível de colunas (usado pelos baixar_* novos). |
| `baixar_votacao.py` | Votação por seção (por candidato) → `dados/votacao_<ano>_t<turno>_<UF>.parquet`. Materialidade e voto concentrado. Confere votos ÷ comparecimento por cargo. |
| `baixar_perfil.py` | Perfil do eleitorado por seção → `dados/perfil_<ano>_<UF>.parquet` (16–17, 60–69, 70+, biometria). |
| `baixar_ibge.py` | População Censo 2022 por idade (SIDRA, tabela 9514, confirmada) → `dados/populacao_2022.parquet`. |
| `baixar_transferencia.py` | Transferência temporária por seção → `dados/transferencia_<ano>.parquet` (pasta `perfil_eleitor_tte` do CDN). |
| `baixar_gastos.py` | Prestação de contas (despesas contratadas) → `dados/gastos_<ano>.parquet` por município do fornecedor e categoria. |
| `testar_sem_internet.py` | Teste completo com dados sintéticos + conferência automática dos casos plantados (31 conferências). ATENÇÃO: grava em `dados/` e `web/dados/` (sobrescreve `populacao_2022.parquet`); rode numa cópia do projeto se houver dados reais. |
| `eleitores_urna.py` | Uma linha por eleitor a partir dos logs → `dados/eleitores_<ano>_t<turno>_<UF>.parquet` (tipo de liberação, cargos, tentativas de digital, foto, mesário numerado, horários). |
| `docs/analise-casos-atipicos.md` | Achados e fórmulas das análises de out/2026 (tempo de voto, liberação pelo mesário, casos atípicos de horário). |

`dados/`, `web/dados/`, `logs/`, `.venv/`, `pacote_servidor.zip` estão no `.gitignore`.
O painel Streamlit (`painel.py`) foi substituído pelo site estático em out/2026 (está no histórico do git).

## 3. Fontes de dados (TSE)

- Abstenção por seção: `https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_secao/detalhe_votacao_secao_2026.zip`
  (CSV `;`, latin-1; colunas usadas: NR_TURNO, SG_UF, CD_MUNICIPIO, NM_MUNICIPIO, NR_ZONA, NR_SECAO, CD_CARGO=1, QT_APTOS, QT_COMPARECIMENTO, QT_ABSTENCOES, NR_LOCAL_VOTACAO, NM_LOCAL_VOTACAO...).
- Logs das urnas ("Arquivos transmitidos para totalização"), um zip por UF:
  `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_1t_<UF>.zip`
  (de centenas de MB a vários GB; CE ≈ 4,3 GB, BA ≈ 6,6 GB; ZIP64).
- O CDN do TSE tinha quedas de conexão (`Read timed out`); por isso o download por faixas com retomada.

### Formato dos logs em 2026 (diferente de 2022!)

- Nome: `o03220ac0101500020088-log.jez` = pleito 03220, UF `ac`, município 01015, zona 0002, seção 0088. Em 2022 era `....logjez`.
- `-log.jez` em 2026 é **ZIP comum** (em 2022 era 7z). Dentro: `logd.dat`, texto latin-1, TAB: `data hora | nível | id urna | app | mensagem | hash`.
- Mensagens usadas (app `VOTA`, só no dia da eleição = dia com mais votos):
  - urna pronta: `Aguardando digitação do título` (2022) / `Aguardando digitação do identificador do eleitor` (2026)
  - voto: `O voto do eleitor foi computado`
  - digital: `Tipo de habilitação do eleitor [biométrica]`
  - **sem cadastro**: `O eleitor não possui biometria` (2022) / em 2026 `Ano de nascimento digitado é igual ao do cadastro` **sem nenhuma tentativa de digital**
  - **liberação manual** (tinha digital, falhou 4 tentativas, mesário liberou): `Solicitação de dado pessoal do eleitor para habilitação manual`
- Validação com dados reais de 2026 (todas as UFs): 124,75 mi votos no log vs 124,93 mi comparecimento oficial; 99,6% das seções batem exatamente; 0 votos sem classificação. Brasil: sem digital 12,2% (sem cadastro 5,6%, manual 6,7%), votos após 17h 2,98%.

## 4. Métodos estatísticos (decisões)

- **z ajustado da abstenção** (padrão): `(taxa − esperada) / sqrt(p(1−p)/aptos + τ²)`; esperada = taxa do próprio município sem a seção (leave-one-out), UF se o município tem < 5 seções; τ² = variação natural entre seções, estimada por UF de forma robusta (mediana/MAD). Também existem z simples e z binomial (em `analise.py`; o site usa o ajustado).
- Mesmo método (`analise.z_proporcao`) para: % sem digital, % liberação manual (denominador = eleitores com digital cadastrada), % após 17h.
- **Horário**: tudo em horário de Brasília (8h–17h). A urna marca hora local. Fuso por seção = fuso oficial da UF (`FUSO_OFICIAL` em `logs_urna.py`: AC −2; AM, MT, MS, RO, RR −1; resto 0), trocado só se a abertura destoar > 45 min (casos reais: oeste do AM −2, Fernando de Noronha +1, leste do MT usa horário de Brasília = 0). Harmonizado pelo fuso mais comum do município. `analise.corrigir_fuso` reaplica a regra em parquets antigos usando os histogramas por hora (`h00..h23`, `s00..` sem digital, `m00..` manual), com resultado idêntico ao reprocessamento.
- Achado: Guaporema, Nova Olímpia e Tapira (PR, 40 seções) têm a curva de votos ~40 min adiantada → relógio das urnas adiantado; aparecem com "abertura atrasada" e % após 17h inflado. Não é indício de fraude.
- **Seções em atenção**: critérios independentes, a seção mostra quantos cumpre (rigor padrão abaixo; rigoroso/amplo em `gerar_site.NIVEIS`):
  - abstenção baixa: z ≤ −limite (padrão 3) e ≥ 50 aptos;
  - voto após 17h: ≥ 15% dos votos após 17h e ≥ 10 votos; por padrão só conta se a hora média da seção for 30+ min mais tarde que as outras seções da mesma escola (escola inteira tarde = fila);
  - liberação manual: z_manual ≥ limite e ≥ 5 casos.
- **Plano de fiscalização** (por local de votação, rigor padrão): ALTA = alguma seção com 2+ critérios, 3+ seções em atenção no local ou desvio muito forte (abst z ≤ −5, manual z ≥ 5, ou ≥30% e ≥30 votos após 17h); MÉDIA = 2 seções ou sinal no log (urna ociosa, maioria sem biometria após 17h, sequência manual, ritmo rápido); BAIXA = 1 seção. Fiscais sugeridos = 1 por local + 1 a cada 4 seções.
- "sinais" por seção (texto): ≥10% após 17h; urna ociosa ≥20 min antes das 17h mas votos depois; maioria sem biometria após 17h; ritmo muito rápido após 17h; 1h+ mais tarde que a escola; sem digital/manual muito acima do município; 8+ liberações manuais seguidas; log ≠ comparecimento; urna substituída; abertura atrasada.

## 5. Site: desempenho e decisões

- Antes (Streamlit): cada visita rodava o script inteiro sobre ~500 mil seções; medido com base sintética de 470 mil seções: 18,5 s na primeira visita, ~10 s nas seguintes, ~730 MB de RAM no servidor após 3 visitas.
- Agora: site estático. Mesma base: 0,2 s para abrir o Panorama (123 KB transferidos, 90 KB são a fonte), 0,7 s o mapa; em 4G simulado (9 Mbps, 150 ms) 0,7 s e 2 s. Servidor: só o Caddy (~50 MB).
- Arquivos divididos para cada tela baixar só o necessário: municípios num arquivo; seções sinalizadas (no rigor amplo; o site filtra os outros níveis) por UF; todas as seções por zona (nenhum arquivo fica grande, nem a capital paulista).
- Critérios em bits por seção (`flags`): bits 0-2 rigoroso, 3-5 padrão, 6-8 amplo (abst=1, 17h=2, manual=4). Níveis em `gerar_site.NIVEIS`.
- Sempre mostrar QUANTIDADE ao lado da porcentagem (pedido do usuário: a % sozinha assusta).
- Visual: cores da urna (laranja do CORRIGE = atenção; verde do CONFIRMA), fonte Archivo; textos em português simples, sem jargão (z aparece só como "intensidade" no detalhe).

## 6. Publicação antiga (servidor Windows de outra pessoa; só histórico, ver seção 7)

- Servidor Windows, IP público **72.167.48.234**, repositório em **`C:\git\esteleicao`**.
- O **Caddy** roda como serviço do **NSSM** com o Caddyfile principal em `C:\Git\veracibot\deploy\windows\Caddyfile`, que importa `C:/git/esteleicao/deploy/Caddyfile.est`.
- Arquitetura: `navegador → Caddy (esteleicao.com, HTTPS automático) → arquivos de C:\git\esteleicao\web`. Sem Python no servidor; o serviço NSSM "esteleicao" (Streamlit) é removido por `publicar_site.ps1`.
- Dados: gerados no Mac (`gerar_site.py`), empacotados (`deploy/empacotar.py`) e extraídos no servidor (`deploy/publicar_site.ps1`).
- Cache: `brasil.json` sem cache (traz `gerado_em`); demais dados pedidos com `?v=<gerado_em>` e cache de 1 dia; vendor/fontes/mapa 7 dias; HTML/JS/CSS `no-cache`.

## 7. Estado atual e PRÓXIMO PASSO (onde paramos)

- 12/out/2026 (sessão na nuvem): Etapas 2 a 4 feitas com DADOS REAIS do 1º turno de 2026. Código em `reformulacao-site`
  (PR #1 do fork). Site publicado no GitHub Pages: **https://rntjr.github.io/esteleicao/** (branch `gh-pages`, um único commit,
  substituída a cada publicação por `deploy/publicar_pages.ps1`; sem os `.gz`, com `.nojekyll`).
- Validação real (bate com a seção 3): 124.746.009 votos no log; 99,57% das seções com log = comparecimento; 3.722.310 votos
  após 17h (2,98%; o site mostra 3.722.495 por causa da harmonização de fuso); sem digital 12,2%.
- O que os arquivos reais mostraram (já ajustado no código):
  - transferência temporária: `odsele/perfil_eleitor_tte/transf_temporaria_secao_<ano>.zip`, uma linha por origem→destino, coluna `TP_TTE`;
    traz também linhas do 2º turno (filtra por NR_TURNO).
  - votação por seção: arquivos por UF trazem Governador, Senador e deputados; **Presidente vem só em `votacao_secao_2026_BR.zip`**
    (todas as UFs e exterior); `..._ZZ.zip` vem vazio. `baixar_votacao.UFS` usa BR no lugar de ZZ; o BR entra só na materialidade.
  - gastos: em 2026 o TSE publica as despesas **sem o município do fornecedor** (100% `#NULO`). A aba mostra só um aviso
    (decisão do usuário). Categorias: R$ 1,33 bi em transporte, combustível, locação de veículos e pessoal.
  - perfil do eleitorado: retrato de julho; bate com os aptos em ~20–45% das seções; 2.043.134 eleitores estão em seções agregadas (sem resultado próprio).
  - IBGE tabela 9514 confirmada (Censo 2022, 203.080.756 pessoas; 162,3 mi com 16+).
  - `referencia/municipios.csv` tinha o código TSE trocado em 7 municípios (Laje, Lajedão, Lajedinho, Lajedo do Tabocal, Lagoa Real/BA;
    Santiago do Sul, Santa Terezinha do Progresso/SC); corrigido. Outras diferenças de nome com o TSE são só grafia.
- Mudanças de apresentação pedidas pelo usuário: materialidade usa a diferença que DECIDIU a disputa (Senado: última vaga;
  1º turno de Governador/Presidente: folga sobre a metade dos válidos, o que faltou para a metade ou 2º × 3º, o que for menor);
  cadastro explica que eleitores > população 16+ é comum em cidade pequena (93% dos municípios < 5 mil eleitores; 14% dos > 100 mil).
- Desempenho real: `gerar_site.py` ~12 min e pico de ~6,2 GB de RAM; `web/dados` 306 MB sem .gz (11,7 mil arquivos, maior 4,4 MB).
  Navegador: 0 erros de console em 60 telas (desktop, celular, escuro), sem rolagem lateral no celular, telas em ≤ 1,4 s.
- Achados reais (rigor padrão; nenhum é prova): 21.898 seções em atenção, 604 com 2 critérios, 2 com os 3 (Taquarana/AL z45 s174:
  99 de 106 liberados pelo mesário, 27 seguidos, 31% após 17h; Nhamundá/AM z43 s47). Após 17h concentrado no NE (AL 9,3%, PE 7,5%,
  BA 7,5%; SP 0,4%). Disputas em que os votos das seções em atenção passam da diferença: Senado RN e PA (última vaga), Governo RN,
  AC (2º turno por 1.064 votos), PR (venceu no 1º turno por 6.012), DF e ES. Votos rápidos em sequência: nenhum (máx. 5 seguidos).
- Limites NOVOS da Etapa 2 (propostos, ajustáveis): `extras.CONC` (voto concentrado: z 5/4/3, fatia 50/40/30%, 50/40/30 votos),
  manual tardio (z ≥ 3,5, ≥ 5 casos, ≥ 2× o esperado), sequência rápida ≥ 10 votos com < 30 s, votos antes das 8h ≥ 3,
  comparecimento entre turnos (z robusto ≥ 4 e +10 p.p.).
- Publicação (decisão do usuário, 12/out/2026): o endereço oficial é **https://rntjr.github.io/esteleicao/** (GitHub Pages),
  sem domínio próprio e sem CNAME. O domínio `esteleicao.com`, o servidor Windows e o Caddy (seção 6) são de OUTRA pessoa,
  que disponibilizou o código original: não configurar domínio nem mexer no servidor; a seção 6 fica só como histórico.
- 12/out (tarde): **Parte 1 publicada**: tags de liberação pelo mesário (`extras.liberacoes`, `flags_lib`): "Mesário após 17h"
  (20/10/5), "Salto às 17h" e "Leitor com defeito provável", com filtro/coluna em Seções em atenção, bloco no Panorama, cartão
  hora a hora no detalhe e textos em Como ler e no quadro "Como comparamos" (topo de todas as telas). Tags NÃO contam como critério.
  Teste sintético: 31/31 (casos novos sorteados com `rng_lib` à parte, para não mudar os antigos).
- **Parte 2 pausada** a pedido do usuário: `eleitores_urna.py` (uma linha por eleitor) gerado na nuvem para 19 UFs; faltam
  SP, RJ, MG, MT, MS, DF, SE, BA. No Mac, rodar SEM `--apagar-brutos` (guardar `dados/logs_brutos_*` para não baixar de novo).
  `download_tse.baixar_so_logs` agora usa janela de pedidos (antes guardava tudo na memória e SP estourava ~11 GB).
- Análises e propostas pendentes (com fórmulas e números nacionais): **docs/analise-casos-atipicos.md**. Próximo passo combinado:
  "Casos extremamente atípicos" (tags Votos fora do log, Urna começou tarde, Terminou sozinha + lista + contexto de zona) e,
  depois, os itens da Parte 2 (liberação seletiva × leitor com defeito, sem digital com foto, sem digital > cadastro,
  tempo de cabine no lugar de "votos rápidos"). Sempre mostrar os números nacionais ao usuário ANTES de publicar.
- PRÓXIMO também: 2º turno em 25/10 (`baixar_dados.py --turno 2`, `baixar_logs.py --turno 2`, `gerar_site.py --turno 2`, `publicar_pages.ps1 -Turno 2`).
- Publicar no Mac: `publicar_pages.ps1` precisa do PowerShell (`brew install powershell`, depois `pwsh deploy/publicar_pages.ps1`).

## 8. Rotinas

- Atualizar o GitHub Pages: `.\deploy\publicar_pages.ps1` (ou `-SemGerar` para publicar o `web/` já gerado).
- Atualizar o site: no Mac `python gerar_site.py` e `python deploy/empacotar.py`; copiar o zip para `C:\git\`; `.\esteleicao\deploy\publicar_site.ps1` (como Administrador).
- 2º turno (25/10/2026): `python baixar_dados.py --turno 2`, `python baixar_logs.py --turno 2` e `python gerar_site.py --ano 2026 --turno 2` no Mac, quando o TSE publicar. O plano de fiscalização do 2º turno deve usar os dados do 1º.
- Testes sem internet: `python testar_sem_internet.py` (gera, processa todas as fontes e confere os casos plantados).

## 9. Preferências e cuidados

- No Mac (zsh), não coloque comentários `#` na mesma linha de comandos que o usuário vai colar (o zsh interativo não os trata como comentário: deu erro no `pip install`).
- No Mac use `python3`/`.venv`; o usuário usa Python 3.14 no Mac.
- O usuário faz os commits/push ele mesmo; não faça push sem pedir.
- Explique em linguagem simples; o usuário não é estatístico.
