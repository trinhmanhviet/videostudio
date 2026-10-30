function Enable-VerifiedFlowBatch([string]$WorkspaceRoot){
 # Explicit operator overrides win. Only this installation's passed pilot enables 10.
 if($null -ne $env:VS_FLOW_BATCH_ENABLED -or $null -ne $env:VS_FLOW_BATCH_VALIDATED_SIZES){return}
 $acceptance=Join-Path $WorkspaceRoot 'data/flow-batch-acceptance.json'
 if(-not (Test-Path -LiteralPath $acceptance)){return}
 try{
  $record=Get-Content -LiteralPath $acceptance -Raw -Encoding UTF8 | ConvertFrom-Json
  if($record.schema_version -ne 1 -or $record.passed -ne $true -or $record.verified_images -ne 10 -or @($record.validated_sizes).Count -ne 1 -or $record.validated_sizes[0] -ne 10){return}
  $env:VS_FLOW_BATCH_ENABLED='1';$env:VS_FLOW_BATCH_VALIDATED_SIZES='10'
 }catch{Write-Warning 'Flow batch acceptance unreadable; keeping sequential mode.'}
}
