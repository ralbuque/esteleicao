"""Comparação histórica entre eleições, sem alterar os cálculos existentes.

O pareamento principal é conservador: mesma UF, município, zona e seção.
Isso evita afirmar que uma seção de um ano é a mesma quando a Justiça Eleitoral
alterou a divisão ou a numeração. Linhas sem par correspondente permanecem no
resultado para que o painel mostre seções criadas ou ausentes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


CHAVE_SECAO = ["uf", "cd_municipio", "zona", "secao"]
COLUNAS_COMPARACAO = [
    "aptos", "comparecimento", "abstencoes", "taxa_abstencao", "z_ajustado",
    "pct_apos_17", "z_horario", "pct_sem_digital", "z_sem_digital",
    "pct_manual_cadastrados", "z_manual", "n_criterios", "criterios_cumpridos",
    "alerta", "tem_log", "f_abst", "f_17", "f_man",
]
FLAGS = {
    "abst": "f_abst",
    "tarde": "f_17",
    "manual": "f_man",
}


def nome_eleicao(caminho: str | Path) -> str:
    """Extrai o rótulo exibido pelo painel a partir de secoes_<ano>_t<turno>."""
    return Path(caminho).stem.replace("secoes_", "")


def filtrar_contexto(df: pd.DataFrame, uf: str, municipio, zona, secao,
                     todos: str = "— Todos —") -> pd.DataFrame:
    """Aplica no outro ano os mesmos filtros geográficos da eleição atual."""
    out = df
    if uf != todos:
        out = out[out["uf"].astype(str) == str(uf)]
    if municipio != todos:
        out = out[out["cd_municipio"] == municipio]
    if zona != todos:
        out = out[out["zona"] == zona]
    if secao != todos:
        out = out[out["secao"] == secao]
    return out


def _colunas_existentes(df: pd.DataFrame, prefixo: str = "") -> list[str]:
    return [f"{prefixo}{c}" for c in COLUNAS_COMPARACAO if f"{prefixo}{c}" in df]


def _deduplicar(df: pd.DataFrame) -> pd.DataFrame:
    """Evita multiplicar linhas se uma fonte histórica tiver chaves repetidas."""
    presentes = [c for c in CHAVE_SECAO if c in df]
    if len(presentes) != len(CHAVE_SECAO):
        raise ValueError("A base não possui todas as colunas da chave de seção")
    return df.drop_duplicates(presentes, keep="first")


def comparar_secoes(anterior: pd.DataFrame, atual: pd.DataFrame,
                    rotulos: tuple[str, str] = ("anterior", "atual")) -> pd.DataFrame:
    """Compara duas bases por seção e calcula variações e persistência.

    O resultado usa *outer join*: seções que só existem em um dos anos não são
    descartadas. Para análises de persistência, filtre ``pareamento == 'ambas'``.
    """
    ant, atu = _deduplicar(anterior), _deduplicar(atual)
    a, b = rotulos
    cols_a = CHAVE_SECAO + _colunas_existentes(ant)
    cols_b = CHAVE_SECAO + _colunas_existentes(atu)
    ant = ant[cols_a].rename(columns={c: f"{c}_{a}" for c in cols_a if c not in CHAVE_SECAO})
    atu = atu[cols_b].rename(columns={c: f"{c}_{b}" for c in cols_b if c not in CHAVE_SECAO})

    out = ant.merge(atu, on=CHAVE_SECAO, how="outer", indicator=True)
    out["pareamento"] = out["_merge"].map({
        "both": "ambas", "left_only": f"somente {a}", "right_only": f"somente {b}"
    })
    out = out.drop(columns="_merge")

    for coluna in ["aptos", "comparecimento", "abstencoes", "taxa_abstencao", "z_ajustado",
                   "pct_apos_17", "z_horario", "pct_sem_digital", "z_sem_digital",
                   "pct_manual_cadastrados", "z_manual", "n_criterios"]:
        ca, cb = f"{coluna}_{a}", f"{coluna}_{b}"
        if ca in out and cb in out:
            out[f"delta_{coluna}"] = out[cb] - out[ca]

    for nome, coluna in FLAGS.items():
        ca, cb = f"{coluna}_{a}", f"{coluna}_{b}"
        if ca in out and cb in out:
            out[f"persistente_{nome}"] = out[ca].fillna(False).astype(bool) & out[cb].fillna(False).astype(bool)

    if all(f"{c}_{a}" in out and f"{c}_{b}" in out for c in FLAGS.values()):
        pareada = out["pareamento"].eq("ambas")
        ant_alerta = out[[f"{c}_{a}" for c in FLAGS.values()]].fillna(False).any(axis=1)
        atu_alerta = out[[f"{c}_{b}" for c in FLAGS.values()]].fillna(False).any(axis=1)
        out["situacao"] = np.select(
            [pareada & ant_alerta & atu_alerta,
             pareada & ~ant_alerta & atu_alerta,
             pareada & ant_alerta & ~atu_alerta],
            ["persistente", "nova em " + b, "resolvida em " + b],
            default=np.where(pareada, "normal nos dois anos", out["pareamento"]),
        )
    else:
        out["situacao"] = np.where(out["pareamento"] == "ambas", "sem critérios comparáveis", out["pareamento"])

    return out.sort_values(CHAVE_SECAO).reset_index(drop=True)


def resumo_comparacao(df: pd.DataFrame, rotulos: tuple[str, str] = ("anterior", "atual")) -> pd.DataFrame:
    """Resumo de cobertura e persistência para o cabeçalho da aba histórica."""
    a, b = rotulos
    total = len(df)
    ambas = int((df["pareamento"] == "ambas").sum())
    resumo = {
        "linhas": total,
        "pareadas": ambas,
        f"somente_{a}": int((df["pareamento"] == f"somente {a}").sum()),
        f"somente_{b}": int((df["pareamento"] == f"somente {b}").sum()),
    }
    if "situacao" in df:
        cont = df.loc[df["pareamento"] == "ambas", "situacao"].value_counts()
        resumo.update({f"situacao_{k}": int(v) for k, v in cont.items()})
    return pd.DataFrame([resumo])
