# Publicar o site no servidor Windows (Caddy)

```
navegador ──https──> Caddy (portas 80/443, já roda no NSSM)
                        │  deploy\Caddyfile.est: esteleicao.com -> pasta C:\git\esteleicao\web
                        ▼
                     arquivos estáticos (HTML, JS e dados JSON pré-calculados)
```

O site é **estático**: o Caddy só entrega arquivos prontos. Não há Python nem
serviço do painel rodando no servidor, então:

- a página abre em menos de 1 segundo, mesmo com muitos visitantes ao mesmo tempo;
- o servidor gasta só a memória do próprio Caddy;
- não existe mais o "Connecting..." do WebSocket do Streamlit.

Os dados são calculados no Mac por `gerar_site.py` e enviados prontos.

## 1. No Mac: gerar o site e o pacote

```bash
cd ~/Git/esteleicao
source .venv/bin/activate
python gerar_site.py
python deploy/empacotar.py
```

Isso cria `pacote_servidor.zip` com a pasta `web` (site + dados).

## 2. No servidor: publicar

Copie `pacote_servidor.zip` para `C:\git\` e, no PowerShell **como Administrador**:

```powershell
cd C:\git
Expand-Archive C:\git\pacote_servidor.zip -DestinationPath C:\git -Force
Get-ChildItem -Recurse C:\git\esteleicao\deploy | Unblock-File
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\esteleicao\deploy\publicar_site.ps1
```

O script:

1. extrai o pacote de novo, apagando antes os dados antigos (para não sobrar
   arquivo de uma geração anterior);
2. na primeira vez, **para e remove o serviço antigo `esteleicao`** do NSSM (o
   painel Streamlit), que não é mais necessário;
3. valida o Caddyfile principal e recarrega o Caddy sem derrubar os outros sites;
4. testa `https://esteleicao.com`.

O Caddyfile principal (`C:\Git\veracibot\deploy\windows\Caddyfile`) continua
com a mesma linha de antes:

```
import C:/git/esteleicao/deploy/Caddyfile.est
```

## Atualizar os dados depois (ex.: 2º turno)

1. No Mac: `python baixar_dados.py --turno 2`, `python baixar_logs.py --turno 2`,
   `python gerar_site.py --turno 2 --ano 2026` e `python deploy/empacotar.py`
2. No servidor: copiar o zip e rodar `.\esteleicao\deploy\publicar_site.ps1`

Não é preciso reiniciar nada: o navegador dos visitantes busca os dados novos
na próxima visita (o `brasil.json` traz a data da geração e os demais arquivos
são pedidos com essa versão).

## Problemas comuns

- **Erro de certificado / `ERR_SSL_PROTOCOL_ERROR`**: rode
  `.\esteleicao\deploy\diagnosticar_caddy.ps1`; ele confere o import, valida,
  reinicia o Caddy e mostra o erro do certificado no log.
- **Página abre mas diz que os dados não foram gerados**: falta a pasta
  `C:\git\esteleicao\web\dados`. Gere no Mac (`python gerar_site.py`) e empacote de novo.
- **Página antiga depois de atualizar**: recarregue com Ctrl+F5.
