"""
Testes do critério "salto sem digital a partir das 16h" (analise.salto_fim_do_dia).

    python testar_fim_do_dia.py                     casos construídos (não precisa de dados)
    python testar_fim_do_dia.py --plantar BA        planta o esquema em seções reais e mede a detecção
    python testar_fim_do_dia.py --resumo            resultado por UF com os logs já processados
    python testar_fim_do_dia.py --bruto 3           baixa do TSE o log das 3 seções com maior excesso
                                                    e confere voto a voto

--plantar, --resumo e --bruto usam dados/secoes_<ano>_t<turno>.parquet e dados/logs_*.parquet
(rode antes baixar_dados.py e baixar_logs.py). Sai com código 1 se algum teste falhar.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from analise import criterio_fim, juntar_horario, pontuar_secoes

PASTA = Path(__file__).parent / "dados"
CHAVE = ["uf", "cd_municipio", "zona", "secao"]
PERFIL = np.array([.13, .14, .13, .11, .09, .10, .11, .10, .09, .03])  # 8h..17h
PERFIL = PERFIL / PERFIL.sum()


# ------------------------------------------------------------------ 1. casos construídos
def _secao(i, votos, sem_dig, manual, aptos=330):
    r = {"uf": "BA", "cd_municipio": 1, "zona": 1, "secao": i, "local": i // 4, "aptos": aptos}
    for p, arr in (("h", votos), ("s", sem_dig), ("m", manual)):
        cheio = np.zeros(24, int)
        cheio[8:18] = arr
        r.update({f"{p}{h:02d}": int(cheio[h]) for h in range(24)})
    comp = int(np.sum(votos))
    r.update(comparecimento=comp, abstencoes=aptos - comp, taxa_abstencao=(aptos - comp) / aptos)
    return r


def _logs_de(linhas: list[dict]) -> pd.DataFrame:
    """Monta um parquet de logs mínimo (só o que juntar_horario precisa) a partir das seções."""
    lg = pd.DataFrame(linhas)
    h = lg[[f"h{x:02d}" for x in range(24)]].to_numpy()
    s = lg[[f"s{x:02d}" for x in range(24)]].to_numpy()
    m = lg[[f"m{x:02d}" for x in range(24)]].to_numpy()
    centro = np.arange(24) + .5
    lg["votos_log"] = h.sum(1)
    lg["fuso"] = 0
    lg["hora_media"] = (h * centro).sum(1) / lg["votos_log"]
    lg["abertura"] = 8.0
    lg["primeiro_voto"] = 8.0
    lg["votos_apos_17"] = h[:, 17:].sum(1)
    lg["pct_apos_17"] = lg["votos_apos_17"] / lg["votos_log"]
    lg["votos_digital"] = lg["votos_log"] - s.sum(1)
    lg["votos_manual"] = m.sum(1)
    lg["votos_sem_cadastro"] = s.sum(1) - m.sum(1)
    for c in ["ociosa_antes_17_min", "pct_sem_bio_apos_17", "intervalo_med_apos_17_s", "maior_seq_manual",
              "n_urnas", "abertura_atrasada_min"]:
        lg[c] = 0.0
    return lg.drop(columns=["local", "aptos", "comparecimento", "abstencoes", "taxa_abstencao"])


def testar_casos() -> int:
    rng = np.random.default_rng(7)

    def normal(i, n=260):
        v = rng.multinomial(n, PERFIL)
        s = rng.binomial(v, .11)
        return _secao(i, v, s, rng.binomial(s, .64))

    linhas = [normal(i) for i in range(60)]
    casos = {}
    v = rng.multinomial(300, (lambda q: q / q.sum())(PERFIL * np.r_[np.ones(7), 1.8, 2.2, 3.0]))
    s = rng.binomial(v, .11)
    casos["fila às 17h (mesma composição)"] = (_secao(100, v, s, rng.binomial(s, .6)), False)
    r = normal(101, n=250)
    for h, k in ((16, 10), (17, 8)):  # 18 votos sem digital (manuais) no fim do dia, tirados da abstenção
        for p in "hsm":
            r[f"{p}{h:02d}"] += k
    r["comparecimento"] += 18
    r["abstencoes"] -= 18
    r["taxa_abstencao"] = r["abstencoes"] / r["aptos"]
    casos["voto no lugar de ausente (18 votos)"] = (r, True)
    v = rng.multinomial(260, PERFIL)
    s = rng.binomial(v, .11)
    m = rng.binomial(s, .6)
    s[8:] = v[8:]
    m[8:] = v[8:] - rng.binomial(v[8:], .04)
    casos["leitor que quebra às 16h"] = (_secao(102, v, s, m), False)
    v = rng.multinomial(260, PERFIL)
    s = rng.binomial(v, .11)
    s[:3] = rng.binomial(v[:3], .45)
    casos["idosos votando cedo"] = (_secao(103, v, s, rng.binomial(s, .7)), False)

    todas = linhas + [c for c, _ in casos.values()]
    sec = pd.DataFrame([{k: v for k, v in r.items() if not k[0] in "hsm" or len(k) != 3} for r in todas])
    df = juntar_horario(pontuar_secoes(sec), _logs_de(todas))
    df["salto"] = criterio_fim(df)
    df = df.set_index("secao")
    falhas = 0
    print("1. Casos construídos")
    for nome, (c, esperado) in casos.items():
        o = df.loc[c["secao"]]
        ok = bool(o["salto"]) == esperado
        falhas += not ok
        print(f"  {'ok  ' if ok else 'ERRO'} {nome:38s} esperado: {'sinaliza' if esperado else 'não sinaliza':13s}"
              f" z {o['z_sem_digital_fim']:+5.1f}  excesso {o['excesso_sem_digital_fim']:+5.1f}"
              f"  leitor ok: {bool(o['leitor_ok_fim'])}")
    fp = int(df.loc[range(60), "salto"].sum())
    falhas += fp > 0
    print(f"  {'ok  ' if fp == 0 else 'ERRO'} seções normais sinalizadas: {fp} de 60")
    return falhas


# ------------------------------------------------------------------ dados reais
def carregar(ano: int, turno: int, ufs: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    sec = pd.read_parquet(PASTA / f"secoes_{ano}_t{turno}.parquet")
    arqs = sorted(PASTA.glob(f"logs_{ano}_t{turno}_*.parquet"))
    if ufs:
        arqs = [a for a in arqs if a.stem.rsplit("_", 1)[-1] in ufs]
    if not arqs:
        sys.exit("Sem logs processados para essas UFs. Rode baixar_logs.py antes.")
    logs = pd.concat([pd.read_parquet(a) for a in arqs], ignore_index=True)
    sec = sec[sec["uf"].astype(str).isin(logs["uf"].unique())].reset_index(drop=True)
    return sec, logs


def calcular(sec: pd.DataFrame, logs: pd.DataFrame) -> pd.DataFrame:
    df = juntar_horario(pontuar_secoes(sec), logs)
    df = df[df["tem_log"]].copy()
    df["uf"] = df["uf"].astype(str)
    df["salto"] = criterio_fim(df)
    df["completo"] = df["salto"] & (df["deficit_abstencao"] >= 0.5 * df["excesso_sem_digital_fim"])
    return df


def testar_plantio(uf: str, ano: int, turno: int, n: int = 1000) -> None:
    sec, logs = carregar(ano, turno, [uf])
    for c in ["cd_municipio", "zona", "secao"]:
        sec[c] = sec[c].astype("Int32")
        logs[c] = logs[c].astype("Int32")
    juntos = sec.merge(logs[CHAVE], on=CHAVE).index
    rng = np.random.default_rng(2026)
    cand = sec.loc[juntos].index[sec.loc[juntos, "abstencoes"] >= 40]
    alvo = rng.choice(cand, min(n, len(cand)), replace=False)
    chaves = sec.loc[alvo, CHAVE]
    i_log = logs.reset_index().merge(chaves, on=CHAVE)["index"].to_numpy()
    base = calcular(sec, logs)
    print(f"2. Esquema plantado em {len(alvo):,} seções reais de {uf} (sem plantio: {int(base['salto'].sum())} "
          f"de {len(base):,} disparam)")
    print(f"  {'votos trocados':>15} {'detectadas':>11} {'padrão completo':>16} {'outras seções':>14}")
    for k in [3, 5, 8, 10, 15, 20, 30, 40]:
        s2, l2 = sec.copy(), logs.copy()
        k16 = int(round(k * .6))
        for h, kk in ((16, k16), (17, k - k16)):  # horário de Brasília; o log guarda a hora local
            col = (h + l2.loc[i_log, "fuso"]).astype(int).clip(0, 23)
            for p, q in (("h", kk), ("s", kk), ("m", int(round(kk * .6)))):
                for hl in col.unique():
                    idx = i_log[(col == hl).to_numpy()]
                    l2.loc[idx, f"{p}{hl:02d}"] += q
        l2.loc[i_log, "votos_log"] += k
        s2.loc[alvo, "comparecimento"] += k
        s2.loc[alvo, "abstencoes"] -= k
        s2["taxa_abstencao"] = s2["abstencoes"] / s2["aptos"]
        d = calcular(s2, l2)
        em = d.set_index(CHAVE).index.isin(chaves.set_index(CHAVE).index)
        print(f"  {k:>15} {d.loc[em, 'salto'].mean():>11.0%} {d.loc[em, 'completo'].mean():>16.0%} "
              f"{int(d.loc[~em, 'salto'].sum()):>14}")


def resumo(ano: int, turno: int) -> pd.DataFrame:
    df = calcular(*carregar(ano, turno))
    t = df.groupby("uf").agg(secoes=("secao", "size"), salto=("salto", "sum"), completo=("completo", "sum"))
    t["esperado_por_acaso"] = (t["secoes"] * 0.00135).round(0).astype(int)  # cauda de 3 desvios
    por_escola = df[df["salto"]].groupby(["uf", "cd_municipio", "zona", "local"], observed=True).size()
    print("3. Resultado por UF")
    print(t.to_string())
    print(f"  escolas com 2 ou mais seções com salto: {int((por_escola >= 2).sum())}")
    return df


def testar_bruto(df: pd.DataFrame, n: int, ano: int, turno: int) -> int:
    import zipfile

    import requests

    from download_tse import ArquivoRemoto, _ler_membro, tamanho_remoto
    from logs_urna import HAB_DIGITAL, extrair_logd, ler_eventos
    from baixar_logs import URL

    top = df[df["completo"]].sort_values("excesso_sem_digital_fim", ascending=False).head(n)
    print(f"4. Conferência no log bruto ({len(top)} seções)")
    falhas = 0
    for uf, g in top.groupby("uf"):
        sessao = requests.Session()
        url = URL.format(ano=ano, turno=turno, uf=uf)
        tam = tamanho_remoto(sessao, url)
        with zipfile.ZipFile(ArquivoRemoto(url, sessao, tam)) as zr:
            infos = zr.infolist()
        for _, s in g.iterrows():
            sufixo = f"{int(s.cd_municipio):05d}{int(s.zona):04d}{int(s.secao):04d}-log.jez"
            votos, hab = [], []
            for info in (i for i in infos if i.filename.lower().endswith(sufixo)):
                ev = ler_eventos(extrair_logd(_ler_membro(sessao, url, tam, info)))
                votos += list(ev["votos_s"])
                hab += list(ev["hab"])
            v, h = np.array(votos), np.array(hab)
            fim = v / 3600 - s["fuso"] >= 16
            pct_fim = float((h[fim] != HAB_DIGITAL).mean()) if fim.any() else np.nan
            ok = abs(pct_fim - s["pct_sem_digital_fim"]) < 1e-6
            falhas += not ok
            print(f"  {'ok  ' if ok else 'ERRO'} {uf} {s['municipio']} z{s['zona']} s{s['secao']}: "
                  f"sem digital a partir das 16h {pct_fim:.1%} no log bruto, {s['pct_sem_digital_fim']:.1%} no parquet")
    return falhas


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", type=int, default=2026)
    p.add_argument("--turno", type=int, default=1)
    p.add_argument("--plantar", metavar="UF", type=str.upper)
    p.add_argument("--resumo", action="store_true")
    p.add_argument("--bruto", type=int, metavar="N")
    a = p.parse_args()
    falhas = testar_casos()
    if a.plantar:
        testar_plantio(a.plantar, a.ano, a.turno)
    if a.resumo or a.bruto:
        df = resumo(a.ano, a.turno)
        if a.bruto:
            falhas += testar_bruto(df, a.bruto, a.ano, a.turno)
    print("\nTudo certo." if not falhas else f"\n{falhas} teste(s) falharam.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
