// WebSocket 客户端
import { wsUrl } from './client'
import type { Snapshot, Signal } from './types'

type SnapshotHandler = (snap: Snapshot) => void
type SignalHandler = (signals: Signal[]) => void

export class QuotesWS {
  private ws: WebSocket | null = null
  private handler: SnapshotHandler | null = null
  private reconnectTimer: number | null = null

  connect(handler: SnapshotHandler) {
    this.handler = handler
    this.open()
  }

  private open() {
    const url = wsUrl('/ws/quotes')
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
      this.reconnectTimer = window.setTimeout(() => this.open(), 3000)
    }
    this.ws.onerror = (e) => console.error('[ws] error', e)
  }

  private ping() {
    setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send('ping')
      }
    }, 30000)
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
  }
}

export class SignalsWS {
  private ws: WebSocket | null = null
  private handler: SignalHandler | null = null

  connect(handler: SignalHandler) {
    this.handler = handler
    const url = wsUrl('/ws/signals')
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
    this.ws?.close()
    this.ws = null
  }
}
