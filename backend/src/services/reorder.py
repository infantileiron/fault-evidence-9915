"""按新讲解顺序重排概率网络。

给定现有概率版本（DAG+完整CPT）与完整节点顺序，生成遵循该顺序且边数最少的新
网络及完整CPT：逐节点在全部前驱中枚举使条件独立成立的最小父集，同样少时按父
节点名称字典序取首个；新CPT由log域联合分布边缘化得到，全部联合状态与原版逐
一对账。严格零以-inf表示并精确比对零模式；极小正概率保持有限log值，不当零。
"""
import itertools
import math
import numpy as np
from scipy.special import logsumexp
from .network_validation import validate_network, validate_cpt
from .log_factor import cpt_factors, product

MAX_PARENTS = 4  # 与validate_network一致的父节点数量上限
CI_TOLERANCE = 1e-9  # log域条件独立判等容差；float64噪声约1e-13
RECONCILE_TOLERANCE = 1e-8  # 逐状态对账容差，覆盖≤10个因子的舍入累积
COMPLETION = (0.5, 0.5)  # 零概率父配置的合法补全


def joint_log_table(nodes, cpt):
    """全状态log联合表；严格零为-inf，极小正概率保持有限log值。"""
    graph = validate_network(nodes)
    rows = validate_cpt(graph['nodes'], cpt)
    final = product(cpt_factors(graph['nodes'], rows))
    return list(final.variables), np.asarray(final.values, dtype=np.float64)


def _marginal(log_joint, ids, keep):
    drop = tuple(axis for axis, ident in enumerate(ids) if ident not in keep)
    values = logsumexp(log_joint, axis=drop) if drop else log_joint
    return [ident for ident in ids if ident in keep], np.asarray(values, dtype=np.float64)


def _ci_check(table, rest_count, given_count, tol):
    """交叉乘积判等：table形状(2,)*(1+rest+given)，轴序为目标、其余、给定。

    零模式（-inf）须精确一致；两侧均有限时差的绝对值须在容差内。
    """
    m = table.reshape(2, 2 ** rest_count, 2 ** given_count)
    finite = np.isfinite(m)
    lhs = m[:, :, None, None, :] + m[None, None, :, :, :]  # 轴序[x1,r1,x2,r2,s]
    lhs_finite = finite[:, :, None, None, :] & finite[None, None, :, :, :]
    rhs = lhs.swapaxes(1, 3)  # 交换r1/r2即m[x1,r2,s]+m[x2,r1,s]
    rhs_finite = lhs_finite.swapaxes(1, 3)
    if np.any(lhs_finite != rhs_finite):
        return False
    both = lhs_finite & rhs_finite
    return not np.any(both) or float(np.max(np.abs(lhs[both] - rhs[both]))) <= tol


def minimal_parent_sets(log_joint, ids, order, max_parents=MAX_PARENTS, tol=CI_TOLERANCE):
    """逐节点在全部前驱中找最小条件独立父集；同大小按父节点名称字典序取首个。"""
    placements = []
    for position, node in enumerate(order):
        predecessors = list(order[:position])
        axes, prefix = _marginal(log_joint, ids, {node} | set(predecessors))
        ranked = sorted(predecessors)
        prefix = np.transpose(prefix, [axes.index(v) for v in [node] + ranked])
        chosen = None
        for size in range(len(predecessors) + 1):
            for combo in itertools.combinations(ranked, size):
                given_axes = [1 + ranked.index(p) for p in combo]
                rest_axes = [a for a in range(1, len(ranked) + 1) if a not in given_axes]
                view = np.transpose(prefix, [0] + rest_axes + given_axes)
                if _ci_check(view, len(rest_axes), len(given_axes), tol):
                    chosen = list(combo)
                    break
            if chosen is not None:
                break
        if len(chosen) > max_parents:
            raise ValueError('节点 %s 在给定顺序下至少需要 %d 个父节点（%s）才能保持联合分布一致，超过父节点数量上限 %d；未创建任何网络或概率版本' % (node, len(chosen), '、'.join(chosen), max_parents))
        placements.append({'node_id': node, 'parents': chosen, 'predecessors': predecessors})
    return placements


