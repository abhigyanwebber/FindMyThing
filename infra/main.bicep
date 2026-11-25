// FindMyThing root deployment (resource-group scope). Local build/validate only; nothing here is deployed by CI.
// Frozen design: Blob (private, MI-only), Azure SQL serverless (Entra-only), Linux App Service (FastAPI, MI), Static Web Apps (frontend).
targetScope = 'resourceGroup'

@description('Short lowercase prefix for resource names (3-12 letters/digits).')
@minLength(3)
@maxLength(12)
param namePrefix string = 'findmything'

@description('Region for App Service, SQL and Storage.')
param location string = resourceGroup().location

@description('Region for Static Web Apps (only a few regions are supported).')
@allowed([ 'westus2', 'centralus', 'eastus2', 'westeurope', 'eastasia' ])
param staticWebAppLocation string = 'eastasia'

@description('Exact https origin of the frontend (custom domain, same registrable domain as the API).')
param frontendOrigin string

@description('Exact https origin of the API (custom hostname).')
param apiPublicOrigin string

@description('Display name of the Entra user/group that administers Azure SQL.')
param sqlEntraAdminLogin string

@description('Object ID of that Entra user/group.')
param sqlEntraAdminObjectId string

@allowed([ 'User', 'Group', 'Application' ])
param sqlEntraAdminPrincipalType string = 'Group'

@description('App Service plan SKU. B1+ required for Always On.')
param appServiceSkuName string = 'B1'

@description('Public API container image, e.g. ghcr.io/<lowercase-owner>/findmything-api:sha-<commit> (built by .github/workflows/publish-image.yml).')
param containerImage string

@description('Absolute campus JSON path on the App Service /home share.')
param campusConfigPath string = '/home/site/campus/campus.json'

param tags object = {
  app: 'findmything'
}

var suffix = uniqueString(resourceGroup().id)
var storageAccountName = take('${toLower(namePrefix)}${suffix}', 24)
var sqlServerName = toLower('${namePrefix}-sql-${suffix}')
var planName = '${namePrefix}-plan'
var siteName = '${namePrefix}-api-${suffix}'
var staticSiteName = '${namePrefix}-web-${suffix}'

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    name: storageAccountName
    location: location
    tags: tags
  }
}

module sql 'modules/sql.bicep' = {
  name: 'sql'
  params: {
    serverName: sqlServerName
    location: location
    tags: tags
    entraAdminLogin: sqlEntraAdminLogin
    entraAdminObjectId: sqlEntraAdminObjectId
    entraAdminPrincipalType: sqlEntraAdminPrincipalType
  }
}

module appservice 'modules/appservice.bicep' = {
  name: 'appservice'
  params: {
    planName: planName
    siteName: siteName
    location: location
    tags: tags
    skuName: appServiceSkuName
    containerImage: containerImage
    frontendOrigin: frontendOrigin
    apiPublicOrigin: apiPublicOrigin
    campusConfigPath: campusConfigPath
    sqlServerFqdn: sql.outputs.serverFqdn
    sqlDatabaseName: sql.outputs.databaseName
    storageBlobEndpoint: storage.outputs.blobEndpoint
    storageContainerName: storage.outputs.containerName
  }
}

module blobRole 'modules/blob-role.bicep' = {
  name: 'blobRole'
  params: {
    storageAccountName: storage.outputs.accountName
    containerName: storage.outputs.containerName
    principalId: appservice.outputs.principalId
  }
}

// Frontend: Azure Static Web Apps (Free). Content is deployed from the built dist/ output by a separate step; no repo link here.
resource staticSite 'Microsoft.Web/staticSites@2023-12-01' = {
  name: staticSiteName
  location: staticWebAppLocation
  tags: tags
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    stagingEnvironmentPolicy: 'Disabled'
    allowConfigFileUpdates: true
  }
}

output apiSiteName string = appservice.outputs.siteName
output apiDefaultHostname string = appservice.outputs.defaultHostname
output apiPrincipalId string = appservice.outputs.principalId
output sqlServerFqdn string = sql.outputs.serverFqdn
output sqlDatabaseName string = sql.outputs.databaseName
output storageAccountName string = storage.outputs.accountName
output storageContainerName string = storage.outputs.containerName
output staticWebAppName string = staticSite.name
output staticWebAppDefaultHostname string = staticSite.properties.defaultHostname
