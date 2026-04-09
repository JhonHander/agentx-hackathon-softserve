param(
    [string]$VolumeName = "evershop_qdrant-storage",
    [string]$OutputDir = ".",
    [string]$ArchiveName = "qdrant-storage.tgz"
)

$ErrorActionPreference = "Stop"

$resolvedOutputDir = (Resolve-Path $OutputDir).Path
$archivePath = Join-Path $resolvedOutputDir $ArchiveName

Write-Host "Creating backup from volume '$VolumeName'..."
docker volume inspect $VolumeName | Out-Null

docker run --rm `
    -v "${VolumeName}:/from" `
    -v "${resolvedOutputDir}:/to" `
    alpine sh -c "cd /from && tar czf /to/$ArchiveName ."

Write-Host "Backup created at: $archivePath"
