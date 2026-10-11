"""
Gera dados FALSOS no mesmo formato dos arquivos do TSE, para testar o sistema
sem baixar nada:

  dados/teste_detalhe_votacao_secao.zip     (abstenção por seção)
  dados/teste_arqurna_1999_1t_<UF>.zip      (logs de urna .logjez por seção)

Inclui seções anômalas plantadas de propósito:
  - abstenção muito alta ou muito baixa;
  - "cruzadas": abstenção baixa + rajada de votos sem biometria após as 17h
    sem fila antes (o padrão que o painel procura);
  - filas legítimas: escolas inteiras votando até tarde (não devem ser destaque);
  - liberação manual alta: seções isoladas onde muitos eleitores COM digital
    cadastrada foram liberados pelo mesário, incluindo 12 seguidos;
  - escolas inteiras com muitos eleitores sem digital cadastrada (legítimo).

    python gerar_dados_teste.py
    python baixar_dados.py --ano 1999 --zip dados/teste_detalhe_votacao_secao.zip
    for f in dados/teste_arqurna_*.zip; do python baixar_logs.py --zip $f; done
    python baixar_locais.py --ano 1999 --zip dados/teste_eleitorado_local_votacao.zip
    python gerar_site.py
"""
import io
import zipfile
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import py7zr

rng = np.random.default_rng(42)
PASTA = Path(__file__).parent / "dados"
UFS = {"SP": 0.225, "CE": 0.153, "MG": 0.226, "MS": 0.238, "RJ": 0.233}
FUSO = {"MS": -1}  # urnas do MS marcam 1h a menos (abrem às 7h locais)
CARGOS = [(1, "Presidente"), (3, "Governador"), (6, "Deputado Federal")]
DIA = date(1999, 10, 3)
PERFIL_CHEGADA = np.array([.13, .14, .13, .11, .09, .10, .11, .10, .09])  # 8h..16h

# ------------------------------------------------------------ simulação dos horários
def sortear_hab(n, p_sem_cad, p_manual):
    """0 = digital, 1 = sem cadastro de digital, 2 = liberação manual (tinha digital)."""
    u = rng.random(n)
    hab = np.zeros(n, dtype=int)
    hab[u < p_sem_cad] = 1
    cad = u >= p_sem_cad
    hab[cad & (rng.random(n) < p_manual)] = 2
    return hab


def simular(n_eleitores, tipo, aptos, p_sem_cad, p_manual):
    """Devolve (segundos dos votos, habilitação) em horário de Brasília."""
    perfil = PERFIL_CHEGADA.copy()
    if tipo == "fila_local":
        perfil = perfil * np.linspace(0.6, 1.9, 9)
    perfil /= perfil.sum()
    n_falsos = int(aptos * 0.25) if tipo == "cruzada" else 0
    n_reais = max(n_eleitores - n_falsos, 1)
    hora = rng.choice(9, n_reais, p=perfil)
    chegada = np.sort((8 + hora + rng.random(n_reais)) * 3600)
    atend = rng.gamma(4, 22 if tipo != "fila_local" else 30, n_reais)  # ~90 s por eleitor
    fim, votos = 8 * 3600, []
    for c, a in zip(chegada, atend):
        fim = max(fim, c) + a
        votos.append(fim)
    if tipo == "escola_sem_cadastro":
        p_sem_cad = 0.40
    if tipo == "manual_alto":
        p_manual = 0.45
    hab = sortear_hab(n_reais, p_sem_cad, p_manual)
    if tipo == "manual_alto":  # rajada de liberações manuais no meio da tarde
        meio = len(hab) // 2
        hab[meio: meio + 12] = 2
    votos = np.array(votos)
    if n_falsos:
        votos = votos[votos < 16.4 * 3600][: n_reais]  # sem fila na última meia hora
        hab = hab[: len(votos)]
        inicio = 17 * 3600 + rng.integers(60, 600)
        falsos = inicio + np.cumsum(rng.integers(25, 50, n_falsos))
        votos = np.concatenate([votos, falsos])
        hab = np.concatenate([hab, np.where(rng.random(n_falsos) < 0.9, 2, 0)])
    return votos.astype(int), hab


