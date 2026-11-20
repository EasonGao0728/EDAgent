// A user-configured budget is distinct from the provider's authorization.
// Never turn a transport failure into a fabricated successful quota snapshot.
export async function checkRequestQuota({readPolicy, refresh, record = async () => {}}) {
  const policy = await readPolicy();
  const threshold = policy.stopBelowPercent === undefined ? 20 : policy.stopBelowPercent;
  if (threshold !== null && (!Number.isFinite(threshold) || threshold < 0 || threshold > 100))
    throw Error('QUOTA_POLICY_INVALID: 额度停止线无效。');
  try {
    const q = await refresh();
    if (q.ordinaryUsageAllowed === false) throw Error('QUOTA_STOP: 服务当前不允许模型使用。');
    if (threshold !== null) {
      if (!Number.isFinite(q.remainingPercent) || q.remainingPercent < 0 || q.remainingPercent > 100)
        throw Error('QUOTA_UNKNOWN: 未返回有效额度，无法执行百分比预算。');
      if (q.remainingPercent < threshold) throw Error('QUOTA_STOP: 低于用户设置的百分比预算。');
    }
    return {...q, availability: 'available', budgetCheckEnforced: threshold !== null};
  } catch (error) {
    // All account, login, policy, known service denial and unexpected errors
    // remain fatal. Only this specific unavailable read can be advisory when
    // the user has explicitly removed their percentage-based budget.
    if (threshold !== null || !/^(?:host bridge: )?(?:ValueError: )?QUOTA_UNAVAILABLE:/.test(error?.message || ''))
      throw error;
    const q = {
      source: 'unavailable', availability: 'unknown', acquisition: 'failed_live_read',
      remainingPercent: null, checkedAt: null, attemptedAt: Date.now(),
      stopBelowPercent: null, ordinaryUsageAllowed: null,
      budgetCheckEnforced: false, providerAuthorizationRequired: true,
      diagnosticCode: 'QUOTA_UNAVAILABLE',
      note: '用户已取消百分比下限；额度未知。仍须通过原有 OAuth 鉴权，实际模型服务可拒绝调用。',
    };
    await record(q);
    return q;
  }
}
