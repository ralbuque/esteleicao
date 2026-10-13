"""
Baixa o arquivo do TSE "Votação por seção eleitoral" (um zip por UF) e gera
dados/votacao_<ano>_t<turno>_<UF>.parquet com os votos de cada candidato
(e brancos e nulos) em cada seção.

É a base de dois relatórios do site ("Mais análises"):
  - materialidade: os votos das seções em atenção comparados com a diferença
    entre o 1º e o 2º colocado (presidente, governador, senador);
  - voto concentrado: seções em que um candidato teve uma fatia de votos muito
    acima da que teve no resto do município (principalmente deputados).

Uso:
    python baixar_votacao.py --ufs AC          # testar com um estado pequeno
    python baixar_votacao.py                   # todos (27 UFs + exterior)
    python baixar_votacao.py --zip votacao_secao_2026_AC.zip

Os downloads retomam de onde pararam: se cair, rode de novo.
Fonte: https://dadosabertos.tse.jus.br/dataset/resultados-2026 ("Votação por seção eleitoral")
"""
from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

import pandas as pd

import leitura_tse as L
from download_tse import baixar_completo

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_{ano}_{uf}.zip"
PASTA = Path(__file__).parent / "dados"
# Em 2026 o Presidente (todas as UFs e o exterior) vem só no arquivo "BR"; o "ZZ" vem vazio.
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
       "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "BR"]

COLUNAS = {
    "turno": ["NR_TURNO"],
    "uf": ["SG_UF"],
    "cd_municipio": ["CD_MUNICIPIO"],
    "zona": ["NR_ZONA"],
    "secao": ["NR_SECAO"],
    "cargo": ["CD_CARGO"],
    "ds_cargo": ["DS_CARGO"],
    "votavel": ["NR_VOTAVEL"],
    "nome": ["NM_VOTAVEL"],
    "votos": ["QT_VOTOS"],
    "partido": ["SG_PARTIDO"],
}
OBRIGATORIAS = ["uf", "cd_municipio", "zona", "secao", "cargo", "votavel", "nome", "votos"]
BRANCO, NULO = 95, 96


def ler(caminho: Path, turno: int) -> pd.DataFrame:
    partes = []
    with zipfile.ZipFile(caminho) as z:
        for nome in L.csvs(z, preferir_brasil=False):
            n = 0
            for d in L.ler(z, nome, COLUNAS, OBRIGATORIAS):
                if "turno" in d:
                    d = d[d["turno"] == str(turno)]
                if d.empty:
                    continue
                out = pd.DataFrame({
                    "uf": d["uf"].str.strip(),
                    "cd_municipio": L.inteiro(d["cd_municipio"]),
                    "zona": L.inteiro(d["zona"], "Int16"),
                    "secao": L.inteiro(d["secao"], "Int16"),
                    "cargo": L.inteiro(d["cargo"], "Int8"),
                    "votavel": L.inteiro(d["votavel"]),
                    "votos": L.inteiro(d["votos"]),
                    "nome": d["nome"].str.strip(),
                })
                if "ds_cargo" in d:
                    out["ds_cargo"] = d["ds_cargo"].str.strip()
                if "partido" in d:
                    out["partido"] = d["partido"].str.strip()
                partes.append(out)
                n += len(out)
            print(f"  ok {nome}: {n:,} linhas")
    if not partes:
        return pd.DataFrame()
    df = pd.concat(partes, ignore_index=True)
    for c in ["uf", "nome", "ds_cargo", "partido"]:
        if c in df:
            df[c] = df[c].astype("category")
    # o mesmo votável pode vir em mais de uma linha (ex.: urnas de contingência): soma
    chave = ["uf", "cd_municipio", "zona", "secao", "cargo", "votavel"]
    extras = [c for c in ["nome", "ds_cargo", "partido"] if c in df]
    nomes = df.drop_duplicates(chave)[chave + extras]
    df = df.groupby(chave, observed=True, as_index=False)["votos"].sum()
    return df.merge(nomes, on=chave, how="left")


def conferir(df: pd.DataFrame, ano: int, turno: int, uf: str):
    """Conferência: soma dos votos por cargo vs comparecimento oficial da seção."""
    print("  votos por cargo:")
    tot = df.groupby("cargo", observed=True)["votos"].sum()
    nomes = df.drop_duplicates("cargo").set_index("cargo")["ds_cargo"] if "ds_cargo" in df else {}
    for c, v in tot.items():
        bn = df[(df["cargo"] == c) & df["votavel"].isin([BRANCO, NULO])]["votos"].sum()
        print(f"    {c:>2} {str(nomes.get(c, '')):<22} {v:>12,} votos ({bn:,} brancos e nulos)")
    sec_arq = PASTA / f"secoes_{ano}_t{turno}.parquet"
    if not sec_arq.exists():
        return
    sec = pd.read_parquet(sec_arq, columns=["uf", "cd_municipio", "zona", "secao", "comparecimento"])
    sec = sec[sec["uf"].astype(str) == uf]
    if sec.empty:
        return
    for c in tot.index:
        v = df[df["cargo"] == c].groupby(["cd_municipio", "zona", "secao"], observed=True)["votos"].sum()
        s = sec.set_index(["cd_municipio", "zona", "secao"])["comparecimento"]
        j = pd.concat([v.rename("votos"), s], axis=1, join="inner")
        if j.empty:
            continue
        razao = j["votos"].sum() / max(j["comparecimento"].sum(), 1)
        k = round(razao)  # senador em 2026: 2 votos por eleitor
        bate = (j["votos"] == k * j["comparecimento"]).mean() if k else float("nan")
        print(f"    cargo {c}: votos ÷ comparecimento = {razao:.3f}; seções que batem exatamente "
              f"({k} voto(s) por eleitor): {bate:.1%}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--ufs", nargs="+", default=UFS, type=str.upper)
    p.add_argument("--zip", type=Path, nargs="+", help="Usar zips já baixados (a UF é lida do nome)")
    p.add_argument("--refazer", action="store_true", help="Reprocessar UFs já processadas")
    a = p.parse_args()
    PASTA.mkdir(exist_ok=True)
    if a.zip:
        tarefas = []
        for z in a.zip:
            m = re.search(r"_(\d{4})_([A-Z]{2})\.zip$", z.name, re.I)
            tarefas.append((m.group(2).upper() if m else input(f"UF de {z.name}: ").strip().upper(), z))
    else:
        tarefas = [(uf, None) for uf in a.ufs]
    for uf, zip_local in tarefas:
        saida = PASTA / f"votacao_{a.ano}_t{a.turno}_{uf}.parquet"
        if saida.exists() and not a.refazer:
            print(f"{uf}: já processado ({saida.name}); use --refazer para refazer")
            continue
        print(f"\n=== {uf} ===")
        try:
            caminho = zip_local or baixar_completo(URL.format(ano=a.ano, uf=uf),
                                                   PASTA / f"votacao_secao_{a.ano}_{uf}.zip")
        except Exception as e:
            print(f"  ! falha no download: {e}\n    Rode o mesmo comando de novo: ele continua de onde parou.")
            continue
        df = ler(caminho, a.turno)
        if df.empty:
            print(f"  ! nenhuma linha do {a.turno}º turno")
            continue
        df.to_parquet(saida, index=False)
        conferir(df, a.ano, a.turno, uf)
        print(f"  {len(df):,} linhas salvas em {saida.name}")
    print("\nPronto. Rode:  python gerar_site.py")


if __name__ == "__main__":
    main()
