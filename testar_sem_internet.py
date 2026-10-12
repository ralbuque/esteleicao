"""
Teste completo SEM INTERNET, com dados inventados (ano 1999) e casos plantados:

    python testar_sem_internet.py               # gera, processa, monta o site e confere
    python testar_sem_internet.py --so-conferir # só confere o site já gerado
    python testar_sem_internet.py --servir      # no fim, abre o site em http://localhost:8000

Roda, na ordem: gerar_dados_teste.py, todos os baixar_*.py com --zip (nos arquivos de
teste), gerar_site.py --ano 1999, e depois confere, caso a caso, se o que foi plantado
aparece no site (dados/teste_gabarito.csv e dados/teste_gabarito_extras.csv).
"""
from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).parent
D = RAIZ / "dados"
WEB = RAIZ / "web" / "dados"


def rodar(*args):
    print(f"\n$ python {' '.join(map(str, args))}")
    r = subprocess.run([sys.executable, *map(str, args)], cwd=RAIZ)
    if r.returncode:
        raise SystemExit(f"falhou: {args}")


def gerar():
    rodar("gerar_dados_teste.py")
    rodar("baixar_dados.py", "--ano", 1999, "--zip", D / "teste_detalhe_votacao_secao.zip")
    rodar("baixar_dados.py", "--ano", 1999, "--turno", 2, "--zip", D / "teste_detalhe_votacao_secao.zip")
    rodar("baixar_dados.py", "--ano", 1995, "--zip", D / "teste_detalhe_votacao_secao_1995.zip")
    for z in sorted(D.glob("teste_arqurna_*.zip")):
        rodar("baixar_logs.py", "--zip", z, "--refazer")
    rodar("baixar_locais.py", "--ano", 1999, "--zip", D / "teste_eleitorado_local_votacao.zip")
    rodar("baixar_votacao.py", "--ano", 1999, "--refazer", "--zip", *sorted(D.glob("teste_votacao_secao_1999_*.zip")))
    rodar("baixar_perfil.py", "--ano", 1999, "--refazer", "--zip", *sorted(D.glob("teste_perfil_eleitor_secao_1999_*.zip")))
    rodar("baixar_ibge.py", "--arquivo", D / "teste_populacao_ibge.zip")
    rodar("baixar_transferencia.py", "--ano", 1999, "--zip", D / "teste_transf_temporaria_secao_1999.zip")
    rodar("baixar_gastos.py", "--ano", 1999, "--zip", D / "teste_prestacao_de_contas_eleitorais_candidatos_1999.zip")
    rodar("gerar_site.py", "--ano", 1999)


def tab(t):
    return pd.DataFrame(t["rows"], columns=t["cols"])


