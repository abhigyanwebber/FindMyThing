// Linux App Service (custom container from a public GHCR image) hosting the FastAPI API (contract section 15 / A23 / A25).
// System-assigned managed identity for SQL (ActiveDirectoryMsi) and Blob. No secrets in app settings.

param planName string
param siteName string
param location string
param tags object = {}

@description('App Service plan SKU. B1+ is required for Always On (in-process matching poller).')
param skuName string = 'B1'

@description('Full image reference of the API container, e.g. ghcr.io/<lowercase-owner>/findmything-api:sha-<commit>. Must be a PUBLIC image (no registry credentials are configured). Pin a sha tag, not latest.')
@minLength(10)
param containerImage string

@description('Exact https origin of the frontend (same registrable domain as the API).')
param frontendOrigin string

@description('Exact https origin of the API custom hostname.')
param apiPublicOrigin string

@description('Absolute path of campus JSON on the App Service persistent /home share.')
param campusConfigPath string = '/home/site/campus/campus.json'

param sqlServerFqdn string
param sqlDatabaseName string
param storageBlobEndpoint string
param storageContainerName string
param logLevel string = 'INFO'

// Frozen ODBC form: encryption + cert validation, managed identity (contract A23). Not a secret.
var databaseUrl = 'Driver={ODBC Driver 18 for SQL Server};Server=tcp:${sqlServerFqdn},1433;Database=${sqlDatabaseName};Authentication=ActiveDirectoryMsi;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30'

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: skuName }
  properties: { reserved: true }
}

resource site 'Microsoft.Web/sites@2023-12-01' = {
  name: siteName
  location: location
  tags: tags
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: false
    siteConfig: {
      linuxFxVersion: 'DOCKER|${containerImage}'
      alwaysOn: true
      http20Enabled: true
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      ftpsState: 'Disabled'
      healthCheckPath: '/api/health'
      appSettings: [
        // Container contract: the image CMD runs uvicorn on 8000 as non-root appuser; no appCommandLine override.
        { name: 'WEBSITES_PORT', value: '8000' }
        // Mounts the persistent /home share so the operator-supplied campus.json survives restarts (custom containers do not mount it by default).
        { name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'true' }
        // Public GHCR image: no DOCKER_REGISTRY_SERVER_* credentials are set on purpose.
        { name: 'APP_ENV', value: 'production' }
        { name: 'FRONTEND_ORIGIN', value: frontendOrigin }
        { name: 'API_PUBLIC_ORIGIN', value: apiPublicOrigin }
        { name: 'CAMPUS_CONFIG_PATH', value: campusConfigPath }
        { name: 'DATABASE_URL', value: databaseUrl }
        { name: 'AZURE_STORAGE_ACCOUNT_URL', value: storageBlobEndpoint }
        { name: 'AZURE_STORAGE_CONTAINER', value: storageContainerName }
        { name: 'SESSION_COOKIE_NAME', value: 'findmything_session' }
        { name: 'LOG_LEVEL', value: logLevel }
        { name: 'TRUST_FORWARDED_FOR', value: 'true' }
        { name: 'MATCHING_WORKER_ENABLED', value: 'true' }
      ]
    }
  }
}

resource basicPublishingFtp 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: site
  name: 'ftp'
  properties: { allow: false }
}

output siteName string = site.name
output defaultHostname string = site.properties.defaultHostName
output principalId string = site.identity.principalId
