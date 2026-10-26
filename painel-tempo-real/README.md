# Painel em tempo real — Presidente 2026 (2º turno)

Painéis web (HTML puro, sem servidor) que leem os arquivos públicos de
`resultados.tse.jus.br` **direto no navegador**, verificam a assinatura digital
**Ed25519 (JWS)** de cada arquivo e atualizam sozinhos durante a apuração.
Mais os scripts que baixam os **logs de urna** de todas as seções.

É um complemento ao painel Streamlit da raiz do repositório: aqui o foco é a
apuração ao vivo (mapa, placar, timeline) em páginas estáticas que abrem com dois
cliques, sem instalar nada.

## Os painéis (abra o `.html` no navegador)

| Arquivo | O que mostra |
|---|---|
| [`apuracao-presidente-2026.html`](apuracao-presidente-2026.html) | Placar nacional com fotos, mapa por estado, **timeline** dos percentuais (guardada no navegador) e tabela por UF. |
| [`apuracao-regioes.html`](apuracao-regioes.html) | Mapa por região: quem venceu, % de apuração e **abstenção**, com a média histórica (2º turno 2010–2022). |
| [`apuracao-municipios.html`](apuracao-municipios.html) | Mapa dos ~5.570 municípios com o candidato mais votado em cada um, com zoom e busca por estado. |

Características comuns:

- **Sem backend e sem build:** cada arquivo é uma página única, com a malha
  geográfica embutida. Basta abrir no navegador.
- **Dados ao vivo** do TSE, com a **assinatura Ed25519 de cada arquivo conferida
  no próprio navegador** (a chave pública vem embutida, igual à do app oficial).
- **Tema automático:** muda conforme quem lidera no Brasil.
- Funcionam em modo claro/escuro e no celular.

> A lista completa de endpoints e o formato dos arquivos do TSE estão
> documentados no painel Streamlit (raiz do repositório). Estes painéis usam os
> mesmos arquivos `…-u.json` (`.jws`) por abrangência.

## Scripts — logs de urna de todas as seções

Em [`scripts/`](scripts/), baixam o **log de cada urna** (`.jez`), de onde saem os
horários da **zerésima**, do primeiro/último voto e do boletim, gerando um CSV
com uma linha por seção.

### `baixar_logs_urnas.py` — pelo site de resultados (seção a seção)

```bash
python -I scripts/baixar_logs_urnas.py <pasta_destino> [ufs]
```

Modos de ritmo (o TSE limita requisições por IP):

| Flag | Comportamento |
|---|---|
| *(padrão)* | ritmo adaptativo: sobe devagar, recua ao receber 429. |
| `--moderado` | ritmo baixo e constante (~9/s), para tentar não disparar bloqueio. |
| `--rapido` | muitas threads, começa no máximo (mais rápido, bloqueia mais). |
| `--proxy` | roteia **tudo** por um proxy (ver `.env`). |
| `--hibrido` | usa a rota direta e **só desvia para o proxy enquanto o TSE estiver bloqueando** o IP, voltando sozinho quando liberar. |

Pode ser interrompido e rodado de novo: pula as seções já gravadas no CSV.

### `baixar_logs_pacote.py` — pelos pacotes de dados abertos (muito mais rápido)

Quando o TSE publica o dataset *"Arquivos transmitidos para totalização"*
(um `.zip` por UF, dias após a eleição), este script baixa e extrai só os logs,
sem limite de requisições — o Brasil todo em cerca de 1 hora.

```bash
python -I scripts/baixar_logs_pacote.py <pasta_destino> 2t
```

### Proxy (opcional, para `--proxy`/`--hibrido`)

O endereço e a credencial do proxy **não ficam no código**: vêm do `.env`.
Copie `.env.example` para `.env` e preencha. O `.env` está no `.gitignore` e
nunca deve ser versionado.

## Colunas do CSV de zerésimas

`uf; municipio; zona; secao; situacao; qtd_logs; arquivo; modelo_urna;
versao_app; urna_ligada; zeresima_gerada; zeresima_impressa;
qtd_zeresimas_no_dia; primeiro_voto; ultimo_voto; votos_computados; bu_gerado;
alertas`

Os horários vêm do relógio de cada urna (fuso local da seção).
