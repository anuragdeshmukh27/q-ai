import { useEffect, useState } from 'react'
import { ApiError } from '../api'

/** Load something about the project and load it again (debounced) whenever `version` moves, e.g. after files or branches change. */
export function useRefetch<T>(load: (() => Promise<T>) | null, key: string, version: number, delay = 600): { data: T | null; error: string } {
  const [state, setState] = useState<{ key: string; data: T | null; error: string }>({ key, data: null, error: '' })
  useEffect(() => {
    if (!load) return
    let stop = false
    const t = window.setTimeout(() => {
      load()
        .then((data) => !stop && setState({ key, data, error: '' }))
        .catch((e) => !stop && setState((s) => ({ key, data: s.key === key ? s.data : null, error: e instanceof ApiError ? e.message : 'Could not load this.' })))
    }, delay)
    return () => {
      stop = true
      clearTimeout(t)
    }
    // `load` is rebuilt on every render by design; key and version say when to reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version, delay])
  return state.key === key ? { data: state.data, error: state.error } : { data: null, error: '' }
}
