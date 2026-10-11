"""
Baixa a votação por seção do TSE (votos de cada candidato a presidente) e gera
dados/votos_<ano>_t<turno>.parquet com, por seção:

  votos_total       votos computados (candidatos + brancos + nulos)
  pct_lula          % dos votos para o nº 13
  pct_bolsonaro     % dos votos para o nº 22
  pct_outros        % para os demais candidatos + brancos + nulos

O painel junta esse arquivo automaticamente quando ele existe.

    python baixar_votos.py
    python baixar_votos.py --turno 2
    python baixar_votos.py --zip caminho/votacao_secao_2026_BR.zip

Fonte: https://dadosabertos.tse.jus.br/dataset/resultados-2026
"""
import argparse
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd

from baixar_dados import PASTA  # noqa: E402  (mesma pasta de dados)

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_{ano}_BR.zip"
CANDIDATOS = {13: "lula", 22: "bolsonaro"}
COLUNAS = ["NR_TURNO", "CD_CARGO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
           "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS"]


def baixar(ano: int) -> Path:
    import requests
    PASTA.mkdir(exist_ok=True)
    destino = PASTA / f"votacao_secao_{ano}_BR.zip"
    if destino.exists() and destino.stat().st_size > 1_000_000:
        print(f"Usando arquivo já baixado: {destino}")
        return destino
    url = URL.format(ano=ano)
    print(f"Baixando {url}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        feito = 0
        with open(destino, "wb") as f:
            for parte in r.iter_content(chunk_size=1 << 20):
                f.write(parte)
                feito += len(parte)
                if total:
                    print(f"\r  {feito / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="")
    print()
    return destino


def ler_zip(caminho_zip: Path, turno: int, cargo: int) -> pd.DataFrame:
    partes, nomes = [], {}
    with zipfile.ZipFile(caminho_zip) as z:
        csvs = sorted(n for n in z.namelist() if n.lower().endswith(".csv"))
        for nome in csvs:
            with z.open(nome) as bruto:
                for pedaco in pd.read_csv(io.TextIOWrapper(bruto, encoding="latin-1"), sep=";",
                                          usecols=COLUNAS, dtype=str, chunksize=500_000):
                    pedaco = pedaco[(pedaco["NR_TURNO"] == str(turno)) &
                                    (pedaco["CD_CARGO"] == str(cargo))]
                    if pedaco.empty:
                        continue
                    nomes.update(pedaco.drop_duplicates("NR_VOTAVEL")
                                 .set_index("NR_VOTAVEL")["NM_VOTAVEL"].to_dict())
                    pedaco = pedaco.assign(
                        NR_VOTAVEL=pd.to_numeric(pedaco["NR_VOTAVEL"], errors="coerce"),
                        QT_VOTOS=pd.to_numeric(pedaco["QT_VOTOS"], errors="coerce").fillna(0))
                    pedaco["quem"] = pedaco["NR_VOTAVEL"].map(CANDIDATOS).fillna("outros")
                    partes.append(pedaco.groupby(["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "quem"],
                                                 observed=True)["QT_VOTOS"].sum().reset_index())
            print(f"  ok {nome}")
    if not partes:
        sys.exit(f"Nenhuma linha encontrada para turno={turno}, cargo={cargo}.")
    print("Candidatos no arquivo:")
    for nr, nm in sorted(nomes.items(), key=lambda kv: int(kv[0])):
        marca = CANDIDATOS.get(int(nr), "outros")
        print(f"  {nr:>3}  {nm:<40} -> {marca}")
    return pd.concat(partes, ignore_index=True)


def montar(df: pd.DataFrame) -> pd.DataFrame:
    chave = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]
    tab = (df.groupby(chave + ["quem"], observed=True)["QT_VOTOS"].sum()
             .unstack("quem", fill_value=0).reset_index())
    for q in [*CANDIDATOS.values(), "outros"]:
        if q not in tab:
            tab[q] = 0
    tab = tab.rename(columns={"SG_UF": "uf", "CD_MUNICIPIO": "cd_municipio",
                              "NR_ZONA": "zona", "NR_SECAO": "secao"})
    for c in ["cd_municipio", "zona", "secao"]:
        tab[c] = pd.to_numeric(tab[c], errors="coerce").astype("Int32")
    tab["votos_total"] = (tab[list(CANDIDATOS.values())].sum(axis=1) + tab["outros"]).astype("int32")
    for q in [*CANDIDATOS.values(), "outros"]:
        tab[f"pct_{q}"] = (tab[q] / tab["votos_total"].where(tab["votos_total"] > 0)).astype("float32")
    saida = tab[["uf", "cd_municipio", "zona", "secao", "votos_total",
                 *[f"pct_{q}" for q in [*CANDIDATOS.values(), "outros"]]]]
    return saida.reset_index(drop=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--cargo", type=int, default=1, help="1 = presidente (padrão)")
    p.add_argument("--zip", type=Path, help="Usar um zip já baixado em vez de baixar")
    a = p.parse_args()

    caminho = a.zip or baixar(a.ano)
    df = montar(ler_zip(caminho, a.turno, a.cargo))
    saida = PASTA / f"votos_{a.ano}_t{a.turno}.parquet"
    df.to_parquet(saida, index=False)
    tot = df["votos_total"].sum()
    print(f"\n{len(df):,} seções | {tot:,} votos | "
          + " | ".join(f"{q} {(df[f'pct_{q}'] * df['votos_total']).sum() / tot:.1%}"
                       for q in [*CANDIDATOS.values(), "outros"]))
    print(f"Salvo em {saida}\nAgora rode:  streamlit run painel.py")


if __name__ == "__main__":
    main()
