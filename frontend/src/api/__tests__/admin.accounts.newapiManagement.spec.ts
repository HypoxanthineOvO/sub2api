import { describe, expect, it, vi } from 'vitest'

const { post } = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('@/api/client', () => ({ apiClient: { post } }))

import { probeNewAPIManagement } from '@/api/admin/accounts'

describe('admin account NewAPI management API', () => {
  it('posts to the account management probe endpoint', async () => {
    const snapshot = { status: 'ok', balance_usd: 2 }
    post.mockResolvedValueOnce({ data: snapshot })

    await expect(probeNewAPIManagement(7)).resolves.toEqual(snapshot)
    expect(post).toHaveBeenCalledWith('/admin/accounts/7/management-probe')
  })
})
