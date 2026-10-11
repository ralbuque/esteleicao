"""
Baixa o arquivo do TSE "Eleitorado por local de votação" e gera
dados/locais_<ano>.parquet com, para cada seção:

    nome do local (escola), endereço, bairro, CEP, latitude e longitude

É isso que permite mostrar no site ONDE fica cada seção sinalizada
(e montar a lista de escolas para os fiscais). Sem este arquivo o site
funciona, mas localiza as seções só pelo município.

Uso:
    python baixar_locais.py                  # 2026
    python baixar_locais.py --zip arquivo.zip

Fonte: https://dadosabertos.tse.jus.br/dataset/eleitorado-2026
       ("Eleitorado por local de votação - 2026")
"""
from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

import pandas as pd

from download_tse import baixar_completo

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/eleitorado_local_votacao_{ano}.zip"
PASTA = Path(__file__).parent / "dados"

# nome no arquivo do TSE -> nome usado aqui (o primeiro que existir)
COLUNAS = {
    "uf": ["SG_UF"],
    "cd_municipio": ["CD_MUNICIPIO"],
    "zona": ["NR_ZONA"],
    "secao": ["NR_SECAO"],
    "local": ["NR_LOCAL_VOTACAO"],
    "nome_local": ["NM_LOCAL_VOTACAO"],
    "tipo_local": ["DS_TIPO_LOCAL"],
    "endereco": ["DS_ENDERECO", "DS_LOCAL_VOTACAO_ENDERECO"],
    "bairro": ["NM_BAIRRO"],
    "cep": ["NR_CEP"],
    "lat": ["NR_LATITUDE"],
    "lon": ["NR_LONGITUDE"],
    "turno": ["NR_TURNO"],
}


def ler(caminho: Path, turno: int) -> pd.DataFrame:
    partes = []
    with zipfile.ZipFile(caminho) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
        brasil = [n for n in csvs if "BRASIL" in n.upper()]
        for nome in brasil or csvs:
            with z.open(nome) as f:
                cab = pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"), sep=";", nrows=0).columns
            mapa = {}
            for novo, opcoes in COLUNAS.items():
                achou = next((c for c in opcoes if c in cab), None)
                if achou:
                    mapa[achou] = novo
            with z.open(nome) as f:
                d = pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"), sep=";", dtype=str,
                                usecols=list(mapa))
            partes.append(d.rename(columns=mapa))
            print(f"  ok {nome}: {len(d):,} linhas")
    df = pd.concat(partes, ignore_index=True)
    if "turno" in df and (df["turno"] == str(turno)).any():
        df = df[df["turno"] == str(turno)]
    for c in ["cd_municipio", "zona", "secao", "local"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int32")
    for c in ["lat", "lon"]:
        if c in df:
            v = pd.to_numeric(df[c].str.replace(",", ".", regex=False), errors="coerce")
            # o TSE usa -1 (ou 0) quando não tem a coordenada
            df[c] = v.where((v.abs() > 0.01) & (v != -1)).astype("float32")
    for c in ["nome_local", "tipo_local", "endereco", "bairro"]:
        if c in df:
            df[c] = df[c].str.strip().str.replace(r"\s+", " ", regex=True)
    df = df.drop(columns=["turno"], errors="ignore")
    df = df.drop_duplicates(subset=["uf", "cd_municipio", "zona", "secao"])
    return df.reset_index(drop=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--zip", type=Path, help="Usar um zip já baixado")
    a = p.parse_args()
    PASTA.mkdir(exist_ok=True)
    caminho = a.zip or baixar_completo(URL.format(ano=a.ano), PASTA / f"eleitorado_local_votacao_{a.ano}.zip")
    df = ler(caminho, a.turno)
    saida = PASTA / f"locais_{a.ano}.parquet"
    df.to_parquet(saida, index=False)
    com = df["lat"].notna().mean() if "lat" in df else 0
    print(f"\n{len(df):,} seções em {df.groupby(['uf', 'cd_municipio', 'zona', 'local']).ngroups:,} locais "
          f"de votação | {com:.1%} com coordenadas | salvo em {saida.name}")


if __name__ == "__main__":
    main()
