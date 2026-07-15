// WebSocket 客户端
import { authenticatedWsUrl } from './client'
import type { Snapshot, Signal } from './types'

type SnapshotHandler = (snap: Snapshot) => void
type SignalHandler = (signals: Signal[]) => void

export class QuotesWS {
  private ws: WebSocket | null = null
  private handler: SnapshotHandler | null = null
  private reconnectTimer: number | null = null
  private pingTimer: number | null = null

  connect(handler: SnapshotHandler) {
    this.handler = handler
    void this.open()
  }

  private async open() {
    let url: string
    try {
      url = await authenticatedWsUrl('/ws/quotes')
    } catch (error) {
      console.error('[ws] authentication failed', error)
      this.scheduleReconnect()
      return
    }
    if (!this.handler) return
    console.log('[ws] connecting to', url)
    this.ws = new WebSocket(url)
    this.ws.onopen = () => {
      console.log('[ws] connected')
      this.ping()
    }
    this.ws.onmessage = (e) => {
      if (e.data === 'pong') return
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'quote_update' && msg.snapshot) {
          this.handler?.(msg.snapshot)
        }
      } catch (err) {
        console.error('[ws] parse error', err)
      }
    }
    this.ws.onclose = () => {
      console.log('[ws] disconnected, reconnecting in 3s')
      this.scheduleReconnect()
    }
    this.ws.onerror = (e) => console.error('[ws] error', e)
  }

  private scheduleReconnect() {
    if (!this.handler || this.reconnectTimer != null) return
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      void this.open()
    }, 3000)
  }

  private ping() {
    if (this.pingTimer != null) window.clearInterval(this.pingTimer)
    this.pingTimer = window.setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send('ping')
      }
    }, 30000)
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    if (this.pingTimer) clearInterval(this.pingTimer)
    this.handler = null
    this.reconnectTimer = null
    this.pingTimer = null
    this.ws?.close()
    this.ws = null
  }
}

export class SignalsWS {
  private ws: WebSocket | null = null
  private handler: SignalHandler | null = null
  private closed = false

  connect(handler: SignalHandler) {
    this.handler = handler
    this.closed = false
    void this.open()
  }

  private async open() {
    let url: string
    try {
      url = await authenticatedWsUrl('/ws/signals')
    } catch (error) {
      console.error('[signals-ws] authentication failed', error)
      return
    }
    if (this.closed) return
    this.ws = new WebSocket(url)
    this.ws.onmessage = (e) => {
      if (e.data === 'pong') return
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'signal_triggered' && msg.signals) {
          this.handler?.(msg.signals)
        }
      } catch (err) {
        console.error('[ws] parse error', err)
      }
    }
    this.ws.onerror = (e) => console.error('[signals-ws] error', e)
  }

  disconnect() {
    this.closed = true
    this.handler = null
    this.ws?.close()
    this.ws = null
  }
}
