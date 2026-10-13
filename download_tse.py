"""
Downloads resilientes dos arquivos grandes do TSE.

Dois modos:

1. baixar_so_logs()  (padrão)
   Um .zip guarda no final um índice (diretório central) com a posição de cada
   arquivo interno. Lendo esse índice por "download parcial" (HTTP Range), dá para
   buscar SÓ os logs de urna (-log.jez / .logjez), sem baixar boletins, RDV e
   assinaturas. Os logs são baixados em várias conexões paralelas, cada um com
   novas tentativas automáticas, e gravados num zip local
   (dados/logs_brutos_<ano>_<turno>t_<UF>.zip). Se o programa for interrompido,
   na próxima execução ele baixa só o que falta.

2. baixar_completo()  (plano B, se o servidor não aceitar download parcial)
   Baixa o zip inteiro, retomando automaticamente de onde parou a cada queda.
"""
from __future__ import annotations

import io
import struct
import threading
import time
import zipfile
import zlib
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from itertools import islice
from pathlib import Path

import requests

CABECALHO = {"User-Agent": "Mozilla/5.0 (analise-eleicao; download de dados abertos)"}
TIMEOUT = (20, 90)  # (conexão, leitura) em segundos


class SemDownloadParcial(Exception):
    """O servidor não respondeu com 206 a um pedido de faixa (Range)."""


def _espera(tentativa: int) -> float:
    return min(2 ** tentativa, 60)


# ------------------------------------------------------------------ download por faixas
def baixar_faixa(sessao: requests.Session, url: str, ini: int, fim: int, tentativas: int = 10) -> bytes:
    """Baixa os bytes [ini, fim] (inclusive) com novas tentativas."""
    ultimo_erro = None
    for t in range(tentativas):
        try:
            r = sessao.get(url, headers={**CABECALHO, "Range": f"bytes={ini}-{fim}"}, timeout=TIMEOUT)
            if r.status_code == 200:
                raise SemDownloadParcial("servidor ignorou o pedido de faixa (devolveu o arquivo inteiro)")
            if r.status_code == 404:
                raise FileNotFoundError(f"não publicado (404): {url}")
            if r.status_code != 206:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            dados = r.content
            if len(dados) != fim - ini + 1:
                raise IOError(f"recebidos {len(dados)} bytes, esperados {fim - ini + 1}")
            return dados
        except (SemDownloadParcial, FileNotFoundError):
            raise
        except Exception as e:  # timeout, conexão caiu, 5xx, resposta incompleta
            ultimo_erro = e
            time.sleep(_espera(t))
    raise IOError(f"falhou após {tentativas} tentativas: {ultimo_erro}")


def tamanho_remoto(sessao: requests.Session, url: str) -> int:
    """Tamanho do arquivo remoto; também confirma que o servidor aceita download parcial."""
    for t in range(8):
        try:
            r = sessao.get(url, headers={**CABECALHO, "Range": "bytes=0-0"}, timeout=TIMEOUT, stream=True)
            r.close()
            if r.status_code == 404:
                raise FileNotFoundError(f"não publicado (404): {url}")
            if r.status_code == 200:
                raise SemDownloadParcial("servidor não aceita download parcial")
            if r.status_code == 206 and "/" in r.headers.get("Content-Range", ""):
                return int(r.headers["Content-Range"].rsplit("/", 1)[1])
            raise requests.HTTPError(f"HTTP {r.status_code}")
        except (SemDownloadParcial, FileNotFoundError):
            raise
        except Exception:
            time.sleep(_espera(t))
    raise IOError("não foi possível consultar o tamanho do arquivo no servidor")


