const BROWSE_UI_KEY = 'image_db_blob_browse_ui'

export function readBrowseUiState() {
  try {
    const raw = sessionStorage.getItem(BROWSE_UI_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function writeBrowseUiState(state) {
  try {
    sessionStorage.setItem(BROWSE_UI_KEY, JSON.stringify(state))
  } catch {
    // ignore quota / private mode
  }
}

export function clearBrowseUiState() {
  sessionStorage.removeItem(BROWSE_UI_KEY)
}