def hms(t):
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def montar_log(mun, zona, secao, votos, hab, fuso, id_urna, extras_teste=True):
    L = []
    d0 = (DIA - timedelta(days=12)).strftime("%d/%m/%Y")
    d = DIA.strftime("%d/%m/%Y")
    ap = lambda dia, t, app, msg: L.append(f"{dia} {hms(t)}\tINFO\t{id_urna}\t{app}\t{msg}\tA162B520DE6255E2")
    for k, v in [("Município", mun), ("Zona Eleitoral", zona), ("Seção Eleitoral", secao)]:
        ap(d0, 9 * 3600, "GAP", f"{k}: {v}")
    if extras_teste:  # votação simulada em dia anterior (deve ser ignorada)
        for t in range(3):
            ap(d0, (10 * 3600) + t * 120, "VOTA", "Aguardando digitação do título")
            ap(d0, (10 * 3600) + t * 120 + 60, "VOTA", "O voto do eleitor foi computado")
    s = fuso * 3600
    ap(d, 7 * 3600 + 1800 + s, "VOTA", "Iniciando aplicação - Oficial - 1º turno")
    ap(d, 7 * 3600 + 2200 + s, "VOTA", "Gerando relatório [ZERÉSIMA] [INÍCIO]")
    ap(d, 8 * 3600 + 2 + s, "VOTA", "Aguardando digitação do título")
    for t, h in zip(votos, hab):
        t = t + s
        ap(d, t - 50, "VOTA", "Título digitado pelo mesário")
        if h == 0:
            ap(d, t - 45, "VOTA", "Solicita digital. Tentativa [1] de [4]")
            ap(d, t - 40, "VOTA", "Tipo de habilitação do eleitor [biométrica]")
        elif h == 1:
            ap(d, t - 45, "VOTA", "O eleitor não possui biometria")
        else:
            for k in range(1, 5):
                ap(d, t - 48, "VOTA", f"Solicita digital. Tentativa [{k}] de [4]")
                ap(d, t - 47, "VOTA", "Digital capturada não corresponde a digital do eleitor: Polegar Direito [score 3]")
            ap(d, t - 45, "VOTA", "Solicitação de dado pessoal do eleitor para habilitação manual")
            ap(d, t - 42, "VOTA", "Solicita digital do mesário")
            ap(d, t - 41, "VOTA", "Capturada a digital do mesário")
        ap(d, t - 39, "VOTA", "Eleitor foi habilitado")
        ap(d, t - 10, "VOTA", "Voto confirmado para [Presidente]")
        ap(d, t, "VOTA", "O voto do eleitor foi computado")
        ap(d, t + 1, "VOTA", "Aguardando digitação do título")
    return "\n".join(L).encode("latin-1")


def logjez(texto: bytes) -> bytes:
    b = io.BytesIO()
    with py7zr.SevenZipFile(b, "w") as z:
        z.writestr(texto, "logd.dat")
    return b.getvalue()



def municipios_reais(uf: str, n: int) -> list[tuple[int, str, float, float]]:
    """Sorteia municípios REAIS da UF (código do TSE, nome, lat, lon) para o mapa funcionar no teste."""
    ref = pd.read_csv(Path(__file__).parent / "referencia" / "municipios.csv").dropna(subset=["cd_tse"])
    ref = ref[ref["uf"] == uf]
    esc = ref.sample(min(n, len(ref)), random_state=int(rng.integers(1 << 30)))
    return [(int(r.cd_tse), r.nome.upper(), r.lat, r.lon) for r in esc.itertuples()]


ENDERECOS = ["RUA DAS FLORES", "AVENIDA BRASIL", "RUA SÃO JOÃO", "PRAÇA DA MATRIZ", "RUA SETE DE SETEMBRO",
             "AVENIDA GETÚLIO VARGAS", "RUA TIRADENTES", "RUA DOM PEDRO II", "AVENIDA CENTRAL"]
BAIRROS = ["CENTRO", "JARDIM AMÉRICA", "VILA NOVA", "SÃO JOSÉ", "BOA VISTA", "SANTA LUZIA", "ZONA RURAL"]
TIPOS_LOCAL = ["ESCOLA ESTADUAL", "ESCOLA MUNICIPAL", "COLÉGIO", "CENTRO COMUNITÁRIO", "UNIVERSIDADE"]