class ArquivoRemoto(io.RawIOBase):
    """Arquivo remoto 'pesquisável' (seek/read) via HTTP Range, com cache de blocos.
    Usado só para o zipfile ler o índice (diretório central) do zip remoto."""

    def __init__(self, url: str, sessao: requests.Session, tamanho: int, bloco: int = 1 << 20):
        self.url, self.sessao, self.tamanho, self.bloco = url, sessao, tamanho, bloco
        self.pos = 0
        self.cache: OrderedDict[int, bytes] = OrderedDict()

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, deslocamento, de_onde=0):
        base = {0: 0, 1: self.pos, 2: self.tamanho}[de_onde]
        self.pos = base + deslocamento
        return self.pos

    def _bloco(self, i: int) -> bytes:
        if i in self.cache:
            self.cache.move_to_end(i)
            return self.cache[i]
        ini = i * self.bloco
        fim = min(ini + self.bloco, self.tamanho) - 1
        dados = baixar_faixa(self.sessao, self.url, ini, fim)
        self.cache[i] = dados
        if len(self.cache) > 32:
            self.cache.popitem(last=False)
        return dados

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.tamanho - self.pos
        n = max(0, min(n, self.tamanho - self.pos))
        saida = bytearray()
        while n > 0:
            i, desloc = divmod(self.pos, self.bloco)
            parte = self._bloco(i)[desloc:desloc + n]
            if not parte:
                break
            saida += parte
            self.pos += len(parte)
            n -= len(parte)
        return bytes(saida)

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)


def _ler_membro(sessao, url: str, tamanho: int, info: zipfile.ZipInfo) -> bytes:
    """Baixa e descompacta um arquivo interno do zip remoto, a partir da posição no índice."""
    ini = info.header_offset
    nome_len = len(info.filename.encode("utf-8"))
    fim = min(ini + 30 + nome_len + 1024 + info.compress_size, tamanho) - 1  # 1 KB de folga p/ "extra"
    buf = baixar_faixa(sessao, url, ini, fim)
    if buf[:4] != b"PK\x03\x04":
        raise IOError(f"cabeçalho local inválido em {info.filename}")
    n, x = struct.unpack("<HH", buf[26:30])
    inicio_dados = 30 + n + x
    dados = buf[inicio_dados:inicio_dados + info.compress_size]
    if len(dados) < info.compress_size:  # "extra" maior que a folga: busca o resto
        faltam = info.compress_size - len(dados)
        a = ini + inicio_dados + len(dados)
        dados += baixar_faixa(sessao, url, a, a + faltam - 1)
    if info.compress_type == zipfile.ZIP_STORED:
        conteudo = dados
    elif info.compress_type == zipfile.ZIP_DEFLATED:
        conteudo = zlib.decompress(dados, -15)
    else:
        raise IOError(f"método de compressão {info.compress_type} não suportado em {info.filename}")
    if zlib.crc32(conteudo) & 0xFFFFFFFF != info.CRC:
        raise IOError(f"CRC não confere em {info.filename}")
    return conteudo


