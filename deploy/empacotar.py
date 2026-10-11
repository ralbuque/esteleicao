"""
Gera pacote_servidor.zip com o SITE PRONTO (pasta web/ com os dados já calculados)
e os arquivos de configuração do servidor. O servidor não precisa de Python:
o Caddy só entrega os arquivos.

    python gerar_site.py          # primeiro, gera web/dados a partir de dados/*.parquet
    python deploy/empacotar.py

No servidor: extrair em C:\\git e rodar deploy\\publicar_site.ps1 (veja deploy/LEIAME_WINDOWS.md).
"""
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "pacote_servidor.zip"
WEB = RAIZ / "web"

if not (WEB / "dados" / "brasil.json").exists():
    raise SystemExit("web/dados ainda não existe. Rode antes:  python gerar_site.py")

arquivos = [a for a in WEB.rglob("*") if a.is_file()]
arquivos += [*(RAIZ / "deploy").glob("*.ps1"), *(RAIZ / "deploy").glob("*.md"),
             *(RAIZ / "deploy").glob("Caddyfile*"), RAIZ / "README.md"]

with zipfile.ZipFile(SAIDA, "w", zipfile.ZIP_DEFLATED) as z:
    for a in sorted(arquivos):
        # .gz já está compactado: guardar sem recompactar é mais rápido
        tipo = zipfile.ZIP_STORED if a.suffix == ".gz" else zipfile.ZIP_DEFLATED
        z.write(a, Path("esteleicao") / a.relative_to(RAIZ), compress_type=tipo)

n_dados = sum(1 for a in arquivos if "dados" in a.parts and a.suffix == ".json")
print(f"{SAIDA.name}: {len(arquivos):,} arquivos ({n_dados:,} de dados), {SAIDA.stat().st_size / 1e6:,.0f} MB")
print("Copie para C:\\git no servidor e siga deploy/LEIAME_WINDOWS.md")
