param(
    [string]$ArchivePath = ".\qdrant-storage.tgz",
    [string]$VolumeName = "evershop_qdrant-storage"
)

$ErrorActionPreference = "Stop"

$resolvedArchivePath = (Resolve-Path $ArchivePath).Path
$archiveDir = Split-Path $resolvedArchivePath -Parent
$archiveFile = Split-Path $resolvedArchivePath -Leaf

Write-Host "Creating volume '$VolumeName' if it does not exist..."
docker volume create $VolumeName | Out-Null

Write-Host "Restoring backup '$resolvedArchivePath' into '$VolumeName'..."
docker run --rm `
    -v "${VolumeName}:/to" `
    -v "${archiveDir}:/from" `
    alpine sh -c "rm -rf /to/* /to/.[!.]* /to/..?* 2>/dev/null; cd /to && tar xzf /from/$archiveFile"

Write-Host "Restore finished for volume: $VolumeName"
