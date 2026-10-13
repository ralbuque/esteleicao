"""
Dados da aba "Simule o 2º turno": para cada disputa que foi ao 2º turno (presidente e
governadores), os votos do 1º turno de cada candidato, brancos, nulos e abstenção, e a
referência histórica usada no cenário de presidente.

NÃO é previsão: o site só soma os votos do 1º turno e deixa a pessoa escolher como os
votos em jogo se dividem. Nada aqui entra nos critérios nem nas tags.

    python simulador.py            # grava web/dados/turno2.json (sem refazer o site inteiro)
    python simulador.py --baixar   # antes, baixa o cadastro de candidatos (nomes de urna)

`gerar_site.py` chama `gerar()` e grava o mesmo arquivo.

Entradas (em dados/): secoes_<ano>_t1.parquet, votacao_<ano>_t1_<UF>.parquet (governador) e
votacao_<ano>_t1_BR.parquet (presidente). Opcional: consulta_cand_<ano>.zip (nome de urna e partido).
"""
from __future__ import annotations

import argparse
import io
import re
import zipfile
from pathlib import Path

import pandas as pd

PASTA = Path(__file__).parent / "dados"
URL_CAND = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{ano}.zip"
BRANCO, NULO = 95, 96
PRESIDENTE, GOVERNADOR = 1, 3

# Presidente, 1º e 2º turno. Totais conferidos em 12/out/2026 com o arquivo oficial do TSE
# "detalhe_votacao_munzona_<ano>.zip" (linha BRASIL, cargo Presidente). "dois" = fatia dos votos
# válidos do 1º turno que os dois finalistas somaram (resultado oficial divulgado pelo TSE).
HISTORICO = [
    dict(ano=2010, aptos=135_804_433, abst=(24_610_296, 29_197_152), brancos=(3_479_340, 2_452_597),
         nulos=(6_124_254, 4_689_428), validos=(101_590_153, 99_463_917), dois=(0.4691, 0.3261)),
    dict(ano=2014, aptos=142_822_046, abst=(27_698_475, 30_137_479), brancos=(4_420_489, 1_921_819),
         nulos=(6_678_592, 5_219_787), validos=(104_023_802, 105_542_273), dois=(0.4159, 0.3355)),
    dict(ano=2018, aptos=147_306_295, abst=(29_941_171, 31_372_373), brancos=(3_106_937, 2_486_593),
         nulos=(7_206_222, 8_608_105), validos=(107_050_749, 104_838_753), dois=(0.4603, 0.2928)),
    dict(ano=2022, aptos=156_454_011, abst=(32_770_982, 32_200_558), brancos=(1_964_779, 1_769_678),
         nulos=(3_487_874, 3_930_765), validos=(118_229_719, 118_552_353), dois=(0.4843, 0.4320)),
]
ANO_REFERENCIA = 2022   # a eleição mais parecida com a atual (ver o texto da aba)


def titulo(s: str) -> str:
    """'DR. FURLAN' -> 'Dr. Furlan'; siglas sem vogal ficam em maiúsculas ('JHC')."""
    minus = {"de", "da", "do", "das", "dos", "e"}
    out = []
    for i, p in enumerate(re.split(r"(\s+)", str(s).strip())):
        b = p.lower()
        if not b.strip():
            out.append(p)
        elif i > 0 and b in minus:
            out.append(b)
        elif len(b) <= 4 and not re.search(r"[aeiouáéíóúâêôãõ]", b):
            out.append(p.upper())
        else:
            out.append(re.sub(r"(^|[.\-'])(\w)", lambda m: m.group(1) + m.group(2).upper(), b))
    return "".join(out)


