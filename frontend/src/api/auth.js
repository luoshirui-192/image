import request from './request'

export function loginApi(username, password) {
  return request.post('/auth/login/', { username, password })
}

export function meApi() {
  return request.get('/auth/me/')
}

export function refreshApi(refresh) {
  return request.post('/auth/refresh/', { refresh })
}

export function healthApi() {
  return request.get('/health/')
}
