<#
.SYNOPSIS
    Construit Yggdrasil depuis Windows, avec Docker Desktop.

.DESCRIPTION
    Toute la construction se fait dans un conteneur Debian 13 : rien n'est installé sur Windows.
    Le cache (paquets téléchargés, chroot) vit dans le volume Docker « yggdrasil-build ».

.EXAMPLE
    .\build.ps1                 # paquets + ISO (édition bureau) dans .\out
    .\build.ps1 -Target serveur # ISO de l'édition serveur (sans bureau, installateur texte)
    .\build.ps1 -Target depot   # dépôt APT signé dans .\out\depot (clé : .\out\cles, à garder)
    .\build.ps1 -Target test    # tests automatiques seulement
    .\build.ps1 -Target debs    # paquets .deb seulement
    .\build.ps1 -Target paquets # paquets .deb, installés, exercés puis purgés dans un Debian 13 vierge
    .\build.ps1 -Target boot    # démarre l'ISO dans QEMU et prend des captures d'écran
    .\build.ps1 -Target cle     # Skíðblaðnir : écrit l'ISO sur une clé virtuelle avec persistance
    .\build.ps1 -Clean          # repart de zéro (vide le cache)
    .\build.ps1 -Resume         # reprend une construction interrompue là où elle s'est arrêtée
#>
param(
    [ValidateSet("iso", "serveur", "debs", "paquets", "test", "boot", "cle", "depot")]
    [string]$Target = "iso",
    [switch]$Clean,
    [switch]$Resume,
    [string]$Mirror = "http://deb.debian.org/debian/",
    # -Target boot : live (défaut), serveur-live, serveur-install, cle
    [string[]]$Scenarios = @()
)

$ErrorActionPreference = "Stop"
$Repo = $PSScriptRoot
$Image = "yggdrasil-builder"
$Volume = "yggdrasil-build"

function Step($text) { Write-Host "`n» $text" -ForegroundColor Yellow }

docker version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker ne répond pas : lance Docker Desktop puis réessaie."
}

Step "Image de construction ($Image)"
docker build -t $Image (Join-Path $Repo "docker")
if ($LASTEXITCODE -ne 0) { throw "échec de docker build" }

New-Item -ItemType Directory -Force (Join-Path $Repo "out") | Out-Null
docker volume create $Volume | Out-Null

$common = @("--rm", "-v", "${Repo}:/src:ro", "-v", "$(Join-Path $Repo 'out'):/out", "-v", "${Volume}:/build")

switch ($Target) {
    "test" {
        Step "Tests"
        docker run @common --privileged $Image bash /src/scripts/test.sh
    }
    "debs" {
        Step "Paquets .deb"
        docker run @common $Image bash -c "cp -r /src /tmp/src && bash /tmp/src/scripts/build-packages.sh /tmp/src /out/debs"
    }
    "paquets" {
        Step "Paquets .deb, installés puis purgés dans un Debian 13 vierge"
        docker run @common $Image bash -c "cp -r /src /tmp/src && bash /tmp/src/scripts/build-packages.sh /tmp/src /out/debs"
        if ($LASTEXITCODE -eq 0) {
            docker run --rm -v "$(Join-Path $Repo 'out\debs'):/debs:ro" -v "${Repo}:/src:ro" debian:trixie bash /src/scripts/test-packages.sh
        }
    }
    "boot" {
        Step "Démarrage de l'ISO dans QEMU"
        docker run @common --privileged $Image bash /src/scripts/test-iso.sh /out @Scenarios
    }
    "cle" {
        Step "Skíðblaðnir : clé USB persistante (périphérique loop)"
        docker run @common --privileged $Image bash /src/scripts/test-skidbladnir.sh /out
    }
    "depot" {
        Step "Dépôt APT signé"
        docker run @common $Image bash -c "cp -r /src /tmp/src && bash /tmp/src/scripts/build-packages.sh /tmp/src /tmp/debs && bash /tmp/src/scripts/build-repo.sh /tmp/debs /out/depot"
    }
    { $_ -in "iso", "serveur" } {
        $edition = if ($Target -eq "serveur") { "serveur" } else { "bureau" }
        Step "ISO Yggdrasil (édition $edition)"
        $envClean = if ($Clean) { "1" } else { "0" }
        $envResume = if ($Resume) { "1" } else { "0" }
        docker run @common --privileged -e "MIRROR=$Mirror" -e "YGG_CLEAN=$envClean" -e "YGG_RESUME=$envResume" `
            -e "YGG_EDITION=$edition" $Image bash /src/scripts/build-iso.sh /build /out
    }
}
if ($LASTEXITCODE -ne 0) { throw "échec (code $LASTEXITCODE)" }
Step "Terminé. Résultats dans $(Join-Path $Repo 'out')"