def nomes_de_urna(pasta: Path, ano: int) -> dict:
    """(UF ou 'BR', cargo, número) -> (nome de urna, partido), do cadastro de candidatos do TSE."""
    caminho = pasta / f"consulta_cand_{ano}.zip"
    if not caminho.exists():
        return {}
    out = {}
    with zipfile.ZipFile(caminho) as z:
        membros = [m for m in z.namelist() if m.lower().endswith(".csv")]
        brasil = [m for m in membros if "BRASIL" in m.upper()]
        for m in brasil or membros:
            d = pd.read_csv(io.BytesIO(z.read(m)), sep=";", encoding="latin-1", dtype=str,
                            usecols=["SG_UF", "CD_CARGO", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO"])
            d = d[d["CD_CARGO"].isin([str(PRESIDENTE), str(GOVERNADOR)])]
            for r in d.itertuples(index=False):
                out[(r.SG_UF, int(r.CD_CARGO), int(r.NR_CANDIDATO))] = (titulo(r.NM_URNA_CANDIDATO), r.SG_PARTIDO)
    return out


def _disputa(v: pd.DataFrame, cargo: int, uf: str, base: pd.Series, nomes: dict) -> dict | None:
    """Resumo de uma disputa; None se foi decidida no 1º turno (mais da metade dos votos válidos)."""
    t = v.groupby("votavel", observed=True).agg(votos=("votos", "sum"), nome=("nome", "first"))
    brancos = int(t["votos"].get(BRANCO, 0))
    nulos = int(t["votos"].get(NULO, 0))
    c = t.drop(index=[BRANCO, NULO], errors="ignore").sort_values("votos", ascending=False)
    validos = int(c["votos"].sum())
    if len(c) < 3 or int(c["votos"].iloc[0]) * 2 > validos:
        return None
    cands = []
    for numero, r in c.iterrows():
        urna, partido = nomes.get((uf, cargo, int(numero)), (titulo(r.nome), None))
        cands.append({"nome": urna, "partido": partido, "numero": int(numero), "votos": int(r.votos)})
    return {"id": uf, "cargo": cargo, "uf": None if uf == "BR" else uf, "aptos": int(base["aptos"]),
            "comparecimento": int(base["comparecimento"]), "abstencoes": int(base["abstencoes"]),
            "brancos": brancos, "nulos": nulos, "validos": validos, "cands": cands}


def ajuste_referencia(aptos: int) -> dict:
    """O que mudou do 1º para o 2º turno no ano de referência, na mesma fatia do eleitorado de agora."""
    h = next(x for x in HISTORICO if x["ano"] == ANO_REFERENCIA)
    f = aptos / h["aptos"]
    voltam = round((h["abst"][0] - h["abst"][1]) * f)       # abstenção caiu: eleitores a mais
    anulam = round((h["nulos"][1] - h["nulos"][0]) * f)     # nulos subiram
    saldo = round((h["validos"][1] - h["validos"][0]) * f)  # votos válidos a mais
    return {"ano": ANO_REFERENCIA, "voltam": voltam, "anulam": anulam, "saldo": saldo,
            "brancos": saldo + anulam - voltam}             # brancos que escolhem (fecha a conta)


def gerar(pasta: Path = PASTA, ano: int = 2026, turno: int = 1) -> dict | None:
    """Conteúdo de turno2.json, ou None se não houver votação por seção do 1º turno."""
    arq_sec, arq_br = pasta / f"secoes_{ano}_t1.parquet", pasta / f"votacao_{ano}_t1_BR.parquet"
    por_estado = {a.stem.rsplit("_", 1)[1]: a for a in sorted(pasta.glob(f"votacao_{ano}_t1_*.parquet")) if not a.stem.endswith("_BR")}
    if turno != 1 or not arq_sec.exists() or not (arq_br.exists() or por_estado):
        return None
    sec = pd.read_parquet(arq_sec, columns=["uf", "aptos", "comparecimento", "abstencoes"])
    por_uf = sec.groupby("uf")[["aptos", "comparecimento", "abstencoes"]].sum()
    nomes = nomes_de_urna(pasta, ano)
    disputas = []
    cols = ["cargo", "votavel", "votos", "nome"]
    estados = {uf: pd.read_parquet(a, columns=cols) for uf, a in por_estado.items()}
    # presidente: em 2026 vem só no arquivo "BR" (todas as UFs e o exterior); antes vinha nos arquivos por UF
    v = pd.read_parquet(arq_br, columns=cols) if arq_br.exists() else pd.concat(list(estados.values()))
    v = v[v["cargo"] == PRESIDENTE]
    d = _disputa(v, PRESIDENTE, "BR", por_uf.sum(), nomes) if len(v) else None
    if d:
        d["ajuste"] = ajuste_referencia(d["aptos"])
        disputas.append(d)
    for uf, v in estados.items():
        v = v[v["cargo"] == GOVERNADOR]
        d = _disputa(v, GOVERNADOR, uf, por_uf.loc[uf], nomes) if len(v) and uf in por_uf.index else None
        if d:
            disputas.append(d)
    if not disputas:
        return None
    return {"ano": ano, "disputas": disputas, "referencia": ANO_REFERENCIA,
            "historico": [{**h, "dois": list(h["dois"]), **{k: list(h[k]) for k in ("abst", "brancos", "nulos", "validos")}}
                          for h in HISTORICO]}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--baixar", action="store_true", help="Baixa o cadastro de candidatos (nomes de urna) antes")
    a = p.parse_args()
    if a.baixar:
        from download_tse import baixar_completo
        baixar_completo(URL_CAND.format(ano=a.ano), PASTA / f"consulta_cand_{a.ano}.zip")
    from gerar_site import SAIDA, gravar
    obj = gerar(PASTA, a.ano, 1)
    if not obj:
        raise SystemExit("Faltam dados/secoes_<ano>_t1.parquet e dados/votacao_<ano>_t1_*.parquet, ou nenhuma disputa foi ao 2º turno.")
    if not (SAIDA / "brasil.json").exists():
        if a.baixar:  # só baixou os nomes: o gerar_site.py grava o turno2.json junto com o resto
            print("Cadastro de candidatos baixado. Agora rode: python gerar_site.py")
            return
        raise SystemExit("Gere o site antes (python gerar_site.py); este comando só acrescenta turno2.json.")
    gravar(SAIDA / "turno2.json", obj)
    for d in obj["disputas"]:
        a_, b_ = d["cands"][:2]
        print(f"  {d['id']}: {a_['nome']} {a_['votos']:,} × {b_['nome']} {b_['votos']:,}; de fora {d['validos'] - a_['votos'] - b_['votos']:,}"
              + (f"; ajuste {d['ajuste']}" if d.get("ajuste") else ""))
    print(f"Gravado {SAIDA / 'turno2.json'}")


if __name__ == "__main__":
    main()