def conferir() -> int:
    secoes = []
    for f in glob.glob(str(WEB / "zona" / "*.json")):
        j = json.load(open(f, encoding="utf-8"))
        secoes.append(tab(j["secoes"]).assign(cd=j["cd"]))
    z = pd.concat(secoes, ignore_index=True)
    z["sinais_cod"] = z["sinais_cod"].fillna("")
    mun = tab(json.load(open(WEB / "municipios.json", encoding="utf-8")))
    ex = json.load(open(WEB / "extras.json", encoding="utf-8"))
    g = pd.read_csv(D / "teste_gabarito.csv")
    gx = pd.read_csv(D / "teste_gabarito_extras.csv")
    k = z.merge(g, left_on=["cd", "zona", "secao"], right_on=["CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"])
    kx = z.merge(gx.dropna(subset=["NR_SECAO"]).astype({"NR_ZONA": int, "NR_SECAO": int}),
                 left_on=["cd", "zona", "secao"], right_on=["CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"])
    PADRAO = 1  # índice do nível padrão
    bitc = lambda s, i: pd.Series((s.fillna(0).astype("int64").to_numpy() >> i) & 1, index=s.index)
    resultados = []

    def caso(nome, plantadas, achadas, fora=None, minimo=1.0):
        ok = plantadas > 0 and achadas >= minimo * plantadas
        extra = f"; fora do gabarito: {fora}" if fora is not None else ""
        resultados.append(ok)
        print(f"  {'OK   ' if ok else 'FALHA'} {nome:<52} {achadas}/{plantadas}{extra}")

    print("\nConferência dos casos plantados (rigor padrão):")
    crit = bitc(k["flags"], 3) + 2 * bitc(k["flags"], 4) + 4 * bitc(k["flags"], 5)
    for tipo, b in [("abstencao_baixa", 1), ("manual_alto", 4)]:
        m = k["tipo"] == tipo
        caso(f"{tipo} -> critério", int(m.sum()), int(((crit & b) > 0)[m].sum()), minimo=0.8)
    m = k["tipo"] == "cruzada"
    caso("cruzada -> 2+ critérios", int(m.sum()), int((((crit & 1) > 0).astype(int) + ((crit & 2) > 0) + ((crit & 4) > 0) >= 2)[m].sum()), minimo=0.8)
    m = k["tipo"] == "fila_local"
    caso("fila_local -> NÃO entra em 'após 17h' (é fila)", int(m.sum()), int(((crit & 2) == 0)[m].sum()), minimo=0.85)
    for tipo, cod in [("rapida", "rapidos"), ("antes_8h", "antes_8h"), ("manual_tarde", "manual_tarde")]:
        m = k["tipo"] == tipo
        fora = int((~m & k["sinais_cod"].str.contains(cod)).sum())
        caso(f"{tipo} -> sinal '{cod}'", int(m.sum()), int(k.loc[m, "sinais_cod"].str.contains(cod).sum()), fora,
             minimo=0.6 if tipo == "manual_tarde" else 1.0)
    if "flags_lib" in k:
        fl = k["flags_lib"]
        m = k["tipo"] == "salto_17h"
        caso("salto_17h -> tag 'salto às 17h'", int(m.sum()), int((bitc(fl, 3 + PADRAO) > 0)[m].sum()),
             int(((bitc(fl, 3 + PADRAO) > 0) & ~m).sum()))
        caso("salto_17h -> tag 'liberações depois das 17h'", int(m.sum()), int((bitc(fl, PADRAO) > 0)[m].sum()))
        for tipo in ["leitor_quebrado", "leitor_quebra_14h"]:
            m = k["tipo"] == tipo
            caso(f"{tipo} -> 'leitor com defeito' e NÃO salto", int(m.sum()),
                 int(((bitc(fl, 6) > 0) & (bitc(fl, 3 + PADRAO) == 0))[m].sum()))
        m = k["tipo"] == "leitor_quebra_14h"
        caso("leitor_quebra_14h -> defeito a partir das 14h", int(m.sum()), int(k.loc[m, "defeito_desde"].between(13, 15).sum()))
    if "flags_atip" in k and "atip" in k:  # casos extremamente atípicos (tags)
        fa, at = k["flags_atip"], k["atip"].fillna("")
        fora, tarde, soz = bitc(fa, 0) > 0, bitc(fa, 1) > 0, bitc(fa, 2) > 0
        m = at == "fora_log"
        caso("fora_log -> tag 'votos fora do log' (e só ela)", int(m.sum()), int((fora & ~tarde & ~soz)[m].sum()),
             int((fora & ~at.isin(["fora_log", "urna_tarde"])).sum()))
        m = at == "urna_tarde"
        caso("urna_tarde -> 'urna começou tarde' + 'votos fora do log'", int(m.sum()), int((tarde & fora)[m].sum()),
             int((tarde & ~m).sum()))
        m = at == "sozinha"
        caso("sozinha -> tag 'terminou sozinha'", int(m.sum()), int(soz[m].sum()), int((soz & ~m).sum()), minimo=0.8)
        m = k["tipo"] == "fila_local"
        caso("fila_local -> NÃO é 'terminou sozinha' (escola inteira tarde)", int(m.sum()), int((~soz)[m].sum()))
        br = json.load(open(WEB / "brasil.json", encoding="utf-8"))["total"]
        caso("total de 'votos fora do log' no Brasil = seções com a tag", int(bitc(z["flags_atip"], 0).sum()),
             int(br["atip_fora"]) if br["atip_fora"] == int(bitc(z["flags_atip"], 0).sum()) else 0)
    if "perfil_explica" in k:
        m = k["tipo"] == "perfil_jovem"
        amplo_abst = bitc(k["flags"], 6) > 0
        caso("perfil_jovem -> abstenção baixa explicada pela idade (amplo)", int(m.sum()),
             int((amplo_abst & (bitc(k["perfil_explica"], 2) > 0))[m].sum()), minimo=0.75)
        m = k["tipo"] == "idosos"
        caso("idosos -> liberação manual explicada pela idade (padrão)", int(m.sum()),
             int((bitc(k["perfil_explica"], 3 + PADRAO) > 0)[m].sum()), minimo=0.75)
    if "flags_conc" in kx:
        m = kx["caso"].str.startswith("concentrado")
        fora = int(((bitc(z["flags_conc"], PADRAO) > 0).sum()) - (bitc(kx.loc[m, "flags_conc"], PADRAO) > 0).sum())
        caso("voto concentrado -> 4º critério", int(m.sum()), int((bitc(kx["flags_conc"], PADRAO) > 0)[m].sum()), fora, minimo=0.8)
        m = kx["caso"] == "concentrado_curral"
        caso("curral -> brancos e nulos muito abaixo", int(m.sum()), int((kx["conc_z_bn"] <= -3)[m].sum()), minimo=0.5)
    if "comp_sobe_turno" in kx:
        m = kx["caso"] == "salto_2turno"
        caso("comparecimento dispara no 2º turno", int(m.sum()), int(kx.loc[m, "comp_sobe_turno"].fillna(0).astype(bool).sum()),
             int(z["comp_sobe_turno"].fillna(0).astype(bool).sum()) - int(kx.loc[m, "comp_sobe_turno"].fillna(0).sum()))
    if "transf_recebidos" in kx:
        m = kx["caso"] == "transferencia_grande"
        caso("transferência temporária grande", int(m.sum()), int((kx["transf_recebidos"] >= 150)[m].sum()))
    if "n_agregadas" in kx:
        m = kx["caso"] == "agregada"
        caso("seção com seções agregadas", int(m.sum()), int((kx["n_agregadas"] > 0)[m].sum()),
             int((z["n_agregadas"].fillna(0) > 0).sum()) - int(m.sum()))
    if "flags_ant" in kx:
        m = kx["caso"] == "repetiu_1995"
        caso("abstenção baixa que já existia em 1995", int(m.sum()), int((bitc(kx["flags_ant"], 6) > 0)[m].sum()), minimo=0.6)
        m = kx["caso"] == "novidade_1999"
        caso("abstenção baixa nova em 1999 (não existia em 1995)", int(m.sum()), int((bitc(kx["flags_ant"], 6) == 0)[m].sum()))
    gm = gx[gx["NR_SECAO"].isna()]
    if "razao_pop" in mun:
        alvo = gm[gm["caso"] == "cadastro_inflado"]["CD_MUNICIPIO"]
        caso("município com mais eleitores que população 16+", len(alvo),
             int((mun.set_index("cd_municipio").loc[alvo, "razao_pop"] > 1.1).sum()), int((mun["razao_pop"] > 1.1).sum()) - len(alvo))
    if "cresc_eleitorado" in mun:
        alvo = gm[gm["caso"] == "crescimento_40pct"]["CD_MUNICIPIO"]
        caso("eleitorado cresceu 40%", len(alvo), int((mun.set_index("cd_municipio").loc[alvo, "cresc_eleitorado"] > 0.3).sum()),
             int((mun["cresc_eleitorado"] > 0.3).sum()) - len(alvo))
    if "gasto_vs_uf" in mun:
        alvo = gm[gm["caso"] == "gasto_alto"]["CD_MUNICIPIO"]
        caso("gasto de campanha por eleitor muito acima da UF", len(alvo),
             int((mun.set_index("cd_municipio").loc[alvo, "gasto_vs_uf"] >= 5).sum()), int((mun["gasto_vs_uf"] >= 5).sum()) - len(alvo))
    mat = ex.get("materialidade", [])
    caso("materialidade: governador do MS em disputa apertada", 1,
         int(any(r["cargo"] == 3 and r["escopo"] == "MS" and r["dif_1_2"] < 0.05 * r["validos"] for r in mat)))

    # totais dos relatórios novos contra os arquivos de origem
    print("\nTotais contra os arquivos de origem:")
    sec = pd.read_parquet(D / "secoes_1999_t1.parquet")
    for cargo in [1, 3, 5]:
        v = 0
        for a in D.glob("votacao_1999_t1_*.parquet"):
            t = pd.read_parquet(a)
            v += t.loc[(t["cargo"] == cargo) & ~t["votavel"].isin([95, 96]), "votos"].sum()
        m = sum(r["validos"] for r in mat if r["cargo"] == cargo)
        caso(f"votos válidos cargo {cargo}: materialidade = votação por seção", int(v), int(m) if m == v else 0)
    if "perfil" in ex:
        p = sum(pd.read_parquet(a)["eleitores"].sum() for a in D.glob("perfil_1999_*.parquet"))
        caso("eleitores no perfil = soma dos arquivos de perfil", int(p), int(ex["perfil"]["eleitores"]) if ex["perfil"]["eleitores"] == p else 0)
        caso("eleitores no perfil = aptos do resultado", int(sec["aptos"].sum()), int(p) if p == sec["aptos"].sum() else 0)
    if "gastos" in ex and ex["gastos"]:
        gg = pd.read_parquet(D / "gastos_1999.parquet")["valor"].sum()
        caso("gastos: total = arquivo de gastos", 1, int(abs(gg - ex["gastos"]["total"]) < 1))
    ok = all(resultados)
    print(f"\n{'Tudo certo' if ok else 'Há falhas'}: {sum(resultados)} de {len(resultados)} conferências.")
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--so-conferir", action="store_true")
    p.add_argument("--servir", action="store_true")
    a = p.parse_args()
    if not a.so_conferir:
        gerar()
    r = conferir()
    if a.servir:
        from gerar_site import servir
        servir(RAIZ / "web")
    return r


if __name__ == "__main__":
    sys.exit(main())
