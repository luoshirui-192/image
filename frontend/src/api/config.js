import request from './request'

export function getSystemConfigApi() {
  return request.get('/config/')
}

export function updateSystemConfigApi(data) {
  return request.patch('/config/', data)
}
