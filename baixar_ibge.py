"""
Baixa do IBGE (API do SIDRA) a população do Censo 2022 por idade e gera
dados/populacao_2022.parquet com, por município:

    cd_ibge, pop_total, pop_16_mais (16 anos ou mais = quem pode ter título)

O site compara com o eleitorado (eleitores ÷ população com 16+). Acima de 1
indica cadastro com eleitores que não moram no município (ou que já morreram e
não foram baixados), o que vale conferir.

Uso:
    python baixar_ibge.py                    # tabela 9514 do SIDRA (Censo 2022)
    python baixar_ibge.py --tabela 9514
    python baixar_ibge.py --arquivo pop.json # resposta do SIDRA salva antes (JSON ou zip de JSONs)
    python baixar_ibge.py --arquivo pop.csv  # CSV com colunas cd_ibge;pop_total;pop_16_mais

Antes de baixar, o script lê a descrição da tabela (metadados) e mostra o
nome e as categorias de idade usadas, para conferir que é a tabela certa.
Fonte: https://sidra.ibge.gov.br/tabela/9514
"""
from __future__ import annotations

import argparse
import io
import json
import re
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

from download_tse import CABECALHO, TIMEOUT

PASTA = Path(__file__).parent / "dados"
METADADOS = "https://servicodados.ibge.gov.br/api/v3/agregados/{t}/metadados"
VALORES = "https://apisidra.ibge.gov.br/values/t/{t}/n6/in%20n3%20{uf}/v/{v}/p/{p}/{cls}"
UF_IBGE = [11, 12, 13, 14, 15, 16, 17, 21, 22, 23, 24, 25, 26, 27, 28, 29, 31, 32, 33, 35, 41, 42, 43,
           50, 51, 52, 53]


