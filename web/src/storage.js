const PREFIX = 'btx.'

export function storageGet(key, fallback = null) {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    if (raw == null) return fallback
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

export function storageSet(key, value) {
  localStorage.setItem(PREFIX + key, JSON.stringify(value))
}

export function storageRemove(key) {
  localStorage.removeItem(PREFIX + key)
}
