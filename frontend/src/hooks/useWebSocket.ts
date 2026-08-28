import { useEffect } from 'react'

export type SocketEvent = {
  type: string
  data: Record<string, unknown>
}

export function useWebSocket(projectId: string | undefined, onEvent: (event: SocketEvent) => void) {
  useEffect(() => {
    if (!projectId) return
    let closedByEffect = false
    let socket: WebSocket | null = null
    let timer: number | undefined

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/projects/${projectId}`)
      socket.onmessage = (message) => {
        try {
          onEvent(JSON.parse(message.data) as SocketEvent)
        } catch {
          // Ignore malformed server messages.
        }
      }
      socket.onclose = () => {
        if (!closedByEffect) {
          timer = window.setTimeout(connect, 3000)
        }
      }
    }

    connect()

    return () => {
      closedByEffect = true
      if (timer) window.clearTimeout(timer)
      socket?.close()
    }
  }, [projectId, onEvent])
}
