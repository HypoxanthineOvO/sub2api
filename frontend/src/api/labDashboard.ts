import { apiClient } from './client'

export interface LabDashboardAccount {
  name: string
  platform: string
  type: string
  plan_type?: string
  status: string
  schedulable: boolean
  quota_5h_used_percent?: number
  quota_7d_used_percent?: number
  quota_factor: number
  selection_probability?: number
  selection_probability_status: string
  today_requests: number
  today_actual_cost: number
  slot_label?: string
  selected_node_name?: string
  selected_node_status?: string
  selected_node_observed_at?: string
}

export interface LabDashboardResponse {
  generated_at: string
  timezone: string
  summary: {
    today_actual_cost: number
    today_requests: number
    active_users: number
    schedulable_accounts: number
    total_accounts: number
    week_actual_cost: number
  }
  accounts: LabDashboardAccount[]
  leaderboard: {
    history_start_date?: string
    history_end_date?: string
    rows: Array<{
      display_name: string
      today_actual_cost: number
      last_active_at?: string
      total_actual_cost: number
    }>
  }
  user_usage_24h: Array<{
    bucket: string
    display_name: string
    requests: number
    actual_cost: number
  }>
  recent_usage: Array<{
    created_at: string
    user_display_name: string
    model: string
    account_name?: string
    switch_from_account_name?: string
    switch_reason?: string
    actual_cost: number
  }>
}

export async function getLabDashboard(): Promise<LabDashboardResponse> {
  const { data } = await apiClient.get<LabDashboardResponse>('/lab/dashboard')
  return data
}

export const labDashboardAPI = { get: getLabDashboard }