def conditional_rows(log_joint, ids, placements):
    """由联合分布边缘化生成新CPT；零概率父配置无法识别，补全等概率并记录。"""
    rows, unidentifiable = [], []
    for placement in placements:
        node, parents = placement['node_id'], placement['parents']
        axes, marginal = _marginal(log_joint, ids, set(parents) | {node})
        table = np.transpose(marginal, [axes.index(v) for v in parents + [node]])
        log_parent = logsumexp(table, axis=-1)
        for values in itertools.product([0, 1], repeat=len(parents)):
            ls = float(log_parent[values])
            if ls == -math.inf:
                p0, p1 = COMPLETION
                unidentifiable.append({'node_id': node, 'parents': list(parents), 'parent_values': list(values), 'completion': {'p0': p0, 'p1': p1}, 'reason': '父配置在原联合分布中概率严格为0，条件概率无法识别，已按合法补全填为等概率0.5/0.5'})
            else:
                probabilities = []
                for state in (0, 1):
                    log_conditional = float(table[values + (state,)]) - ls
                    probabilities.append(0.0 if log_conditional == -math.inf else min(1.0, max(0.0, math.exp(log_conditional))))
                p0, p1 = probabilities
            rows.append({'node_id': node, 'parent_values': list(values), 'p0': p0, 'p1': p1, 'row_sum': math.fsum([p0, p1])})
    rows.sort(key=lambda r: (r['node_id'], r['parent_values']))
    return rows, unidentifiable


def reconcile(ids, old_log, new_log, tol=RECONCILE_TOLERANCE):
    """逐状态对账：零模式精确比对，有限log值按容差判一致。"""
    states, max_diff, zero_mismatches = [], 0.0, 0
    for assignment in itertools.product([0, 1], repeat=len(ids)):
        lo, ln = float(old_log[assignment]), float(new_log[assignment])
        zero_old, zero_new = lo == -math.inf, ln == -math.inf
        if zero_old or zero_new:
            diff, match = None, zero_old == zero_new
            if not match:
                zero_mismatches += 1
        else:
            diff = abs(lo - ln)
            max_diff = max(max_diff, diff)
            match = diff <= tol
        states.append({'assignment': dict(zip(ids, assignment)), 'log_old': None if zero_old else lo, 'log_new': None if zero_new else ln, 'abs_diff': diff, 'zero_old': zero_old, 'zero_new': zero_new, 'match': match})
    consistent = zero_mismatches == 0 and all(s['match'] for s in states)
    summary = {'state_count': len(states), 'max_abs_log_diff': max_diff, 'zero_pattern_mismatches': zero_mismatches, 'tolerance': tol, 'consistent': consistent}
    return summary, states


def convert(nodes, cpt, order, max_parents=MAX_PARENTS):
    """纯函数：校验顺序与输入，生成新节点、新CPT、父集选择、无法识别行与逐状态对账。"""
    graph = validate_network(nodes)
    clean = graph['nodes']
    ids = sorted(n['node_id'] for n in clean)
    if not isinstance(order, (list, tuple)) or any(not isinstance(o, str) for o in order):
        raise ValueError('节点顺序须为节点ID数组')
    missing = [i for i in ids if i not in order]
    unknown = [o for o in order if o not in ids]
    duplicated = sorted({o for o in order if list(order).count(o) > 1})
    if len(order) != len(ids) or missing or unknown or duplicated:
        raise ValueError('节点顺序须为全部%d个节点的不重复排列；缺失：%s；未知：%s；重复：%s' % (len(ids), '、'.join(missing) or '无', '、'.join(unknown) or '无', '、'.join(duplicated) or '无'))
    old_ids, old_log = joint_log_table(clean, cpt)
    placements = minimal_parent_sets(old_log, old_ids, list(order), max_parents)
    new_rows, unidentifiable = conditional_rows(old_log, old_ids, placements)
    labels = {n['node_id']: n['label'] for n in clean}
    new_nodes = [{'node_id': p['node_id'], 'label': labels[p['node_id']], 'parents': p['parents']} for p in placements]
    validate_cpt(new_nodes, new_rows)  # 自检：新DAG合法、新CPT完整且行和为1
    new_ids, new_log = joint_log_table(new_nodes, new_rows)
    summary, states = reconcile(old_ids, old_log, new_log)
    if not summary['consistent']:
        raise ValueError('重排后联合分布与原版不一致（最大log偏差 %g，零模式冲突 %d 处）；未创建任何网络或概率版本' % (summary['max_abs_log_diff'], summary['zero_pattern_mismatches']))
    return {'order': list(order), 'new_nodes': new_nodes, 'new_rows': new_rows, 'placements': placements, 'unidentifiable': unidentifiable, 'reconciliation': summary, 'states': states, 'edges_before': sum(len(n['parents']) for n in clean), 'edges_after': sum(len(p['parents']) for p in placements)}
