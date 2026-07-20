// 预测跟踪 API — agent 记忆系统的预测命中率闭环
import { apiGet } from './client'
import type { Prediction, PredictionStats } from './types'

/** 获取最近 limit 条预测记录（按 created_at 降序）。 */
export function getPredictions(limit = 20): Promise<Prediction[]> {
  return apiGet<{ predictions: Prediction[]; total: number }>(
    `/api/agent/predictions?limit=${limit}`,
  ).then((r) => r.predictions)
}

/** 获取预测统计（各状态计数 + 命中率）。 */
export function getPredictionStats(): Promise<PredictionStats> {
  return apiGet<PredictionStats>('/api/agent/predictions/stats')
}
