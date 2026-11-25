// Azure SQL logical server + serverless database (contract A23/A25).
// Entra-only authentication: no SQL admin password exists anywhere in IaC.

param serverName string
param databaseName string = 'findmything'
param location string
param tags object = {}

@description('Display name of the Entra user/group that administers the server (runs migrations and identity grants).')
param entraAdminLogin string

@description('Object ID of that Entra user/group.')
param entraAdminObjectId string

@allowed([ 'User', 'Group', 'Application' ])
param entraAdminPrincipalType string = 'Group'

@description('Serverless max vCores (GP_S_Gen5 capacity).')
param maxVCores int = 1

@description('Serverless min vCores.')
param minCapacity string = '0.5'

@description('Auto-pause delay in minutes (-1 disables).')
param autoPauseDelayMinutes int = 60

@description('Max database size in bytes (default 5 GiB).')
param maxSizeBytes int = 5368709120

@description('Allow Azure-hosted services (App Service) through the server firewall.')
param allowAzureServices bool = true

resource server 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: serverName
  location: location
  tags: tags
  properties: {
    version: '12.0'
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    administrators: {
      administratorType: 'ActiveDirectory'
      azureADOnlyAuthentication: true
      login: entraAdminLogin
      sid: entraAdminObjectId
      principalType: entraAdminPrincipalType
      tenantId: subscription().tenantId
    }
  }
}

resource database 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: server
  name: databaseName
  location: location
  tags: tags
  sku: {
    name: 'GP_S_Gen5'
    tier: 'GeneralPurpose'
    family: 'Gen5'
    capacity: maxVCores
  }
  properties: {
    autoPauseDelay: autoPauseDelayMinutes
    minCapacity: json(minCapacity)
    maxSizeBytes: maxSizeBytes
    zoneRedundant: false
    requestedBackupStorageRedundancy: 'Local'
  }
}

resource allowAzure 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = if (allowAzureServices) {
  parent: server
  name: 'AllowAllWindowsAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

output serverName string = server.name
output serverFqdn string = server.properties.fullyQualifiedDomainName
output databaseName string = database.name
