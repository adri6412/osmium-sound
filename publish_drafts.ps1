# PowerShell script to publish all draft releases
$lines = Get-Content draft_releases.txt
$isProcessing = $false

foreach ($line in $lines) {
    if ($line -match 'Draft') {
        $parts = $line -split '\s+'
        $tag = $parts[0]
        
        # Handle the special case for "HiFi Player v2.5.8"
        if ($tag -eq "HiFi") {
            $tag = "HiFi Player v2.5.8"
        }
        
        Write-Host "Publishing release: $tag"
        gh release edit "$tag" --draft=false
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Successfully published: $tag" -ForegroundColor Green
        } else {
            Write-Host "Failed to publish: $tag" -ForegroundColor Red
        }
        
        # Add a small delay to avoid rate limiting
        Start-Sleep -Seconds 1
    }
}