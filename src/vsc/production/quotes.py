"""Deterministic quotes of fixed effective requests; never an invoice or budget."""
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
import hashlib
import json
import re


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def quote_request(model, request, native_units, *, now=None):
    """cost_rule is the existing model registry authority, copied into a quote.

    A configured monetary rate needs a dated source and an explicit native unit.
    Subscription usage remains native quantities; absence of a cash price is
    unknown, including when a subscription may cover the eventual request.
    """
    identity = {key: str(model[key]) for key in ('id', 'model_key', 'model_version', 'provider_id')}
    # Materialized media/voice details are derived from the pinned context.
    logical = {key: value for key, value in request.items() if key not in ('input_media', 'input_versions', 'voice_binding')}
    result = {'model': identity, 'request_sha256': fingerprint(logical), 'native_units': dict(native_units),
              'model_config_sha256': fingerprint({key: model.get(key) for key in ('capabilities', 'default_params')}),
              'pricing_sha256': fingerprint(model.get('cost_rule') or {}), 'status': 'unknown',
              'amount': None, 'currency': None, 'source': None, 'reason': '尚未配置适用于此请求的有日期报价；未知不表示免费。'}
    rule = model.get('cost_rule') or {}
    if not isinstance(rule, dict):
        result['reason'] = '模型报价配置无法核实。'
    elif rule:
        result['source'] = {key: rule[key] for key in ('source_url', 'source_date', 'source_revision', 'basis', 'expires_at') if key in rule}
        try:
            unit = rule['unit']
            price = Decimal(str(rule['unit_price']))
            assert unit in native_units and type(native_units[unit]) is int and native_units[unit] >= 0
            assert price.is_finite() and price >= 0 and not isinstance(rule['unit_price'], bool)
            assert len(str(rule['unit_price'])) <= 64 and abs(price.as_tuple().exponent) <= 12
            assert re.fullmatch('[A-Z]{3}', rule['currency'])
            assert isinstance(rule['source_url'], str) and rule['source_url'].startswith('https://')
            dated = datetime.fromisoformat(rule['source_date'].replace('Z', '+00:00'))
            now = now or datetime.now(timezone.utc)
            if dated.tzinfo is None:
                dated = dated.replace(tzinfo=timezone.utc)
            assert dated <= now
            if rule.get('expires_at'):
                expiry = datetime.fromisoformat(rule['expires_at'].replace('Z', '+00:00'))
                assert expiry.tzinfo is not None and expiry > now
            assert rule.get('basis') == 'cash'
            conditions = rule.get('conditions', {})
            assert isinstance(conditions, dict) and all(request.get(key) == value for key, value in conditions.items())
            result.update(status='estimate', amount=str(price * native_units[unit]), currency=rule['currency'],
                          priced_unit=unit, unit_price=str(price), reason='按所列已配置价格估算；实际账单与套餐抵扣尚未确认。')
        except (KeyError, TypeError, ValueError, AttributeError, DecimalException, AssertionError):
            result['reason'] = '价格、来源日期、套餐或请求适用条件不完整；金额保持未知。'
    result['quote_sha256'] = fingerprint(result)
    return result


def reconcile_quote(quote, actual_units, *, actual_cost=None, policy=None):
    """Compare recorded native use and a separately evidenced bill, if present."""
    if not isinstance(actual_units, dict) or any(type(v) is not int or v < 0 for v in actual_units.values()):
        raise ValueError('实际原生用量必须为非负整数')
    policy = {} if policy is None else policy
    if quote_policy_errors(policy):
        raise ValueError('报价偏差策略无效')
    delta = {key: actual_units[key] - quote['native_units'].get(key, 0) for key in actual_units}
    result = {'quote_sha256': quote['quote_sha256'], 'estimated_amount': quote.get('amount'),
              'currency': quote.get('currency'), 'actual_units': actual_units, 'native_delta': delta,
              'actual_amount': None, 'actual_cost_basis': 'unknown', 'threshold_exceeded': None}
    thresholds = policy.get('max_native_delta')
    if thresholds is not None:
        if all(key in actual_units for key in thresholds):
            result['threshold_exceeded'] = any(abs(delta[key]) > bound for key, bound in thresholds.items())
    if actual_cost is not None:
        if not isinstance(actual_cost, dict):
            raise ValueError('实际费用必须是账单对象')
        try:
            amount = Decimal(str(actual_cost.get('amount')))
        except DecimalException as error:
            raise ValueError('实际费用金额无效') from error
        if (not amount.is_finite() or amount < 0 or not actual_cost.get('evidence')
                or not re.fullmatch('[A-Z]{3}', str(actual_cost.get('currency', '')))):
            raise ValueError('实际费用须有金额、币种和账单依据')
        result.update(actual_amount=str(amount), actual_currency=actual_cost['currency'],
                      actual_cost_basis='recorded_bill', actual_cost_evidence=actual_cost['evidence'])
        if actual_cost['currency'] == quote.get('currency') and quote.get('amount') is not None:
            result['amount_delta'] = str(amount - Decimal(quote['amount']))
    return result


