<#
.SYNOPSIS
    Publica o site estatico do esteleicao no GitHub Pages (branch gh-pages).

.DESCRIPTION
    1. Roda gerar_site.py (dados de dados\*.parquet -> web\dados), com o Python do .venv
    2. Copia web\ para uma pasta temporaria, sem os arquivos .gz (o GitHub Pages ja
       compacta sozinho) e com um arquivo .nojekyll (para o GitHub nao processar a pasta)
    3. Cria ali um repositorio com um unico commit e envia para a branch gh-pages do
       mesmo remoto (origin). A gh-pages e substituida a cada publicacao (push --force):
       ela so guarda a versao atual do site, para o repositorio nao crescer a cada
       atualizacao dos dados. O codigo continua nas outras branches.

    O site fica em https://<usuario>.github.io/<repositorio>/ depois de ativar o Pages
    uma vez: Settings > Pages > Source "Deploy from a branch", branch gh-pages, pasta / (root).

    Uso (PowerShell, na pasta do projeto):
        .\deploy\publicar_pages.ps1
        .\deploy\publicar_pages.ps1 -SemGerar          # publica o web\ que ja esta gerado
        .\deploy\publicar_pages.ps1 -Ano 2026 -Turno 2

.PARAMETER SemGerar
    Nao roda gerar_site.py; publica o conteudo atual de web\.
.PARAMETER Remoto
    Remoto do git para onde enviar (padrao origin).
#>
param(
    [int]$Ano = 2026,
    [int]$Turno = 1,
    [string]$Remoto = "origin",
    [string]$Branch = "gh-pages",
    [switch]$SemGerar
)
$ErrorActionPreference = "Stop"
function Passo($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Ok($t) { Write-Host "  ok  $t" -ForegroundColor Green }
function RodaGit { & git @args; if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') falhou" } }

$raiz = Split-Path -Parent $PSScriptRoot
$web = Join-Path $raiz "web"

if (-not $SemGerar) {
    Passo "Gerando os dados do site (gerar_site.py --ano $Ano --turno $Turno)"
    # Windows: .venv\Scripts\python.exe; Mac/Linux (pwsh): .venv/bin/python
    $py = @((Join-Path $raiz ".venv\Scripts\python.exe"), (Join-Path $raiz ".venv/bin/python")) |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $py) { throw "Nao achei o Python do .venv em $raiz. Crie com: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }
    & $py (Join-Path $raiz "gerar_site.py") --ano $Ano --turno $Turno
    if ($LASTEXITCODE -ne 0) { throw "gerar_site.py falhou" }
    Ok "dados gerados em $web\dados"
}
if (-not (Test-Path (Join-Path $web "dados\brasil.json"))) { throw "Falta $web\dados\brasil.json. Rode sem -SemGerar." }

Passo "Copiando web\ (sem os .gz) para uma pasta temporaria"
$tmp = Join-Path ([IO.Path]::GetTempPath()) "esteleicao-pages"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory $tmp | Out-Null
$n = 0; $bytes = 0
Get-ChildItem $web -Recurse -File | Where-Object { $_.Extension -ne ".gz" } | ForEach-Object {
    $rel = $_.FullName.Substring($web.Length).TrimStart('\', '/')
    $dest = Join-Path $tmp $rel
    New-Item -ItemType Directory (Split-Path $dest) -Force | Out-Null
    Copy-Item $_.FullName $dest
    $n++; $bytes += $_.Length
}
New-Item -ItemType File (Join-Path $tmp ".nojekyll") | Out-Null
Ok ("{0:N0} arquivos, {1:N0} MB" -f $n, ($bytes / 1MB))
$grandes = Get-ChildItem $tmp -Recurse -File | Where-Object { $_.Length -gt 50MB }
if ($grandes) { throw "Arquivos acima de 50 MB (o GitHub recusa acima de 100 MB): $($grandes.FullName -join ', ')" }

Passo "Enviando para a branch $Branch de $Remoto"
$url = (& git -C $raiz remote get-url $Remoto).Trim()
$versao = (& git -C $raiz rev-parse --short HEAD).Trim()
Push-Location $tmp
try {
    RodaGit init -q
    RodaGit checkout -q -b $Branch
    RodaGit add -A
    $nome = (& git -C $raiz config user.name); $email = (& git -C $raiz config user.email)
    if ($nome) { RodaGit config user.name $nome }
    if ($email) { RodaGit config user.email $email }
    RodaGit commit -q -m "Site gerado em $(Get-Date -Format 'yyyy-MM-dd HH:mm') a partir de $versao (eleicao $Ano, turno $Turno)"
    RodaGit push --force $url "HEAD:refs/heads/$Branch"
} finally { Pop-Location }
Remove-Item $tmp -Recurse -Force
Ok "publicado em $Branch"

if ($url -match "github\.com[:/]([^/]+)/([^/.]+)") {
    Write-Host "`nSite: https://$($Matches[1].ToLower()).github.io/$($Matches[2])/  (o GitHub leva 1 a 2 minutos para atualizar)" -ForegroundColor Green
}
