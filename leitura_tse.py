"""
Leitura dos CSVs do TSE (separados por ";", texto latin-1) com detecção flexível
de colunas: cada campo tem uma lista de nomes possíveis e vale o primeiro que
existir no arquivo. Os nomes mudam de um ano para outro, então os scripts
baixar_*.py mostram o cabeçalho real quando falta alguma coluna obrigatória.
"""
from __future__ import annotations

import io
import unicodedata
import zipfile
from pathlib import Path
from typing import Iterator

import pandas as pd

ENCODING = "latin-1"


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")


def csvs(z: zipfile.ZipFile, contem: str | None = None, preferir_brasil: bool = True) -> list[str]:
    """CSVs do zip. Se houver um consolidado BRASIL, usa só ele (para não contar em dobro)."""
    nomes = [n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))]
    if contem:
        nomes = [n for n in nomes if contem.lower() in Path(n).name.lower()]
    if preferir_brasil:
        brasil = [n for n in nomes if "BRASIL" in n.upper()]
        if brasil:
            return brasil
    return sorted(nomes)


def cabecalho(z: zipfile.ZipFile, nome: str) -> list[str]:
    with z.open(nome) as f:
        return list(pd.read_csv(io.TextIOWrapper(f, encoding=ENCODING), sep=";", nrows=0).columns)


def mapear(cab: list[str], colunas: dict[str, list[str]]) -> dict[str, str]:
    """{nome no arquivo: nome usado aqui}, com o primeiro nome possível que existir."""
    mapa = {}
    for novo, opcoes in colunas.items():
        achou = next((c for c in opcoes if c in cab), None)
        if achou:
            mapa[achou] = novo
    return mapa


def conferir(cab: list[str], mapa: dict[str, str], obrigatorias: list[str], nome: str) -> bool:
    faltam = [c for c in obrigatorias if c not in mapa.values()]
    if faltam:
        print(f"  ! {nome}: não achei as colunas {faltam}.")
        print(f"    Colunas do arquivo: {', '.join(cab)}")
        print("    Ajuste a lista COLUNAS no script com o nome certo.")
        return False
    return True


def ler(z: zipfile.ZipFile, nome: str, colunas: dict[str, list[str]], obrigatorias: list[str],
        pedaco: int = 1_000_000) -> Iterator[pd.DataFrame]:
    """Lê um CSV do zip em pedaços, só com as colunas mapeadas, já renomeadas (tudo como texto)."""
    cab = cabecalho(z, nome)
    mapa = mapear(cab, colunas)
    if not conferir(cab, mapa, obrigatorias, nome):
        return
    with z.open(nome) as f:
        for d in pd.read_csv(io.TextIOWrapper(f, encoding=ENCODING), sep=";", dtype=str,
                             usecols=list(mapa), chunksize=pedaco):
            yield d.rename(columns=mapa)


def inteiro(s: pd.Series, tipo: str = "Int32") -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype(tipo)


def decimal_br(s: pd.Series) -> pd.Series:
    """'1.234,56' ou '1234,56' ou '1234.56' -> 1234.56"""
    t = s.astype(str).str.strip()
    br = t.str.contains(",", regex=False)
    t = t.where(~br, t.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(t, errors="coerce")