def main():
    # ------------------------------------------------------------ seções e abstenção
    linhas = []
    coords = {}
    for uf, base in UFS.items():
        for cd, nm, lat, lon in municipios_reais(uf, int(rng.integers(8, 20))):
            coords[cd] = (lat, lon)
            p_mun = np.clip(base + rng.normal(0, 0.03), 0.05, 0.6)
            p_sem_cad_mun = float(rng.uniform(0.04, 0.18))  # cobertura biométrica varia por município
            for zona in range(1, rng.integers(2, 5)):
                for s in range(1, rng.integers(15, 70)):
                    aptos = int(rng.integers(30, 420))
                    p = np.clip(p_mun + rng.normal(0, 0.035), 0.01, 0.95)
                    abst = int(rng.binomial(aptos, p))
                    linhas.append([uf, cd, nm, zona, s, aptos, abst, (zona * 1000 + s // 8), p_sem_cad_mun])

    df = pd.DataFrame(linhas, columns=["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA",
                                       "NR_SECAO", "QT_APTOS", "QT_ABSTENCOES", "NR_LOCAL_VOTACAO",
                                       "p_sem_cad"])
    df["tipo"] = "normal"

    # abstenção anômala (alta / baixa)
    idx = rng.choice(len(df), 12, replace=False)
    for i, j in enumerate(idx):
        df.loc[j, "QT_ABSTENCOES"] = int(df.loc[j, "QT_APTOS"] * (0.02 if i % 2 else 0.65))
        df.loc[j, "tipo"] = "abstencao_baixa" if i % 2 else "abstencao_alta"

    # cruzadas: abstenção baixa + votos tardios sem biometria (seções grandes)
    grandes = df.index[(df["QT_APTOS"] > 250) & (df["tipo"] == "normal")]
    cruz = rng.choice(grandes, 8, replace=False)
    df.loc[cruz, "tipo"] = "cruzada"

    # filas legítimas: alguns locais de votação inteiros com eleitores chegando no fim do dia
    locais = df.loc[df["tipo"] == "normal", ["CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]].drop_duplicates()
    fila = locais.sample(6, random_state=1)
    marca = df.merge(fila.assign(_f=1), how="left", on=list(fila.columns))["_f"].eq(1).to_numpy()
    df.loc[marca & (df["tipo"] == "normal"), "tipo"] = "fila_local"

    # liberação manual alta (tinha digital, mesário liberou) em seções isoladas
    normais = df.index[(df["tipo"] == "normal") & (df["QT_APTOS"] > 150)]
    df.loc[rng.choice(normais, 8, replace=False), "tipo"] = "manual_alto"

    # escolas inteiras com muita gente sem digital cadastrada (legítimo: ex. eleitores novos)
    locais = df.loc[df["tipo"] == "normal", ["CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]].drop_duplicates()
    esc = locais.sample(4, random_state=7)
    marca = df.merge(esc.assign(_f=1), how="left", on=list(esc.columns))["_f"].eq(1).to_numpy()
    df.loc[marca & (df["tipo"] == "normal"), "tipo"] = "escola_sem_cadastro"

    # locais de votação (formato do arquivo do TSE "Eleitorado por local de votação"),
    # com endereço e coordenadas inventados perto do centro do município
    loc = df[["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO", "QT_APTOS"]].copy()
    unicos = loc[["CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]].drop_duplicates()
    info = {}
    for r in unicos.itertuples(index=False):
        lat, lon = coords[r.CD_MUNICIPIO]
        k = int(rng.integers(1000))
        info[tuple(r)] = (f"{TIPOS_LOCAL[k % 5]} {['ANITA GARIBALDI', 'RUI BARBOSA', 'MONTEIRO LOBATO', 'CECÍLIA MEIRELES', 'PAULO FREIRE'][k % 5]} {r.NR_LOCAL_VOTACAO % 100}",
                          f"{ENDERECOS[k % 9]}, {int(rng.integers(10, 2000))}", BAIRROS[k % 7],
                          f"{int(rng.integers(10000, 99999))}{int(rng.integers(100, 999))}",
                          round(lat + rng.normal(0, 0.02), 6) if k % 13 else -1,
                          round(lon + rng.normal(0, 0.02), 6) if k % 13 else -1)
    vals = [info[(a, b, c)] for a, b, c in zip(loc["CD_MUNICIPIO"], loc["NR_ZONA"], loc["NR_LOCAL_VOTACAO"])]
    for i, col in enumerate(["NM_LOCAL_VOTACAO", "DS_ENDERECO", "NM_BAIRRO", "NR_CEP", "NR_LATITUDE", "NR_LONGITUDE"]):
        loc[col] = [v[i] for v in vals]
    loc = loc.rename(columns={"QT_APTOS": "QT_ELEITOR_SECAO"})
    loc.insert(0, "NR_TURNO", 1)
    loc.insert(0, "AA_ELEICAO", 1999)
    buf = io.StringIO()
    loc.to_csv(buf, sep=";", index=False, decimal=",")
    PASTA.mkdir(exist_ok=True)
    with zipfile.ZipFile(PASTA / "teste_eleitorado_local_votacao.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("eleitorado_local_votacao_1999.csv", buf.getvalue().encode("latin-1"))
    nomes_local = {k: v[0] for k, v in info.items()}

    PASTA.mkdir(exist_ok=True)
    for f in PASTA.glob("teste_arqurna_*.zip"):
        f.unlink()
    zips = {uf: zipfile.ZipFile(PASTA / f"teste_arqurna_1999_1t_{uf}.zip", "w", zipfile.ZIP_STORED) for uf in UFS}
    interno = io.BytesIO()
    zip_interno = zipfile.ZipFile(interno, "w")  # CE: logs dentro de um zip interno (testa os dois formatos)
    pendentes = []
    for i, r in enumerate(df.itertuples()):
        comparec = r.QT_APTOS - r.QT_ABSTENCOES
        if r.tipo == "cruzada":
            comparec = r.QT_APTOS - int(r.QT_APTOS * 0.03)
            df.at[r.Index, "QT_ABSTENCOES"] = r.QT_APTOS - comparec
        if r.tipo == "fila_local":
            comparec = r.QT_APTOS - int(r.QT_APTOS * 0.12)
            df.at[r.Index, "QT_ABSTENCOES"] = r.QT_APTOS - comparec
        p_manual = float(np.clip(rng.normal(0.08, 0.025), 0.01, 0.2))
        votos, hab = simular(comparec, r.tipo, r.QT_APTOS, r.p_sem_cad, p_manual)
        nome = f"o00999-{r.CD_MUNICIPIO:05d}{r.NR_ZONA:04d}{r.NR_SECAO:04d}"
        texto = montar_log(r.CD_MUNICIPIO, r.NR_ZONA, r.NR_SECAO, votos, hab, FUSO.get(r.SG_UF, 0), 2000000 + i)
        pendentes.append((r.SG_UF, nome, texto))
    print(f"Compactando {len(pendentes):,} logs…")
    with ProcessPoolExecutor() as ex:
        comprimidos = list(ex.map(logjez, [p[2] for p in pendentes], chunksize=64))
    for (uf, nome, _), conteudo in zip(pendentes, comprimidos):
        destino = zip_interno if uf == "CE" else zips[uf]
        destino.writestr(f"{nome}.logjez", conteudo)
        destino.writestr(f"{nome}.bu", b"bu-falso")
    zip_interno.close()
    zips["CE"].writestr("logs_ce.zip", interno.getvalue())
    for z in zips.values():
        z.close()

    print("Seções plantadas:")
    print(df[df["tipo"] != "normal"].groupby("tipo").size().to_string())
    print(df[df["tipo"] == "cruzada"][["SG_UF", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO"]].to_string())

    # ------------------------------------------------------------ zip de abstenção
    df["QT_COMPARECIMENTO"] = df["QT_APTOS"] - df["QT_ABSTENCOES"]
    df["NM_LOCAL_VOTACAO"] = [nomes_local[(a, b, c)] for a, b, c in
                              zip(df["CD_MUNICIPIO"], df["NR_ZONA"], df["NR_LOCAL_VOTACAO"])]
    df["NR_TURNO"] = 1
    df["ANO_ELEICAO"] = 1999
    partes = []
    for cd, ds in CARGOS:
        d = df.drop(columns=["tipo", "p_sem_cad"]).copy()
        d["CD_CARGO"], d["DS_CARGO"] = cd, ds
        partes.append(d)
    tudo = pd.concat(partes)
    saida = PASTA / "teste_detalhe_votacao_secao.zip"
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for uf, g in tudo.groupby("SG_UF"):
            buf = io.StringIO()
            g.to_csv(buf, sep=";", index=False)
            z.writestr(f"detalhe_votacao_secao_1999_{uf}.csv", buf.getvalue().encode("latin-1"))
    df[["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "tipo"]].to_csv(PASTA / "teste_gabarito.csv", index=False)
    print(f"\n{len(df):,} seções sintéticas -> {saida} e dados/teste_arqurna_*.zip")


if __name__ == "__main__":
    main()