def baixar_so_logs(url: str, destino: Path, extensoes: tuple[str, ...], conexoes: int = 8) -> tuple[Path, int, int]:
    """
    Baixa só os arquivos com as extensões dadas, gravando em `destino` (zip local).
    Retoma o que já foi baixado. Devolve (destino, total_esperado, faltando).
    """
    sessao = requests.Session()
    tamanho = tamanho_remoto(sessao, url)
    print(f"  arquivo no servidor: {tamanho / 1e6:,.0f} MB — lendo o índice para baixar só os logs…")
    with zipfile.ZipFile(ArquivoRemoto(url, sessao, tamanho)) as zr:
        alvos = [i for i in zr.infolist() if i.filename.lower().endswith(extensoes)]
    total_bytes = sum(i.compress_size for i in alvos)
    print(f"  {len(alvos):,} logs no zip ({total_bytes / 1e6:,.0f} MB, "
          f"{total_bytes / tamanho:.0%} do arquivo completo)")

    ja = set()
    if destino.exists():
        try:
            with zipfile.ZipFile(destino) as z:
                ja = set(z.namelist())
        except zipfile.BadZipFile:
            print("  ! arquivo parcial anterior corrompido; recomeçando")
            destino.unlink()
    faltam = [i for i in alvos if i.filename not in ja]
    if ja:
        print(f"  {len(ja):,} já baixados antes; faltam {len(faltam):,}")
    if not faltam:
        return destino, len(alvos), 0

    local = threading.local()

    def tarefa(info):
        if not hasattr(local, "s"):
            local.s = requests.Session()
        return info, _ler_membro(local.s, url, tamanho, info)

    feitos, falhas, bytes_ok, t0 = 0, [], 0, time.time()
    ex = ThreadPoolExecutor(max_workers=conexoes)
    try:
        with zipfile.ZipFile(destino, "a", zipfile.ZIP_STORED) as saida:
            # janela de pedidos: cada log sai da memória assim que é gravado (pedir todos de uma vez
            # guardava os ~11 GB de SP na memória até o fim)
            fila = iter(faltam)
            pendentes = {ex.submit(tarefa, i) for i in islice(fila, conexoes * 8)}
            while pendentes:
                prontos, pendentes = wait(pendentes, return_when=FIRST_COMPLETED)
                for f in prontos:
                    try:
                        info, conteudo = f.result()
                    except Exception as e:
                        falhas.append(str(e))
                    else:
                        saida.writestr(info.filename, conteudo)
                        feitos += 1
                        bytes_ok += info.compress_size
                        if feitos % 50 == 0 or feitos == len(faltam):
                            dt = max(time.time() - t0, 1e-6)
                            resto = (len(faltam) - feitos) / (feitos / dt)
                            print(f"\r  {feitos:,}/{len(faltam):,} logs  ({bytes_ok / dt / 1e6:,.1f} MB/s, "
                                  f"faltam ~{resto / 60:,.0f} min)   ", end="", flush=True)
                    pendentes |= {ex.submit(tarefa, i) for i in islice(fila, 1)}
    except KeyboardInterrupt:
        ex.shutdown(wait=False, cancel_futures=True)
        print("\n  interrompido — o que já foi baixado está salvo; rode de novo para continuar")
        raise
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    print()
    if falhas:
        print(f"  ! {len(falhas)} logs falharam (ex.: {falhas[0]})")
    return destino, len(alvos), len(falhas)


# ------------------------------------------------------------------ download completo
def baixar_completo(url: str, destino: Path, tentativas: int = 200) -> Path:
    """Baixa o arquivo inteiro, retomando de onde parou a cada queda de conexão."""
    if destino.exists():
        print(f"  zip já baixado: {destino.name}")
        return destino
    parcial = destino.with_suffix(destino.suffix + ".part")
    total = None
    for t in range(tentativas):
        ja = parcial.stat().st_size if parcial.exists() else 0
        if total and ja >= total:
            break
        cab = dict(CABECALHO)
        if ja:
            cab["Range"] = f"bytes={ja}-"
        try:
            with requests.get(url, stream=True, timeout=TIMEOUT, headers=cab) as r:
                if r.status_code == 404:
                    raise FileNotFoundError(f"não publicado (404): {url}")
                if r.status_code == 416:  # já está completo
                    break
                r.raise_for_status()
                if ja and r.status_code != 206:  # servidor ignorou o Range: recomeça do zero
                    ja = 0
                total = ja + int(r.headers.get("Content-Length", 0))
                feito, t0 = ja, time.time()
                with open(parcial, "ab" if ja else "wb") as f:
                    for bloco in r.iter_content(chunk_size=1 << 20):
                        f.write(bloco)
                        feito += len(bloco)
                        vel = (feito - ja) / max(time.time() - t0, 1e-6) / 1e6
                        print(f"\r  {feito / 1e6:,.0f} / {total / 1e6:,.0f} MB  ({vel:,.1f} MB/s)   ",
                              end="", flush=True)
            if total and parcial.stat().st_size >= total:
                break
        except FileNotFoundError:
            raise
        except Exception as e:
            espera = _espera(min(t, 5))
            print(f"\n  conexão caiu ({type(e).__name__}); retomando em {espera:.0f}s "
                  f"(tentativa {t + 1}/{tentativas})")
            time.sleep(espera)
    else:
        raise IOError("download não concluído; rode de novo para continuar de onde parou")
    print()
    parcial.rename(destino)
    return destino
