import request from './request'

export function loginApi(username, password) {
  return request.post('/auth/login/', { username, password })
}

export function meApi() {
  return request.get('/auth/me/')
}

export function refreshApi(refresh) {
  // skipGlobalError: refresh 401 is handled by the session interceptor / caller.
  return request.post('/auth/refresh/', { refresh }, { skipGlobalError: true })
}

export function healthApi() {
  return request.get('/health/')
}
