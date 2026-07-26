#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ServiceSentry — Azure watchful: spend
#
"""The invoice, which in Azure hurts more often than an outage does.

``check_budgets`` reads the subscription's budgets and the spend against them — actual
**and forecast**. Azure already knows both; nothing was reading them.
"""

from lib.providers.azure.arm import API_BUDGETS
from lib.providers.entraid.client import EntraApiError
from lib.providers.entraid.graph_api import q, qs

from ._names import _slug

# Consumption (budgets) is far slower than the rest of ARM: a first read routinely takes
# tens of seconds. A floor, not an override — a longer configured timeout still wins.
_BUDGET_TIMEOUT = 60


class CostChecks:
    """Spend against the subscription's budgets."""

    def _check_budgets(self, it, key, label, token, timeout) -> None:
        """Spend against the subscription's budgets.

        In Azure the thing that hurts is rarely an outage — it is the invoice, and it is
        the one number the person paying actually asks about. Azure already knows the
        budget and the spend against it; nothing was reading them.

        The **forecast** matters as much as the actual: a budget that will be blown on the
        24th is worth knowing on the 10th, which is the whole point of forecasting.
        """
        sub = str(it.get('subscription_id') or '').strip()
        pct_max = int(it.get('budget_pct') or 90)
        path = (f'/subscriptions/{q(sub)}'
                f'/providers/Microsoft.Consumption/budgets'
                f'?{qs({"api-version": API_BUDGETS})}')
        try:
            # Consumption is the slowest surface in ARM by a wide margin — tens of seconds
            # is normal for a first read, so the module's general timeout (tuned for
            # health calls that answer in one) times out on a perfectly healthy account.
            data = self._arm_json(token, path, max(int(timeout or 0), _BUDGET_TIMEOUT))
        except EntraApiError as exc:
            self._emit(f'{key}/budgets', False, self._msg('az_bud_fail', exc.msg),
                       {'name': label})
            return
        rows = []
        for b in (data.get('value') or []):
            if not isinstance(b, dict):
                continue
            props = b.get('properties') or {}
            amount = props.get('amount')
            if not isinstance(amount, (int, float)) or amount <= 0:
                continue
            spend = props.get('currentSpend') or {}
            fore = props.get('forecastSpend') or {}
            spent = float(spend.get('amount') or 0)
            rows.append({
                'name': str(b.get('name') or '?'),
                'amount': float(amount), 'spent': round(spent, 2),
                'unit': str(spend.get('unit') or fore.get('unit') or ''),
                'grain': str(props.get('timeGrain') or ''),
                'pct': round(100.0 * spent / float(amount), 1),
                # Only present when the budget carries a forecast alert — absent is
                # "not forecast", not "forecast of zero".
                'fore_pct': (round(100.0 * float(fore['amount']) / float(amount), 1)
                             if isinstance(fore.get('amount'), (int, float)) else None),
            })
        if not rows:
            # A subscription with no budget is not "within budget" — nothing is watching
            # the spend at all, which is the state worth saying out loud.
            self._emit(f'{key}/budgets', False, self._msg('az_bud_none'),
                       {'name': label, 'budgets': 0}, severity='warning')
            return
        bad = [r for r in rows
               if r['pct'] >= pct_max or (r['fore_pct'] or 0) >= 100]
        if not bad:
            self._emit(f'{key}/budgets', True,
                       self._msg('az_bud_ok', str(len(rows)), str(pct_max)),
                       {'name': label, 'budgets': len(rows)})
            return
        for r in bad:
            over = r['pct'] >= 100
            money = f"{r['spent']:g}/{r['amount']:g} {r['unit']}".strip()
            # Forecast-only breach: still inside budget today, on course to blow it.
            fore_only = not over and r['pct'] < pct_max
            self._emit(f'{key}/budgets/{_slug(r["name"])}', False,
                       self._msg('az_bud_forecast' if fore_only else 'az_bud_over',
                                 r['name'], str(r['fore_pct'] if fore_only else r['pct']),
                                 money),
                       {'name': r['name'], 'used_pct': r['pct'], 'grain': r['grain'],
                        'spent': r['spent'], 'budget': r['amount'], 'currency': r['unit'],
                        **({'forecast_pct': r['fore_pct']} if r['fore_pct'] is not None else {})},
                       # Over budget is done and billable; on course to be is a warning.
                       severity=None if over else 'warning')