def checked_bill(value):
    """An explicitly recorded invoice; never inferred from provider raw JSON."""
    if not isinstance(value, dict) or set(value) != {'amount', 'currency', 'evidence'}:
        raise ValueError('账单需要明确amount、currency、evidence')
    try:
        amount = Decimal(str(value['amount']))
    except DecimalException as error:
        raise ValueError('账单金额无效') from error
    if (isinstance(value['amount'], bool) or not amount.is_finite() or amount < 0
            or len(str(value['amount'])) > 64 or abs(amount.as_tuple().exponent) > 12
            or not re.fullmatch('[A-Z]{3}', str(value['currency']))
            or not isinstance(value['evidence'], str) or not value['evidence'].strip()
            or len(value['evidence']) > 4000):
        raise ValueError('账单需要非负金额、币种及可核对的依据')
    return dict(value, amount=str(amount), evidence=value['evidence'].strip())


def quote_policy_errors(policy):
    from vsc.production.budget import UNITS
    if not isinstance(policy, dict) or set(policy) - {'max_native_delta'}:
        return ['quote_policy只支持显式max_native_delta原生用量偏差提示']
    thresholds = policy.get('max_native_delta', {})
    if (not isinstance(thresholds, dict) or set(thresholds) - set(UNITS)
            or any(type(value) is not int or value < 0 for value in thresholds.values())):
        return ['max_native_delta需为已支持原生单位的非负整数']
    return []


def quote_errors(document):
    """Validate an optional fixed quote before a run can be approved."""
    try:
        assert isinstance(document, dict) and document['format'] == 'vsc.generation-quote/v1'
        assert document['quote_sha256'] == fingerprint({key: value for key, value in document.items() if key != 'quote_sha256'})
        assert isinstance(document['jobs'], list) and 1 <= len(document['jobs']) <= 200
        operations, units, totals, unknown = set(), {}, {}, 0
        for row in document['jobs']:
            assert isinstance(row, dict) and isinstance(row['operation'], str) and row['operation'] not in operations
            operations.add(row['operation'])
            assert row['quote_sha256'] == fingerprint({key: value for key, value in row.items() if key not in ('quote_sha256', 'operation')})
            assert row['status'] in ('estimate', 'unknown')
            assert isinstance(row['native_units'], dict) and row['native_units']
            for key, value in row['native_units'].items():
                assert type(value) is int and value >= 0
                units[key] = units.get(key, 0) + value
            if row['status'] == 'unknown':
                assert row['amount'] is None and row['currency'] is None
                unknown += 1
            else:
                assert isinstance(row['amount'], str)
                amount = Decimal(row['amount'])
                assert amount.is_finite() and amount >= 0 and re.fullmatch('[A-Z]{3}', row['currency'])
                totals[row['currency']] = totals.get(row['currency'], Decimal(0)) + amount
        assert document['native_units'] == units
        assert document['unknown_jobs'] == unknown and type(document['all_prices_known']) is bool
        assert document['all_prices_known'] == (unknown == 0)
        assert document['known_subtotals'] == {key: str(value) for key, value in totals.items()}
        return []
    except (KeyError, TypeError, ValueError, DecimalException, AssertionError):
        return ['generation_quote 必须绑定完整请求/模型/价格快照、原生用量和未知金额，且摘要及合计一致']
