// Private Blob Storage for item photos (contract A9/A21/A25).
// No public blob access and no shared-key auth: the API uses its managed identity only.

@description('Globally unique storage account name (3-24 lowercase letters/digits).')
@minLength(3)
@maxLength(24)
param name string

param location string
param tags object = {}

@description('Private container name; must match AZURE_STORAGE_CONTAINER.')
param containerName string = 'findmything-private'

@description('Days deleted blobs/containers stay recoverable.')
@minValue(1)
@maxValue(365)
param deleteRetentionDays int = 7

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    allowCrossTenantReplication: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: account
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: deleteRetentionDays }
    containerDeleteRetentionPolicy: { enabled: true, days: deleteRetentionDays }
  }
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: containerName
  properties: { publicAccess: 'None' }
}

output accountName string = account.name
output blobEndpoint string = account.properties.primaryEndpoints.blob
output containerName string = container.name
