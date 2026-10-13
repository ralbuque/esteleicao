"""
Baixa o arquivo oficial do TSE "Detalhe da apuração por seção eleitoral"
e gera um arquivo compacto (Parquet) com aptos, comparecimento e abstenção
por seção eleitoral.

Uso:
    python baixar_dados.py                 # 2026, 1º turno
    python baixar_dados.py --turno 2       # 2º turno (quando publicado)
    python baixar_dados.py --ano 2022      # outra eleição, para comparar
    python baixar_dados.py --zip caminho/detalhe_votacao_secao_2026.zip   # se já baixou o zip

Fonte: https://dadosabertos.tse.jus.br/dataset/resultados-2026
"""
import argparse
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_secao/detalhe_votacao_secao_{ano}.zip"
PASTA = Path(__file__).parent / "dados"

# Colunas que usamos. As marcadas como opcionais podem não existir em todos os anos.
OBRIGATORIAS = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                "CD_CARGO", "DS_CARGO", "QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES"]
OPCIONAIS = ["NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "DS_LOCAL_VOTACAO_ENDERECO",
             "ST_VOTO_EM_TRANSITO", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS"]


def baixar(ano: int) -> Path:
    PASTA.mkdir(exist_ok=True)
    destino = PASTA / f"detalhe_votacao_secao_{ano}.zip"
    if destino.exists() and destino.stat().st_size > 0:
        print(f"Zip já existe: {destino} (apague para baixar de novo)")
        return destino
    url = URL.format(ano=ano)
    print(f"Baixando {url}")
    tmp = destino.with_suffix(".part")
    with requests.get(url, stream=True, timeout=60,
                      headers={"User-Agent": "Mozilla/5.0 (analise-abstencao)"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        feito = 0
        with open(tmp, "wb") as f:
            for bloco in r.iter_content(chunk_size=1 << 20):
                f.write(bloco)
                feito += len(bloco)
                if total:
                    print(f"\r  {feito / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="", flush=True)
    print()
    tmp.rename(destino)
    return destino


def ler_zip(caminho_zip: Path, turno: int, cargo: int) -> pd.DataFrame:
    with zipfile.ZipFile(caminho_zip) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
        # O zip costuma trazer um CSV por UF e às vezes um consolidado "BRASIL".
        # Usamos só o consolidado se existir, para não contar seções em dobro.
        brasil = [n for n in csvs if "BRASIL" in n.upper()]
        alvos = brasil if brasil else csvs
        print(f"Lendo {len(alvos)} arquivo(s) CSV do zip")
        partes = []
        for nome in sorted(alvos):
            with z.open(nome) as bruto:
                cabecalho = pd.read_csv(io.TextIOWrapper(bruto, encoding="latin-1"),
                                        sep=";", nrows=0).columns
            faltando = [c for c in OBRIGATORIAS if c not in cabecalho]
            if faltando:
                print(f"  ! {nome}: colunas ausentes {faltando} — pulando")
                continue
            usar = OBRIGATORIAS + [c for c in OPCIONAIS if c in cabecalho]
            with z.open(nome) as bruto:
                for pedaco in pd.read_csv(io.TextIOWrapper(bruto, encoding="latin-1"), sep=";",
                                          usecols=usar, dtype=str, chunksize=500_000):
                    pedaco = pedaco[(pedaco["NR_TURNO"] == str(turno)) &
                                    (pedaco["CD_CARGO"] == str(cargo))]
                    if len(pedaco):
                        partes.append(pedaco)
            print(f"  ok {nome}")
    if not partes:
        sys.exit(f"Nenhuma linha encontrada para turno={turno}, cargo={cargo}. "
                 "O turno já foi publicado pelo TSE?")
    return pd.concat(partes, ignore_index=True)


def limpar(df: pd.DataFrame) -> pd.DataFrame:
    for c in ["QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype("int32")
    for c in ["NR_ZONA", "NR_SECAO", "CD_MUNICIPIO", "NR_LOCAL_VOTACAO"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int32")
    df = df.rename(columns={
        "SG_UF": "uf", "CD_MUNICIPIO": "cd_municipio", "NM_MUNICIPIO": "municipio",
        "NR_ZONA": "zona", "NR_SECAO": "secao", "QT_APTOS": "aptos",
        "QT_COMPARECIMENTO": "comparecimento", "QT_ABSTENCOES": "abstencoes",
        "NR_LOCAL_VOTACAO": "local", "NM_LOCAL_VOTACAO": "nome_local",
        "DS_LOCAL_VOTACAO_ENDERECO": "endereco_local", "ST_VOTO_EM_TRANSITO": "transito",
        "QT_VOTOS_BRANCOS": "brancos", "QT_VOTOS_NULOS": "nulos",
    }).drop(columns=["NR_TURNO", "CD_CARGO", "DS_CARGO"])
    chave = ["uf", "cd_municipio", "zona", "secao"]
    antes = len(df)
    df = df.drop_duplicates(subset=chave)
    if len(df) < antes:
        print(f"  {antes - len(df)} linhas duplicadas removidas")
    df = df[df["aptos"] > 0].copy()
    # conferência básica de consistência
    inconsist = (df["comparecimento"] + df["abstencoes"] != df["aptos"]).sum()
    if inconsist:
        print(f"  Aviso: {inconsist} seções com comparecimento + abstenção != aptos")
    df["taxa_abstencao"] = df["abstencoes"] / df["aptos"]
    return df.reset_index(drop=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--cargo", type=int, default=1,
                   help="1 = Presidente (padrão). Os aptos/abstenção da seção são os mesmos em todos os cargos.")
    p.add_argument("--zip", type=Path, help="Usar um zip já baixado em vez de baixar")
    a = p.parse_args()

    caminho = a.zip or baixar(a.ano)
    df = limpar(ler_zip(caminho, a.turno, a.cargo))
    saida = PASTA / f"secoes_{a.ano}_t{a.turno}.parquet"
    PASTA.mkdir(exist_ok=True)
    df.to_parquet(saida, index=False)
    total = df["aptos"].sum()
    print(f"\n{len(df):,} seções | {total:,} aptos | abstenção agregada "
          f"{df['abstencoes'].sum() / total:.2%}")
    print(f"Salvo em {saida}")
    print("Agora rode:  python gerar_site.py --servir")


if __name__ == "__main__":
    main()
