$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'flow_batch_capability.ps1')
$taskRoot=Join-Path (Split-Path $PSScriptRoot -Parent) ('data/test-flow-capability/'+[guid]::NewGuid())
New-Item -ItemType Directory -Path (Join-Path $taskRoot 'data') -Force | Out-Null
$taskSavedEnabled=$env:VS_FLOW_BATCH_ENABLED;$taskSavedSizes=$env:VS_FLOW_BATCH_VALIDATED_SIZES
try{
 Remove-Item Env:VS_FLOW_BATCH_ENABLED,Env:VS_FLOW_BATCH_VALIDATED_SIZES -ErrorAction SilentlyContinue
 Enable-VerifiedFlowBatch $taskRoot
 if($env:VS_FLOW_BATCH_ENABLED){throw 'Missing evidence must not enable batch'}
 Write-Output 'PASS missing acceptance stays disabled'
 '{"schema_version":1,"passed":false,"verified_images":10,"validated_sizes":[10]}' | Set-Content (Join-Path $taskRoot 'data/flow-batch-acceptance.json')
 Enable-VerifiedFlowBatch $taskRoot
 if($env:VS_FLOW_BATCH_ENABLED){throw 'Failed pilot must not enable batch'}
 Write-Output 'PASS failed acceptance stays disabled'
 '{"schema_version":1,"passed":true,"verified_images":10,"validated_sizes":[10]}' | Set-Content (Join-Path $taskRoot 'data/flow-batch-acceptance.json')
 Enable-VerifiedFlowBatch $taskRoot
 if($env:VS_FLOW_BATCH_ENABLED -ne '1' -or $env:VS_FLOW_BATCH_VALIDATED_SIZES -ne '10'){throw 'Passed pilot must enable only ten'}
 Write-Output 'PASS ten enabled after acceptance'
 $env:VS_FLOW_BATCH_ENABLED='0';Enable-VerifiedFlowBatch $taskRoot
 if($env:VS_FLOW_BATCH_ENABLED -ne '0'){throw 'Explicit disable must be preserved'}
 Write-Output 'PASS explicit disable preserved'
}finally{
 if($null -eq $taskSavedEnabled){Remove-Item Env:VS_FLOW_BATCH_ENABLED -ErrorAction SilentlyContinue}else{$env:VS_FLOW_BATCH_ENABLED=$taskSavedEnabled}
 if($null -eq $taskSavedSizes){Remove-Item Env:VS_FLOW_BATCH_VALIDATED_SIZES -ErrorAction SilentlyContinue}else{$env:VS_FLOW_BATCH_VALIDATED_SIZES=$taskSavedSizes}
}