def pegar(url: str, tentativas: int = 8):
    for t in range(tentativas):
        try:
            r = requests.get(url, headers=CABECALHO, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                raise SystemExit(f"O IBGE recusou a consulta ({r.status_code}): {url}\n{r.text[:300]}")
        except (requests.RequestException, ValueError):
            pass
        time.sleep(min(2 ** t, 30))
    raise SystemExit(f"Não consegui acessar {url}")


def idade_categoria(nome: str) -> tuple[int, int] | None:
    """'Menos de 1 ano' -> (0,0); '15 anos' -> (15,15); '15 a 19 anos' -> (15,19); '100 anos ou mais' -> (100,999)."""
    s = nome.lower()
    if "menos de 1" in s:
        return (0, 0)
    m = re.match(r"^(\d+) a (\d+) anos?$", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d+) anos? ou mais$", s)
    if m:
        return int(m.group(1)), 999
    m = re.match(r"^(\d+) anos?$", s)
    if m:
        return int(m.group(1)), int(m.group(1))
    return None


def planejar(tabela: int) -> tuple[str, str, str, list[str], str]:
    """Lê os metadados e escolhe: variável de população, período, filtro das classificações,
    categorias de idade 0..15 (uma a uma) e a categoria Total de idade."""
    meta = pegar(METADADOS.format(t=tabela))
    print(f"Tabela {tabela}: {meta.get('nome')}")
    var = next((v for v in meta["variaveis"] if "popula" in v["nome"].lower()), meta["variaveis"][0])
    periodo = "2022" if "2022" in json.dumps(meta.get("periodicidade", {})) else "last"
    print(f"  variável {var['id']}: {var['nome']}")
    cls_idade, filtros, menores, total_idade = None, [], [], None
    for c in meta["classificacoes"]:
        cats = c["categorias"]
        total = next((k for k in cats if k["nome"].strip().lower() == "total"), None)
        if "idade" in c["nome"].lower() and "forma" not in c["nome"].lower():
            cls_idade = c
            total_idade = total
            simples = {}
            for k in cats:
                faixa = idade_categoria(k["nome"].strip())
                if faixa and faixa[0] == faixa[1] and faixa[0] <= 15:
                    simples[faixa[0]] = str(k["id"])
            if set(simples) != set(range(16)):
                # sem idade simples: tenta faixas que cubram exatamente 0..15
                faixas = [(idade_categoria(k["nome"].strip()), str(k["id"])) for k in cats]
                faixas = sorted((f, i) for f, i in faixas if f and f[1] <= 15)
                cob, ini = [], 0
                for (a, b), i in faixas:
                    if a == ini:
                        cob.append(i)
                        ini = b + 1
                if ini != 16:
                    raise SystemExit("Não achei categorias de idade que cubram 0 a 15 anos nesta tabela.")
                menores = cob
            else:
                menores = [simples[i] for i in range(16)]
        elif total:
            filtros.append(f"c{c['id']}/{total['id']}")
    if not cls_idade or not total_idade:
        raise SystemExit("A tabela não tem a classificação 'Idade' com categoria 'Total'. Confira o número da tabela.")
    print(f"  idade: classificação {cls_idade['id']} ({cls_idade['nome']}), {len(menores)} categorias de 0 a 15 anos")
    cls = "/".join(filtros + [f"c{cls_idade['id']}/{','.join([str(total_idade['id'])] + menores)}"])
    return str(var["id"]), periodo, cls, menores, str(total_idade["id"])


def montar(linhas: list[dict], menores: list[str], total_id: str) -> pd.DataFrame:
    """Respostas do SIDRA (lista de dicionários, a 1ª linha é o cabeçalho) -> população por município."""
    cab = linhas[0]
    col_idade = next(k for k, v in cab.items() if k.startswith("D") and k.endswith("C") and "idade" in str(v).lower()
                     and "forma" not in str(v).lower())
    col_mun = next(k for k, v in cab.items() if k.startswith("D") and k.endswith("C") and "munic" in str(v).lower())
    d = pd.DataFrame(linhas[1:])
    d["valor"] = pd.to_numeric(d["V"], errors="coerce").fillna(0)
    total = d[d[col_idade] == total_id].groupby(col_mun)["valor"].sum()
    menor = d[d[col_idade].isin(menores)].groupby(col_mun)["valor"].sum()
    out = pd.DataFrame({"pop_total": total, "pop_0_15": menor}).fillna(0)
    out["pop_16_mais"] = out["pop_total"] - out["pop_0_15"]
    out.index.name = "cd_ibge"
    return out.reset_index().astype({"cd_ibge": str, "pop_total": "int64", "pop_0_15": "int64", "pop_16_mais": "int64"})


def ler_arquivo(caminho: Path) -> pd.DataFrame:
    if caminho.suffix.lower() == ".csv":
        d = pd.read_csv(caminho, sep=None, engine="python", dtype={"cd_ibge": str})
        return d[["cd_ibge", "pop_total", "pop_16_mais"]]
    blocos = []
    if caminho.suffix.lower() == ".zip":
        with zipfile.ZipFile(caminho) as z:
            meta = json.loads(z.read("metadados.json")) if "metadados.json" in z.namelist() else None
            for n in z.namelist():
                if n.endswith(".json") and n != "metadados.json":
                    blocos.append(json.loads(z.read(n)))
    else:
        meta, blocos = None, [json.loads(caminho.read_text(encoding="utf-8"))]
    menores = (meta or {}).get("menores") or [str(i) for i in range(16)]
    total_id = (meta or {}).get("total") or "total"
    linhas = [blocos[0][0]] + [l for b in blocos for l in b[1:]]
    return montar(linhas, menores, total_id)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tabela", type=int, default=9514)
    p.add_argument("--arquivo", "--zip", type=Path, dest="arquivo",
                   help="Usar dados já baixados (JSON do SIDRA, zip de JSONs ou CSV)")
    a = p.parse_args()
    PASTA.mkdir(exist_ok=True)
    if a.arquivo:
        df = ler_arquivo(a.arquivo)
    else:
        var, periodo, cls, menores, total_id = planejar(a.tabela)
        linhas = []
        for uf in UF_IBGE:
            r = pegar(VALORES.format(t=a.tabela, uf=uf, v=var, p=periodo, cls=cls))
            linhas += r if not linhas else r[1:]
            print(f"\r  UF {uf}: {len(linhas) - 1:,} valores", end="", flush=True)
        print()
        df = montar(linhas, menores, total_id)
    saida = PASTA / "populacao_2022.parquet"
    df.to_parquet(saida, index=False)
    print(f"{len(df):,} municípios | população {df['pop_total'].sum():,} | com 16 anos ou mais "
          f"{df['pop_16_mais'].sum():,} | salvo em {saida.name}")
    print("Para o crescimento do eleitorado, baixe também a eleição anterior:  python baixar_dados.py --ano 2022")


if __name__ == "__main__":
    main()
