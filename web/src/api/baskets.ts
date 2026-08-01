import { apiGet, apiPost } from './client'

export type BasketKind = 'theme' | 'custom'
export type BasketStatus = 'ok' | 'stale' | 'unavailable'

export interface BasketMover {
  code: string
  name: string
  change_pct: string
}

export interface BasketMember {
  code: string
  name: string
  weight: string | null
  note: string
}

export interface Basket {
  id: string
  source_id: string
  kind: BasketKind
  name: string
  description: string
  total_stocks: number
  followed: boolean
  hidden: boolean
  sort_order: number
  reason: string
}

export interface BasketDetail extends Basket {
  members: BasketMember[]
  change_pct: string | null
  leader: BasketMover | null
  laggard: BasketMover | null
  anomaly: string | null
  as_of: string | null
  status: BasketStatus
  message: string | null
}

export interface BasketPreferenceUpdate {
  followed?: boolean
  hidden?: boolean
  sort_order?: number
  reason?: string | null
}

export function getBaskets(): Promise<Basket[]> {
  return apiGet<Basket[]>('/api/baskets')
}

export function getBasket(id: string): Promise<BasketDetail> {
  return apiGet<BasketDetail>(`/api/baskets/${encodeURIComponent(id)}`)
}

export function updateBasketPreference(
  id: string,
  update: BasketPreferenceUpdate,
): Promise<Basket> {
  return apiPost<Basket>(`/api/baskets/${encodeURIComponent(id)}/preference`, update)
}

export function updateBasketMemberWeight(
  id: string,
  code: string,
  weight: string | null,
): Promise<BasketMember> {
  return apiPost<BasketMember>(
    `/api/baskets/${encodeURIComponent(id)}/members/${encodeURIComponent(code)}/weight`,
    { weight },
  )
}
