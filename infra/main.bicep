targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment used to generate a short unique hash for resources.')
param environmentName string

@minLength(1)
@description('Primary location for all resources.')
param location string

@description('Microsoft Entra tenant ID used to validate bearer tokens.')
param entraTenantId string = ''

@description('Accepted token audience (Application ID URI from the Teams Developer Portal SSO registration).')
param entraAudience string = ''

@description('Whether the MCP server enforces Entra bearer-token authentication.')
param authRequired string = 'false'

@description('Optional NCBI API key for higher PubMed rate limits.')
@secure()
param ncbiApiKey string = ''

@description('Optional contact email reported to the NCBI E-utilities API.')
param ncbiEmail string = ''

@description('Container image for the MCP service. azd overrides this on deploy.')
param mcpImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Whether the MCP container app already exists. azd sets this so re-provisioning preserves the deployed image instead of resetting it to the placeholder.')
param mcpExists bool = false

var abbrs = {
  resourceGroup: 'rg-'
}
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
}

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: '${abbrs.resourceGroup}${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    location: location
    resourceToken: resourceToken
    tags: tags
    entraTenantId: entraTenantId
    entraAudience: entraAudience
    authRequired: authRequired
    ncbiApiKey: ncbiApiKey
    ncbiEmail: ncbiEmail
    mcpImage: mcpImage
    mcpExists: mcpExists
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.AZURE_CONTAINER_REGISTRY_ENDPOINT
output AZURE_RESOURCE_GROUP string = rg.name
output SERVICE_MCP_URI string = resources.outputs.SERVICE_MCP_URI
output SERVICE_MCP_ENDPOINT string = resources.outputs.SERVICE_MCP_ENDPOINT
