"""Read-only interaction hints. Requests still require current auth and Gateway permits."""


def interaction_view(runtime, active, mode, phase=None):
    permitted = bool(active and not runtime.get('security_blocked') and not runtime.get('recovery_required'))
    observing = bool(permitted and mode in ('normal', 'frozen')
        and runtime.get('status') in ('ready', 'draining')
        and runtime.get('gate_policy') in ('open', 'draining', 'closed', 'reopen_check', 'open_pending')
        and phase not in ('closing', 'applying', 'reconciling'))
    submitting = bool(observing and mode == 'normal' and runtime.get('status') == 'ready'
        and runtime.get('gate_policy') == 'open' and runtime.get('manual_stop_reason', 'none') == 'none')
    return {'maintenance_mode': mode, 'interaction': {
        'can_submit_new': submitting, 'can_observe': observing, 'can_continue': observing}}
