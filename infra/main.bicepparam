using 'main.bicep'

// Placeholder values for local validation only. Replace before any real deployment. No secrets belong here.
param namePrefix = 'findmything'
// Azure for Students policy "Allowed resource deployment regions" permits only: eastasia, koreacentral, malaysiawest, austriaeast, uaenorth.
// Do not rely on the resource group's region (rscgrp-01 is centralindia, which the policy rejects).
param location = 'eastasia'
param frontendOrigin = 'https://app.example.edu'
param apiPublicOrigin = 'https://api.example.edu'
param sqlEntraAdminLogin = 'findmything-sql-admins'
param sqlEntraAdminObjectId = '00000000-0000-0000-0000-000000000000'
param sqlEntraAdminPrincipalType = 'Group'
param appServiceSkuName = 'B1'
// Placeholder: replace with the sha-tagged image published by publish-image.yml (package must be PUBLIC).
param containerImage = 'ghcr.io/abhigyanwebber/findmything-api:main'
param staticWebAppLocation = 'eastasia'
