"""
Leitura dos logs da urna eletrônica (.logjez) e cálculo de métricas de horário por seção.

O log vem compactado, com o "logd.dat" dentro:
    2022: <...>.logjez   (7-zip)
    2026: <...>-log.jez  (zip comum)
O logd.dat é um texto latin-1, uma linha por evento, separado por TAB:

    02/10/2022 08:04:13  INFO  2032321  VOTA  O voto do eleitor foi computado  A162B5...
    data hora            nível ID urna  app   mensagem                         hash

Eventos usados (aplicação VOTA, apenas no dia da eleição):
    "Aguardando digitação do título" (2022) /
    "Aguardando digitação do identificador do eleitor" (2026)
                                               -> urna pronta para o próximo eleitor
    "O voto do eleitor foi computado"          -> um voto (momento exato)
Como o eleitor foi liberado (último evento antes do voto):
    "Tipo de habilitação do eleitor [biométrica]"   -> DIGITAL reconhecida
    "O eleitor não possui biometria" (2022) /
    "Ano de nascimento digitado é igual ao do cadastro" sem tentativa de digital (2026)
                                                    -> SEM CADASTRO de digital
    "Solicitação de dado pessoal do eleitor para habilitação manual"
                                                    -> MANUAL: tinha digital, ela não foi
                                                       reconhecida (4 tentativas) e o
                                                       mesário liberou com a digital dele

Horários: a urna registra a hora LOCAL. Desde 2022 a votação ocorre de 8h às 17h
no horário de Brasília em todo o país, então no AM/MT/MS/RO/RR a urna abre às 7h
locais e no AC às 6h. O fuso de cada seção é estimado pelo horário de abertura
(primeira vez que a urna fica pronta para receber eleitor) e depois harmonizado
pelo fuso mais comum do município. Todos os horários do painel estão em
"horário equivalente": 8h = abertura, 17h = encerramento.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from datetime import datetime

import zipfile

import numpy as np

MSG_VOTO = "O voto do eleitor foi computado"
MSG_PRONTA = ("Aguardando digitação do título", "Aguardando digitação do identificador do eleitor")
MSG_BIO = "Tipo de habilitação do eleitor [biométrica]"
MSG_SEM_CADASTRO = "O eleitor não possui biometria"
MSG_ANO_NASCIMENTO = "Ano de nascimento digitado é igual ao do cadastro"  # 2026: liberação biográfica
MSG_MANUAL = "Solicitação de dado pessoal do eleitor para habilitação manual"
HAB_DIGITAL, HAB_SEM_CADASTRO, HAB_MANUAL, HAB_OUTRO = 0, 1, 2, 3
ABERTURA, ENCERRAMENTO = 8.0, 17.0
RE_NOME = re.compile(r"(\d{5})(\d{4})(\d{4})(?:\.logjez|-log\.jez)$", re.I)
EXT_LOG = (".logjez", "-log.jez")
RE_GAP = {"cd_municipio": re.compile(r"^Município: (\d+)"),
          "zona": re.compile(r"^Zona Eleitoral: (\d+)"),
          "secao": re.compile(r"^Seção Eleitoral: (\d+)")}


def extrair_logd(conteudo_logjez: bytes) -> str:
    """Descompacta o log (zip em 2026, 7z em 2022) e devolve o texto do logd.dat."""
    if conteudo_logjez[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(conteudo_logjez)) as z:
            nomes = z.namelist()
            nome = next((n for n in nomes if n.lower().endswith("logd.dat")), nomes[0])
            return z.read(nome).decode("latin-1")
    import py7zr  # só necessário para os logs no formato antigo (7z)
    with py7zr.SevenZipFile(io.BytesIO(conteudo_logjez), "r") as z:
        if hasattr(z, "readall"):  # py7zr < 1.0
            arquivos = {n: b.read() for n, b in z.readall().items()}
        else:  # py7zr >= 1.0
            from py7zr.io import BytesIOFactory
            fabrica = BytesIOFactory(limit=200 * 1024 * 1024)
            z.extractall(factory=fabrica)
            arquivos = {}
            for n, p in fabrica.products.items():
                p.seek(0)
                arquivos[n] = p.read()
    nome = next((n for n in arquivos if n.lower().endswith("logd.dat")), None)
    if nome is None:
        nome = next(iter(arquivos))
    return arquivos[nome].decode("latin-1")


def ler_eventos(texto: str) -> dict:
    """
    Extrai do log os eventos do dia da eleição.
    Devolve segundos-desde-meia-noite (hora local) de cada voto, se foi biométrico,
    o horário de abertura, IDs de urna e a identificação da seção (pelo próprio log).
    """
    linhas = []
    contagem_dias = Counter()
    ident = {}
    for linha in texto.splitlines():
        partes = linha.split("\t")
        if len(partes) < 5:
            continue
        data_hora, _, id_urna, app, msg = partes[:5]
        if app == "GAP" and len(ident) < 3:
            for k, rx in RE_GAP.items():
                if k not in ident and (m := rx.match(msg)):
                    ident[k] = int(m.group(1))
        if app != "VOTA":
            continue
        dia = data_hora[:10]
        if msg == MSG_VOTO:
            contagem_dias[dia] += 1
        linhas.append((dia, data_hora[11:19], id_urna, msg))

    if not contagem_dias:
        return {"votos_s": np.array([], dtype=np.int32), "hab": np.array([], dtype=np.int8),
                "abertura_s": None, "urnas": set(), "dia": None, "ident": ident}
    dia_eleicao = contagem_dias.most_common(1)[0][0]

    votos, hab, urnas = [], [], set()
    abertura = None
    hab_atual = HAB_OUTRO
    for dia, hora, id_urna, msg in linhas:
        if dia != dia_eleicao:
            continue
        h, m, s = hora.split(":")
        t = int(h) * 3600 + int(m) * 60 + int(s)
        urnas.add(id_urna)
        if msg in MSG_PRONTA:
            if abertura is None and t >= 5 * 3600:
                abertura = t
            hab_atual = HAB_OUTRO
        elif msg == MSG_BIO:
            hab_atual = HAB_DIGITAL
        elif msg == MSG_SEM_CADASTRO:
            hab_atual = HAB_SEM_CADASTRO
        elif msg == MSG_ANO_NASCIMENTO and hab_atual == HAB_OUTRO:
            hab_atual = HAB_SEM_CADASTRO
        elif msg == MSG_MANUAL:
            hab_atual = HAB_MANUAL
        elif msg == MSG_VOTO:
            votos.append(t)
            hab.append(hab_atual)
            hab_atual = HAB_OUTRO
    ordem = np.argsort(votos, kind="stable")
    return {"votos_s": np.asarray(votos, dtype=np.int32)[ordem],
            "hab": np.asarray(hab, dtype=np.int8)[ordem],
            "abertura_s": abertura, "urnas": urnas,
            "dia": datetime.strptime(dia_eleicao, "%d/%m/%Y").date().isoformat(), "ident": ident}


# fuso oficial de cada UF em relação a Brasília (o resto é 0)
FUSO_OFICIAL = {"AC": -2, "AM": -1, "MT": -1, "MS": -1, "RO": -1, "RR": -1}


def fuso_por_abertura(ref_horas: float | None, uf: str | None = None) -> int:
    """
    Fuso (horas inteiras) entre o relógio da urna e Brasília, a partir da hora local em que
    a urna abriu (ou do primeiro voto). Usa o fuso oficial da UF, salvo quando a abertura
    destoa dele em mais de 45 min — casos reais: oeste do AM (-2), Fernando de Noronha (+1),
    leste do MT que usa o horário de Brasília (0). No exterior (ZZ) vale só o dado.
    """
    if ref_horas is None or ref_horas != ref_horas:  # None ou NaN
        return FUSO_OFICIAL.get(uf, 0)
    if uf and uf != "ZZ":
        padrao = FUSO_OFICIAL.get(uf, 0)
        if abs(ref_horas - ABERTURA - padrao) <= 0.75:
            return padrao
    return int(np.clip(round(ref_horas - ABERTURA), -3, 2))


def estimar_fuso(abertura_s: int | None, primeiro_voto_s: int | None, uf: str | None = None) -> int:
    """Diferença inteira (em horas) entre o relógio da urna e o horário de Brasília."""
    ref = abertura_s if abertura_s is not None else primeiro_voto_s
    return fuso_por_abertura(None if ref is None else ref / 3600, uf)


def _maior_sequencia(mask: np.ndarray) -> int:
    """Maior número de True consecutivos."""
    if not mask.any():
        return 0
    m = np.concatenate([[0], mask.astype(np.int8), [0]])
    d = np.diff(m)
    return int((np.flatnonzero(d == -1) - np.flatnonzero(d == 1)).max())


INTERVALO_RAPIDO_S = 30  # votos com menos de 30 s entre um e outro


def _sequencia_rapida(votos_s: np.ndarray, fuso: int) -> dict:
    """Maior sequência de votos seguidos com menos de INTERVALO_RAPIDO_S entre um e outro,
    em qualquer horário. Uma sequência de k intervalos curtos envolve k + 1 votos."""
    if len(votos_s) < 2:
        return {"intervalos_rapidos": 0, "maior_seq_rapida": 0, "seq_rapida_inicio": np.nan}
    curto = np.diff(votos_s) < INTERVALO_RAPIDO_S
    if not curto.any():
        return {"intervalos_rapidos": 0, "maior_seq_rapida": 0, "seq_rapida_inicio": np.nan}
    m = np.concatenate([[0], curto.astype(np.int8), [0]])
    d = np.diff(m)
    ini, fim = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    k = int(np.argmax(fim - ini))
    return {"intervalos_rapidos": int(curto.sum()),
            "maior_seq_rapida": int(fim[k] - ini[k] + 1),
            "seq_rapida_inicio": float(votos_s[ini[k]] / 3600 - fuso)}


def metricas(votos_s: np.ndarray, hab: np.ndarray, fuso: int) -> dict:
    """Métricas de horário e de habilitação de uma seção, em horário equivalente (8h–17h)."""
    n = len(votos_s)
    hora_local = np.clip(votos_s // 3600, 0, 23)
    hist = lambda mask: np.bincount(hora_local[mask], minlength=24) if n else np.zeros(24, int)
    sem_digital = hab != HAB_DIGITAL
    manual = hab == HAB_MANUAL
    sem_cad = hab == HAB_SEM_CADASTRO
    h_tot, h_sd, h_man = hist(np.ones(n, bool)), hist(sem_digital), hist(manual)
    base = {"votos_log": n, "fuso": fuso,
            **{f"h{h:02d}": int(h_tot[h]) for h in range(24)},
            **{f"s{h:02d}": int(h_sd[h]) for h in range(24)},
            **{f"m{h:02d}": int(h_man[h]) for h in range(24)}}
    if n == 0:
        return base
    bio = ~sem_digital
    horas = votos_s / 3600 - fuso
    apos = horas >= ENCERRAMENTO
    # maior intervalo sem votos na última hora antes do encerramento (16h–17h).
    # Se havia fila às 17h, a última hora deveria estar "cheia".
    janela = np.concatenate([[ENCERRAMENTO - 1], horas[(horas >= ENCERRAMENTO - 1) & ~apos], [ENCERRAMENTO]])
    ociosa = float(np.diff(janela).max() * 60)
    d_apos = np.diff(votos_s[apos])
    return {
        **base,
        "hora_media": float(horas.mean()),
        "hora_mediana": float(np.median(horas)),
        "hora_p90": float(np.quantile(horas, 0.9)),
        "primeiro_voto": float(horas[0]),
        "ultimo_voto": float(horas[-1]),
        "votos_apos_17": int(apos.sum()),
        "pct_apos_17": float(apos.mean()),
        "pct_ultima_hora": float(((horas >= ENCERRAMENTO - 1) & ~apos).mean()),
        "pct_manha": float((horas < 12).mean()),
        "pct_sem_bio": float(1 - bio.mean()),
        "pct_sem_bio_apos_17": float(1 - bio[apos].mean()) if apos.any() else np.nan,
        # habilitação
        "votos_digital": int(bio.sum()),
        "votos_sem_cadastro": int(sem_cad.sum()),
        "votos_manual": int(manual.sum()),
        "votos_hab_outro": int((hab == HAB_OUTRO).sum()),
        "votos_manual_apos_17": int((manual & apos).sum()),
        "pct_sem_cadastro": float(sem_cad.mean()),
        "pct_manual": float(manual.mean()),
        "pct_manual_cadastrados": float(manual.sum() / max(n - sem_cad.sum(), 1)),
        "maior_seq_manual": _maior_sequencia(manual),
        "maior_seq_sem_digital": _maior_sequencia(sem_digital),
        "ociosa_antes_17_min": ociosa,
        "intervalo_med_apos_17_s": float(np.median(d_apos)) if len(d_apos) else np.nan,
        "intervalo_med_s": float(np.median(np.diff(votos_s))) if n > 1 else np.nan,
        **_sequencia_rapida(votos_s, fuso),
    }


def processar_logjez(nome: str, conteudo: bytes) -> dict | None:
    """Função usada em paralelo: um arquivo .logjez -> eventos + chave da seção."""
    try:
        ev = ler_eventos(extrair_logd(conteudo))
    except Exception as e:  # arquivo corrompido, formato inesperado
        return {"nome": nome, "erro": f"{type(e).__name__}: {e}"}
    m = RE_NOME.search(nome)
    if m:
        chave = tuple(int(x) for x in m.groups())
    elif {"cd_municipio", "zona", "secao"} <= ev["ident"].keys():
        chave = (ev["ident"]["cd_municipio"], ev["ident"]["zona"], ev["ident"]["secao"])
    else:
        return {"nome": nome, "erro": "não foi possível identificar a seção"}
    return {"nome": nome, "chave": chave, **ev}
