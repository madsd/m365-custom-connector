@description('Name of the existing container app whose deployed image should be preserved.')
param name string

// Looking up the existing app in a separate module keeps this same-named
// `existing` reference out of the deployment scope that defines the app itself,
// which avoids an ARM "circular dependency" error on re-provision.
resource existingApp 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: name
}

output image string = existingApp.properties.template.containers[0].image
