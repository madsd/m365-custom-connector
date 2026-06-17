@description('Primary location for all resources.')
param location string

@description('Unique token used to name resources.')
param resourceToken string

@description('Tags applied to all resources.')
param tags object

param entraTenantId string
param entraAudience string
param authRequired string
@secure()
param ncbiApiKey string
param ncbiEmail string
param mcpImage string
param mcpExists bool

var mcpPath = '/mcp'
var targetPort = 8000

// When the app already exists, keep its current image so a `provision` that
// only changes env vars does not reset the running image to the placeholder.
// The lookup lives in a separate module to avoid an ARM circular-dependency
// error (the `existing` reference shares the app's name).
module fetchMcpImage 'fetch-image.bicep' = if (mcpExists) {
  name: 'fetch-mcp-image'
  params: {
    name: 'ca-mcp-${resourceToken}'
  }
}
var effectiveImage = mcpExists ? fetchMcpImage!.outputs.image : mcpImage

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acr${resourceToken}'
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${resourceToken}'
  location: location
  tags: tags
}

// AcrPull role so the container app can pull images using its managed identity.
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, identity.id, acrPullRoleId)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${resourceToken}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource mcpApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-mcp-${resourceToken}'
  location: location
  tags: union(tags, { 'azd-service-name': 'mcp' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: containerRegistry.properties.loginServer
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'mcp'
          image: effectiveImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'PORT', value: string(targetPort) }
            { name: 'MCP_PATH', value: mcpPath }
            { name: 'AUTH_REQUIRED', value: authRequired }
            { name: 'ENTRA_TENANT_ID', value: entraTenantId }
            { name: 'ENTRA_AUDIENCE', value: entraAudience }
            { name: 'NCBI_EMAIL', value: ncbiEmail }
            { name: 'NCBI_API_KEY', value: ncbiApiKey }
            { name: 'NCBI_TOOL', value: 'm365-pubmed-connector' }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.properties.loginServer
output SERVICE_MCP_URI string = 'https://${mcpApp.properties.configuration.ingress.fqdn}'
output SERVICE_MCP_ENDPOINT string = 'https://${mcpApp.properties.configuration.ingress.fqdn}${mcpPath}'
